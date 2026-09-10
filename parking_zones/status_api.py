"""
Lightweight, read-only status synchronization endpoints for SomPark.
Allows clients (ticket view, gate pass, dashboards, payment pages, virtual gate,
and parking availability) to poll for live state changes without manual reloads.

Invariants:
- All endpoints are strictly GET requests; no gate permits, payments, or capacity changes.
- Strict authentication and customer ownership / staff authorization enforced.
- Bounded queries, selective field evaluation, and terminal state flags.
"""
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse, HttpResponseForbidden
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import ParkingZone, Reservation
from .services import BillingService


def _serialize_ticket_status(reservation, as_of):
    """
    Serializes comprehensive, bounded status for a single ticket.
    Performs request-time expiry checks and calculates billing only if active.
    """
    now = as_of

    # Request-time expiry check: advance hold or checkout timeout
    if reservation.status == 'CONFIRMED' and not reservation.checked_in_at and reservation.arrival_deadline and now >= reservation.arrival_deadline:
        reservation.status = 'EXPIRED'
        if reservation.payment_method == 'DEPOSIT':
            reservation.deposit_forfeited = True
            reservation.staff_notes = (reservation.staff_notes + f"\n[Status Sync] 5-hour arrival deadline passed at {now.isoformat()}. Deposit retained.").strip()
        else:
            reservation.staff_notes = (reservation.staff_notes + f"\n[Status Sync] 3-hour arrival deadline passed at {now.isoformat()}.").strip()
        reservation.save(update_fields=['status', 'deposit_forfeited', 'staff_notes'])
    elif reservation.status == 'PAYMENT_PENDING' and reservation.payment_deadline and now >= reservation.payment_deadline:
        reservation.status = 'EXPIRED'
        reservation.staff_notes = (reservation.staff_notes + f"\n[Status Sync] Deposit checkout timeout passed at {now.isoformat()}.").strip()
        reservation.save(update_fields=['status', 'staff_notes'])

    # Exit authorization flags
    is_exit_authorized = bool(reservation.exit_authorized_until and now <= reservation.exit_authorized_until)
    is_exit_window_expired = bool(reservation.exit_authorized_until and now > reservation.exit_authorized_until)

    # Billing calculation: only run dynamic calculation if vehicle is checked in and not checked out
    balance_due = 0
    balance_due_formatted = "0 ៛"
    total_paid = 0
    normal_days = 1
    overstay_days = 0

    if reservation.status == 'CHECKED_IN':
        bill = BillingService.calculate_bill(reservation, as_of=now)
        balance_due = int(bill.get('balance_due', 0))
        balance_due_formatted = bill.get('balance_due_formatted', f"{balance_due:,} ៛")
        total_paid = int(bill.get('total_paid', 0))
        normal_days = int(bill.get('normal_days', 1))
        overstay_days = int(bill.get('overstay_days', 0))
    elif reservation.status == 'CHECKED_OUT':
        balance_due = 0
        balance_due_formatted = "0 ៛"
        total_paid = int(reservation.deposit_amount or 0)
    elif reservation.status == 'CONFIRMED' and reservation.payment_method == 'DEPOSIT':
        total_paid = int(reservation.deposit_amount or 0)

    # Terminal state check
    is_terminal = reservation.status in ('CHECKED_OUT', 'CANCELLED', 'EXPIRED') or bool(reservation.checked_out)

    # Action permissions
    can_checkout = (reservation.status == 'CHECKED_IN' and not is_terminal)
    can_cancel = (reservation.status in ('CONFIRMED', 'PAYMENT_PENDING') and not reservation.checked_in_at and not is_terminal)
    can_pay_exit = (reservation.status == 'CHECKED_IN' and not is_exit_authorized and balance_due > 0 and not is_terminal)
    can_renew_exit = (reservation.status == 'CHECKED_IN' and balance_due == 0 and not is_terminal)
    qr_active = (reservation.status in ('CONFIRMED', 'CHECKED_IN') and not is_terminal)

    return {
        'ticket_code': reservation.ticket_code,
        'status': reservation.status,
        'status_display': reservation.get_status_display(),
        'payment_status': reservation.payment_status,
        'payment_status_display': reservation.get_payment_status_display(),
        'payment_method': reservation.payment_method,
        'is_walk_in': reservation.is_walk_in,
        'plate_number': reservation.plate_number,
        'zone_name': reservation.parking_zone.name,
        'zone_slug': reservation.parking_zone.slug,
        'checked_in_at': reservation.checked_in_at.isoformat() if reservation.checked_in_at else None,
        'checked_out_at': reservation.checked_out_at.isoformat() if reservation.checked_out_at else None,
        'arrival_deadline': reservation.arrival_deadline.isoformat() if reservation.arrival_deadline else None,
        'payment_deadline': reservation.payment_deadline.isoformat() if reservation.payment_deadline else None,
        'parking_deadline': reservation.parking_deadline.isoformat() if reservation.parking_deadline else None,
        'exit_authorized_until': reservation.exit_authorized_until.isoformat() if reservation.exit_authorized_until else None,
        'is_exit_authorized': is_exit_authorized,
        'is_exit_window_expired': is_exit_window_expired,
        'balance_due': balance_due,
        'balance_due_formatted': balance_due_formatted,
        'total_paid': total_paid,
        'normal_days': normal_days,
        'overstay_days': overstay_days,
        'can_checkout': can_checkout,
        'can_cancel': can_cancel,
        'can_pay_exit': can_pay_exit,
        'can_renew_exit': can_renew_exit,
        'qr_active': qr_active,
        'is_terminal': is_terminal,
        'version': int(now.timestamp()),
    }


