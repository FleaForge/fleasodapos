from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Sum, Q, F
from django.utils import timezone
from django.contrib import messages
from django.http import HttpResponse
from .models import Product, Client, Sale, SaleItem, Payment
from django.template.loader import get_template
from xhtml2pdf import pisa

from django.contrib.auth.decorators import login_required

# Helper for cart
def get_cart_data(session):
    cart = session.get('cart', {})
    cart_items = []
    total = 0
    for parsed_id, item in cart.items():
        subtotal = item['quantity'] * item['price']
        total += subtotal
        # item is a dict, we can add subtotal for display
        item['subtotal'] = subtotal 
        cart_items.append(item)
    return cart_items, total

@login_required
def dashboard(request):
    now = timezone.now()
    # Monthly sales (current month)
    monthly_sales = Sale.objects.filter(
        date__year=now.year,
        date__month=now.month
    ).aggregate(Sum('total'))['total__sum'] or 0
    
    today_sales = Sale.objects.filter(date__date=now.date()).aggregate(Sum('total'))['total__sum'] or 0
    
    # Calculate detailed debt: Sum of (Credit Sales Total) - Sum of (All Payments)
    # This ensures the portfolio decreases as clients make payments
    total_credit_sales = Sale.objects.filter(payment_method='CREDIT').aggregate(Sum('total'))['total__sum'] or 0
    total_payments = Payment.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    debt_pending = total_credit_sales - total_payments
    
    context = {
        'total_sales': monthly_sales,
        'today_sales': today_sales,
        'debt_pending': debt_pending,
    }
    return render(request, 'pos/dashboard.html', context)

@login_required
def inventory(request):
    products = Product.objects.all().order_by('-id')
    if request.htmx:
        query = request.GET.get('search')
        if query:
            products = products.filter(name__icontains=query)
        return render(request, 'pos/partials/product_list.html', {'products': products})
    return render(request, 'pos/inventory.html', {'products': products})

@login_required
def clients(request):
    clients_list = Client.objects.all().order_by('-created_at')
    if request.htmx:
        query = request.GET.get('search')
        if query:
            clients_list = clients_list.filter(name__icontains=query)
        return render(request, 'pos/partials/client_list.html', {'clients': clients_list})
    return render(request, 'pos/clients.html', {'clients': clients_list})

