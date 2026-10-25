from django.test import TestCase, Client as TestClient
from django.contrib.auth.models import User
from django.urls import reverse
from .models import Product, ProductPriceHistory

class PriceAndProfitabilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='admin_test', password='password123')
        self.client = TestClient()
        self.client.login(username='admin_test', password='password123')

    def test_product_profit_and_margins(self):
        # Product with cost 1000, price 1300
        p = Product.objects.create(name='Papas Fritas', cost_price=1000, price=1300, stock=10)
        self.assertEqual(p.profit, 300)
        self.assertEqual(p.margin_markup, 30.0) # (300 / 1000) * 100
        self.assertEqual(p.margin_profit, 23.08) # (300 / 1300) * 100
        self.assertEqual(p.cost_valuation, 10000)
        self.assertEqual(p.sale_valuation, 13000)
        self.assertEqual(p.profit_valuation, 3000)

    def test_add_product_creates_price_history(self):
        response = self.client.post(reverse('add_product'), {
            'name': 'Gaseosa Manzana',
            'barcode': '770111222',
            'cost_price': '2000',
            'price': '3000',
            'stock': '20',
            'price_change_reason': 'Creación inicial'
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        product = Product.objects.get(barcode='770111222')
        self.assertEqual(product.cost_price, 2000)
        self.assertEqual(product.price, 3000)
        self.assertEqual(product.stock, 20)

        history = ProductPriceHistory.objects.filter(product=product)
        self.assertEqual(history.count(), 1)
        h = history.first()
        self.assertEqual(h.old_price, 0)
        self.assertEqual(h.new_price, 3000)
        self.assertEqual(h.old_cost_price, 0)
        self.assertEqual(h.new_cost_price, 2000)
        self.assertEqual(h.user, self.user)
        self.assertEqual(h.reason, 'Creación inicial')

    def test_edit_product_records_price_history_on_change(self):
        p = Product.objects.create(name='Leche Entera', cost_price=3000, price=4000, stock=15)
        ProductPriceHistory.objects.create(
            product=p, old_price=0, new_price=4000, old_cost_price=0, new_cost_price=3000, user=self.user, reason='Inicial'
        )

        # Update price to 4500 and cost to 3200
        response = self.client.post(reverse('edit_product', args=[p.id]), {
            'name': 'Leche Entera 1L',
            'barcode': '',
            'cost_price': '3200',
            'price': '4500',
            'stock': '15',
            'price_change_reason': 'Subida de precio proveedor'
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        p.refresh_from_db()
        self.assertEqual(p.name, 'Leche Entera 1L')
        self.assertEqual(p.cost_price, 3200)
        self.assertEqual(p.price, 4500)

        history = ProductPriceHistory.objects.filter(product=p).order_by('-date')
        self.assertEqual(history.count(), 2)
        latest = history.first()
        self.assertEqual(latest.old_price, 4000)
        self.assertEqual(latest.new_price, 4500)
        self.assertEqual(latest.price_diff, 500)
        self.assertEqual(latest.price_diff_percent, 12.5) # 500 / 4000 * 100
        self.assertEqual(latest.old_cost_price, 3000)
        self.assertEqual(latest.new_cost_price, 3200)
        self.assertEqual(latest.cost_diff, 200)
        self.assertEqual(latest.new_profit, 1300)
        self.assertEqual(latest.reason, 'Subida de precio proveedor')

    def test_edit_product_no_duplicate_history_if_prices_unchanged(self):
        p = Product.objects.create(name='Galletas', cost_price=1000, price=1500, stock=5)
        ProductPriceHistory.objects.create(
            product=p, old_price=0, new_price=1500, old_cost_price=0, new_cost_price=1000, user=self.user
        )

        # Only update stock and name
        self.client.post(reverse('edit_product', args=[p.id]), {
            'name': 'Galletas Festival',
            'barcode': '',
            'cost_price': '1000',
            'price': '1500',
            'stock': '20',
        }, follow=True)

        history = ProductPriceHistory.objects.filter(product=p)
        self.assertEqual(history.count(), 1) # No new price history created

    def test_views_render_successfully(self):
        p = Product.objects.create(name='Jugo Hit', cost_price=1800, price=2500, stock=8)
        
        # Inventory view
        res = self.client.get(reverse('inventory'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Jugo Hit')
        self.assertContains(res, 'Valor Estimado Venta')

        # Edit view
        res_edit = self.client.get(reverse('edit_product', args=[p.id]))
        self.assertEqual(res_edit.status_code, 200)
        self.assertContains(res_edit, 'Fijación de Precios y Rentabilidad')

        # Product price history modal view
        res_hist = self.client.get(reverse('product_price_history', args=[p.id]))
        self.assertEqual(res_hist.status_code, 200)
        self.assertContains(res_hist, 'Jugo Hit')

        # Global price history view
        res_global = self.client.get(reverse('global_price_history'))
        self.assertEqual(res_global.status_code, 200)
        self.assertContains(res_global, 'Historial de Cambios de Precios')

    def test_scan_and_add_to_cart_success(self):
        p = Product.objects.create(name='Póker 330ml', barcode='77020011', cost_price=2000, price=3000, stock=50)
        res = self.client.post(reverse('scan_and_add_to_cart'), {'barcode': '77020011'})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['product_name'], 'Póker 330ml')
        self.assertEqual(data['price'], 3000)
        self.assertIn('cart_html', data)
        self.assertEqual(self.client.session['cart'][str(p.id)]['quantity'], 1)

    def test_scan_and_add_to_cart_not_found(self):
        res = self.client.post(reverse('scan_and_add_to_cart'), {'barcode': '999999999999'})
        self.assertEqual(res.status_code, 404)
        data = res.json()
        self.assertFalse(data['success'])

    def test_search_products_by_barcode(self):
        Product.objects.create(name='Agua Cristal', barcode='770333444', cost_price=1000, price=1500, stock=30)
        res = self.client.get(reverse('search_products'), {'search': '770333444'})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Agua Cristal')

    def test_product_image_upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        # 1x1 transparent GIF image
        gif_bytes = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        test_image = SimpleUploadedFile('test_product.gif', gif_bytes, content_type='image/gif')

        res = self.client.post(reverse('add_product'), {
            'name': 'Gaseosa Colombiana',
            'barcode': '770555666',
            'cost_price': '1500',
            'price': '2500',
            'stock': '12',
            'image': test_image
        }, follow=True)
        self.assertEqual(res.status_code, 200)

        p = Product.objects.get(barcode='770555666')
        self.assertTrue(bool(p.image))
        self.assertTrue(p.image.name.startswith('products/'))
        
        # Test cleaning image
        if p.image:
            try:
                p.image.delete(save=False)
            except Exception:
                pass

    def test_sale_profitability_and_report_analytics(self):
        from .models import Client, Sale, SaleItem
        client = Client.objects.create(name='Empresa ABC', phone='3001234567')
        p1 = Product.objects.create(name='Cuaderno 100H', cost_price=2000, price=3500, stock=50)
        p2 = Product.objects.create(name='Bolígrafo Azul', cost_price=500, price=1200, stock=100)

        # Create a sale with 2 Cuadernos and 3 Bolígrafos
        sale = Sale.objects.create(
            client=client,
            total=10600, # (2 * 3500) + (3 * 1200) = 7000 + 3600 = 10600
            payment_method='CASH',
            is_paid=True
        )
        item1 = SaleItem.objects.create(sale=sale, product=p1, quantity=2, price=3500, cost_price=2000)
        item2 = SaleItem.objects.create(sale=sale, product=p2, quantity=3, price=1200, cost_price=500)

        # Check item profitability
        self.assertEqual(item1.total_cost, 4000)
        self.assertEqual(item1.profit, 3000)
        self.assertEqual(item1.margin_profit, 42.86) # 3000 / 7000 * 100
        self.assertEqual(item1.margin_markup, 75.0)  # 3000 / 4000 * 100

        self.assertEqual(item2.total_cost, 1500)
        self.assertEqual(item2.profit, 2100)
        self.assertEqual(item2.margin_profit, 58.33) # 2100 / 3600 * 100
        self.assertEqual(item2.margin_markup, 140.0) # 2100 / 1500 * 100

        # Check sale total profitability
        self.assertEqual(sale.total_cost, 5500)
        self.assertEqual(sale.total_profit, 5100) # 10600 - 5500
        self.assertEqual(sale.margin_profit, 48.1) # round(5100 / 10600 * 100, 1) = 48.1
        self.assertEqual(sale.margin_markup, 92.7) # round(5100 / 5500 * 100, 1) = 92.7

        # Request report_analytics view
        res = self.client.get(reverse('reports'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Rentabilidad & Márgenes')
        self.assertContains(res, 'Top 10 Artículos Más Rentables')
        self.assertContains(res, 'Cuaderno 100H')
        self.assertContains(res, 'Bolígrafo Azul')
        self.assertEqual(res.context['total_profit_period'], 5100)
        self.assertEqual(res.context['total_cost_period'], 5500)
        self.assertEqual(res.context['star_product']['name'], 'Cuaderno 100H')

    def test_pos_cart_lifecycle_and_checkout(self):
        from .models import Client, Sale, SaleItem
        client = Client.objects.create(name='Carlos Ruiz', phone='3109998877')
        prod = Product.objects.create(name='Pony Malta', barcode='770123456789', cost_price=1200, price=2000, stock=20)

        # 1. Search product
        res = self.client.get(reverse('search_products'), {'search': 'Pony'})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Pony Malta')

        # 2. Add to cart
        res_add = self.client.post(reverse('add_to_cart'), {'product_id': prod.id, 'quantity': 2})
        self.assertEqual(res_add.status_code, 200)
        self.assertIn('HX-Trigger', res_add.headers)
        self.assertIn('itemAdded', res_add.headers['HX-Trigger'])
        self.assertContains(res_add, 'Pony Malta')
        self.assertContains(res_add, '$4,000')

        # Check session
        cart = self.client.session.get('cart', {})
        self.assertEqual(cart[str(prod.id)]['quantity'], 2)

        # 3. Update cart (increment)
        res_inc = self.client.post(reverse('update_cart_item'), {'product_id': prod.id, 'action': 'increment'})
        self.assertEqual(res_inc.status_code, 200)
        self.assertEqual(self.client.session['cart'][str(prod.id)]['quantity'], 3)

        # 4. Checkout
        res_checkout = self.client.post(reverse('checkout'), {
            'client_id': client.id,
            'payment_method': 'CASH',
            'note': 'Venta rápida POS'
        }, follow=True)
        self.assertEqual(res_checkout.status_code, 200)

        # Verify sale was created
        sale = Sale.objects.filter(client=client).last()
        self.assertIsNotNone(sale)
        self.assertEqual(sale.total, 6000) # 3 * 2000
        self.assertTrue(sale.is_paid)

        # Verify stock was deducted
        prod.refresh_from_db()
        self.assertEqual(prod.stock, 17) # 20 - 3


