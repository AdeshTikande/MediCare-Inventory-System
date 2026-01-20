from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Sum
from django.utils import timezone
from django.http import HttpResponse
from django.contrib import messages
from .models import Product, Transaction
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import pandas as pd # <--- Essential for reading files
import os
from django.conf import settings
from django.core.files.storage import FileSystemStorage

# --- AUTHENTICATION ---
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()
    return render(request, 'login.html', {'form': form})

def logout_view(request):
    logout(request)
    return redirect('login')

# --- DASHBOARD ---
@login_required
@login_required
def dashboard_view(request):
    transactions = Transaction.objects.select_related('product').order_by('-date')[:5]
    sellable_products = Product.objects.filter(quantity__gt=0)
    
    # ROUND THESE NUMBERS TO 2 DECIMAL PLACES
    total_sales = round(Transaction.objects.aggregate(Sum('amount'))['amount__sum'] or 0, 2)
    today_sales = round(Transaction.objects.filter(date__date=timezone.now().date()).aggregate(Sum('amount'))['amount__sum'] or 0, 2)
    
    low_stock = Product.objects.filter(quantity__lt=10, quantity__gt=0).count()

    context = {
        'transactions': transactions, 
        'products': sellable_products,
        'total_sales': total_sales, 
        'today_sales': today_sales, 
        'low_stock': low_stock,
        'active_page': 'dashboard'
    }
    return render(request, 'dashboard.html', context)

# --- INVENTORY (Search & Filter Added) ---
@login_required
def inventory_view(request):
    # Base Query
    products = Product.objects.all().order_by('-added_date')
    
    # 1. Search Logic
    search_query = request.GET.get('q')
    if search_query:
        products = products.filter(name__icontains=search_query)
    
    # 2. Filter Logic (from Dashboard Cards)
    filter_type = request.GET.get('filter')
    if filter_type == 'low_stock':
        products = products.filter(quantity__lt=10, quantity__gt=0)
    elif filter_type == 'out_of_stock':
        products = products.filter(quantity=0)

    # KPI Stats (Always calculated on ALL products)
    all_products = Product.objects.all()
    
    context = {
        'products': products,
        'totalProducts': all_products.count(),
        'lowStock': all_products.filter(quantity__lt=10, quantity__gt=0).count(),
        'outOfStock': all_products.filter(quantity=0).count(),
        'inventoryValue': sum(p.price * p.quantity for p in all_products),
        'active_page': 'inventory',
        'search_query': search_query
    }
    return render(request, 'inventory.html', context)

# --- REPORTS ---
# --- REPORT VIEW ---
@login_required
def report_view(request):
    now = timezone.now()
    
    # ROUND THE RETURN VALUE HERE
    def get_rev(start): 
        val = Transaction.objects.filter(date__gte=start).aggregate(Sum('amount'))['amount__sum'] or 0
        return round(val, 2)

    context = {
        'todayRevenue': get_rev(now.replace(hour=0, minute=0, second=0)),
        'monthRevenue': get_rev(now.replace(day=1, hour=0, minute=0, second=0)),
        'yearRevenue': get_rev(now.replace(month=1, day=1, hour=0, minute=0, second=0)),
        'active_page': 'report'
    }
    return render(request, 'report.html', context)
# --- ACTIONS (Add/Sell) ---
@login_required
def add_product(request):
    if request.method == 'POST':
        Product.objects.create(
            name=request.POST.get('name'),
            price=request.POST.get('price'),
            quantity=request.POST.get('quantity')
        )
        messages.success(request, "Product added successfully!")
    return redirect('inventory')

@login_required
def sell_product(request):
    if request.method == 'POST':
        p_id = request.POST.get('product_id')
        qty = int(request.POST.get('qty'))
        product = get_object_or_404(Product, id=p_id)
        
        # --- NEW STOCK VALIDATION LOGIC ---
        if product.quantity == 0:
            messages.error(request, f"Error: '{product.name}' is Out of Stock!")
        elif product.quantity < qty:
            messages.error(request, f"Error: Insufficient stock! Only {product.quantity} left.")
        else:
            # Process Sale
            total = product.price * qty
            Transaction.objects.create(
                product=product, quantity=qty, amount=total, payment_method=request.POST.get('payment')
            )
            product.quantity -= qty
            product.save()
            messages.success(request, f"Sold {qty} x {product.name} successfully!")
            
    return redirect('dashboard')

