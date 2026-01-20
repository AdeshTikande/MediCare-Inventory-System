from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Pages
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('inventory/', views.inventory_view, name='inventory'),
    path('report/', views.report_view, name='report'),

    # Actions
    path('add-product/', views.add_product, name='add_product'),
    path('sell-product/', views.sell_product, name='sell_product'),
    path('export/<str:timeframe>/', views.generate_pdf_report, name='export_pdf'),

    # Redirect root
    path('', views.login_view),

    # ... previous urls ...
    path('upload-inventory/', views.upload_inventory, name='upload_inventory'), # <--- ADD THIS

]