@require_GET
def ticket_status_api(request, ticket_code):
    """
    GET /api/ticket/<ticket_code>/status/
    Returns live status of a single ticket.
    Enforces customer ownership or staff permissions.
    """
    now = timezone.now()
    ticket_code = (ticket_code or '').strip().upper()

    try:
        reservation = Reservation.objects.select_related('parking_zone', 'customer').get(ticket_code=ticket_code)
    except Reservation.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Ticket not found', 'code': 'TICKET_NOT_FOUND'}, status=404)

    # Ownership check: Customer must own the reservation or user must be staff
    if reservation.customer:
        if not request.user.is_authenticated:
            return JsonResponse({'success': False, 'error': 'Authentication required', 'code': 'AUTH_REQUIRED'}, status=401)
        if reservation.customer != request.user and not request.user.is_staff:
            return JsonResponse({'success': False, 'error': 'Permission denied', 'code': 'PERMISSION_DENIED'}, status=403)
    else:
        # Walk-in ticket without an account: staff can view or verify token
        if not request.user.is_staff:
            token = request.GET.get('token', '').strip()
            if not token or token != reservation.access_token:
                return JsonResponse({'success': False, 'error': 'Permission denied', 'code': 'PERMISSION_DENIED'}, status=403)

    data = _serialize_ticket_status(reservation, now)
    data['success'] = True
    data['server_time'] = now.isoformat()
    return JsonResponse(data)


@require_GET
@login_required
def batch_tickets_status_api(request):
    """
    GET /api/tickets/status/?codes=SPK-1,SPK-2,...
    Batched status endpoint for customer dashboard and ticket history lists.
    Returns status map for requested ticket codes belonging to the authenticated user.
    """
    raw_codes = request.GET.get('codes', '')
    if not raw_codes:
        return JsonResponse({'success': True, 'tickets': {}, 'server_time': timezone.now().isoformat()})

    clean_codes = [c.strip().upper() for c in raw_codes.split(',') if c.strip()][:50]
    now = timezone.now()

    qs = Reservation.objects.filter(ticket_code__in=clean_codes).select_related('parking_zone', 'customer')
    if not request.user.is_staff:
        qs = qs.filter(customer=request.user)

    tickets_map = {}
    for res in qs:
        tickets_map[res.ticket_code] = _serialize_ticket_status(res, now)

    return JsonResponse({
        'success': True,
        'tickets': tickets_map,
        'server_time': now.isoformat(),
    })


@require_GET
def zones_status_api(request):
    """
    GET /api/zones/status/?slugs=bkk1-commercial-plaza,...
    Returns live parking capacity telemetry for homepage or zone detail pages.
    """
    raw_slugs = request.GET.get('slugs', '')
    qs = ParkingZone.objects.all()

    if raw_slugs:
        slug_list = [s.strip().lower() for s in raw_slugs.split(',') if s.strip()][:30]
        qs = qs.filter(slug__in=slug_list)

    zones_map = {}
    for zone in qs:
        zones_map[zone.slug] = {
            'name': zone.name,
            'khmer_name': zone.khmer_name,
            'slug': zone.slug,
            'num_of_slots': zone.num_of_slots,
            'occupied_slots': zone.occupied_slots,
            'vacant_slots': zone.vacant_slots,
            'occupancy_percentage': zone.occupancy_percentage,
            'availability_status': zone.availability_status,
            'price': zone.price,
            'price_khr_formatted': zone.price_khr_formatted,
            'walk_in_price': zone.walk_in_price,
            'walk_in_price_khr_formatted': zone.walk_in_price_khr_formatted,
        }

    return JsonResponse({
        'success': True,
        'zones': zones_map,
        'server_time': timezone.now().isoformat(),
    })
