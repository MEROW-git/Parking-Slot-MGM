from django.contrib import admin
from django.urls import path
from source import views as source_views
from parking_zones import views as pz_views
from users import views as user_views
from parking_zones.gate_machine import virtual_gate

admin.site.site_header = 'SomPark Phnom Penh Administration (រដ្ឋបាល SomPark)'
admin.site.site_title = 'SomPark Admin'
admin.site.index_title = 'Smart Parking Operations Dashboard'

urlpatterns = [
    path('admin/virtual-gate/', admin.site.admin_view(virtual_gate), name='admin_virtual_gate'),
    path('admin/', admin.site.urls),

    # Core Source Views
    path('', source_views.home, name='home'),
    path('components/', source_views.component_showcase, name='component_showcase'),

    # Parking Zones, Booking & Payments
    path('zone/<slug:slug>/', pz_views.zone_detail, name='zone_detail'),
    path('book/', pz_views.booking, name='book'),
    path('book/<str:ticket_code>/pay-deposit/', pz_views.pay_deposit, name='pay_deposit'),
    path('book/simulate-payment/<int:txn_id>/', pz_views.payment_simulate, name='payment_simulate'),
    path('book/<str:ticket_code>/cancel/', pz_views.cancel_booking, name='cancel_booking'),
    path('checkout/', pz_views.checkout, name='checkout'),
    path('ticket/', pz_views.ticket_detail, name='ticket'),
    path('ticket/<str:ticket_code>/', pz_views.ticket_detail, name='ticket_code'),
    path('ticket/<str:ticket_code>/pay-exit/', pz_views.pay_exit, name='pay_exit'),
    path('ticket/<str:ticket_code>/renew-exit/', pz_views.renew_exit_authorization, name='renew_exit_authorization'),
    path('ticket/<str:ticket_code>/qr.png', pz_views.ticket_qr_image, name='ticket_qr_image'),
    path('ticket/<str:ticket_code>/gate-mode/', pz_views.ticket_gate_mode, name='ticket_gate_mode'),
    path('all_tickets/', pz_views.all_tickets, name='all_tickets'),
    path('api/ai-assistant/', pz_views.ai_parking_assistant, name='ai_parking_assistant'),

    # Staff Operations Workbench & Gate Scanner
    path('staff/dashboard/', pz_views.admin_dashboard, name='admin_dashboard'),
    path('staff/gate/', pz_views.staff_gate_scanner, name='staff_gate_scanner'),
    path('staff/gate/action/', pz_views.staff_gate_action, name='staff_gate_action'),
    path('staff/checkout/', pz_views.admin_checkout, name='admin_checkout'),

    # Users & Auth
    path('dashboard/', user_views.dashboard, name='dashboard'),
    path('user/login/', user_views.login_user, name='login'),
    path('user/signup/', user_views.register_user, name='signup'),
    path('user/logout/', user_views.logout_user, name='logout'),
]
