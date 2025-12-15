from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('inventory/', views.inventory, name='inventory'),
    path('reports/', views.report_analytics, name='reports'),
    path('clients/', views.clients, name='clients'),
    path('clients/<int:client_id>/statement/', views.client_statement, name='client_statement'),
    path('clients/<int:client_id>/statement/pdf/', views.client_statement_pdf, name='client_statement_pdf'),
    path('clients/<int:client_id>/payment/add/', views.add_payment, name='add_payment'),
    path('pos/', views.pos, name='pos'),
    
    # HTMX Partials
    path('pos/search/', views.search_products, name='search_products'),
    path('pos/add-cart/', views.add_to_cart, name='add_to_cart'),
    path('pos/update-cart/', views.update_cart_item, name='update_cart_item'),
    path('pos/clear-cart/', views.clear_cart, name='clear_cart'),
    path('pos/checkout/', views.checkout, name='checkout'),
    path('invoice/<int:sale_id>/', views.invoice_detail, name='invoice_detail'),
    path('inventory/add/', views.add_product, name='add_product'),
    path('clients/search/', views.search_clients, name='search_clients'),
    path('clients/add/', views.add_client, name='add_client'),
    
    # Auth & Public
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('public/search/', views.public_search, name='public_search'),
    path('public/check/', views.public_check_debt, name='public_check_debt'),
    path('client/<int:client_id>/public-statement/', views.client_public_statement, name='client_public_statement'),
    path('sw.js', views.service_worker, name='service_worker'),
]
