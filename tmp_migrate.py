import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from pos.models import Client, PaymentAllocation

clients = Client.objects.all()
for client in clients:
    allocations_exists = PaymentAllocation.objects.filter(payment__client=client).exists()
    if allocations_exists:
        continue

    payments = client.payments.order_by('date')
    sales = list(client.sale_set.filter(payment_method='CREDIT', is_annulled=False).order_by('date'))
    
    for payment in payments:
        remaining = payment.amount
        for sale in sales:
            if remaining <= 0:
                break
            
            # calculate pending locally directly from DB dynamically to avoid stale state
            already_allocated = sum(alloc.amount for alloc in sale.allocations.all())
            pending = sale.total - already_allocated
            
            if pending > 0:
                if remaining >= pending:
                    alloc_amt = pending
                    remaining -= pending
                else:
                    alloc_amt = remaining
                    remaining = 0
                
                PaymentAllocation.objects.create(payment=payment, sale=sale, amount=alloc_amt)

print("Migration completed!")
