from django.contrib import admin
from .models import Product, ProductPriceHistory, Category, Client, Sale, SaleItem, Payment, PaymentAllocation

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'barcode', 'cost_price', 'price', 'profit', 'stock')
    search_fields = ('name', 'barcode')
    list_filter = ('category',)

@admin.register(ProductPriceHistory)
class ProductPriceHistoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'old_cost_price', 'new_cost_price', 'old_price', 'new_price', 'user', 'reason', 'date')
    search_fields = ('product__name', 'reason')
    list_filter = ('date', 'user')

admin.site.register(Category)
admin.site.register(Client)
admin.site.register(Sale)
admin.site.register(SaleItem)
admin.site.register(Payment)
admin.site.register(PaymentAllocation)
