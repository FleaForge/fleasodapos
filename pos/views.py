from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.db import IntegrityError
from django.db.models import Sum, Q, F, Count
from django.utils import timezone
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from .models import Product, ProductPriceHistory, Client, Sale, SaleItem, Payment, ProductComponent
from django.template.loader import get_template, render_to_string
from xhtml2pdf import pisa
import json

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
    today = now.date()
    
    # 1. Ventas de Hoy (Excluye ajustes contables de cartera)
    today_sales_qs = Sale.objects.filter(date__date=today, is_annulled=False, is_adjustment=False)
    today_sales = today_sales_qs.aggregate(Sum('total'))['total__sum'] or 0
    today_sales_count = today_sales_qs.count()
    
    # 2. Ventas del Mes (Excluye ajustes contables de cartera)
    month_sales_qs = Sale.objects.filter(
        date__year=now.year,
        date__month=now.month,
        is_annulled=False,
        is_adjustment=False
    )
    monthly_sales = month_sales_qs.aggregate(Sum('total'))['total__sum'] or 0
    monthly_sales_count = month_sales_qs.count()
    monthly_cash = month_sales_qs.filter(payment_method='CASH').aggregate(Sum('total'))['total__sum'] or 0
    monthly_credit = month_sales_qs.filter(payment_method='CREDIT').aggregate(Sum('total'))['total__sum'] or 0
    
    # 3. Recaudos / Abonos recibidos este mes
    monthly_payments = Payment.objects.filter(
        date__year=now.year,
        date__month=now.month,
        is_annulled=False,
        is_consolidation=False
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    # 4. Cartera Total Pendiente (Incluye créditos comerciales y ajustes pendientes)
    total_credit_sales = Sale.objects.filter(payment_method='CREDIT', is_annulled=False).aggregate(Sum('total'))['total__sum'] or 0
    total_payments = Payment.objects.filter(is_annulled=False).aggregate(Sum('amount'))['amount__sum'] or 0
    debt_pending = max(0, total_credit_sales - total_payments)
    
    # 5. Inventario & Clientes (Artículos activos en operación)
    active_products_qs = Product.objects.filter(is_active=True)
    total_products = active_products_qs.count()
    physical_products_qs = active_products_qs.filter(is_service=False)
    total_stock_units = physical_products_qs.aggregate(Sum('stock'))['stock__sum'] or 0
    all_products = list(active_products_qs)
    total_inventory_valuation = sum(p.sale_valuation for p in all_products)
    total_inventory_cost = sum(p.cost_valuation for p in all_products)
    low_stock_products = physical_products_qs.filter(stock__lte=5).order_by('stock')[:5]
    low_stock_count = physical_products_qs.filter(stock__lte=5).count()
    total_clients = Client.objects.count()
    
    # 6. Tendencia de Ventas (Últimos 14 Días comerciales)
    fourteen_days_ago = today - timezone.timedelta(days=13)
    sales_14_days = Sale.objects.filter(
        date__date__gte=fourteen_days_ago,
        date__date__lte=today,
        is_annulled=False,
        is_adjustment=False
    ).values('date__date').annotate(daily_sum=Sum('total'))
    daily_dict = {item['date__date']: item['daily_sum'] for item in sales_14_days}
    
    labels_trend = []
    data_trend = []
    for i in range(14):
        d = fourteen_days_ago + timezone.timedelta(days=i)
        labels_trend.append(d.strftime('%d/%m'))
        data_trend.append(int(daily_dict.get(d, 0)))
        
    # 7. Composición de Flujo / Proceso Financiero
    flow_labels = ['Ventas de Contado', 'Abonos Recaudados', 'Cartera Pendiente']
    flow_data = [int(monthly_cash), int(monthly_payments), int(debt_pending)]
    
    # 8. Top 5 Productos Más Vendidos
    top_items = SaleItem.objects.filter(sale__is_annulled=False).values('product__name').annotate(
        total_qty=Sum('quantity'),
        total_revenue=Sum(F('quantity') * F('price'))
    ).order_by('-total_qty')[:5]
    
    top_prod_labels = [item['product__name'] for item in top_items]
    top_prod_data = [item['total_qty'] for item in top_items]
    
    # 9. Últimas Operaciones (Facturas Recientes)
    recent_sales = Sale.objects.filter(is_annulled=False).select_related('client').order_by('-date')[:6]
    
    context = {
        'total_sales': monthly_sales,
        'monthly_sales_count': monthly_sales_count,
        'today_sales': today_sales,
        'today_sales_count': today_sales_count,
        'debt_pending': debt_pending,
        'monthly_cash': monthly_cash,
        'monthly_credit': monthly_credit,
        'monthly_payments': monthly_payments,
        'total_products': total_products,
        'total_stock_units': total_stock_units,
        'total_inventory_valuation': total_inventory_valuation,
        'total_inventory_cost': total_inventory_cost,
        'low_stock_count': low_stock_count,
        'low_stock_products': low_stock_products,
        'total_clients': total_clients,
        'recent_sales': recent_sales,
        
        # Chart JSON data
        'labels_trend_json': json.dumps(labels_trend),
        'data_trend_json': json.dumps(data_trend),
        'flow_labels_json': json.dumps(flow_labels),
        'flow_data_json': json.dumps(flow_data),
        'top_prod_labels_json': json.dumps(top_prod_labels),
        'top_prod_data_json': json.dumps(top_prod_data),
        'now': now,
    }
    return render(request, 'pos/dashboard.html', context)

@login_required
def inventory(request):
    status_filter = request.GET.get('status', 'active')
    
    all_qs = Product.objects.all()
    active_count = all_qs.filter(is_active=True).count()
    inactive_count = all_qs.filter(is_active=False).count()
    all_count = all_qs.count()

    if status_filter == 'inactive':
        products = all_qs.filter(is_active=False).order_by('-id')
    elif status_filter == 'all':
        products = all_qs.order_by('-is_active', '-id')
    else:
        status_filter = 'active'
        products = all_qs.filter(is_active=True).order_by('-id')

    if request.htmx:
        query = request.GET.get('search', '').strip()
        if query:
            products = products.filter(Q(name__icontains=query) | Q(barcode__icontains=query))
        return render(request, 'pos/partials/product_list.html', {
            'products': products,
            'current_status': status_filter
        })

    # Resumen de inventario y rentabilidad (enfocado en artículos activos)
    active_products = all_qs.filter(is_active=True)
    total_products = active_count
    
    # Métricas físicas de stock (excluyen servicios para no distorsionar conteos de bodega)
    physical_products = active_products.filter(is_service=False)
    low_stock_count = physical_products.filter(stock__gt=0, stock__lte=5).count()
    out_of_stock_count = physical_products.filter(stock__lte=0).count()
    in_stock_count = physical_products.filter(stock__gt=5).count()
    total_stock_units = physical_products.aggregate(Sum('stock'))['stock__sum'] or 0

    total_cost_valuation = sum(p.cost_valuation for p in active_products)
    total_sale_valuation = sum(p.sale_valuation for p in active_products)
    total_potential_profit = total_sale_valuation - total_cost_valuation
    avg_markup = round((total_potential_profit / total_cost_valuation * 100), 1) if total_cost_valuation > 0 else 0
    avg_margin = round((total_potential_profit / total_sale_valuation * 100), 1) if total_sale_valuation > 0 else 0

    # Top 10 productos con mayor valor comercial en bodega (Capital físico real, excluye servicios)
    top_valued_products = sorted(
        [p for p in active_products if p.sale_valuation > 0 and not p.is_service and not p.has_components],
        key=lambda x: x.sale_valuation,
        reverse=True
    )[:10]
    for p in top_valued_products:
        p.valuation_share = round((p.sale_valuation / total_sale_valuation * 100), 1) if total_sale_valuation > 0 else 0.0

    services_with_stock_count = active_products.filter(Q(is_service=True) | Q(components__isnull=False), stock__gt=0).distinct().count()

    recent_price_changes = ProductPriceHistory.objects.select_related('product', 'user').order_by('-date')[:6]

    context = {
        'products': products,
        'current_status': status_filter,
        'active_count': active_count,
        'inactive_count': inactive_count,
        'all_count': all_count,
        'total_products': total_products,
        'total_stock_units': total_stock_units,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'in_stock_count': in_stock_count,
        'total_cost_valuation': total_cost_valuation,
        'total_sale_valuation': total_sale_valuation,
        'total_potential_profit': total_potential_profit,
        'avg_markup': avg_markup,
        'avg_margin': avg_margin,
        'top_valued_products': top_valued_products,
        'services_with_stock_count': services_with_stock_count,
        'recent_price_changes': recent_price_changes,
    }
    return render(request, 'pos/inventory.html', context)

@login_required
def clients(request):
    clients_list = Client.objects.all().order_by('-created_at')
    if request.htmx:
        query = request.GET.get('search')
        if query:
            clients_list = clients_list.filter(name__icontains=query)
        return render(request, 'pos/partials/client_list.html', {'clients': clients_list})
    return render(request, 'pos/clients.html', {'clients': clients_list})

def reconcile_client_allocations(client):
    """
    Conciliación automática estricta FIFO (First-In, First-Out) de cartera:
    Distribuye todos los pagos activos (no anulados) del cliente sobre
    sus ventas a crédito activas (no anuladas), desde la más antigua a la más nueva.
    Garantiza que:
    1. Si client.balance <= 0, todas las facturas a crédito quedan saldadas con pending_balance == 0.
    2. Las facturas más antiguas se liquidan al 100% antes de abonar a las siguientes.
    3. Ninguna factura queda con saldo pendiente ficticio si existen pagos registrados.
    4. La suma de pending_balance de todas las facturas coincide exactamente con client.balance (cuando balance > 0).
    """
    from .models import Sale, Payment, PaymentAllocation
    from django.db import transaction

    with transaction.atomic():
        credit_sales = list(Sale.objects.filter(
            client=client, 
            payment_method='CREDIT', 
            is_annulled=False
        ).order_by('date', 'id'))
        
        payments = list(Payment.objects.filter(
            client=client, 
            is_annulled=False
        ).order_by('date', 'id'))

        # Limpiar asignaciones previas del cliente para recalcular limpiamente según FIFO
        PaymentAllocation.objects.filter(sale__client=client).delete()
        PaymentAllocation.objects.filter(payment__client=client).delete()

        if not credit_sales or not payments:
            return

        sale_pending = {s.id: s.total for s in credit_sales}
        sale_idx = 0
        num_sales = len(credit_sales)

        for payment in payments:
            payment_rem = payment.amount
            while payment_rem > 0 and sale_idx < num_sales:
                current_sale = credit_sales[sale_idx]
                needed = sale_pending[current_sale.id]

                if needed <= 0:
                    sale_idx += 1
                    continue

                alloc_amount = min(payment_rem, needed)
                PaymentAllocation.objects.create(
                    payment=payment,
                    sale=current_sale,
                    amount=alloc_amount
                )
                sale_pending[current_sale.id] -= alloc_amount
                payment_rem -= alloc_amount

                if sale_pending[current_sale.id] <= 0:
                    sale_idx += 1

def consolidate_client_debt_after_payment(client, source_payment):
    """
    Cuando se registra un abono y aún queda saldo pendiente:
    - Liquida las facturas/productos anteriores que existían hasta ese abono.
    - Deja un único Ajuste de Cartera con el saldo total restante.
    - Las nuevas compras se agregarán como nuevas cuentas a partir de ese punto.
    """
    reconcile_client_allocations(client)
    
    # Obtener todas las cuentas que quedaron con saldo pendiente tras el abono
    pending_sales = list(
        client.sale_set.filter(payment_method='CREDIT', is_annulled=False)
        .exclude(consolidation_source_payment=source_payment)
        .order_by('date', 'id')
    )
    unpaid_sales = [s for s in pending_sales if s.pending_balance > 0]
    total_remaining = sum(s.pending_balance for s in unpaid_sales)
    
    if total_remaining <= 0 or not unpaid_sales:
        return None
        
    now = timezone.now()
    
    # 1. Pago de transferencia interna para saldar por completo las cuentas anteriores
    consolidation_payment = Payment.objects.create(
        client=client,
        amount=total_remaining,
        date=now + timezone.timedelta(milliseconds=500),
        is_consolidation=True,
        consolidation_source_payment=source_payment,
        note=f"Liquidación y consolidación de cuentas anteriores tras abono de ${source_payment.amount:,}"
    )
    
    # 2. Nuevo Ajuste de Cartera con el saldo consolidado de la deuda
    consolidation_sale = Sale.objects.create(
        client=client,
        payment_method='CREDIT',
        is_adjustment=True,
        consolidation_source_payment=source_payment,
        total=total_remaining,
        date=now + timezone.timedelta(seconds=1),
        note=f"Saldo consolidado de cartera tras abono de ${source_payment.amount:,}"
    )
    
    # 3. Recalcular las asignaciones FIFO para que las cuentas viejas queden en 0 y solo quede el nuevo ajuste
    reconcile_client_allocations(client)
    return consolidation_sale

def get_account_timeline(client, exclude_annulled=False):
    sales = Sale.objects.filter(client=client).order_by('date')
    if exclude_annulled:
        sales = sales.filter(is_annulled=False)
    
    payments = Payment.objects.filter(client=client).order_by('date')
    if exclude_annulled:
        payments = payments.filter(is_annulled=False)

    timeline = []
    
    # Add Credit Sales
    for sale in sales:
        if sale.payment_method == 'CREDIT':
            timeline.append({
                'type': 'SALE',
                'date': sale.date,
                'amount': sale.total,
                'ref': f"Ajuste de Cartera #{sale.id}" if getattr(sale, 'is_adjustment', False) else f"Factura #{sale.id}",
                'items': sale.items.all(),
                'object': sale,
                'is_annulled': sale.is_annulled
            })
            if sale.is_annulled:
                # Insert a credit note to neutralize the annulled invoice
                timeline.append({
                    'type': 'ANNULMENT',
                    'date': sale.date + timezone.timedelta(seconds=1), # Order it right after
                    'amount': sale.total,
                    'ref': f"Nota Crédito (Anul. Factura #{sale.id})",
                    'object': sale
                })
        
    # Add Payments
    for payment in payments:
        timeline.append({
            'type': 'PAYMENT',
            'date': payment.date,
            'amount': payment.amount,
            'ref': payment.note or "Abono",
            'object': payment
        })
        if getattr(payment, 'is_annulled', False) and not exclude_annulled:
            timeline.append({
                'type': 'PAYMENT_ANNULMENT',
                'date': payment.date + timezone.timedelta(seconds=2),
                'amount': payment.amount,
                'ref': "Anulación de Abono",
                'object': payment
            })
        
    # Sort chronologically (Oldest first)
    timeline.sort(key=lambda x: x['date'])
    
    running_balance = 0
    cutoff_index = -1
    
    calculated_timeline = []
    for i, event in enumerate(timeline):
        if event['type'] == 'SALE':
            running_balance += event['amount']
            event['debit'] = event['amount']
            event['credit'] = 0
        elif event['type'] == 'ANNULMENT':
            running_balance -= event['amount']
            event['debit'] = 0
            event['credit'] = event['amount']
        elif event['type'] == 'PAYMENT':
            running_balance -= event['amount']
            event['debit'] = 0
            event['credit'] = event['amount']
        elif event['type'] == 'PAYMENT_ANNULMENT':
            running_balance += event['amount']
            event['debit'] = event['amount']
            event['credit'] = 0
        
        event['balance'] = running_balance
        calculated_timeline.append(event)
        
    oldest_unpaid = None
    for sale in client.sale_set.filter(payment_method='CREDIT', is_annulled=False).order_by('date', 'id'):
        if sale.pending_balance > 0:
            oldest_unpaid = sale
            break
            
    if oldest_unpaid:
        for i, event in enumerate(calculated_timeline):
            if event['type'] == 'SALE' and event['object'].id == oldest_unpaid.id:
                cutoff_index = i - 1
                break
    else:
        if len(calculated_timeline) > 0 and abs(calculated_timeline[-1]['balance']) < 1:
            cutoff_index = len(calculated_timeline) - 1
            
    return calculated_timeline, cutoff_index

@login_required
def client_statement(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    
    # 1. Reconciliación estricta FIFO de cartera
    reconcile_client_allocations(client)
    
    full_timeline, cutoff_index = get_account_timeline(client)
    
    # Split timeline into History and Active
    previous_balance = 0
    if cutoff_index != -1:
        history_timeline = full_timeline[:cutoff_index+1]
        active_timeline = full_timeline[cutoff_index+1:]
        if history_timeline:
            previous_balance = history_timeline[-1]['balance']
    else:
        history_timeline = []
        active_timeline = full_timeline

    real_balance = client.balance
    current_debt = max(0, real_balance)
    credit_balance = abs(real_balance) if real_balance < 0 else 0
    
    active_credit = sum(e['amount'] for e in active_timeline if e['type'] == 'SALE')
    active_paid = sum(e['amount'] for e in active_timeline if e['type'] == 'PAYMENT')

    if current_debt == 0:
        pending_sales = []
    else:
        sales_list = list(
            client.sale_set.filter(payment_method='CREDIT', is_annulled=False)
            .prefetch_related('items__product', 'allocations__payment')
            .order_by('date', 'id')
        )
        pending_sales = [s for s in sales_list if s.pending_balance > 0]
    
    recent_payments = client.payments.filter(is_annulled=False, is_consolidation=False).prefetch_related('allocations__sale').order_by('-date')[:15]

    context = {
        'client': client,
        'timeline': active_timeline, 
        'history_timeline': history_timeline,
        'previous_balance': previous_balance,
        'pending_sales': pending_sales,
        'recent_payments': recent_payments,
        'total_credit': active_credit,
        'total_paid': active_paid,
        'current_debt': current_debt,
        'credit_balance': credit_balance,
        'now': timezone.now(),
        'is_public': False
    }
    return render(request, 'pos/client_statement.html', context)

def client_public_statement(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    
    reconcile_client_allocations(client)
    
    full_timeline, cutoff_index = get_account_timeline(client, exclude_annulled=True)
    
    previous_balance = 0
    if cutoff_index != -1:
        history_timeline = full_timeline[:cutoff_index+1]
        active_timeline = full_timeline[cutoff_index+1:]
        if history_timeline:
            previous_balance = history_timeline[-1]['balance']
    else:
        history_timeline = []
        active_timeline = full_timeline
        
    real_balance = client.balance
    current_debt = max(0, real_balance)
    credit_balance = abs(real_balance) if real_balance < 0 else 0
    
    active_credit = sum(e['amount'] for e in active_timeline if e['type'] == 'SALE')
    active_paid = sum(e['amount'] for e in active_timeline if e['type'] == 'PAYMENT')

    if current_debt == 0:
        pending_sales = []
    else:
        sales_list = list(
            client.sale_set.filter(payment_method='CREDIT', is_annulled=False)
            .prefetch_related('items__product', 'allocations__payment')
            .order_by('date', 'id')
        )
        pending_sales = [s for s in sales_list if s.pending_balance > 0]

    recent_payments = client.payments.filter(is_annulled=False, is_consolidation=False).prefetch_related('allocations__sale').order_by('-date')[:15]

    context = {
        'client': client,
        'timeline': active_timeline,
        'previous_balance': previous_balance,
        'pending_sales': pending_sales,
        'recent_payments': recent_payments,
        'total_credit': active_credit,
        'total_paid': active_paid,
        'current_debt': current_debt,
        'credit_balance': credit_balance,
        'now': timezone.now(),
        'is_public': True
    }
    return render(request, 'pos/client_statement.html', context)

@login_required
def add_payment(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    
    reconcile_client_allocations(client)
    
    if request.method == 'POST':
        amount = int(request.POST.get('amount', 0))
        note = request.POST.get('note', '').strip()
        
        if amount <= 0:
            messages.error(request, 'El monto recibido debe ser mayor a cero.')
            return redirect('add_payment', client_id=client.id)
        
        # Registrar el pago real en caja
        payment = Payment.objects.create(
            client=client,
            amount=amount,
            note=note or "Abono a cartera"
        )
        
        # Reconciliar en cascada estricta FIFO de la deuda más vieja a la más nueva
        reconcile_client_allocations(client)
        
        new_balance = client.balance
        if new_balance > 0:
            # Consolidar cuentas anteriores dejando un único Ajuste de Cartera con el saldo total restante
            consolidate_client_debt_after_payment(client, payment)
            messages.success(request, f'Pago de ${amount:,} registrado correctamente. Se liquidaron las cuentas anteriores y se consolidó el saldo restante de ${new_balance:,} en un Ajuste de Cartera.')
        else:
            messages.success(request, f'¡Excelente! Se registró el pago de ${amount:,}. La cuenta del cliente ha quedado totalmente en PAZ Y SALVO (Saldo: $0).')
            
        return redirect('client_statement', client_id=client_id)
    
    current_debt = max(0, client.balance)
    pending_sales = [s for s in client.sale_set.filter(payment_method='CREDIT', is_annulled=False).order_by('date', 'id') if s.pending_balance > 0]
    
    return render(request, 'pos/add_payment.html', {
        'client': client, 
        'pending_sales': pending_sales,
        'current_debt': current_debt
    })

@login_required
def adjust_client_balance(request, client_id):
    """
    Permite registrar un Saldo Inicial o Ajuste de Deuda sin necesidad de
    crear productos ficticios en el inventario ni afectar estadísticas de ventas.
    """
    client = get_object_or_404(Client, id=client_id)
    if request.method == 'POST':
        amount = int(request.POST.get('amount', 0))
        concept = request.POST.get('concept', '').strip() or 'Saldo inicial / Ajuste de cartera'
        
        if amount <= 0:
            messages.error(request, 'El monto del saldo/ajuste debe ser mayor a cero.')
            return redirect('client_statement', client_id=client.id)
            
        Sale.objects.create(
            client=client,
            payment_method='CREDIT',
            total=amount,
            is_paid=False,
            is_adjustment=True,
            note=f"Ajuste Contable: {concept}",
            date=timezone.now()
        )
        reconcile_client_allocations(client)
        messages.success(request, f'Saldo / Ajuste de cartera de ${amount:,} asignado a {client.name}. Inventario no afectado.')
        return redirect('client_statement', client_id=client.id)
    return redirect('client_statement', client_id=client.id)

@login_required
def annul_payment(request, payment_id):
    if request.method == 'POST':
        payment = get_object_or_404(Payment, id=payment_id)
        if not payment.is_annulled:
            payment.is_annulled = True
            payment.save()
            
            # Anular también cualquier pago o ajuste de consolidación generado por este abono
            Payment.objects.filter(consolidation_source_payment=payment).update(is_annulled=True)
            Sale.objects.filter(consolidation_source_payment=payment).update(is_annulled=True)
            
            # Recalcular asignaciones tras la anulación
            reconcile_client_allocations(payment.client)
            messages.success(request, 'Pago y consolidación anulados correctamente. Las cuentas anteriores se han reactivado.')
        return redirect('client_statement', client_id=payment.client_id)
    return redirect('dashboard')

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
    query = request.GET.get('search', '').strip()
    if query:
        products = Product.objects.filter(is_active=True).filter(
            Q(name__icontains=query) | Q(barcode__icontains=query)
        ).order_by('name')
    else:
        products = []
    return render(request, 'pos/partials/pos_product_search.html', {'products': products})

@login_required
def scan_and_add_to_cart(request):
    """
    Escaneo directo con cámara en el POS:
    Busca por código de barras exacto o ID, suma 1 unidad al carrito y retorna el HTML actualizado del carrito.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Método no permitido'}, status=405)
        
    barcode = request.POST.get('barcode', '').strip()
    if not barcode:
        return JsonResponse({'success': False, 'message': 'Código vacío'}, status=400)
        
    product = Product.objects.filter(barcode=barcode).first()
    if not product and barcode.isdigit():
        product = Product.objects.filter(id=int(barcode)).first()
        
    if not product:
        return JsonResponse({
            'success': False, 
            'message': f'Producto con código "{barcode}" no encontrado en inventario.'
        }, status=404)
        
    if not product.is_active:
        return JsonResponse({
            'success': False,
            'message': f'El producto "{product.name}" está dado de baja / inactivo. No se puede vender.'
        }, status=400)
        
    cart = request.session.get('cart', {})
    product_id_str = str(product.id)
    current_qty = cart.get(product_id_str, {}).get('quantity', 0)
    target_qty = current_qty + 1

    can_sell, reason = product.can_sell(target_qty)
    if not can_sell:
        return JsonResponse({
            'success': False,
            'message': reason
        }, status=400)
    
    if product_id_str in cart:
        cart[product_id_str]['quantity'] = target_qty
    else:
        cart[product_id_str] = {
            'id': product.id,
            'name': product.name,
            'price': product.price,
            'quantity': 1,
        }
    request.session['cart'] = cart
    
    cart_items, cart_total = get_cart_data(request.session)
    cart_html = render_to_string('pos/partials/cart_item_rows.html', {
        'cart_items': cart_items, 
        'cart_total': cart_total
    }, request=request)
    
    return JsonResponse({
        'success': True,
        'product_id': product.id,
        'product_name': product.name,
        'price': product.price,
        'cart_count': len(cart_items),
        'cart_total': cart_total,
        'cart_html': cart_html
    })

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

    if quantity_add < 1:
        quantity_add = 1

    product = get_object_or_404(Product, id=product_id)
    if not product.is_active:
        return HttpResponse('El producto está dado de baja / inactivo y no se puede vender.', status=400)
        
    product_id_str = str(product_id) # JSON keys are strings
    current_qty = cart.get(product_id_str, {}).get('quantity', 0)
    target_qty = current_qty + quantity_add

    # Validar disponibilidad real de insumos o stock físico
    can_sell, reason = product.can_sell(target_qty)
    if not can_sell:
        cart_items, cart_total = get_cart_data(request.session)
        response = render(request, 'pos/partials/cart_items.html', {'cart_items': cart_items, 'cart_total': cart_total})
        import json
        response['HX-Trigger'] = json.dumps({
            'cartError': {
                'message': reason
            }
        })
        return response
    
    if product_id_str in cart:
        cart[product_id_str]['quantity'] = target_qty
    else:
        cart[product_id_str] = {
            'id': product.id,
            'name': product.name,
            'price': product.price,
            'quantity': target_qty,
        }
    
    request.session['cart'] = cart
    
    cart_items, cart_total = get_cart_data(request.session)
    response = render(request, 'pos/partials/cart_items.html', {'cart_items': cart_items, 'cart_total': cart_total})
    import json
    response['HX-Trigger'] = json.dumps({
        'itemAdded': {
            'name': product.name,
            'price': product.price,
            'total': cart_total
        }
    })
    return response

@login_required
def update_cart_item(request):
    cart = request.session.get('cart', {})
    product_id = request.POST.get('product_id')
    action = request.POST.get('action') # 'increment', 'decrement', 'remove'
    
    product_id_str = str(product_id)
    
    if product_id_str and product_id_str in cart:
        if action == 'increment':
            product = Product.objects.filter(id=product_id).first()
            if product:
                can_sell, reason = product.can_sell(cart[product_id_str]['quantity'] + 1)
                if not can_sell:
                    cart_items, cart_total = get_cart_data(request.session)
                    response = render(request, 'pos/partials/cart_items.html', {'cart_items': cart_items, 'cart_total': cart_total})
                    import json
                    response['HX-Trigger'] = json.dumps({'cartError': {'message': reason}})
                    return response
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

        # Validar disponibilidad real de stock e insumos para todos los ítems del carrito antes de facturar
        for item in cart.values():
            product = get_object_or_404(Product, id=item['id'])
            can_sell, reason = product.can_sell(item['quantity'])
            if not can_sell:
                messages.error(request, f'No se pudo completar la venta: {reason}')
                return redirect('pos')
        
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
                price=item['price'],
                cost_price=product.effective_cost
            )
            # Update stock (deducts components if product has recipe/supplies, or direct stock)
            product.deduct_stock(item['quantity'])
            
        request.session['cart'] = {}
        messages.success(request, f'Venta #{sale.id} registrada correctamente')
        return redirect('pos')
        
    return redirect('pos')

@login_required
def check_barcode(request):
    barcode = request.GET.get('barcode', '').strip()
    product_id = request.GET.get('product_id')
    
    if not barcode:
        return HttpResponse("")
        
    qs = Product.objects.filter(barcode=barcode)
    if product_id:
        try:
            qs = qs.exclude(id=int(product_id))
        except (ValueError, TypeError):
            pass
            
    existing = qs.first()
    if existing:
        return HttpResponse(
            f'<div class="mt-1.5 p-2.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-bold flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1.5 shadow-2xs animate-pulse">'
            f'  <div class="flex items-center gap-1.5">'
            f'    <span class="text-rose-500 text-sm">⚠️</span>'
            f'    <span>Ya asignado a: <strong>{existing.name}</strong> (Stock: {existing.stock})</span>'
            f'  </div>'
            f'  <a href="/inventory/edit/{existing.id}/" class="inline-flex items-center gap-1 text-[11px] font-black text-rose-800 hover:text-rose-950 underline self-start sm:self-auto">Ver / Editar producto ➔</a>'
            f'</div>'
        )
    return HttpResponse(
        '<div class="mt-1.5 text-[11px] font-bold text-emerald-600 flex items-center gap-1">'
        '  <span>✓ Código de barras disponible</span>'
        '</div>'
    )

@login_required
def add_product(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        barcode = request.POST.get('barcode', '').strip() or None
        is_service = request.POST.get('is_service') in ('true', 'on', '1')
        
        # Validar si ya existe un producto con este código de barras
        if barcode:
            existing = Product.objects.filter(barcode=barcode).first()
            if existing:
                messages.error(
                    request, 
                    f'No se pudo registrar "{name}": El código de barras "{barcode}" ya está asignado a "{existing.name}" (ID #{existing.id}, Stock actual: {existing.stock}). No se permiten códigos duplicados.'
                )
                return redirect('inventory')
        
        try:
            cost_price = int(float(request.POST.get('cost_price') or 0))
        except (ValueError, TypeError):
            cost_price = 0
            
        try:
            price = int(float(request.POST.get('price') or 0))
        except (ValueError, TypeError):
            price = 0
            
        try:
            stock = int(request.POST.get('stock') or 0)
        except (ValueError, TypeError):
            stock = 0
            
        if is_service:
            stock = 0
            
        image = request.FILES.get('image')

        try:
            product = Product.objects.create(
                name=name,
                barcode=barcode,
                cost_price=cost_price,
                price=price,
                stock=stock,
                is_service=is_service,
                image=image
            )
        except IntegrityError:
            messages.error(
                request, 
                f'Error de integridad: El código de barras "{barcode}" ya existe en el sistema.'
            )
            return redirect('inventory')
        
        # Registrar en Historial de Precios
        ProductPriceHistory.objects.create(
            product=product,
            old_price=0,
            new_price=price,
            old_cost_price=0,
            new_cost_price=cost_price,
            user=request.user if request.user.is_authenticated else None,
            reason=request.POST.get('price_change_reason', '').strip() or 'Precio inicial de creación'
        )
        
        messages.success(request, f'Producto "{product.name}" agregado correctamente.')
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
             credit_sales = client.sale_set.filter(payment_method='CREDIT', is_annulled=False).aggregate(Sum('total'))['total__sum'] or 0
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
    # Search & Filter Parameters
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'all') # 'all', 'active', 'annulled'
    method_filter = request.GET.get('method', 'all') # 'all', 'CASH', 'CREDIT'
    client_id_filter = request.GET.get('client_id', '').strip()

    # Date Filtering
    date_start_str = request.GET.get('date_start')
    date_end_str = request.GET.get('date_end')
    
    today = timezone.now().date()
    
    if date_start_str:
        try:
            date_start = timezone.datetime.strptime(date_start_str, '%Y-%m-%d').date()
        except ValueError:
            date_start = today - timezone.timedelta(days=30)
    else:
        date_start = today - timezone.timedelta(days=30)
        
    if date_end_str:
        try:
            date_end = timezone.datetime.strptime(date_end_str, '%Y-%m-%d').date()
        except ValueError:
            date_end = today
    else:
        date_end = today

    all_clients = Client.objects.all().order_by('name')
    selected_client = None
    if client_id_filter and client_id_filter.isdigit():
        selected_client = Client.objects.filter(id=int(client_id_filter)).first()

    # Active sales query for KPIs and charts in selected period (commercial sales only)
    active_period_sales = Sale.objects.filter(
        date__date__gte=date_start,
        date__date__lte=date_end,
        is_annulled=False,
        is_adjustment=False
    )

    # Invoices query for listing / searching (includes sales & adjustments)
    sales_qs = Sale.objects.all().select_related('client').prefetch_related('items__product')

    # Apply Client Filter if selected
    if selected_client:
        active_period_sales = active_period_sales.filter(client=selected_client)
        sales_qs = sales_qs.filter(client=selected_client)

    # Adjustments total in period (tracked separately from trading revenue)
    adjustments_qs = Sale.objects.filter(
        date__date__gte=date_start,
        date__date__lte=date_end,
        is_annulled=False,
        is_adjustment=True
    )
    if selected_client:
        adjustments_qs = adjustments_qs.filter(client=selected_client)
    adjustments_total = adjustments_qs.aggregate(Sum('total'))['total__sum'] or 0

    # Apply search filter
    clean_id = search_query.lstrip('#')
    if search_query:
        search_filter = Q(client__name__icontains=search_query) | Q(client__phone__icontains=search_query)
        if clean_id.isdigit():
            search_filter |= Q(id=int(clean_id))
        sales_qs = sales_qs.filter(search_filter)
        # Only restrict dates if explicit checkbox or when no search query
        if request.GET.get('filter_dates_with_search') == '1':
            sales_qs = sales_qs.filter(date__date__gte=date_start, date__date__lte=date_end)
    else:
        sales_qs = sales_qs.filter(date__date__gte=date_start, date__date__lte=date_end)

    # Apply status filter
    if status_filter == 'active':
        sales_qs = sales_qs.filter(is_annulled=False)
    elif status_filter == 'annulled':
        sales_qs = sales_qs.filter(is_annulled=True)

    # Apply payment method filter
    if method_filter in ['CASH', 'CREDIT']:
        sales_qs = sales_qs.filter(payment_method=method_filter)

    sales_qs = sales_qs.order_by('-date')

    # Handle HTMX live search / partial update
    is_htmx = getattr(request, 'htmx', False) or request.headers.get('HX-Request') == 'true'
    if is_htmx and request.GET.get('table_only') == '1':
        return render(request, 'pos/partials/invoice_table.html', {
            'invoices': sales_qs,
            'search_query': search_query,
            'status_filter': status_filter,
            'method_filter': method_filter,
        })

    # 1. Period Items & Financial / Profitability Aggregations
    period_items = SaleItem.objects.filter(sale__in=active_period_sales).select_related('product', 'sale')
    
    total_cost_period = 0
    product_perf = {}
    
    for item in period_items:
        qty = item.quantity
        rev = item.subtotal
        cost_unit = item.effective_cost_price
        c = qty * cost_unit
        p = rev - c
        total_cost_period += c
        
        pid = item.product_id
        if pid not in product_perf:
            product_perf[pid] = {
                'id': pid,
                'name': item.product.name if item.product else 'Artículo sin nombre',
                'barcode': item.product.barcode if (item.product and item.product.barcode) else None,
                'image': item.product.image.url if (item.product and item.product.image) else None,
                'qty': 0,
                'revenue': 0,
                'cost': 0,
                'profit': 0,
            }
        product_perf[pid]['qty'] += qty
        product_perf[pid]['revenue'] += rev
        product_perf[pid]['cost'] += c
        product_perf[pid]['profit'] += p

    for p in product_perf.values():
        p['margin_profit'] = round((p['profit'] / p['revenue'] * 100), 1) if p['revenue'] > 0 else 0.0
        p['margin_markup'] = round((p['profit'] / p['cost'] * 100), 1) if p['cost'] > 0 else (100.0 if p['profit'] > 0 else 0.0)

    # Top 10 by Profit ($ COP)
    top_profitable_products = sorted(product_perf.values(), key=lambda x: x['profit'], reverse=True)[:10]
    # Top 10 by Units (Volume)
    top_volume_products = sorted(product_perf.values(), key=lambda x: x['qty'], reverse=True)[:10]

    labels_products = [p['name'] for p in top_volume_products]
    data_products = [p['qty'] for p in top_volume_products]

    # 2. Daily Sales & Profit Trend for period
    daily_map = {}
    for sale in active_period_sales.prefetch_related('items__product'):
        d = sale.date.date()
        if d not in daily_map:
            daily_map[d] = {'sales': 0, 'cost': 0, 'profit': 0}
        daily_map[d]['sales'] += sale.total
        daily_map[d]['cost'] += sale.total_cost
        daily_map[d]['profit'] += sale.total_profit

    sorted_days = sorted(daily_map.keys())
    labels_dates = [d.strftime('%d/%m') for d in sorted_days]
    data_sales = [int(daily_map[d]['sales']) for d in sorted_days]
    data_profits = [int(daily_map[d]['profit']) for d in sorted_days]

    # 3. KPI Metrics for period
    total_period = active_period_sales.aggregate(Sum('total'))['total__sum'] or 0
    count_period = active_period_sales.count()
    avg_ticket = total_period / count_period if count_period > 0 else 0
    
    total_profit_period = total_period - total_cost_period
    margin_profit_pct = round((total_profit_period / total_period * 100), 1) if total_period > 0 else 0.0
    margin_markup_pct = round((total_profit_period / total_cost_period * 100), 1) if total_cost_period > 0 else (100.0 if total_profit_period > 0 else 0.0)
    avg_profit_per_ticket = round(total_profit_period / count_period) if count_period > 0 else 0
    star_product = top_profitable_products[0] if top_profitable_products else None

    cash_total = active_period_sales.filter(payment_method='CASH').aggregate(Sum('total'))['total__sum'] or 0
    credit_total = active_period_sales.filter(payment_method='CREDIT').aggregate(Sum('total'))['total__sum'] or 0
    annulled_period = Sale.objects.filter(
        date__date__gte=date_start, 
        date__date__lte=date_end, 
        is_annulled=True
    )
    if selected_client:
        annulled_period = annulled_period.filter(client=selected_client)
    annulled_period_count = annulled_period.count()

    # 4. Top Clients Ranking (when general view) or Client Profile (when selected)
    top_clients = []
    client_metrics = {}
    if selected_client:
        client_metrics = {
            'balance': selected_client.balance,
            'lifetime_total': Sale.objects.filter(client=selected_client, is_annulled=False, is_adjustment=False).aggregate(Sum('total'))['total__sum'] or 0,
            'lifetime_count': Sale.objects.filter(client=selected_client, is_annulled=False, is_adjustment=False).count(),
        }
    else:
        # General view: compute Top 10 Clients by total purchases in the period
        period_clients = Sale.objects.filter(
            date__date__gte=date_start,
            date__date__lte=date_end,
            is_annulled=False,
            is_adjustment=False
        ).values('client__id', 'client__name', 'client__phone').annotate(
            total_spent=Sum('total'),
            invoices_count=Count('id'),
            credit_spent=Sum('total', filter=Q(payment_method='CREDIT')),
            cash_spent=Sum('total', filter=Q(payment_method='CASH'))
        ).order_by('-total_spent')[:10]

        for tc in period_clients:
            cl = Client.objects.filter(id=tc['client__id']).first()
            tc['current_balance'] = cl.balance if cl else 0
            top_clients.append(tc)

    context = {
        'all_clients': all_clients,
        'selected_client': selected_client,
        'selected_client_id': client_id_filter,
        'client_metrics': client_metrics,
        'top_clients': top_clients,
        'labels_products': labels_products,
        'data_products': data_products,
        'labels_dates': labels_dates,
        'data_sales': data_sales,
        'data_profits': data_profits,
        'invoices': sales_qs,
        'date_start': date_start.strftime('%Y-%m-%d'),
        'date_end': date_end.strftime('%Y-%m-%d'),
        'total_period': total_period,
        'count_period': count_period,
        'avg_ticket': avg_ticket,
        'cash_total': cash_total,
        'credit_total': credit_total,
        'adjustments_total': adjustments_total,
        'annulled_period': annulled_period_count,
        # Rentabilidad y Métricas Financieras
        'total_cost_period': total_cost_period,
        'total_profit_period': total_profit_period,
        'margin_profit_pct': margin_profit_pct,
        'margin_markup_pct': margin_markup_pct,
        'avg_profit_per_ticket': avg_profit_per_ticket,
        'top_profitable_products': top_profitable_products,
        'star_product': star_product,
        'search_query': search_query,
        'status_filter': status_filter,
        'method_filter': method_filter,
        'filter_dates_with_search': request.GET.get('filter_dates_with_search', ''),
    }
    return render(request, 'pos/reports.html', context)

@login_required
def invoice_detail(request, sale_id):
    sale = get_object_or_404(Sale, id=sale_id)
    return render(request, 'pos/invoice_detail.html', {'sale': sale, 'now': timezone.now()})

def client_statement_pdf(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    
    reconcile_client_allocations(client)
    
    full_timeline, cutoff_index = get_account_timeline(client)
    
    if cutoff_index != -1:
        active_timeline = full_timeline[cutoff_index+1:]
    else:
        active_timeline = full_timeline
        
    real_balance = client.balance
    current_debt = max(0, real_balance)
    credit_balance = abs(real_balance) if real_balance < 0 else 0
    active_credit = sum(e['amount'] for e in active_timeline if e['type'] == 'SALE')
    active_paid = sum(e['amount'] for e in active_timeline if e['type'] == 'PAYMENT')

    if current_debt == 0:
        pending_sales = []
    else:
        pending_sales = [
            s for s in client.sale_set.filter(payment_method='CREDIT', is_annulled=False)
            .prefetch_related('items__product', 'allocations__payment')
            .order_by('date', 'id')
            if s.pending_balance > 0
        ]

    recent_payments = client.payments.filter(is_annulled=False, is_consolidation=False).prefetch_related('allocations__sale').order_by('-date')[:15]

    context = {
        'client': client,
        'pending_sales': pending_sales,
        'recent_payments': recent_payments,
        'total_credit': active_credit,
        'total_paid': active_paid,
        'current_debt': current_debt,
        'credit_balance': credit_balance,
        'now': timezone.now(),
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

@login_required
def inventory_valuation_pdf(request):
    products = Product.objects.filter(is_active=True).order_by('name')
    total_products = products.count()
    physical_products = products.filter(is_service=False)
    total_stock_units = physical_products.aggregate(Sum('stock'))['stock__sum'] or 0
    total_cost_valuation = sum(p.cost_valuation for p in products)
    total_sale_valuation = sum(p.sale_valuation for p in products)
    total_potential_profit = total_sale_valuation - total_cost_valuation
    avg_markup = round((total_potential_profit / total_cost_valuation * 100), 1) if total_cost_valuation > 0 else 0

    context = {
        'products': products,
        'total_products': total_products,
        'total_stock_units': total_stock_units,
        'total_cost_valuation': total_cost_valuation,
        'total_sale_valuation': total_sale_valuation,
        'total_potential_profit': total_potential_profit,
        'avg_markup': avg_markup,
        'now': timezone.now(),
    }
    
    template_path = 'pos/pdf/inventory_valuation_pdf.html'
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="Valorizacion_Inventario.pdf"'
    
    template = get_template(template_path)
    html = template.render(context)
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Error generando PDF de valorización: <pre>' + html + '</pre>')
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
        old_price = product.price
        old_cost_price = product.cost_price
        
        product.name = request.POST.get('name', '').strip()
        barcode_val = request.POST.get('barcode', '').strip()
        new_barcode = barcode_val if barcode_val else None
        
        # Validar si el nuevo código de barras ya pertenece a otro producto
        if new_barcode:
            duplicate = Product.objects.filter(barcode=new_barcode).exclude(id=product.id).first()
            if duplicate:
                messages.error(
                    request,
                    f'No se pudo asignar el código de barras "{new_barcode}": ya está asignado al producto "{duplicate.name}" (ID #{duplicate.id}). No se permiten códigos duplicados.'
                )
                return redirect('edit_product', product_id=product.id)
                
        product.barcode = new_barcode
        
        try:
            new_cost_price = int(float(request.POST.get('cost_price') or 0))
        except (ValueError, TypeError):
            new_cost_price = old_cost_price
            
        try:
            new_price = int(float(request.POST.get('price') or 0))
        except (ValueError, TypeError):
            new_price = old_price
            
        product.cost_price = new_cost_price
        product.price = new_price
        
        stock_val = request.POST.get('stock')
        if stock_val is not None and stock_val != '':
            try:
                product.stock = int(stock_val)
            except ValueError:
                pass
                
        if 'image' in request.FILES:
            if product.image:
                try:
                    product.image.delete(save=False)
                except Exception:
                    pass
            product.image = request.FILES['image']
        elif request.POST.get('clear_image') == 'true':
            if product.image:
                try:
                    product.image.delete(save=False)
                except Exception:
                    pass
            product.image = None

        product.is_service = request.POST.get('is_service') in ('true', 'on', '1') or product.has_components

        # Manejo de estado activo / dado de baja
        is_active_val = request.POST.get('is_active')
        if is_active_val is not None:
            wants_active = is_active_val in ('true', 'on', '1', 'True')
            if not wants_active and product.stock > 0:
                messages.error(
                    request,
                    f'No se puede dar de baja "{product.name}": aún tiene {product.stock} unidades en inventario. '
                    f'El producto debe estar agotado (stock = 0) para marcarlo como inactivo.'
                )
                return redirect('edit_product', product_id=product.id)
            product.is_active = wants_active

        try:
            product.save()
        except IntegrityError:
            messages.error(request, f'Error de integridad: El código de barras "{new_barcode}" ya existe en otro producto.')
            return redirect('edit_product', product_id=product.id)
        
        # Detectar si hubo cambio de precio o costo
        if old_price != new_price or old_cost_price != new_cost_price:
            reason = request.POST.get('price_change_reason', '').strip()
            if not reason:
                parts = []
                if old_price != new_price:
                    parts.append(f"Venta: ${old_price:,} ➔ ${new_price:,}")
                if old_cost_price != new_cost_price:
                    parts.append(f"Costo: ${old_cost_price:,} ➔ ${new_cost_price:,}")
                reason = "Actualización de precios (" + ", ".join(parts) + ")"
                
            ProductPriceHistory.objects.create(
                product=product,
                old_price=old_price,
                new_price=new_price,
                old_cost_price=old_cost_price,
                new_cost_price=new_cost_price,
                user=request.user if request.user.is_authenticated else None,
                reason=reason
            )
            messages.success(request, 'Producto actualizado y cambio de precio registrado en el historial.')
        else:
            messages.success(request, 'Producto actualizado correctamente.')
            
        return redirect('inventory')
        
    price_history = product.price_history.select_related('user').order_by('-date')
    components = product.components.select_related('component_product').all()
    available_supplies = Product.objects.filter(is_active=True).exclude(id=product.id).order_by('name')
    return render(request, 'pos/edit_product.html', {
        'product': product,
        'price_history': price_history,
        'components': components,
        'available_supplies': available_supplies,
    })

@login_required
def add_product_component(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        component_id = request.POST.get('component_product_id')
        quantity_str = request.POST.get('quantity', '1')
        try:
            quantity = max(1, int(quantity_str))
        except (ValueError, TypeError):
            quantity = 1
            
        if component_id:
            try:
                component_product = Product.objects.get(id=component_id)
                if component_product.id != product.id:
                    comp, created = ProductComponent.objects.get_or_create(
                        parent_product=product,
                        component_product=component_product,
                        defaults={'quantity': quantity}
                    )
                    if not created:
                        comp.quantity += quantity
                        comp.save(update_fields=['quantity'])
                    
                    # Al vincular insumos, el producto pasa automáticamente a ser un servicio/preparación
                    if not product.is_service:
                        product.is_service = True
                        product.save(update_fields=['is_service'])

                    messages.success(request, f'Insumo "{component_product.name}" agregado a la receta correctamente. Su capacidad de venta en POS ahora se calcula según las existencias de este insumo.')
            except Product.DoesNotExist:
                messages.error(request, 'El insumo seleccionado no existe.')
    return redirect('edit_product', product_id=product.id)

@login_required
def delete_product_component(request, component_id):
    component = get_object_or_404(ProductComponent, id=component_id)
    product_id = component.parent_product_id
    if request.method == 'POST':
        name = component.component_product.name
        component.delete()
        messages.success(request, f'Insumo "{name}" retirado de la receta.')
    return redirect('edit_product', product_id=product_id)

@login_required
def product_price_history(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    history = product.price_history.select_related('user').order_by('-date')
    return render(request, 'pos/partials/product_price_history_modal.html', {
        'product': product,
        'history': history
    })

@login_required
def global_price_history(request):
    history_qs = ProductPriceHistory.objects.select_related('product', 'user').order_by('-date')
    query = request.GET.get('search', '').strip()
    if query:
        history_qs = history_qs.filter(
            Q(product__name__icontains=query) | 
            Q(product__barcode__icontains=query) |
            Q(reason__icontains=query) |
            Q(user__username__icontains=query)
        )
    
    total_changes = history_qs.count()
    return render(request, 'pos/price_history.html', {
        'history': history_qs[:150],
        'total_changes': total_changes,
        'query': query,
    })

@login_required
def add_stock(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        try:
            quantity = int(request.POST.get('quantity'))
            if quantity > 0:
                product.stock += quantity
                was_inactive = not product.is_active
                if was_inactive:
                    product.is_active = True
                    product.save()
                    messages.success(
                        request, 
                        f'Se agregaron {quantity} unidades a "{product.name}" y se reactivó automáticamente en el inventario.'
                    )
                else:
                    product.save()
                    messages.success(request, f'Se agregaron {quantity} unidades a {product.name}')
            else:
                 messages.error(request, 'La cantidad debe ser mayor a 0')
        except ValueError:
            messages.error(request, 'Cantidad inválida')
            
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('inventory')
    return redirect(next_url)

@login_required
def toggle_product_status(request, product_id):
    """
    Da de baja un producto agotado (is_active=False) o lo reactiva (is_active=True).
    Condición estricta: Para marcarlo como inactivo / darlo de baja, debe estar SIN inventario (stock <= 0).
    """
    product = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        action = request.POST.get('action') # 'deactivate', 'reactivate', o toggle automático
        should_deactivate = (action == 'deactivate') or (action is None and product.is_active)
        
        if should_deactivate:
            if not product.can_be_deactivated:
                messages.error(
                    request,
                    f'No se puede dar de baja "{product.name}": aún tiene {product.stock} unidades en inventario. '
                    f'El producto debe estar totalmente agotado (stock = 0) para poder darlo de baja.'
                )
            else:
                try:
                    product.deactivate()
                    messages.warning(
                        request,
                        f'El producto "{product.name}" ha sido dado de baja y trasladado al apartado de Inactivos.'
                    )
                except ValueError as e:
                    messages.error(request, str(e))
        else:
            product.reactivate()
            messages.success(
                request,
                f'El producto "{product.name}" ha sido reactivado y devuelto al inventario activo para venta.'
            )
            
        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('inventory')
        return redirect(next_url)
        
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
        products = Product.objects.filter(is_active=True, name__icontains=query).order_by('name')[:10]
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
        if not product.is_active:
            return HttpResponse('El producto está dado de baja / inactivo y no se puede vender.', status=400)
        
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
                price=product.price,
                cost_price=product.effective_cost
            )
        
        # Update stock
        product.deduct_stock(1)
        
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
            item.product.deduct_stock(1)
            
        elif action == 'decrement':
            if item.quantity > 1:
                # Decrease quantity
                item.quantity -= 1
                item.save()
                # Increase stock
                item.product.restore_stock(1)
            else:
                # Remove item if quantity would be 0
                item.product.restore_stock(item.quantity)
                item.delete()
                
        elif action == 'remove':
            # Return stock
            item.product.restore_stock(item.quantity)
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

@login_required
def annul_sale(request, sale_id):
    sale = get_object_or_404(Sale, id=sale_id)
    if request.method == 'POST':
        if not sale.is_annulled:
            sale.is_annulled = True
            sale.save()
            
            # Return stock
            for item in sale.items.all():
                item.product.restore_stock(item.quantity)
            
            messages.success(request, f'La factura #{sale.id} ha sido anulada y el inventario restaurado.')
        else:
            messages.info(request, f'La factura #{sale.id} ya estaba anulada.')
            
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('invoice_detail', sale_id=sale.id)

@login_required
def clean_services_stock(request):
    """
    Normaliza a 0 el stock directo de todos los servicios o productos con receta/insumos vinculados.
    Esto elimina de golpe cualquier stock ficticio remanente (ej. 9999 o 10000) introducido previamente.
    """
    if request.method == 'POST':
        services_to_fix = Product.objects.filter(Q(is_service=True) | Q(components__isnull=False), stock__gt=0)
        count = services_to_fix.count()
        services_to_fix.update(stock=0)
        messages.success(
            request, 
            f'Se normalizó a 0 el stock en {count} servicio(s) e impresiones con receta. La valoración de inventario ahora refleja con total exactitud tus activos físicos en bodega.'
        )
    return redirect('inventory')
