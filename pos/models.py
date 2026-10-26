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
    is_active = models.BooleanField(default=True, help_text="Indica si el producto está activo para venta e inventario regular")
    is_service = models.BooleanField(default=False, help_text="Indica si es un servicio o producto que consume insumos")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    image = models.ImageField(upload_to='products/', null=True, blank=True)

    def __str__(self):
        return self.name

    @property
    def has_components(self):
        """Verifica si este producto tiene insumos/componentes vinculados"""
        return self.components.exists()

    @property
    def components_cost(self):
        """Costo acumulado calculado a partir de sus insumos vinculados"""
        return sum(comp.subtotal_cost for comp in self.components.select_related('component_product').all())

    @property
    def effective_cost(self):
        """
        Costo real de compra o producción:
        - Si tiene insumos vinculados, suma el costo de sus insumos más cualquier costo directo base (cost_price).
        - Si no tiene insumos, usa su cost_price directo.
        """
        if self.has_components:
            return self.cost_price + self.components_cost
        return self.cost_price

    @property
    def profit(self):
        """Ganancia unitaria en pesos: Precio venta - Costo real efectivo"""
        return self.price - self.effective_cost

    @property
    def margin_markup(self):
        """Rentabilidad sobre el costo (Markup) %: ((Precio Venta - Costo) / Costo) * 100"""
        eff = self.effective_cost
        if eff > 0:
            return round(((self.price - eff) / eff) * 100, 2)
        return 100.0 if self.price > 0 else 0.0

    @property
    def margin_profit(self):
        """Margen comercial sobre la venta %: ((Precio Venta - Costo) / Precio Venta) * 100"""
        if self.price > 0:
            return round(((self.price - self.effective_cost) / self.price) * 100, 2)
        return 0.0

    @property
    def cost_valuation(self):
        """Valoración total del stock a costo (los servicios no duplican capital, se mide en sus insumos)"""
        if self.is_service or self.has_components:
            return 0
        return self.effective_cost * self.stock

    @property
    def sale_valuation(self):
        """Valoración total del stock a precio de venta"""
        if self.is_service or self.has_components:
            return 0
        return self.price * self.stock

    @property
    def profit_valuation(self):
        """Ganancia potencial total sobre el stock actual"""
        if self.is_service or self.has_components:
            return 0
        return self.profit * self.stock

    @property
    def available_service_units(self):
        """
        Calcula cuántos servicios se pueden prestar según las existencias actuales de sus insumos.
        - Si tiene insumos vinculados, la disponibilidad es el mínimo que permiten los insumos.
        - Si es un servicio puro sin insumos, está siempre disponible (no limitado por stock físico).
        - Si es un producto físico normal, devuelve su propio stock.
        """
        if not self.has_components:
            return 9999 if self.is_service else self.stock
        availabilities = []
        for comp in self.components.select_related('component_product').all():
            if comp.quantity > 0:
                availabilities.append(int(comp.component_product.stock // comp.quantity))
        return min(availabilities) if availabilities else 0

    @property
    def max_available_for_sale(self):
        """
        Límite máximo de unidades que se pueden vender en el POS:
        - Si tiene insumos/componentes vinculados: se limita estrictamente por el stock de sus insumos (available_service_units).
        - Si es un servicio puro (sin insumos): ilimitado (None).
        - Si es un producto físico comercial: su stock físico actual (>= 0).
        """
        if self.has_components:
            return max(0, self.available_service_units)
        if self.is_service:
            return None
        return max(0, self.stock)

    def can_sell(self, quantity=1):
        """
        Verifica si se pueden vender 'quantity' unidades en el POS:
        - Si tiene insumos, verifica que cada insumo físico tenga stock suficiente.
        - Si es un servicio puro, siempre es True.
        - Si es un producto físico, verifica que self.stock >= quantity.
        """
        if not self.is_active:
            return False, f'El producto "{self.name}" está inactivo o dado de baja.'
        if self.has_components:
            for comp in self.components.select_related('component_product').all():
                needed = int(float(comp.quantity) * quantity)
                if comp.component_product.stock < needed:
                    available = int(comp.component_product.stock // comp.quantity) if comp.quantity > 0 else 0
                    return False, f'Insumos insuficientes de "{comp.component_product.name}". Requieres {needed} unid(s) pero solo quedan {comp.component_product.stock} disponibles en bodega (máximo {available} servicio(s)).'
            return True, ""
        if self.is_service:
            return True, ""
        if self.stock < quantity:
            return False, f'Stock insuficiente de "{self.name}". Requieres {quantity} unid(s) pero solo hay {self.stock} en bodega.'
        return True, ""

    def deduct_stock(self, quantity=1):
        """
        Descuenta inventario:
        - Si tiene insumos vinculados, descuenta de cada insumo físico (ej: Papel fotográfico).
        - Si es un producto físico comercial, descuenta de su stock directo.
        - Si es un servicio puro (sin insumos físicos), NO descuenta stock directo para evitar números negativos.
        """
        if self.has_components:
            for comp in self.components.select_related('component_product').all():
                qty_to_deduct = int(float(comp.quantity) * quantity)
                comp.component_product.stock -= qty_to_deduct
                comp.component_product.save(update_fields=['stock'])
        elif not self.is_service:
            self.stock -= quantity
            self.save(update_fields=['stock'])

    def restore_stock(self, quantity=1):
        """
        Restaura inventario (en caso de anulación o retiro de ítem de venta):
        - Si tiene insumos vinculados, reincorpora a los insumos físicos.
        - Si es un producto físico comercial, restaura a su stock directo.
        - Si es un servicio puro, no altera stock directo.
        """
        if self.has_components:
            for comp in self.components.select_related('component_product').all():
                qty_to_restore = int(float(comp.quantity) * quantity)
                comp.component_product.stock += qty_to_restore
                comp.component_product.save(update_fields=['stock'])
        elif not self.is_service:
            self.stock += quantity
            self.save(update_fields=['stock'])

    @property
    def can_be_deactivated(self):
        """
        Un producto físico solo se puede dar de baja (desactivar) si está completamente agotado (stock <= 0).
        Los servicios se pueden dar de baja directamente si ya no se van a ofrecer.
        """
        return self.stock <= 0 or self.is_service

    def deactivate(self):
        """
        Marca el producto como inactivo si y solo si no tiene inventario disponible.
        """
        if not self.can_be_deactivated:
            raise ValueError(f"No se puede dar de baja un producto con existencias (stock actual: {self.stock}).")
        self.is_active = False
        self.save(update_fields=['is_active'])

    def reactivate(self):
        """
        Reactiva un producto previamente dado de baja para volver a comercializarlo e inventariarlo.
        """
        self.is_active = True
        self.save(update_fields=['is_active'])

    class Meta:
        ordering = ['-is_active', 'name']

class ProductComponent(models.Model):
    """
    Componente / Insumo consumido por un servicio o producto compuesto.
    Ejemplo: 1 Impresión fotográfica consume 1 Papel Fotográfico.
    """
    parent_product = models.ForeignKey(
        Product, 
        related_name='components', 
        on_delete=models.CASCADE, 
        help_text="Servicio o producto final que consume el insumo"
    )
    component_product = models.ForeignKey(
        Product, 
        related_name='used_in_products', 
        on_delete=models.CASCADE, 
        help_text="Insumo o materia prima que se descuenta del inventario"
    )
    quantity = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=1.0, 
        help_text="Cantidad consumida por cada venta (ej: 1 hoja, 0.5 unidades, etc.)"
    )

    class Meta:
        unique_together = ('parent_product', 'component_product')
        verbose_name = 'Insumo de Producto'
        verbose_name_plural = 'Insumos de Productos'

    @property
    def subtotal_cost(self):
        return int(float(self.quantity) * self.component_product.effective_cost)

    def __str__(self):
        return f"{self.quantity} x {self.component_product.name} en {self.parent_product.name}"

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
    is_default = models.BooleanField(default=False, help_text="Cliente por defecto / Consumidor Final para ventas rápidas en POS")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.is_default:
            Client.objects.filter(is_default=True).exclude(id=self.id).update(is_default=False)
        super().save(*args, **kwargs)

    @classmethod
    def get_default_client(cls):
        """
        Retorna el cliente asignado para Consumidor Final / Ventas Rápidas en POS.
        Busca por is_default=True, luego por 'CONTADO POS', luego por palabras clave 'CONTADO' / 'CONSUMIDOR FINAL'.
        Si no existe ninguno, crea 'CONTADO POS' automáticamente.
        """
        client = cls.objects.filter(is_default=True).first()
        if client:
            return client
        
        client = cls.objects.filter(name__iexact='CONTADO POS').first()
        if not client:
            client = cls.objects.filter(name__icontains='CONTADO POS').first()
        if not client:
            client = cls.objects.filter(name__icontains='CONTADO').first()
        if not client:
            client = cls.objects.filter(name__icontains='CONSUMIDOR FINAL').first()
        
        if not client:
            client = cls.objects.create(name='CONTADO POS', is_default=True)
        else:
            if not client.is_default:
                client.is_default = True
                client.save(update_fields=['is_default'])
        return client

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
