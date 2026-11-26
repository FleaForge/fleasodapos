from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Client, Payment, Product, ProductComponent, Sale
from .views import reconcile_client_allocations


class InitialPaymentTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user(username='cashier'))
        self.customer = Client.objects.create(name='Cliente abono')
        self.product = Product.objects.create(name='Gaseosa', price=5000, stock=10)
        session = self.client.session
        session['cart'] = {str(self.product.id): {
            'id': self.product.id, 'name': self.product.name, 'price': 5000, 'quantity': 1,
        }}
        session.save()

    def checkout(self, amount='4000', **kwargs):
        data = {'client_id': self.customer.id, 'payment_method': 'CREDIT', 'initial_payment': amount}
        data.update(kwargs)
        return self.client.post(reverse('checkout'), data)

    def test_partial_payment_and_reports(self):
        self.checkout()
        sale = Sale.objects.get(client=self.customer)
        payment = Payment.objects.get(client=self.customer)
        self.assertEqual((sale.total, sale.amount_paid, sale.pending_balance), (5000, 4000, 1000))
        self.assertEqual(self.customer.balance, 1000)
        self.assertEqual(payment.sale_id, sale.id)
        self.assertFalse(sale.is_paid)
        self.assertEqual(self.client.session['cart'], {})
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 9)
        report = self.client.get(reverse('reports'))
        self.assertEqual(report.context['total_period'], 5000)
        self.assertEqual(report.context['total_cash_in'], 4000)
        self.assertEqual(report.context['portfolio_total_pending'], 1000)
        self.assertContains(report, 'Abonado: $4,000')
        self.assertContains(report, 'Pendiente: $1,000')
        detail = self.client.get(reverse('invoice_detail', args=[sale.id]))
        self.assertContains(detail, 'Abonos recibidos:')
        self.assertContains(detail, '$1,000')
        self.client.get(reverse('client_statement', args=[self.customer.id]))
        self.assertEqual(sale.pending_balance, 1000)

    def test_initial_payment_stays_on_new_sale_after_reconciliation(self):
        old = Sale.objects.create(client=self.customer, payment_method='CREDIT', total=9000, is_paid=False)
        self.checkout()
        new = Sale.objects.exclude(pk=old.pk).get()
        reconcile_client_allocations(self.customer)
        self.assertEqual(old.pending_balance, 9000)
        self.assertEqual(new.pending_balance, 1000)
        self.assertEqual(self.customer.balance, 10000)
        Payment.objects.create(client=self.customer, amount=2000)
        reconcile_client_allocations(self.customer)
        self.assertEqual(old.pending_balance, 7000)
        self.assertEqual(new.pending_balance, 1000)

    def test_full_payment_and_no_payment(self):
        self.checkout('5000')
        sale = Sale.objects.get()
        self.assertTrue(sale.is_paid)
        self.assertEqual(sale.pending_balance, 0)
        self.assertEqual(self.customer.balance, 0)

    def test_credit_without_initial_payment(self):
        self.checkout('')
        sale = Sale.objects.get()
        self.assertEqual(sale.pending_balance, 5000)
        self.assertFalse(Payment.objects.exists())

    def test_invalid_amounts_leave_cart_stock_and_account_untouched(self):
        for amount in ('-1', '5001', 'abc', '4.5'):
            with self.subTest(amount=amount):
                self.checkout(amount)
                self.assertFalse(Sale.objects.exists())
                self.assertFalse(Payment.objects.exists())
                self.assertTrue(self.client.session['cart'])
                self.product.refresh_from_db()
                self.assertEqual(self.product.stock, 10)

    def test_cash_does_not_create_payment(self):
        self.checkout('', payment_method='CASH')
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(self.customer.balance, 0)
        self.assertTrue(Sale.objects.get().is_paid)

    def test_backdated_payment_uses_sale_date(self):
        self.checkout(created_at='2026-11-20T21:30')
        sale = Sale.objects.get()
        payment = Payment.objects.get()
        self.assertEqual(payment.date, sale.date)
        self.assertEqual(str(timezone.localdate(payment.date)), '2026-11-20')

    def test_payment_failure_rolls_back_sale_and_stock(self):
        with patch('pos.views.Payment.objects.create', side_effect=RuntimeError('Payment failed')):
            with self.assertRaises(RuntimeError):
                self.checkout()
        self.assertFalse(Sale.objects.exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)
        self.assertTrue(self.client.session['cart'])

    def test_annulling_initial_payment_restores_debt(self):
        self.checkout()
        self.client.post(reverse('annul_payment', args=[Payment.objects.get().pk]))
        sale = Sale.objects.get()
        self.assertEqual(sale.pending_balance, 5000)
        self.assertEqual(self.customer.balance, 5000)
        self.assertFalse(sale.is_paid)


class SupplyEditorTests(TestCase):
    def test_supply_inclusion_and_editor_rendering(self):
        self.client.force_login(User.objects.create_user(username='editor'))
        service = Product.objects.create(name='Impresión', is_service=True, price=1000)
        supply = Product.objects.create(name='Papel fotográfico', barcode='770123', stock=10, cost_price=200)
        response = self.client.get(reverse('edit_product', args=[service.pk]))
        self.assertContains(response, 'relative z-20 bg-white')
        self.assertContains(response, 'Papel fotogr')
        for emoji in ('📦', '🧪', '⚡', '⚠', '📷', '➕', '🏷', '🔍', '✨', '🔒', '🚫', '📊'):
            self.assertNotContains(response, emoji)
        self.client.post(reverse('add_product_component', args=[service.pk]), {
            'component_product_id': supply.pk, 'quantity': 2,
        })
        component = ProductComponent.objects.get(parent_product=service)
        self.assertEqual(component.component_product, supply)
        self.assertEqual(component.quantity, 2)
        response = self.client.get(reverse('edit_product', args=[service.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['product'].available_service_units, 5)
