from django.contrib import admin
from django.urls import path
from source import views as source_views
from parking_zones import views as pz_views
from users import views as user_views

admin.site.site_header = 'SomPark Phnom Penh Administration (រដ្ឋបាល SomPark)'
admin.site.site_title = 'SomPark Admin'
admin.site.index_title = 'Smart Parking Operations Dashboard'

urlpatterns = [
    path('admin/', admin.site.urls),

    # Core Source Views
    path('', source_views.home, name='home'),
    path('components/', source_views.component_showcase, name='component_showcase'),

    # Parking Zones & Booking
    path('zone/<slug:slug>/', pz_views.zone_detail, name='zone_detail'),
    path('book/', pz_views.booking, name='book'),
    path('checkout/', pz_views.checkout, name='checkout'),
    path('ticket/', pz_views.ticket_detail, name='ticket'),
    path('ticket/<str:ticket_code>/', pz_views.ticket_detail, name='ticket_code'),
    path('all_tickets/', pz_views.all_tickets, name='all_tickets'),

    # Staff Operations Workbench
    path('staff/dashboard/', pz_views.admin_dashboard, name='admin_dashboard'),
    path('staff/checkout/', pz_views.admin_checkout, name='admin_checkout'),

    # Users & Auth
    path('dashboard/', user_views.dashboard, name='dashboard'),
    path('user/login/', user_views.login_user, name='login'),
    path('user/signup/', user_views.register_user, name='signup'),
    path('user/logout/', user_views.logout_user, name='logout'),
]
