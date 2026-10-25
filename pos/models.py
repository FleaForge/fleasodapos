from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

class Category(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class Product(models.Model):
    name = models.CharField(max_length=200)
    barcode = models.CharField(max_length=100, unique=True, blank=True, null=True)
    cost_price = models.IntegerField(default=0, help_text="Precio de costo / compra")
    price = models.IntegerField(default=0, help_text="Precio de venta final (PVP)")
    stock = models.IntegerField(default=0)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    image = models.ImageField(upload_to='products/', null=True, blank=True)

    def __str__(self):
        return self.name

    @property
    def profit(self):
        """Ganancia unitaria en pesos: Precio venta - Costo de compra"""
        return self.price - self.cost_price

    @property
    def margin_markup(self):
        """Rentabilidad sobre el costo (Markup) %: ((Precio Venta - Costo) / Costo) * 100"""
        if self.cost_price > 0:
            return round(((self.price - self.cost_price) / self.cost_price) * 100, 2)
        return 100.0 if self.price > 0 else 0.0

    @property
    def margin_profit(self):
        """Margen comercial sobre la venta %: ((Precio Venta - Costo) / Precio Venta) * 100"""
        if self.price > 0:
            return round(((self.price - self.cost_price) / self.price) * 100, 2)
        return 0.0

    @property
    def cost_valuation(self):
        """Valoración total del stock a costo"""
        return self.cost_price * self.stock

    @property
    def sale_valuation(self):
        """Valoración total del stock a precio de venta"""
        return self.price * self.stock

    @property
    def profit_valuation(self):
        """Ganancia potencial total sobre el stock actual"""
        return self.profit * self.stock

class ProductPriceHistory(models.Model):
    product = models.ForeignKey(Product, related_name='price_history', on_delete=models.CASCADE)
    old_price = models.IntegerField(default=0)
    new_price = models.IntegerField(default=0)
    old_cost_price = models.IntegerField(default=0)
    new_cost_price = models.IntegerField(default=0)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True, default='')
    date = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-date', '-id']
        verbose_name = 'Historial de Precio'
        verbose_name_plural = 'Historial de Precios'

    @property
    def price_diff(self):
        return self.new_price - self.old_price

    @property
    def price_diff_percent(self):
        if self.old_price > 0:
            return round(((self.new_price - self.old_price) / self.old_price) * 100, 2)
        return 0.0

    @property
    def cost_diff(self):
        return self.new_cost_price - self.old_cost_price

    @property
    def new_profit(self):
        return self.new_price - self.new_cost_price

    @property
    def new_margin_markup(self):
        if self.new_cost_price > 0:
            return round(((self.new_price - self.new_cost_price) / self.new_cost_price) * 100, 2)
        return 100.0 if self.new_price > 0 else 0.0

    @property
    def new_margin_profit(self):
        if self.new_price > 0:
            return round(((self.new_price - self.new_cost_price) / self.new_price) * 100, 2)
        return 0.0

    def __str__(self):
        return f"{self.product.name}: ${self.old_price:,} -> ${self.new_price:,} ({self.date.strftime('%Y-%m-%d %H:%M')})"


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
        credit_sales = self.sale_set.filter(payment_method='CREDIT', is_annulled=False).aggregate(models.Sum('total'))['total__sum'] or 0
        payments = self.payments.filter(is_annulled=False).aggregate(models.Sum('amount'))['amount__sum'] or 0
        return credit_sales - payments

class Sale(models.Model):
    PAYMENT_METHODS = [
        ('CASH', 'Contado'),
        ('CREDIT', 'Crédito'),
    ]
    client = models.ForeignKey(Client, on_delete=models.PROTECT)
    date = models.DateTimeField(default=timezone.now)
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHODS, default='CASH')
    total = models.IntegerField(default=0)
    is_paid = models.BooleanField(default=True) # Cash is paid immediately
    is_annulled = models.BooleanField(default=False) # Annulled invoice
    is_adjustment = models.BooleanField(default=False) # True if manual debt/balance adjustment, NOT commercial sale
    consolidation_source_payment = models.ForeignKey('Payment', on_delete=models.SET_NULL, null=True, blank=True, related_name='consolidated_sales')
    note = models.TextField(blank=True, null=True)

    @property
    def amount_paid(self):
        return sum(alloc.amount for alloc in self.allocations.filter(payment__is_annulled=False))

    @property
    def pending_balance(self):
        if self.payment_method == 'CASH' or self.is_annulled:
            return 0
        return max(0, self.total - self.amount_paid)

    @property
    def total_cost(self):
        if self.is_adjustment or self.is_annulled:
            return 0
        return sum(item.total_cost for item in self.items.all())

    @property
    def total_profit(self):
        if self.is_adjustment or self.is_annulled:
            return 0
        return self.total - self.total_cost

    @property
    def margin_profit(self):
        if self.total > 0 and not self.is_annulled:
            return round((self.total_profit / self.total) * 100, 1)
        return 0.0

    @property
    def margin_markup(self):
        if self.total_cost > 0 and not self.is_annulled:
            return round((self.total_profit / self.total_cost) * 100, 1)
        return 100.0 if self.total_profit > 0 else 0.0

    def __str__(self):
        return f"Factura #{self.id} - {self.client.name}"

class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.IntegerField(default=1)
    price = models.IntegerField(default=0)  # Price at moment of sale
    cost_price = models.IntegerField(default=0, help_text="Costo unitario de compra al momento de la venta")

    @property
    def subtotal(self):
        return self.quantity * self.price

    @property
    def effective_cost_price(self):
        """Si cost_price quedó en 0 por venta histórica, usa el cost_price del producto"""
        if self.cost_price > 0:
            return self.cost_price
        return self.product.cost_price if self.product else 0

    @property
    def total_cost(self):
        return self.quantity * self.effective_cost_price

    @property
    def profit(self):
        return self.subtotal - self.total_cost

    @property
    def margin_markup(self):
        if self.total_cost > 0:
            return round((self.profit / self.total_cost) * 100, 2)
        return 100.0 if self.subtotal > 0 else 0.0

    @property
    def margin_profit(self):
        if self.subtotal > 0:
            return round((self.profit / self.subtotal) * 100, 2)
        return 0.0

class Payment(models.Model):
    sale = models.ForeignKey(Sale, related_name='payments', on_delete=models.SET_NULL, null=True, blank=True)
    client = models.ForeignKey(Client, related_name='payments', on_delete=models.CASCADE, null=True) # Check if null=True works locally before migration or default... I will handle default by deleting rows or providing 1.
    amount = models.IntegerField(default=0)
    date = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)
    is_annulled = models.BooleanField(default=False)
    is_consolidation = models.BooleanField(default=False)
    consolidation_source_payment = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='consolidation_transfers')

    def __str__(self):
        return f"Pago {self.amount} - {self.client.name}"

class PaymentAllocation(models.Model):
    payment = models.ForeignKey(Payment, related_name='allocations', on_delete=models.CASCADE)
    sale = models.ForeignKey(Sale, related_name='allocations', on_delete=models.CASCADE)
    amount = models.IntegerField(default=0)
    
    def __str__(self):
        return f"Abono ${self.amount} a Factura #{self.sale.id}"
