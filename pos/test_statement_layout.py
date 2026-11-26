from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Client, Payment, Sale


class StatementPaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='statement-review')
        cls.customer = Client.objects.create(name='Cliente de prueba de diseño', phone='3000000000')
        Sale.objects.bulk_create([
            Sale(client=cls.customer, total=5000, payment_method='CREDIT', is_paid=False,
                 note='Compra de prueba con descripción extensa para comprobar espacios')
            for _ in range(200)
        ])
        cls.sales = list(Sale.objects.order_by('date', 'id'))
        Payment.objects.create(client=cls.customer, sale=cls.sales[0], amount=4000)

    def test_200_sales_are_paginated_without_changing_totals_or_exports(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('client_statement', args=[self.customer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['current_debt'], 996000)
        self.assertEqual(len(response.context['pending_sales']), 200)
        page = response.context['pending_sales_page']
        self.assertEqual(len(page), 25)
        self.assertEqual(page.paginator.num_pages, 8)
        self.assertContains(response, '1–25 de 200 cuentas')
        self.assertContains(response, f'aria-controls="sale-details-{self.sales[0].pk}"')
        self.assertNotContains(response, f'aria-controls="sale-details-{self.sales[25].pk}"')
        self.assertContains(response, 'Anular recibo')
        # The full list is retained for the image and printed document.
        self.assertContains(response, f'#{self.sales[-1].pk}')
        response = self.client.get(reverse('client_statement', args=[self.customer.pk]), {'accounts_page': 8})
        self.assertContains(response, '176–200 de 200 cuentas')
        self.assertEqual(response.context['current_debt'], 996000)

    def test_public_pagination_does_not_expose_annulment_actions(self):
        url = reverse('client_public_statement', args=[self.customer.pk])
        response = self.client.get(url, {'accounts_page': 'invalid'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['pending_sales_page'].number, 1)
        self.assertNotContains(response, 'Anular recibo')
        response = self.client.get(url, {'accounts_page': 999})
        self.assertEqual(response.context['pending_sales_page'].number, 8)

    def test_empty_account(self):
        customer = Client.objects.create(name='Cuenta al día')
        response = self.client.get(reverse('client_public_statement', args=[customer.pk]))
        self.assertContains(response, 'No hay cuentas pendientes de pago.')
        self.assertEqual(len(response.context['pending_sales_page']), 0)
