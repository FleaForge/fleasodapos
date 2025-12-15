from django.db import models
from django.utils import timezone

class Category(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class Product(models.Model):
    name = models.CharField(max_length=200)
    barcode = models.CharField(max_length=100, unique=True, blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.IntegerField(default=0)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    image = models.ImageField(upload_to='products/', null=True, blank=True)

    def __str__(self):
        return self.name

class Client(models.Model):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def balance(self):
        credit_sales = self.sale_set.filter(payment_method='CREDIT').aggregate(models.Sum('total'))['total__sum'] or 0
        payments = self.payments.aggregate(models.Sum('amount'))['amount__sum'] or 0
        return credit_sales - payments

class Sale(models.Model):
    PAYMENT_METHODS = [
        ('CASH', 'Contado'),
        ('CREDIT', 'Crédito'),
    ]
    client = models.ForeignKey(Client, on_delete=models.PROTECT)
    date = models.DateTimeField(default=timezone.now)
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHODS, default='CASH')
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_paid = models.BooleanField(default=True) # Cash is paid immediately

    def __str__(self):
        return f"Factura #{self.id} - {self.client.name}"

class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.IntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2) # Price at moment of sale

    @property
    def subtotal(self):
        return self.quantity * self.price

class Payment(models.Model):
    sale = models.ForeignKey(Sale, related_name='payments', on_delete=models.SET_NULL, null=True, blank=True)
    client = models.ForeignKey(Client, related_name='payments', on_delete=models.CASCADE, null=True) # Check if null=True works locally before migration or default... I will handle default by deleting rows or providing 1.
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

    def __str__(self):
        return f"Pago {self.amount} - {self.client.name}"
