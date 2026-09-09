import json
from functools import wraps
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum
from django.views.decorators.http import require_POST
from django.utils import timezone
from .models import ParkingZone, Reservation, PaymentTransaction
from .forms import ReservationForm
from .services import BillingService, CapacityService, PaymentService, GateService, ExpiryService
from .qr import generate_access_qr_base64, render_access_qr_response
from .payments import DemoPaymentAdapter


def staff_required(view_func):
    """
    Access control decorator for staff operations workbench.
    - Redirects unauthenticated visitors to login (/user/login/?next=...).
    - Raises PermissionDenied (HTTP 403) for authenticated non-staff accounts.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url='login')
        if not request.user.is_staff:
            raise PermissionDenied('Access denied. Staff authorization required.')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def zone_detail(request, slug):
    """Display individual parking zone status and details."""
    zone = get_object_or_404(ParkingZone, slug=slug)
    user_active_res = None
    if request.user.is_authenticated:
        user_active_res = Reservation.objects.filter(
            customer=request.user,
            parking_zone=zone,
            status__in=['CONFIRMED', 'CHECKED_IN']
        ).first()

    context = {
        'parking_zone': zone,
        'title': f'{zone.name} - SomPark Phnom Penh',
        'user_active_res': user_active_res,
    }
    return render(request, 'parking_zones/status.html', context)


@login_required
def booking(request):
    """Reserve a parking slot with payment method selection and capacity enforcement."""
    # Pre-check active reservation
    active_reservation = Reservation.objects.filter(
        customer=request.user,
        status__in=['CONFIRMED', 'CHECKED_IN']
    ).first()

    if active_reservation:
        messages.warning(
            request,
            f'You already have an active reservation at {active_reservation.parking_zone.name} '
            f'(Ticket: {active_reservation.ticket_code}). Please check out before booking another space.'
        )
        return redirect('ticket_code', ticket_code=active_reservation.ticket_code)

    zones_list = list(ParkingZone.objects.all())
    selected_zone_slug = request.GET.get('zone')
    initial_data = {}
    selected_zone = None
    if selected_zone_slug:
        selected_zone = next((z for z in zones_list if z.slug == selected_zone_slug and z.vacant_slots > 0), None)
        if selected_zone:
            initial_data['parking_zone'] = selected_zone

    zones_meta = {
        str(z.id): {
            'id': z.id,
            'name': z.name,
            'price': z.price,
            'price_formatted': f"{z.price:,} ៛",
            'overstay_price': z.price * 2,
            'overstay_formatted': f"{z.price * 2:,} ៛",
        }
        for z in zones_list
    }
    zones_meta_json = json.dumps(zones_meta)

    if request.method == 'POST':
        form = ReservationForm(request.POST)
        if form.is_valid():
            zone = form.cleaned_data['parking_zone']
            start_dt = form.cleaned_data.get('start_datetime')
            finish_dt = form.cleaned_data.get('finish_datetime')
            payment_method = form.cleaned_data.get('payment_method', 'DEPOSIT')

            try:
                with transaction.atomic():
                    # Check capacity atomically with select_for_update inside service
                    has_capacity = CapacityService.check_date_range_availability(zone.id, start_dt, finish_dt)
                    if not has_capacity:
                        messages.error(request, f'Sorry, {zone.name} does not have sufficient space available for this period.')
                        return render(request, 'parking_zones/booking.html', {
                            'form': form,
                            'title': 'Reserve Parking Slot | SomPark',
                            'active_reservation': active_reservation,
                            'parking_zones': zones_list,
                            'selected_zone': zone,
                            'zones_meta_json': zones_meta_json,
                        })

                    # Check for duplicate active reservation for this user inside transaction
                    if Reservation.objects.filter(customer=request.user, status__in=['CONFIRMED', 'CHECKED_IN']).exists():
                        messages.warning(request, 'You already have an active reservation.')
                        return redirect('home')

                    reservation = form.save(commit=False)
                    reservation.customer = request.user
                    reservation.save()

                    if payment_method == 'DEPOSIT':
                        # Create deposit transaction with 15-minute checkout timer
                        PaymentService.create_deposit_transaction(reservation)
                        messages.info(
                            request,
                            'Please complete your first-day deposit payment to confirm your guaranteed parking space.'
                        )
                        return redirect('pay_deposit', ticket_code=reservation.ticket_code)
                    else:
                        # Pay at exit: 3-hour arrival hold
                        messages.success(
                            request,
                            f'ចំណតត្រូវបានកក់ដោយជោគជ័យ! 3-hour arrival hold confirmed. '
                            f'Ticket Code: {reservation.ticket_code}. Please arrive before deadline.'
                        )
                        return redirect('ticket_code', ticket_code=reservation.ticket_code)

            except Exception as e:
                messages.error(request, f'An unexpected error occurred during reservation: {str(e)}')
                return redirect('book')
    else:
        today = timezone.localdate()
        initial_data.setdefault('start_date', today)
        initial_data.setdefault('finish_date', today)
        form = ReservationForm(initial=initial_data)

    if not selected_zone:
        if form.is_bound:
            zone_id = form.data.get('parking_zone')
            if zone_id:
                selected_zone = next((z for z in zones_list if str(z.id) == str(zone_id)), None)
        elif initial_data.get('parking_zone'):
            selected_zone = initial_data['parking_zone']
    if not selected_zone and zones_list:
        selected_zone = zones_list[0]

    context = {
        'form': form,
        'title': 'Reserve Parking Slot | SomPark',
        'active_reservation': active_reservation,
        'parking_zones': zones_list,
        'selected_zone': selected_zone,
        'zones_meta_json': zones_meta_json,
    }
    return render(request, 'parking_zones/booking.html', context)


@login_required
def pay_deposit(request, ticket_code):
    """
    Deposit payment screen. Explains deposit policy, displays 15-minute timeout countdown,
    and provides demo simulation buttons in development mode.
    """
    reservation = get_object_or_404(Reservation, ticket_code=ticket_code)

    if reservation.customer != request.user and not request.user.is_staff:
        raise PermissionDenied('Access denied to another user’s deposit payment.')

    if reservation.status == 'CONFIRMED' and reservation.payment_status == 'PARTIALLY_PAID':
        messages.success(request, 'Deposit payment has already been verified.')
        return redirect('ticket_code', ticket_code=reservation.ticket_code)

    if reservation.status in ('EXPIRED', 'CANCELLED'):
        messages.error(request, f'This reservation is {reservation.get_status_display().lower()}. Please book a new slot.')
        return redirect('book')

    txn = reservation.transactions.filter(purpose='DEPOSIT', status='PENDING').first()
    if not txn:
        txn = PaymentService.create_deposit_transaction(reservation)

    context = {
        'reservation': reservation,
        'transaction': txn,
        'deposit_amount': reservation.daily_rate,
        'demo_enabled': DemoPaymentAdapter.is_enabled(),
        'title': f'Deposit Payment · Ticket #{reservation.ticket_code} | SomPark',
    }
    return render(request, 'parking_zones/pay_deposit.html', context)


@login_required
@require_POST
def payment_simulate(request, txn_id):
    """
    Simulates payment gateway outcomes (success, failure, cancel).
    Restricted to DEMO_PAYMENT_ENABLED=True.
    """
    txn = get_object_or_404(PaymentTransaction, id=txn_id)
    reservation = txn.reservation

    if reservation.customer != request.user and not request.user.is_staff:
        raise PermissionDenied('Access denied to this payment simulation.')

    outcome = request.POST.get('outcome', 'success')
    success, msg = DemoPaymentAdapter.simulate_payment(txn.id, outcome)

    if success:
        messages.success(request, f'ការទូទាត់ប្រាក់កក់ទទួលបានជោគជ័យ! {msg}')
        return redirect('ticket_code', ticket_code=reservation.ticket_code)
    else:
        if outcome == 'cancel':
            messages.info(request, msg)
        else:
            messages.error(request, msg)
        return redirect('pay_deposit', ticket_code=reservation.ticket_code)


@login_required
@require_POST
def cancel_booking(request, ticket_code):
    """Allows customer or staff to cancel an un-checked-in reservation."""
    reservation = get_object_or_404(Reservation, ticket_code=ticket_code)

    if reservation.customer != request.user and not request.user.is_staff:
        raise PermissionDenied('Access denied to cancel this reservation.')

    if reservation.status == 'CHECKED_IN':
        messages.error(request, 'Cannot cancel a vehicle that is physically parked. Please complete gate checkout.')
        return redirect('ticket_code', ticket_code=reservation.ticket_code)

    if reservation.status in ('CHECKED_OUT', 'CANCELLED', 'EXPIRED'):
        messages.info(request, f'This reservation is already {reservation.get_status_display().lower()}.')
        return redirect('dashboard')

    reservation.status = 'CANCELLED'
    reservation.staff_notes = (reservation.staff_notes + f"\nCancelled by {request.user.username} at {timezone.now().isoformat()}").strip()
    reservation.save(update_fields=['status', 'staff_notes'])

    messages.success(request, f'Reservation #{reservation.ticket_code} was cancelled.')
    return redirect('dashboard')


@login_required
def ticket_detail(request, ticket_code=None):
    """View and print a parking ticket with scannable access QR code and billing details."""
    if ticket_code:
        if request.user.is_staff:
            reservation = get_object_or_404(Reservation, ticket_code=ticket_code)
        else:
            reservation = get_object_or_404(Reservation, ticket_code=ticket_code, customer=request.user)
    else:
        reservation = Reservation.objects.filter(
            customer=request.user,
            status__in=['CONFIRMED', 'CHECKED_IN']
        ).order_by('-created_on').first()

        if not reservation:
            reservation = Reservation.objects.filter(
                customer=request.user
            ).order_by('-created_on').first()

    if not reservation:
        messages.info(request, 'No reservation records found. Book your first parking spot below.')
        return redirect('book')

    now = timezone.now()
    bill = BillingService.calculate_bill(reservation, as_of=now)
    qr_data_uri = generate_access_qr_base64(reservation.access_token)

    context = {
        'reservation': reservation,
        'bill': bill,
        'qr_data_uri': qr_data_uri,
        'now': now,
        'title': f'Ticket #{reservation.ticket_code} - SomPark',
    }
    return render(request, 'parking_zones/ticket.html', context)


def ticket_qr_image(request, ticket_code):
    """Serves pure streaming PNG QR image for external tags."""
    reservation = get_object_or_404(Reservation, ticket_code=ticket_code)
    return render_access_qr_response(reservation.access_token)


@login_required
def ticket_gate_mode(request, ticket_code):
    """High-contrast full-screen 'Show at gate' view for smartphone display."""
    if request.user.is_staff:
        reservation = get_object_or_404(Reservation, ticket_code=ticket_code)
    else:
        reservation = get_object_or_404(Reservation, ticket_code=ticket_code, customer=request.user)

    qr_data_uri = generate_access_qr_base64(reservation.access_token)
    bill = BillingService.calculate_bill(reservation)

    context = {
        'reservation': reservation,
        'bill': bill,
        'qr_data_uri': qr_data_uri,
        'title': f'Gate Pass #{reservation.ticket_code} | SomPark',
    }
    return render(request, 'parking_zones/gate_pass_fullscreen.html', context)


@login_required
def all_tickets(request):
    """View customer reservation history."""
    reservations = Reservation.objects.filter(
        customer=request.user
    ).select_related('parking_zone').order_by('-created_on')

    active_reservation = reservations.filter(status__in=['CONFIRMED', 'CHECKED_IN']).first()

    context = {
        'tickets': reservations,
        'reservations': reservations,
        'active_reservation': active_reservation,
        'title': 'My Parking Tickets | SomPark',
    }
    return render(request, 'parking_zones/all_tickets.html', context)


@staff_required
def staff_gate_scanner(request):
    """
    Dedicated Staff Gate Operations Scanner.
    Supports camera QR scanning, manual code/token lookup,
    entry validation, and exit settlement with barrier simulation.
    """
    zones = ParkingZone.objects.all().order_by('name')
    selected_zone_id = request.GET.get('zone_id')
    selected_zone = None
    if selected_zone_id:
        selected_zone = ParkingZone.objects.filter(id=selected_zone_id).first()

    context = {
        'zones': zones,
        'selected_zone': selected_zone,
        'title': 'Gate Access Scanner | SomPark Staff',
    }
    return render(request, 'parking_zones/gate_scanner.html', context)


@staff_required
@require_POST
def staff_gate_action(request):
    """
    Unified staff gate action handler:
    - lookup_entry
    - confirm_entry
    - lookup_exit
    - collect_exit_payment
    - confirm_exit
    """
    action = request.POST.get('action')
    token_or_code = request.POST.get('token_or_code', '').strip()
    zone_id = request.POST.get('zone_id')
    zone_id = int(zone_id) if zone_id and zone_id.isdigit() else None

    # Handle lookup for entry
    if action == 'lookup_entry':
        is_valid, reservation, msg = GateService.validate_entry(token_or_code, zone_id=zone_id)
        if not reservation:
            messages.error(request, msg)
            return redirect('staff_gate_scanner')
        context = {
            'reservation': reservation,
            'is_valid': is_valid,
            'message': msg,
            'mode': 'entry_preview',
            'zones': ParkingZone.objects.all(),
            'title': 'Verify Entry | SomPark Gate',
        }
        return render(request, 'parking_zones/gate_scanner.html', context)

    # Handle confirmation of entry
    elif action == 'confirm_entry':
        res_id = request.POST.get('reservation_id')
        success, reservation, msg = GateService.confirm_entry(res_id, staff_user=request.user)
        if success:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect('staff_gate_scanner')

    # Handle lookup for exit
    elif action == 'lookup_exit':
        can_exit, reservation, bill, msg = GateService.prepare_exit(token_or_code)
        if not reservation:
            messages.error(request, msg)
            return redirect('staff_gate_scanner')
        context = {
            'reservation': reservation,
            'bill': bill,
            'can_exit': can_exit,
            'message': msg,
            'mode': 'exit_preview',
            'now': timezone.now(),
            'demo_enabled': DemoPaymentAdapter.is_enabled(),
            'zones': ParkingZone.objects.all(),
            'title': 'Process Exit | SomPark Gate',
        }
        return render(request, 'parking_zones/gate_scanner.html', context)

    # Handle settlement of exit balance
    elif action == 'collect_exit_payment':
        res_id = request.POST.get('reservation_id')
        reservation = get_object_or_404(Reservation, id=res_id)
        bill = BillingService.calculate_bill(reservation)
        amount = bill['balance_due']

        if amount > 0:
            provider = request.POST.get('payment_provider', 'CASH')
            PaymentService.record_exit_payment(reservation, amount=amount, provider=provider)
            messages.success(
                request,
                f'Exit balance of {amount:,} KHR paid via {provider}. '
                f'5-minute departure window authorized.'
            )
        else:
            messages.info(request, 'No outstanding balance due. Departure authorized.')

        return_to = request.POST.get('return_to') or request.GET.get('return_to')
        if return_to == 'virtual_gate':
            return redirect(f"{reverse('admin_virtual_gate')}?zone={reservation.parking_zone_id}&mode=exit&code={reservation.ticket_code}")
        return redirect(f"{redirect('staff_gate_scanner').url}?token={reservation.ticket_code}&mode=exit")

    # Handle physical gate exit completion
    elif action == 'confirm_exit':
        res_id = request.POST.get('reservation_id')
        success, reservation, msg = GateService.confirm_physical_exit(res_id, staff_user=request.user)
        if success:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return_to = request.POST.get('return_to') or request.GET.get('return_to')
        if return_to == 'virtual_gate' and reservation:
            return redirect(f"{reverse('admin_virtual_gate')}?zone={reservation.parking_zone_id}&mode=exit&code={reservation.ticket_code}")
        return redirect('staff_gate_scanner')

    messages.error(request, 'Invalid gate operation requested.')
    return redirect('staff_gate_scanner')


@login_required
@require_POST
def checkout(request):
    """
    Customer checkout action.
    Validates ticket ownership, enforces settlement, and authorizes exit.
    Only allows check out for reservations that are currently CHECKED_IN.
    """
    ticket_code = request.POST.get('ticket_code', '').strip()
    if ticket_code and Reservation.objects.filter(ticket_code=ticket_code).exclude(customer=request.user).exists() and not request.user.is_staff:
        raise PermissionDenied('You do not have permission to check out another user’s ticket.')

    reservation = get_object_or_404(Reservation, ticket_code=ticket_code)
    if reservation.customer != request.user and not request.user.is_staff:
        raise PermissionDenied('You do not have permission to check out another user’s ticket.')

    if reservation.checked_out or reservation.status == 'CHECKED_OUT':
        messages.info(request, 'This parking ticket is already checked out.')
        return redirect('ticket_code', ticket_code=reservation.ticket_code)

    if reservation.status != 'CHECKED_IN':
        messages.error(
            request,
            'Cannot check out a reservation that has not checked in. If you wish to release your hold, please cancel the reservation.'
        )
        return redirect('ticket_code', ticket_code=reservation.ticket_code)

    bill = BillingService.calculate_bill(reservation, as_of=timezone.now())
    now = timezone.now()
    if bill['balance_due'] > 0 and not (reservation.exit_authorized_until and now <= reservation.exit_authorized_until):
        messages.error(
            request,
            f'Outstanding balance of {bill["balance_due"]:,} KHR must be settled before checkout. Please present your pass at the gate barrier.'
        )
        return redirect('ticket_code', ticket_code=reservation.ticket_code)

    success, reservation, msg = GateService.confirm_physical_exit(reservation.pk, staff_user=request.user if request.user.is_staff else None)
    if success:
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    return redirect('dashboard')


@staff_required
@require_POST
def admin_checkout(request):
    """
    Dedicated staff checkout action.
    Gracefully handles ticket lookup, enforces idempotency,
    and updates capacity while logging reconciliation notes.
    """
    ticket_code = request.POST.get('ticket_code', '').strip()
    reservation = Reservation.objects.filter(ticket_code=ticket_code).first()

    if not reservation:
        messages.error(request, f'Reservation ticket "{ticket_code}" could not be found.')
        return redirect('admin_dashboard')

    if reservation.checked_out or reservation.status == 'CHECKED_OUT':
        messages.warning(
            request,
            f'Ticket #{reservation.ticket_code} ({reservation.plate_number}) has already checked out. Occupancy unchanged.'
        )
        return redirect('admin_dashboard')

    if reservation.status == 'CHECKED_IN':
        bill = BillingService.calculate_bill(reservation, as_of=timezone.now())
        now = timezone.now()
        if bill['balance_due'] > 0 and not (reservation.exit_authorized_until and now <= reservation.exit_authorized_until):
            messages.error(
                request,
                f'Cannot check out ticket #{reservation.ticket_code}. Outstanding balance of {bill["balance_due"]:,} KHR must be settled before exit.'
            )
            return redirect('admin_dashboard')

        success, reservation, msg = GateService.confirm_physical_exit(reservation.pk, staff_user=request.user)
        if success:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect('admin_dashboard')

    with transaction.atomic():
        zone = ParkingZone.objects.select_for_update().get(id=reservation.parking_zone_id)
        reservation.status = 'CHECKED_OUT'
        reservation.checked_out = True
        reservation.checked_out_at = timezone.now()
        reservation.staff_notes = (
            reservation.staff_notes + f"\nAdmin manual checkout by {request.user.username} at {timezone.now().isoformat()}"
        ).strip()
        reservation.save(update_fields=['status', 'checked_out', 'checked_out_at', 'staff_notes'])

        if zone.occupied_slots > 0:
            zone.increment_slot()

    messages.success(
        request,
        f'Ticket #{reservation.ticket_code} ({reservation.plate_number}) checked out successfully. '
        f'Parking space released at {reservation.parking_zone.name}.'
    )
    return redirect('admin_dashboard')



@staff_required
def admin_dashboard(request):
    """
    Dedicated Staff Operations Dashboard for SomPark Phnom Penh.
    Distinguishes physically occupied, active arrival holds, and vacant spots.
    Shows real-time overstay alerts and links to Gate Access Scanner.
    """
    total_zones = ParkingZone.objects.count()
    zone_stats = ParkingZone.objects.aggregate(
        total_capacity=Sum('num_of_slots'),
        total_occupied=Sum('occupied_slots'),
        total_vacant=Sum('vacant_slots'),
    )
    total_capacity = zone_stats['total_capacity'] or 0
    total_occupied = zone_stats['total_occupied'] or 0
    total_vacant = zone_stats['total_vacant'] or 0

    if total_capacity > 0:
        overall_occupancy_pct = int(round((total_occupied / total_capacity) * 100))
    else:
        overall_occupancy_pct = 0

    now = timezone.now()

    # Active holds (arriving soon)
    active_holds_count = Reservation.objects.filter(
        status='CONFIRMED',
        payment_method='PAY_AT_EXIT',
        arrival_deadline__gt=now
    ).count() + Reservation.objects.filter(
        status='PAYMENT_PENDING',
        payment_deadline__gt=now
    ).count()

    active_reservations_count = Reservation.objects.filter(status__in=['CONFIRMED', 'CHECKED_IN']).count()
    completed_reservations_count = Reservation.objects.filter(status='CHECKED_OUT').count()
    registered_customers_count = User.objects.filter(is_staff=False).count()

    # Overstay count (physically checked in beyond booked finish time)
    overstay_count = Reservation.objects.filter(
        status='CHECKED_IN',
        finish_time__lt=now
    ).count()

    # Parking zone status ordered so most occupied zones are visible first
    zones = ParkingZone.objects.all().order_by('-occupied_slots', '-num_of_slots', 'name')

    # Recent active reservations with queryset optimization & pagination
    active_reservations_list = (
        Reservation.objects.filter(status__in=['CONFIRMED', 'CHECKED_IN'])
        .select_related('customer', 'parking_zone')
        .order_by('-created_on', '-id')
    )
    active_paginator = Paginator(active_reservations_list, 10)
    active_page = request.GET.get('active_page', 1)
    active_reservations = active_paginator.get_page(active_page)

    # Recently completed reservations with queryset optimization & pagination
    completed_reservations_list = (
        Reservation.objects.filter(status='CHECKED_OUT')
        .select_related('customer', 'parking_zone')
        .order_by('-checked_out_at', '-id')
    )
    completed_paginator = Paginator(completed_reservations_list, 10)
    completed_page = request.GET.get('completed_page', 1)
    completed_reservations = completed_paginator.get_page(completed_page)

    context = {
        'total_zones': total_zones,
        'total_capacity': total_capacity,
        'total_occupied': total_occupied,
        'total_vacant': total_vacant,
        'active_holds_count': active_holds_count,
        'active_reservations_count': active_reservations_count,
        'completed_reservations_count': completed_reservations_count,
        'registered_customers_count': registered_customers_count,
        'overstay_count': overstay_count,
        'overall_occupancy_pct': overall_occupancy_pct,
        'zones': zones,
        'active_reservations': active_reservations,
        'completed_reservations': completed_reservations,
        'now': now,
        'title': 'Staff Operations Dashboard | SomPark Phnom Penh',
    }
    return render(request, 'parking_zones/admin_dashboard.html', context)
