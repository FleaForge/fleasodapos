from django.test import TestCase, Client as TestClient
from django.contrib.auth.models import User
from django.urls import reverse
from .models import Product, ProductPriceHistory, ProductComponent, Client, Sale, SaleItem

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
        self.assertContains(res_edit, 'productEditor(1800, 2500, 8, 0, false, false)')

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

    def test_inventory_valuation_and_pdf(self):
        # Create test products
        p1 = Product.objects.create(name='Arroz Diana 1kg', cost_price=3500, price=4500, stock=20) # sale: 90,000, cost: 70,000
        p2 = Product.objects.create(name='Aceite Premier 1L', cost_price=7000, price=9000, stock=10) # sale: 90,000, cost: 70,000

        # Check inventory view
        res = self.client.get(reverse('inventory'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Valor Inventario (PVP)')
        self.assertContains(res, 'Valor Estimado Venta')
        self.assertContains(res, 'Valor en Stock')
        self.assertEqual(res.context['total_stock_units'], 30) # 20 + 10
        self.assertEqual(res.context['total_sale_valuation'], 180000) # 90,000 + 90,000

        # Check dashboard inventory valuation widget
        res_dash = self.client.get(reverse('dashboard'))
        self.assertEqual(res_dash.status_code, 200)
        self.assertContains(res_dash, 'Patrimonio en Mercancía')
        self.assertContains(res_dash, 'Valorización Inventario (PVP)')
        self.assertEqual(res_dash.context['total_inventory_valuation'], 180000)

        # Check inventory valuation PDF generation
        res_pdf = self.client.get(reverse('inventory_valuation_pdf'))
        self.assertEqual(res_pdf.status_code, 200)
        self.assertEqual(res_pdf['Content-Type'], 'application/pdf')
        self.assertIn('Valorizacion_Inventario.pdf', res_pdf['Content-Disposition'])
        self.assertTrue(res_pdf.content.startswith(b'%PDF'))

    def test_product_components_and_effective_cost(self):
        # 1. Supply: Papel Fotográfico (bought at 308, sold at 500, stock 50)
        paper = Product.objects.create(name='Papel Fotográfico A4', cost_price=308, price=500, stock=50)

        # 2. Service: Impresión Papel Fotográfico (cost 0, price 1000, is_service=True)
        service = Product.objects.create(name='Impresión Papel Fotográfico', cost_price=0, price=1000, stock=0, is_service=True)

        # Link paper as component: 1 unit per print
        comp = ProductComponent.objects.create(
            parent_product=service,
            component_product=paper,
            quantity=1
        )

        service.refresh_from_db()
        self.assertTrue(service.has_components)
        self.assertEqual(service.components_cost, 308)
        self.assertEqual(service.effective_cost, 308)
        self.assertEqual(service.profit, 692) # 1000 - 308
        self.assertEqual(service.margin_markup, 224.68) # ((1000 - 308) / 308) * 100
        self.assertEqual(service.available_service_units, 50) # 50 paper / 1
        self.assertEqual(service.cost_valuation, 0) # Services don't duplicate capital valuation

    def test_checkout_deducts_components_and_records_effective_cost(self):
        client = Client.objects.create(name='Cliente Impresiones', phone='3001112233')
        paper = Product.objects.create(name='Papel Fotográfico Premium', cost_price=308, price=500, stock=20)
        service = Product.objects.create(name='Foto 10x15 Impresa', cost_price=0, price=1000, stock=0, is_service=True)
        ProductComponent.objects.create(parent_product=service, component_product=paper, quantity=1)

        # Add service to cart with quantity 2
        session = self.client.session
        session['cart'] = {
            str(service.id): {
                'id': service.id,
                'name': service.name,
                'price': service.price,
                'quantity': 2,
                'image': ''
            }
        }
        session.save()

        # Checkout
        res = self.client.post(reverse('checkout'), {
            'client_id': client.id,
            'payment_method': 'CASH',
        }, follow=True)
        self.assertEqual(res.status_code, 200)

        # Verify sale and item
        sale = Sale.objects.filter(client=client).last()
        self.assertIsNotNone(sale)
        self.assertEqual(sale.total, 2000)

        sale_item = sale.items.first()
        self.assertEqual(sale_item.product, service)
        self.assertEqual(sale_item.quantity, 2)
        self.assertEqual(sale_item.price, 1000)
        self.assertEqual(sale_item.cost_price, 308) # Recorded effective cost, not 0!
        self.assertEqual(sale_item.profit, 1384) # 2 * (1000 - 308)

        # Verify stock of component was deducted
        paper.refresh_from_db()
        self.assertEqual(paper.stock, 18) # 20 - 2

        # Verify service stock remained 0
        service.refresh_from_db()
        self.assertEqual(service.stock, 0)

        # Annul sale and verify stock is restored
        res_annul = self.client.post(reverse('annul_sale', args=[sale.id]), follow=True)
        self.assertEqual(res_annul.status_code, 200)

        paper.refresh_from_db()
        self.assertEqual(paper.stock, 20) # Restored back to 20

    def test_add_and_delete_product_component_views(self):
        paper = Product.objects.create(name='Papel Bond Carta', barcode='7701112223334', cost_price=50, price=100, stock=100)
        service = Product.objects.create(name='Fotocopia B/N', cost_price=0, price=200, stock=0, is_service=True)

        # Check edit_product view supplies_data context
        res_edit = self.client.get(reverse('edit_product', args=[service.id]))
        self.assertEqual(res_edit.status_code, 200)
        self.assertIn('supplies_data', res_edit.context)
        supplies_list = res_edit.context['supplies_data']
        self.assertTrue(any(s['id'] == paper.id and s['barcode'] == '7701112223334' for s in supplies_list))

        # Add component via barcode_or_search fallback
        res_add_barcode = self.client.post(reverse('add_product_component', args=[service.id]), {
            'barcode_or_search': '7701112223334',
            'quantity': 2
        })
        self.assertEqual(res_add_barcode.status_code, 302)
        self.assertTrue(res_add_barcode.url.endswith('#receta'))

        comp = ProductComponent.objects.filter(parent_product=service, component_product=paper).first()
        self.assertIsNotNone(comp)
        self.assertEqual(comp.quantity, 2)

        # Add more component via component_product_id
        res_add = self.client.post(reverse('add_product_component', args=[service.id]), {
            'component_product_id': paper.id,
            'quantity': 1
        })
        self.assertEqual(res_add.status_code, 302)
        comp.refresh_from_db()
        self.assertEqual(comp.quantity, 3)

        # Delete component via view
        res_del = self.client.post(reverse('delete_product_component', args=[comp.id]))
        self.assertEqual(res_del.status_code, 302)
        self.assertTrue(res_del.url.endswith('#receta'))
        self.assertFalse(ProductComponent.objects.filter(id=comp.id).exists())

    def test_add_product_duplicate_barcode_handled_gracefully(self):
        # Existing product
        Product.objects.create(name='Pincel Marfil #2', barcode='7706616498417', cost_price=1000, price=2000, stock=5)

        # Attempt to add another product with the exact same barcode
        response = self.client.post(reverse('add_product'), {
            'name': 'PINCEL REDONDO CERDA NARANJA #4 MARFIL',
            'barcode': '7706616498417',
            'cost_price': '0',
            'price': '0',
            'stock': '0',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ya está asignado')
        # Ensure second product was NOT created
        self.assertEqual(Product.objects.filter(barcode='7706616498417').count(), 1)

    def test_edit_product_duplicate_barcode_handled_gracefully(self):
        p1 = Product.objects.create(name='Producto A', barcode='CODE111', cost_price=100, price=200, stock=10)
        p2 = Product.objects.create(name='Producto B', barcode='CODE222', cost_price=100, price=200, stock=10)

        # Attempt to assign p1's barcode to p2
        response = self.client.post(reverse('edit_product', args=[p2.id]), {
            'name': 'Producto B Modificado',
            'barcode': 'CODE111',
            'cost_price': '100',
            'price': '200',
            'stock': '10',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No se pudo asignar el código de barras')

        p2.refresh_from_db()
        self.assertEqual(p2.barcode, 'CODE222') # Barcode was not overwritten

    def test_check_barcode_endpoint(self):
        Product.objects.create(name='Cuaderno Norma', barcode='770999888', cost_price=3000, price=5000, stock=12)

        # Checking existing barcode
        res_exists = self.client.get(reverse('check_barcode'), {'barcode': '770999888'})
        self.assertEqual(res_exists.status_code, 200)
        self.assertContains(res_exists, 'Ya asignado a:')
        self.assertContains(res_exists, 'Cuaderno Norma')

        # Checking new unused barcode
        res_new = self.client.get(reverse('check_barcode'), {'barcode': '1234567890123'})
        self.assertEqual(res_new.status_code, 200)
        self.assertContains(res_new, 'Código de barras disponible')

    def test_product_deactivation_rules_model(self):
        # Product with stock > 0 cannot be deactivated
        p = Product.objects.create(name='Pintura Acrílica', barcode='PINT1', cost_price=1000, price=2000, stock=8)
        self.assertFalse(p.can_be_deactivated)
        with self.assertRaises(ValueError):
            p.deactivate()
        p.refresh_from_db()
        self.assertTrue(p.is_active)

        # Once stock is 0, it can be deactivated
        p.stock = 0
        p.save()
        self.assertTrue(p.can_be_deactivated)
        p.deactivate()
        p.refresh_from_db()
        self.assertFalse(p.is_active)

        # Can be reactivated
        p.reactivate()
        p.refresh_from_db()
        self.assertTrue(p.is_active)

    def test_toggle_product_status_view_validations(self):
        p = Product.objects.create(name='Tijeras Escolares', barcode='TIJ1', cost_price=1500, price=2500, stock=4)

        # 1. Attempt to deactivate while having stock (should fail)
        res = self.client.post(reverse('toggle_product_status', args=[p.id]), {'action': 'deactivate'}, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'No se puede dar de baja')
        self.assertContains(res, 'aún tiene 4 unidades')
        p.refresh_from_db()
        self.assertTrue(p.is_active)

        # 2. Set stock to 0 and deactivate (should succeed)
        p.stock = 0
        p.save()
        res = self.client.post(reverse('toggle_product_status', args=[p.id]), {'action': 'deactivate'}, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'ha sido dado de baja')
        p.refresh_from_db()
        self.assertFalse(p.is_active)

        # 3. Reactivate product
        res = self.client.post(reverse('toggle_product_status', args=[p.id]), {'action': 'reactivate'}, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'ha sido reactivado')
        p.refresh_from_db()
        self.assertTrue(p.is_active)

    def test_inventory_tabs_filter_active_and_inactive(self):
        active_p = Product.objects.create(name='Goma en Barra', barcode='GOM1', cost_price=500, price=1000, stock=10, is_active=True)
        inactive_p = Product.objects.create(name='Papel Crepé Agotado', barcode='PAP1', cost_price=300, price=600, stock=0, is_active=False)

        # Default / active tab: context contains active_p, not inactive_p
        res_active = self.client.get(reverse('inventory'), {'status': 'active'})
        self.assertEqual(res_active.status_code, 200)
        self.assertIn(active_p, list(res_active.context['products']))
        self.assertNotIn(inactive_p, list(res_active.context['products']))

        # Inactive tab: context contains inactive_p, not active_p
        res_inactive = self.client.get(reverse('inventory'), {'status': 'inactive'})
        self.assertEqual(res_inactive.status_code, 200)
        self.assertIn(inactive_p, list(res_inactive.context['products']))
        self.assertNotIn(active_p, list(res_inactive.context['products']))

        # HTMX partial renders
        res_active_htmx = self.client.get(reverse('inventory'), {'status': 'active'}, headers={'hx-request': 'true'})
        self.assertContains(res_active_htmx, 'Goma en Barra')
        self.assertNotContains(res_active_htmx, 'Papel Crepé Agotado')

        res_inactive_htmx = self.client.get(reverse('inventory'), {'status': 'inactive'}, headers={'hx-request': 'true'})
        self.assertContains(res_inactive_htmx, 'Papel Crepé Agotado')
        self.assertNotContains(res_inactive_htmx, 'Goma en Barra')

    def test_pos_blocks_selling_and_scanning_inactive_products(self):
        p_active = Product.objects.create(name='Cuaderno Activo', barcode='ACT123', cost_price=2000, price=3000, stock=10, is_active=True)
        p_inactive = Product.objects.create(name='Cuaderno Dado de Baja', barcode='INA123', cost_price=2000, price=3000, stock=0, is_active=False)

        # POS search only returns active products
        res_search = self.client.get(reverse('search_products'), {'search': 'Cuaderno'})
        self.assertEqual(res_search.status_code, 200)
        self.assertContains(res_search, 'Cuaderno Activo')
        self.assertNotContains(res_search, 'Cuaderno Dado de Baja')

        # Direct camera scan rejects inactive product
        res_scan = self.client.post(reverse('scan_and_add_to_cart'), {'barcode': 'INA123'})
        self.assertEqual(res_scan.status_code, 400)
        self.assertIn('dado de baja / inactivo', res_scan.json()['message'])

        # Add to cart directly rejects inactive product
        res_add = self.client.post(reverse('add_to_cart'), {'product_id': p_inactive.id, 'quantity': 1})
        self.assertEqual(res_add.status_code, 400)

    def test_add_stock_to_inactive_product_reactivates_it(self):
        p = Product.objects.create(name='Marcador Borrable', barcode='MAR1', cost_price=1000, price=1800, stock=0, is_active=False)
        res = self.client.post(reverse('add_stock', args=[p.id]), {'quantity': '10'}, follow=True)
        self.assertEqual(res.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.stock, 10)
        self.assertTrue(p.is_active) # Reactivated automatically

class ServicesAndInventoryValuationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='admin_services', password='password123')
        self.client.login(username='admin_services', password='password123')

    def test_service_with_dummy_stock_does_not_inflate_valuation(self):
        # Even if someone assigns 9999 units to a service, valuation MUST be 0
        service = Product.objects.create(name='HISTORIAL LABORAL', price=5000, cost_price=0, stock=9999, is_service=True)
        self.assertEqual(service.cost_valuation, 0)
        self.assertEqual(service.sale_valuation, 0)
        self.assertEqual(service.profit_valuation, 0)

    def test_top_valued_products_modal_excludes_services(self):
        # Create a real physical product
        physical = Product.objects.create(name='CARPETA 4 ALAS', cost_price=2000, price=3500, stock=999, is_service=False)
        # Create a service with 9999 dummy stock (like in the user screenshot)
        service = Product.objects.create(name='Hoja de vida', cost_price=0, price=3000, stock=9999, is_service=True)

        res = self.client.get(reverse('inventory'))
        self.assertEqual(res.status_code, 200)
        top_list = res.context['top_valued_products']

        # CARPETA 4 ALAS should be in top valued
        self.assertIn(physical, top_list)
        # Hoja de vida must NOT be in top valued
        self.assertNotIn(service, top_list)

        # total_stock_units in inventory context must only count physical products (999, not 999 + 9999)
        self.assertEqual(res.context['total_stock_units'], 999)

    def test_pure_service_sale_does_not_become_negative_stock(self):
        service = Product.objects.create(name='Descarga Certificado', cost_price=0, price=2000, stock=0, is_service=True)
        
        # Deduct stock on checkout
        service.deduct_stock(1)
        service.refresh_from_db()
        self.assertEqual(service.stock, 0) # Remains 0, does not become -1

        # Restore stock on annulment
        service.restore_stock(1)
        service.refresh_from_db()
        self.assertEqual(service.stock, 0) # Remains 0

    def test_clean_services_stock_view_resets_stock_to_zero(self):
        s1 = Product.objects.create(name='COPIAS COLOR', price=300, stock=9813, is_service=True)
        s2 = Product.objects.create(name='COLOR IMPRESIÓN', price=300, stock=9946, is_service=True)
        p_real = Product.objects.create(name='Cuaderno 100H', price=3500, stock=50, is_service=False)

        res = self.client.post(reverse('clean_services_stock'), follow=True)
        self.assertEqual(res.status_code, 200)

        s1.refresh_from_db()
        s2.refresh_from_db()
        p_real.refresh_from_db()

        self.assertEqual(s1.stock, 0)
        self.assertEqual(s2.stock, 0)
        self.assertEqual(p_real.stock, 50) # Physical stock untouched

    def test_service_with_components_cannot_exceed_component_stock_in_cart(self):
        # Insumo real: Opalina Laser con stock = 5
        opalina = Product.objects.create(name='OPALINA LASER', cost_price=260, price=500, stock=5)
        # Servicio de impresión que consume 1 opalina
        impresion = Product.objects.create(name='OPALINA IMPRESIÓN COLOR', cost_price=0, price=800, stock=0, is_service=True)
        ProductComponent.objects.create(parent_product=impresion, component_product=opalina, quantity=1)

        self.assertEqual(impresion.available_service_units, 5)

        # Intento de agregar 6 unidades al carrito (mayor que las 5 disponibles de insumo)
        res_fail = self.client.post(reverse('add_to_cart'), {'product_id': impresion.id, 'quantity': 6})
        self.assertEqual(res_fail.status_code, 200)
        self.assertIn('cartError', res_fail.headers.get('HX-Trigger', ''))
        # El carrito debe seguir vacío
        self.assertEqual(self.client.session.get('cart', {}), {})

        # Agregar 5 unidades (justo el stock disponible) -> DEBE PERMITIRSE
        res_ok = self.client.post(reverse('add_to_cart'), {'product_id': impresion.id, 'quantity': 5})
        self.assertEqual(res_ok.status_code, 200)
        self.assertIn('itemAdded', res_ok.headers.get('HX-Trigger', ''))
        self.assertEqual(self.client.session['cart'][str(impresion.id)]['quantity'], 5)

        # Intento de incrementar 1 unidad más en el carrito (total 6 > 5)
        res_inc_fail = self.client.post(reverse('update_cart_item'), {'product_id': impresion.id, 'action': 'increment'})
        self.assertEqual(res_inc_fail.status_code, 200)
        self.assertIn('cartError', res_inc_fail.headers.get('HX-Trigger', ''))
        # La cantidad se mantiene en 5
        self.assertEqual(self.client.session['cart'][str(impresion.id)]['quantity'], 5)

    def test_checkout_blocks_sale_if_component_stock_exhausted(self):
        client = Client.objects.create(name='Cliente Impresiones Test', phone='3000000000')
        papel = Product.objects.create(name='Papel Foto Especial', cost_price=300, price=600, stock=2)
        servicio = Product.objects.create(name='Foto 10x15 Especial', cost_price=0, price=1000, stock=0, is_service=True)
        ProductComponent.objects.create(parent_product=servicio, component_product=papel, quantity=1)

        # Carrito con 3 unidades cuando solo hay 2 de papel
        session = self.client.session
        session['cart'] = {
            str(servicio.id): {
                'id': servicio.id,
                'name': servicio.name,
                'price': servicio.price,
                'quantity': 3
            }
        }
        session.save()

        # Checkout debe fallar por insumos insuficientes
        res = self.client.post(reverse('checkout'), {
            'client_id': client.id,
            'payment_method': 'CASH'
        }, follow=True)

        self.assertEqual(res.status_code, 200)
        # La venta no debe haberse creado
        self.assertEqual(Sale.objects.filter(client=client).count(), 0)
        # El stock del insumo debe seguir intacto en 2 (no en -1)
        papel.refresh_from_db()
        self.assertEqual(papel.stock, 2)


class FinalConsumerAndFastCheckoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='pos_cashier', password='password123')
        self.client.login(username='pos_cashier', password='password123')

    def test_default_client_auto_detection_and_creation(self):
        # Cuando existe CONTADO POS, get_default_client lo detecta
        client_contado = Client.objects.create(name='CONTADO POS')
        default_client = Client.get_default_client()
        self.assertEqual(default_client.id, client_contado.id)
        self.assertTrue(default_client.is_default)

    def test_pos_view_includes_default_client(self):
        Client.objects.create(name='CONTADO POS', is_default=True)
        res = self.client.get(reverse('pos'))
        self.assertEqual(res.status_code, 200)
        self.assertIn('default_client', res.context)
        self.assertEqual(res.context['default_client'].name, 'CONTADO POS')

    def test_fast_checkout_without_selecting_client_defaults_to_contado_pos(self):
        contado_pos = Client.objects.create(name='CONTADO POS', is_default=True)
        prod = Product.objects.create(name='1L COCACOLA', cost_price=2000, price=4000, stock=10)

        # Carrito con producto
        session = self.client.session
        session['cart'] = {
            str(prod.id): {
                'id': prod.id,
                'name': prod.name,
                'price': prod.price,
                'quantity': 1
            }
        }
        session.save()

        # Checkout sin enviar client_id (flujo rápido de mostrador)
        res = self.client.post(reverse('checkout'), {
            'client_id': '',  # Vacío
            'payment_method': ''
        }, follow=True)

        self.assertEqual(res.status_code, 200)
        sale = Sale.objects.order_by('-id').first()
        self.assertIsNotNone(sale)
        self.assertEqual(sale.client.id, contado_pos.id)
        self.assertEqual(sale.payment_method, 'CASH')
        self.assertTrue(sale.is_paid)
        self.assertEqual(sale.total, 4000)

        # Stock descontado
        prod.refresh_from_db()
        self.assertEqual(prod.stock, 9)

    def test_set_default_client_view(self):
        c1 = Client.objects.create(name='CONTADO POS', is_default=True)
        c2 = Client.objects.create(name='CONSUMIDOR FINAL CAJA 2', is_default=False)

        res = self.client.get(reverse('set_default_client', args=[c2.id]), follow=True)
        self.assertEqual(res.status_code, 200)

        c1.refresh_from_db()
        c2.refresh_from_db()
        self.assertFalse(c1.is_default)
        self.assertTrue(c2.is_default)
        self.assertEqual(Client.get_default_client().id, c2.id)