@login_required
def client_statement(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    sales = Sale.objects.filter(client=client).order_by('-date')
    
    # Calculate summary fields for context
    total_credit = sales.filter(payment_method='CREDIT').aggregate(Sum('total'))['total__sum'] or 0
    # Payment query is done below but we need sum now
    total_paid = Payment.objects.filter(client=client).aggregate(Sum('amount'))['amount__sum'] or 0
    current_debt = total_credit - total_paid

    # Create unified timeline
    timeline = []
    
    # Add Credit Sales to timeline
    for sale in sales.filter(payment_method='CREDIT'):
        timeline.append({
            'type': 'SALE',
            'date': sale.date,
            'amount': sale.total,
            'ref': f"Factura #{sale.id}",
            'items': sale.items.all(), # Prefetch would be better but for simple app is ok
            'object': sale
        })
        
    # Add Payments to timeline
    payments = Payment.objects.filter(client=client).order_by('-date')
    for payment in payments:
        timeline.append({
            'type': 'PAYMENT',
            'date': payment.date,
            'amount': payment.amount,
            'ref': payment.note or "Abono",
            'object': payment
        })
        
    # Sort by date ascending to calculate running balance
    timeline.sort(key=lambda x: x['date'])
    
    running_balance = 0
    calculated_timeline = []
    
    for event in timeline:
        if event['type'] == 'SALE':
            running_balance += event['amount']
            event['debit'] = event['amount']
            event['credit'] = 0
        else:
            running_balance -= event['amount']
            event['debit'] = 0
            event['credit'] = event['amount']
        
        event['balance'] = running_balance
        calculated_timeline.append(event)

    context = {
        'client': client,
        'timeline': calculated_timeline,  # Chronological order (oldest first)
        'total_credit': total_credit,
        'total_paid': total_paid,
        'current_debt': current_debt,
        'now': timezone.now()
    }
    return render(request, 'pos/client_statement.html', context)

def client_public_statement(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    sales = Sale.objects.filter(client=client).order_by('-date')
    payments = Payment.objects.filter(client=client).order_by('-date')
    
    total_credit = sales.filter(payment_method='CREDIT').aggregate(Sum('total'))['total__sum'] or 0
    total_paid = payments.aggregate(Sum('amount'))['amount__sum'] or 0
    current_debt = total_credit - total_paid

    timeline = []
    for sale in sales.filter(payment_method='CREDIT'):
        timeline.append({ 'type': 'SALE', 'date': sale.date, 'amount': sale.total, 'ref': f"Factura #{sale.id}", 'items': sale.items.all(), 'object': sale })
        
    for payment in payments:
        timeline.append({ 'type': 'PAYMENT', 'date': payment.date, 'amount': payment.amount, 'ref': payment.note or "Abono", 'object': payment })
        
    timeline.sort(key=lambda x: x['date'])
    running_balance = 0
    calculated_timeline = []
    for event in timeline:
        if event['type'] == 'SALE':
            running_balance += event['amount']
            event['debit'] = event['amount']
            event['credit'] = 0
        else:
            running_balance -= event['amount']
            event['debit'] = 0
            event['credit'] = event['amount']
        event['balance'] = running_balance
        calculated_timeline.append(event)

    context = {
        'client': client,
        'timeline': calculated_timeline,  # Chronological order (oldest first)
        'total_credit': total_credit,
        'total_paid': total_paid,
        'current_debt': current_debt,
        'now': timezone.now(),
        'is_public': True
    }
    return render(request, 'pos/client_statement.html', context)

@login_required
def add_payment(request, client_id):
    if request.method == 'POST':
        client = get_object_or_404(Client, id=client_id)
        amount = request.POST.get('amount')
        note = request.POST.get('note')
        
        Payment.objects.create(
            client=client,
            amount=amount,
            note=note
        )
        messages.success(request, 'Pago registrado')
    return redirect('client_statement', client_id=client_id)

@login_required
def pos(request):
    clients = Client.objects.all()
    cart_items, cart_total = get_cart_data(request.session)
    return render(request, 'pos/pos.html', {
        'clients': clients, 
        'cart_items': cart_items, 
        'cart_total': cart_total
    })

@login_required
def search_products(request):
    query = request.GET.get('search')
    if query:
        products = Product.objects.filter(name__icontains=query)
    else:
        products = []
    return render(request, 'pos/partials/pos_product_search.html', {'products': products})

@login_required
def add_to_cart(request):
    cart = request.session.get('cart', {})
    product_id = request.POST.get('product_id')
    
    if not product_id:
        return HttpResponse(status=400)
    
    # Get custom quantity (default 1)
    try:
        quantity_add = int(request.POST.get('quantity', 1))
    except ValueError:
        quantity_add = 1

    product = get_object_or_404(Product, id=product_id)
    product_id_str = str(product_id) # JSON keys are strings
    
    if product_id_str in cart:
        cart[product_id_str]['quantity'] += quantity_add
    else:
        cart[product_id_str] = {
            'id': product.id,
            'name': product.name,
            'price': product.price,
            'quantity': quantity_add,
        }
    
    request.session['cart'] = cart
    
    cart_items, cart_total = get_cart_data(request.session)
    return render(request, 'pos/partials/cart_items.html', {'cart_items': cart_items, 'cart_total': cart_total})

@login_required
def update_cart_item(request):
    cart = request.session.get('cart', {})
    product_id = request.POST.get('product_id')
    action = request.POST.get('action') # 'increment', 'decrement', 'remove'
    
    product_id_str = str(product_id)
    
    if product_id_str and product_id_str in cart:
        if action == 'increment':
            cart[product_id_str]['quantity'] += 1
        elif action == 'decrement':
            cart[product_id_str]['quantity'] -= 1
            if cart[product_id_str]['quantity'] < 1:
                del cart[product_id_str]
        elif action == 'remove':
            del cart[product_id_str]
            
    request.session['cart'] = cart
    cart_items, cart_total = get_cart_data(request.session)
    return render(request, 'pos/partials/cart_items.html', {'cart_items': cart_items, 'cart_total': cart_total})

@login_required
def clear_cart(request):
    request.session['cart'] = {}
    return render(request, 'pos/partials/cart_items.html', {'cart_items': [], 'cart_total': 0})

@login_required
def checkout(request):
    if request.method == 'POST':
        client_id = request.POST.get('client_id')
        payment_method = request.POST.get('payment_method')
        cart = request.session.get('cart', {})
        
        if not cart or not client_id:
            messages.error(request, 'Carrito vacío o cliente no seleccionado')
            return redirect('pos')
            
        client = get_object_or_404(Client, id=client_id)
        
        # Recalculate total just to be safe
        total = sum(item['price'] * item['quantity'] for item in cart.values())
        
        # Custom Date Handling
        created_at_str = request.POST.get('created_at')
        sale_date = timezone.now()
        
        note = request.POST.get('note', '')

        if created_at_str:
            try:
                # datetime-local format is YYYY-MM-DDTHH:MM
                # We need to make it aware potentially, or just let Django handle the naive datetime if USE_TZ=True it might warn.
                # Simplest is using standard parsing
                dt = timezone.datetime.strptime(created_at_str, '%Y-%m-%dT%H:%M')
                sale_date = timezone.make_aware(dt)
            except (ValueError, TypeError):
                pass
        
        sale = Sale.objects.create(
            client=client,
            payment_method=payment_method,
            total=total,
            is_paid=(payment_method == 'CASH'),
            date=sale_date,
            note=note
        )
        
        for item in cart.values():
            product = get_object_or_404(Product, id=item['id'])
            SaleItem.objects.create(
                sale=sale,
                product=product,
                quantity=item['quantity'],
                price=item['price']
            )
            # Update stock
            product.stock -= item['quantity']
            product.save()
            
        request.session['cart'] = {}
        messages.success(request, f'Venta #{sale.id} registrada correctamente')
        return redirect('pos')
        
    return redirect('pos')

@login_required
def add_product(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        barcode = request.POST.get('barcode')
        price = request.POST.get('price')
        stock = request.POST.get('stock')
        
        Product.objects.create(
            name=name,
            barcode=barcode,
            price=price,
            stock=stock
        )
        messages.success(request, 'Producto agregado correctamente.')
    return redirect('inventory')

@login_required
def add_client(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        phone = request.POST.get('phone')
        email = request.POST.get('email')
        address = request.POST.get('address')
        
        try:
            initial_debt = int(request.POST.get('initial_debt', 0) or 0)
        except ValueError:
            initial_debt = 0
            
        client = Client.objects.create(
            name=name,
            phone=phone,
            email=email,
            address=address
        )
        
        # Handle Initial Debt / Historical Balance
        if initial_debt > 0:
            # Get or Create system product for opening balances
            # Use price=0 as base, we will override in SaleItem
            debt_product, _ = Product.objects.get_or_create(
                name="SALDO ANTERIOR",
                defaults={'price': 0, 'stock': 0, 'barcode': 'SYS-DEBT'}
            )
            
            # Create the Debt Sale
            sale = Sale.objects.create(
                client=client,
                payment_method='CREDIT',
                total=initial_debt,
                is_paid=False,
                date=timezone.now() # Or ideally allow date selection, but NOW is fine for "Opening"
            )
            
            SaleItem.objects.create(
                sale=sale,
                product=debt_product,
                quantity=1,
                price=initial_debt
            )
            
        messages.success(request, 'Cliente agregado correctamente.')
    return redirect('clients')

@login_required
def search_clients(request):
    # HTMX sends the input name as the key. We handled 'search' but 'client_search_display' is coming from POS.
    query = request.GET.get('search') or request.GET.get('client_search_display') or ''
    
    if query:
        clients = Client.objects.filter(
            Q(name__icontains=query) | Q(phone__icontains=query)
        )[:10] # Limit results
    else:
        clients = []
    return render(request, 'pos/partials/client_search_dropdown.html', {'clients': clients})

# Public Views
def public_search(request):
    return render(request, 'pos/public_search.html')

def public_check_debt(request):
    if request.method == 'POST':
        phone = request.POST.get('phone')
        # Removing non-numeric chars could be good practice
        client = Client.objects.filter(phone=phone).first()
        
        if client:
             # Reuse logic or template? Let's use a simplified partial
             # Calculate balance
             credit_sales = client.sale_set.filter(payment_method='CREDIT').aggregate(Sum('total'))['total__sum'] or 0
             payments = client.payments.aggregate(Sum('amount'))['amount__sum'] or 0
             balance = credit_sales - payments
             
             last_sales = client.sale_set.order_by('-date')[:5]
             
             context = {
                 'client': client,
                 'balance': balance,
                 'last_sales': last_sales,
             }
             return render(request, 'pos/partials/public_result.html', context)
        else:
            return HttpResponse('<div class="bg-red-100 text-red-700 p-4 rounded-xl text-center">No encontramos un cliente con ese número.</div>')
@login_required
def report_analytics(request):
    # Date Filtering
    date_start_str = request.GET.get('date_start')
    date_end_str = request.GET.get('date_end')
    
    today = timezone.now().date()
    
    if date_start_str:
        date_start = timezone.datetime.strptime(date_start_str, '%Y-%m-%d').date()
    else:
        date_start = today - timezone.timedelta(days=30)
        
    if date_end_str:
        date_end = timezone.datetime.strptime(date_end_str, '%Y-%m-%d').date()
    else:
        date_end = today

    # Filter Querysets
    # Use __date__range for inclusive filtering on DateTimeField
    sales_qs = Sale.objects.filter(date__date__gte=date_start, date__date__lte=date_end).order_by('-date')

    # 1. Sales by Product (Quantity)
    # Filter items by the filtered sales
    product_sales = SaleItem.objects.filter(sale__in=sales_qs).values('product__name').annotate(
        total_qty=Sum('quantity')
    ).order_by('-total_qty')[:10] 
    
    labels_products = [item['product__name'] for item in product_sales]
    data_products = [item['total_qty'] for item in product_sales]
    
    # 2. Daily Sales Trend
    daily_sales = sales_qs.values('date__date').annotate(
        daily_total=Sum('total')
    ).order_by('date__date')
    
    labels_dates = [item['date__date'].strftime('%d/%m') for item in daily_sales]
    data_sales = [int(item['daily_total']) for item in daily_sales]
    
    # 3. KPI Metrics
    total_period = sales_qs.aggregate(Sum('total'))['total__sum'] or 0
    count_period = sales_qs.count()
    # Handle Division by zero
    avg_ticket = total_period / count_period if count_period > 0 else 0
    
    cash_total = sales_qs.filter(payment_method='CASH').aggregate(Sum('total'))['total__sum'] or 0
    credit_total = sales_qs.filter(payment_method='CREDIT').aggregate(Sum('total'))['total__sum'] or 0

    context = {
        'labels_products': labels_products,
        'data_products': data_products,
        'labels_dates': labels_dates,
        'data_sales': data_sales,
        'invoices': sales_qs, # Pass the detailed list
        'date_start': date_start.strftime('%Y-%m-%d'),
        'date_end': date_end.strftime('%Y-%m-%d'),
        'total_period': total_period,
        'avg_ticket': avg_ticket,
        'cash_total': cash_total,
        'credit_total': credit_total
    }
    return render(request, 'pos/reports.html', context)

@login_required
def invoice_detail(request, sale_id):
    sale = get_object_or_404(Sale, id=sale_id)
    return render(request, 'pos/invoice_detail.html', {'sale': sale, 'now': timezone.now()})

def client_statement_pdf(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    sales = Sale.objects.filter(client=client).order_by('-date')
    
    total_credit = sales.filter(payment_method='CREDIT').aggregate(Sum('total'))['total__sum'] or 0
    total_paid = Payment.objects.filter(client=client).aggregate(Sum('amount'))['amount__sum'] or 0
    current_debt = total_credit - total_paid

    timeline = []
    
    for sale in sales.filter(payment_method='CREDIT'):
        timeline.append({
            'type': 'SALE',
            'date': sale.date,
            'amount': sale.total,
            'ref': f"Factura #{sale.id}",
            'items': sale.items.all(),
            'object': sale
        })
        
    payments = Payment.objects.filter(client=client).order_by('-date')
    for payment in payments:
        timeline.append({
            'type': 'PAYMENT',
            'date': payment.date,
            'amount': payment.amount,
            'ref': payment.note or "Abono",
            'object': payment
        })
        
    timeline.sort(key=lambda x: x['date'])
    
    running_balance = 0
    calculated_timeline = []
    
    # 1. Calculate running balance forward
    for event in timeline:
        if event['type'] == 'SALE':
            running_balance += event['amount']
            event['debit'] = event['amount']
            event['credit'] = 0
        else:
            running_balance -= event['amount']
            event['debit'] = 0
            event['credit'] = event['amount']
        
        event['balance'] = running_balance
        calculated_timeline.append(event)

    # 2. Filter logic: Find the last time balance was close to 0 (allow for small float diffs if needed, but 0 is safer for now)
    # If the user has a current debt, we want the history starting AFTER the last 0 balance.
    # If the user is currently 0, we might want to show the last cycle? Or just empty. 
    # Usually "what they owe" implies current cycle.
    
    cutoff_index = -1
    for i, event in enumerate(calculated_timeline):
        # We check if balance is 0. If so, the next item is the start of new cycle.
        if abs(event['balance']) < 0.01:
            cutoff_index = i
            
    # Slice the timeline to keep only events occurring AFTER the cutoff
    if cutoff_index != -1 and cutoff_index < len(calculated_timeline) - 1:
        # Check if we are at the very end (balance is 0 currently)
        # If current debt is 0, we can show just the "Settled" state or the last cycle? 
        # User said "solo salir lo que debe y lo que abono". 
        # If debt is 0, maybe showing nothing is weird. Let's assume we show active items.
        
        if current_debt > 0.01:
             calculated_timeline = calculated_timeline[cutoff_index+1:]
        else:
             # If completely paid off, maybe show the last cycle? 
             # Or as per user "reset", it might mean show nothing or just header. 
             # Let's keep the logic simple: Show Active Cycle.
             # If balance is 0, list might be empty.
             calculated_timeline = [] 

    # Reverse for display (actives usually show newest first, but for PDF statement printed sometimes chronological is better? 
    # The existing code reversed it. Let's keep it reversed or check user intent.
    # User said "reset... only what he owes".
    # Existing 'reversed_timeline' implies newest first.
    
    context = {
        'client': client,
        'timeline': calculated_timeline,  # Chronological order (oldest first)
        'total_credit': total_credit,
        'total_paid': total_paid,
        'current_debt': current_debt,
        'now': timezone.now(),
        # Pass full URL for static/media if needed (xhtml2pdf handles relative usually if configured, but let's keep simple)
    }
    
    template_path = 'pos/pdf/client_statement_pdf.html'
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Estado_Cuenta_{client.name}.pdf"'
    
    template = get_template(template_path)
    html = template.render(context)
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response

def service_worker(request):
    from django.conf import settings
    import os
    
    # Adjust path assuming static is in root
    sw_path = os.path.join(settings.BASE_DIR, 'static', 'sw.js')
    
    try:
        with open(sw_path, 'r') as f:
            content = f.read()
        return HttpResponse(content, content_type='application/javascript')
    except FileNotFoundError:
        return HttpResponse("console.error('Service Worker NOT FOUND');", content_type='application/javascript')

def manifest(request):
    from django.conf import settings
    import os
    
    manifest_path = os.path.join(settings.BASE_DIR, 'static', 'manifest.json')
    
    try:
        with open(manifest_path, 'r') as f:
            content = f.read()
        return HttpResponse(content, content_type='application/json')
    except FileNotFoundError:
        return HttpResponse("{}", content_type='application/json')

@login_required
def edit_product(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        product.name = request.POST.get('name')
        product.barcode = request.POST.get('barcode')
        product.price = request.POST.get('price')
        
        stock_val = request.POST.get('stock')
        if stock_val:
             product.stock = stock_val
             
        product.save()
        messages.success(request, 'Producto actualizado correctamente.')
        return redirect('inventory')
        
    return render(request, 'pos/edit_product.html', {'product': product})

@login_required
def add_stock(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        try:
            quantity = int(request.POST.get('quantity'))
            if quantity > 0:
                product.stock += quantity
                product.save()
                messages.success(request, f'Se agregaron {quantity} unidades a {product.name}')
            else:
                 messages.error(request, 'La cantidad debe ser mayor a 0')
        except ValueError:
            messages.error(request, 'Cantidad inválida')
            
    return redirect('inventory')

@login_required
def edit_client(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    if request.method == 'POST':
        client.name = request.POST.get('name')
        client.phone = request.POST.get('phone')
        client.email = request.POST.get('email')
        client.address = request.POST.get('address')
        client.save()
        messages.success(request, 'Cliente actualizado correctamente.')
        return redirect('clients')
    return render(request, 'pos/edit_client.html', {'client': client})

@login_required
def edit_sale(request, sale_id):
    sale = get_object_or_404(Sale, id=sale_id)
    if request.method == 'POST':
        # Edit Client
        client_id = request.POST.get('client_id')
        if client_id:
            client = get_object_or_404(Client, id=client_id)
            sale.client = client
            
        # Edit Date
        date_str = request.POST.get('date')
        if date_str:
            try:
                # Expecting YYYY-MM-DDTHH:MM
                dt = timezone.datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
                sale.date = timezone.make_aware(dt)
            except (ValueError, TypeError):
                 messages.error(request, 'Formato de fecha inválido')
        
        sale.note = request.POST.get('note', '')
        sale.save()
        messages.success(request, 'Factura actualizada correctamente.')
        return redirect('invoice_detail', sale_id=sale.id)
    
    clients = Client.objects.all()
    # Format date for datetime-local input
    local_date = timezone.localtime(sale.date).strftime('%Y-%m-%dT%H:%M')
    return render(request, 'pos/edit_sale.html', {'sale': sale, 'clients': clients, 'formatted_date': local_date})

@login_required
def search_products_for_sale(request, sale_id):
    """Search products to add to a sale"""
    query = request.GET.get('search', '')
    sale = get_object_or_404(Sale, id=sale_id)
    
    if query:
        products = Product.objects.filter(name__icontains=query)[:10]
    else:
        products = []
    
    return render(request, 'pos/partials/product_search_sale.html', {
        'products': products,
        'sale_id': sale_id,
        'search_query': query
    })

@login_required
def add_product_to_sale(request, sale_id):
    """Add a product to an existing sale"""
    if request.method == 'POST':
        sale = get_object_or_404(Sale, id=sale_id)
        product_id = request.POST.get('product_id')
        product = get_object_or_404(Product, id=product_id)
        
        # Check if product already exists in sale
        existing_item = sale.items.filter(product=product).first()
        
        if existing_item:
            # Increment quantity
            existing_item.quantity += 1
            existing_item.save()
        else:
            # Create new item
            SaleItem.objects.create(
                sale=sale,
                product=product,
                quantity=1,
                price=product.price
            )
        
        # Update stock
        product.stock -= 1
        product.save()
        
        # Recalculate total
        sale.total = sum(item.subtotal for item in sale.items.all())
        sale.save()
        
        # Return updated items list
        items = sale.items.all()
        return render(request, 'pos/partials/sale_items.html', {
            'items': items,
            'sale_id': sale_id,
            'total': sale.total
        })
    
    return HttpResponse(status=400)

@login_required
def update_sale_item(request, sale_id, item_id):
    """Update quantity or remove a sale item"""
    if request.method == 'POST':
        sale = get_object_or_404(Sale, id=sale_id)
        item = get_object_or_404(SaleItem, id=item_id, sale=sale)
        action = request.POST.get('action')
        
        if action == 'increment':
            # Increase quantity
            item.quantity += 1
            item.save()
            # Decrease stock
            item.product.stock -= 1
            item.product.save()
            
        elif action == 'decrement':
            if item.quantity > 1:
                # Decrease quantity
                item.quantity -= 1
                item.save()
                # Increase stock
                item.product.stock += 1
                item.product.save()
            else:
                # Remove item if quantity would be 0
                item.product.stock += item.quantity
                item.product.save()
                item.delete()
                
        elif action == 'remove':
            # Return stock
            item.product.stock += item.quantity
            item.product.save()
            # Delete item
            item.delete()
        
        # Recalculate total
        sale.total = sum(i.subtotal for i in sale.items.all())
        sale.save()
        
        # Return updated items list
        items = sale.items.all()
        return render(request, 'pos/partials/sale_items.html', {
            'items': items,
            'sale_id': sale_id,
            'total': sale.total
        })
    
    return HttpResponse(status=400)