# --- PDF EXPORT ---
@login_required
# --- PDF EXPORT VIEW (FIXED) ---
@login_required
def generate_pdf_report(request, timeframe):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="report_{timeframe}.pdf"'

    p = canvas.Canvas(response, pagesize=letter)
    width, height = letter # Get page dimensions
    
    # --- HEADER ---
    p.setFont("Helvetica-Bold", 18)
    p.drawString(50, height - 50, f"MediCare+ Sales Report")
    
    p.setFont("Helvetica", 12)
    p.drawString(50, height - 70, f"Period: {timeframe.capitalize()}")
    p.drawString(50, height - 85, f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M')}")
    
    # --- DATE FILTERING ---
    now = timezone.now()
    if timeframe == 'day':
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif timeframe == 'month':
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif timeframe == 'year':
        start_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Fetch transactions
    txns = Transaction.objects.filter(date__gte=start_date).order_by('-date')

    # --- TABLE HEADERS ---
    y = height - 120 # Start position (Top of page)
    p.setFont("Helvetica-Bold", 10)
    p.drawString(50, y, "Date")
    p.drawString(200, y, "Medicine Name")
    p.drawString(380, y, "Qty")
    p.drawString(450, y, "Amount (Rs)")
    
    # Draw a line under headers
    p.line(50, y - 5, 550, y - 5)
    y -= 25 # Move down for first row

    # --- DATA ROWS ---
    p.setFont("Helvetica", 10)
    total_rev = 0
    
    if not txns.exists():
        p.drawString(50, y, "No transactions found for this period.")
    else:
        for txn in txns:
            # Check if we ran out of space on the page
            if y < 50: 
                p.showPage() # Create new page
                y = height - 50 # Reset Y to top
                p.setFont("Helvetica", 10) # Reset font

            # Write Data
            p.drawString(50, y, str(txn.date.strftime('%Y-%m-%d')))
            p.drawString(200, y, txn.product.name[:25]) # Truncate long names
            p.drawString(380, y, str(txn.quantity))
            p.drawString(450, y, f"{txn.amount:.2f}")
            
            total_rev += txn.amount
            y -= 20 # Move down for next row

    # --- TOTAL SUMMARY ---
    p.line(50, y + 10, 550, y + 10) # Line above total
    p.setFont("Helvetica-Bold", 12)
    p.drawString(300, y - 10, "Total Revenue:")
    p.drawString(450, y - 10, f"Rs. {total_rev:.2f}")
    
    p.showPage()
    p.save()
    return response

# --- ACTION: ADD PRODUCT ---
@login_required
def add_product(request):
    if request.method == 'POST':
        try:
            name = request.POST.get('name')
            price = request.POST.get('price')
            qty = request.POST.get('quantity')
            
            if name and price and qty:
                Product.objects.create(name=name, price=price, quantity=qty)
                messages.success(request, f"Successfully added {name}!")
            else:
                messages.error(request, "All fields are required.")
        except Exception as e:
            messages.error(request, f"Error adding product: {str(e)}")
            
    return redirect('inventory')

# --- ACTION: UPLOAD INVENTORY ---
@login_required
def upload_inventory(request):
    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        try:
            # Check for pandas
            try:
                import pandas as pd
            except ImportError:
                messages.error(request, "Server Error: Pandas library not installed. Run 'pip install pandas'.")
                return redirect('inventory')

            if file.name.endswith('.csv'):
                data = pd.read_csv(file)
            elif file.name.endswith('.xlsx'):
                data = pd.read_excel(file)
            else:
                messages.error(request, "Invalid file format. Use CSV or Excel.")
                return redirect('inventory')
                
            required_cols = ['name', 'price', 'quantity']
            if not all(col in data.columns for col in required_cols):
                messages.error(request, f"Missing columns! File must have: {', '.join(required_cols)}")
                return redirect('inventory')

            count = 0
            for index, row in data.iterrows():
                Product.objects.update_or_create(
                    name=row['name'],
                    defaults={'price': row['price'], 'quantity': row['quantity']}
                )
                count += 1

            messages.success(request, f"Uploaded {count} products successfully!")

        except Exception as e:
            messages.error(request, f"Upload failed: {str(e)}")

    return redirect('inventory')