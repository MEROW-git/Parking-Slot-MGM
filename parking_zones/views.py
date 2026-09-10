import json
from datetime import timedelta
from functools import wraps
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
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
from django.http import JsonResponse
from .models import ParkingZone, Reservation, PaymentTransaction
from .forms import ReservationForm
from .services import BillingService, CapacityService, PaymentService, GateService, ExpiryService, AntiSpamService
from .qr import generate_access_qr_base64, render_access_qr_response, generate_demo_payment_qr_base64
from .payments import DemoPaymentAdapter
from .ai import check_ai_rate_limit, GeminiService


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

    coords = zone.coordinates
    zone_map_data = {
        'id': zone.id,
        'name': zone.name,
        'khmer_name': zone.khmer_name,
        'slug': zone.slug,
        'address': zone.address,
        'district': zone.district,
        'price': zone.price,
        'price_formatted': zone.price_khr_formatted,
        'vacant_slots': zone.vacant_slots,
        'num_of_slots': zone.num_of_slots,
        'occupied_slots': zone.occupied_slots,
        'availability_status': zone.availability_status,
        'lat': coords['lat'],
        'lng': coords['lng'],
        'book_url': reverse('book') + f'?zone={zone.slug}',
        'detail_url': reverse('zone_detail', kwargs={'slug': zone.slug}),
    }

    context = {
        'parking_zone': zone,
        'zone_map_json': json.dumps(zone_map_data),
        'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY,
        'title': f'{zone.name} - SomPark Phnom Penh',
        'user_active_res': user_active_res,
    }
    return render(request, 'parking_zones/status.html', context)


@login_required
def booking(request):
    """Reserve a parking slot with payment method selection, anti-spam enforcement, and capacity checks."""
    # 1. Request Throttling Check
    throttle_ok, throttle_msg = AntiSpamService.check_request_throttling(request)
    if not throttle_ok:
        messages.error(request, throttle_msg)
        return redirect('dashboard')

    # 2. Check Active Reservation Limit (1 per account, including PAYMENT_PENDING)
    has_no_active, active_reservation, active_msg = AntiSpamService.check_active_reservation_limit(request.user)
    if not has_no_active and active_reservation:
        messages.warning(request, active_msg)
        if active_reservation.status == 'PAYMENT_PENDING':
            return redirect('pay_deposit', ticket_code=active_reservation.ticket_code)
        return redirect('ticket_code', ticket_code=active_reservation.ticket_code)

    # 3. Check Pay-Later Eligibility for this customer
    pay_later_allowed, pay_later_reason, pay_later_meta = AntiSpamService.check_pay_later_eligibility(request.user)

    zones_list = list(ParkingZone.objects.all())
    selected_zone_slug = request.GET.get('zone')
    initial_data = {}
    selected_zone = None
    if selected_zone_slug:
        selected_zone = next((z for z in zones_list if z.slug == selected_zone_slug and z.vacant_slots > 0), None)
        if selected_zone:
            initial_data['parking_zone'] = selected_zone

    # Default to PAY_AT_EXIT if eligible, or DEPOSIT if pay-later is locked out
    if not pay_later_allowed:
        initial_data['payment_method'] = 'DEPOSIT'

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
            reserved_days = form.cleaned_data.get('reserved_days', 1)
            plate_number = form.cleaned_data.get('plate_number', '')
            normalized_plate = AntiSpamService.normalize_plate(plate_number)

            # Check for duplicate submission first (double-clicks / retries within 2 minutes)
            # Duplicate submissions must return the existing booking without consuming extra capacity
            duplicate_res = AntiSpamService.find_duplicate_submission(
                user=request.user,
                zone=zone,
                normalized_plate=normalized_plate,
                payment_method=payment_method,
                within_seconds=120
            )
            if duplicate_res:
                if duplicate_res.status == 'PAYMENT_PENDING':
                    messages.info(request, f"Resuming your pending booking for vehicle {duplicate_res.plate_number}.")
                    return redirect('pay_deposit', ticket_code=duplicate_res.ticket_code)
                messages.info(request, f"Your reservation for vehicle {duplicate_res.plate_number} is already confirmed.")
                return redirect('ticket_code', ticket_code=duplicate_res.ticket_code)

            # Anti-Spam Check: One active reservation per account
            has_no_active, existing_active, active_err = AntiSpamService.check_active_reservation_limit(request.user)
            if not has_no_active:
                messages.warning(request, active_err)
                if existing_active and existing_active.status == 'PAYMENT_PENDING':
                    return redirect('pay_deposit', ticket_code=existing_active.ticket_code)
                elif existing_active:
                    return redirect('ticket_code', ticket_code=existing_active.ticket_code)
                return redirect('dashboard')

            # Anti-Spam Check: Pay-Later Rules
            if payment_method == 'PAY_AT_EXIT':
                can_pay_later, pay_later_err, _ = AntiSpamService.check_pay_later_eligibility(request.user)
                if not can_pay_later:
                    messages.error(request, pay_later_err)
                    return render(request, 'parking_zones/booking.html', {
                        'form': form,
                        'title': 'Reserve Parking Slot | SomPark',
                        'active_reservation': None,
                        'parking_zones': zones_list,
                        'selected_zone': zone,
                        'zones_meta_json': zones_meta_json,
                        'pay_later_allowed': False,
                        'pay_later_reason': pay_later_err,
                        'pay_later_meta': pay_later_meta,
                    })

            # Anti-Spam Check: Prevent simultaneous holds for the same normalized vehicle plate across facilities
            plate_free, plate_holder, plate_err = AntiSpamService.check_simultaneous_plate_hold(normalized_plate)
            if not plate_free:
                messages.error(request, plate_err)
                return render(request, 'parking_zones/booking.html', {
                    'form': form,
                    'title': 'Reserve Parking Slot | SomPark',
                    'active_reservation': None,
                    'parking_zones': zones_list,
                    'selected_zone': zone,
                    'zones_meta_json': zones_meta_json,
                    'pay_later_allowed': pay_later_allowed,
                    'pay_later_reason': pay_later_reason,
                    'pay_later_meta': pay_later_meta,
                })

            try:
                with transaction.atomic():
                    # Check capacity atomically with select_for_update inside service
                    has_capacity = CapacityService.check_date_range_availability(
                        zone.id, start_dt, finish_dt, reserved_days=reserved_days
                    )
                    if not has_capacity:
                        messages.error(request, f'Sorry, {zone.name} does not have sufficient space available for this period.')
                        return render(request, 'parking_zones/booking.html', {
                            'form': form,
                            'title': 'Reserve Parking Slot | SomPark',
                            'active_reservation': None,
                            'parking_zones': zones_list,
                            'selected_zone': zone,
                            'zones_meta_json': zones_meta_json,
                            'pay_later_allowed': pay_later_allowed,
                            'pay_later_reason': pay_later_reason,
                            'pay_later_meta': pay_later_meta,
                        })

                    # Final race condition check inside transaction
                    if Reservation.objects.filter(
                        customer=request.user,
                        status__in=['CONFIRMED', 'CHECKED_IN', 'PAYMENT_PENDING'],
                        checked_out=False
                    ).exists():
                        messages.warning(request, 'You already have an active reservation.')
                        return redirect('dashboard')

                    reservation = form.save(commit=False)
                    reservation.customer = request.user
                    reservation.save()

                    if payment_method == 'DEPOSIT':
                        # Create deposit transaction with short 15-minute checkout timer
                        PaymentService.create_deposit_transaction(reservation)
                        messages.info(
                            request,
                            'Please complete your first-day deposit payment to confirm your 5-hour guaranteed arrival window.'
                        )
                        return redirect('pay_deposit', ticket_code=reservation.ticket_code)
                    else:
                        # Pay at exit: 3-hour arrival hold
                        messages.success(
                            request,
                            f'ចំណតត្រូវបានកក់ដោយជោគជ័យ! Enter within 3 hours after booking. Pay when you leave. '
                            f'Ticket Code: {reservation.ticket_code}.'
                        )
                        return redirect('ticket_code', ticket_code=reservation.ticket_code)

            except Exception as e:
                messages.error(request, f'An unexpected error occurred during reservation: {str(e)}')
                return redirect('book')
    else:
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
        'pay_later_allowed': pay_later_allowed,
        'pay_later_reason': pay_later_reason,
        'pay_later_meta': pay_later_meta,
    }
    return render(request, 'parking_zones/booking.html', context)


@login_required
def pay_deposit(request, ticket_code):
    """
    Deposit payment screen. Explains deposit policy, displays 15-minute timeout countdown,
    provides ABA QR demo simulation experience, and enforces that cash deposits must be
    confirmed by parking staff (never a customer self-certification button).
    """
    reservation = get_object_or_404(Reservation, ticket_code=ticket_code)

    if reservation.customer != request.user and not request.user.is_staff:
        raise PermissionDenied('Access denied to another user’s deposit payment.')

    if reservation.status == 'CONFIRMED' and reservation.payment_status == 'PARTIALLY_PAID':
        messages.success(request, 'Deposit payment has already been verified.')
        return redirect('ticket_code', ticket_code=reservation.ticket_code)

    now = timezone.now()
    if reservation.status == 'PAYMENT_PENDING' and reservation.payment_deadline and now >= reservation.payment_deadline:
        reservation.status = 'EXPIRED'
        reservation.staff_notes = (reservation.staff_notes + f"\n[Request-Time Check] Deposit checkout timeout passed at {now.isoformat()}.").strip()
        reservation.save(update_fields=['status', 'staff_notes'])
        messages.error(request, 'The deposit checkout window has expired. Please book a new slot.')
        return redirect('book')

    if reservation.status in ('EXPIRED', 'CANCELLED'):
        messages.error(request, f'This reservation is {reservation.get_status_display().lower()}. Please book a new slot.')
        return redirect('book')

    # Handle staff cash deposit confirmation or reject customer cash self-certification attempts
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'staff_confirm_cash':
            if not request.user.is_staff:
                raise PermissionDenied('Customers cannot self-confirm cash deposits. Cash must be verified by parking staff.')
            success, msg = PaymentService.record_cash_deposit(reservation, staff_user=request.user)
            if success:
                messages.success(request, msg)
                return redirect('ticket_code', ticket_code=reservation.ticket_code)
            else:
                messages.error(request, msg)
                return redirect('pay_deposit', ticket_code=reservation.ticket_code)
        elif 'cash' in (action or '').lower() or request.POST.get('payment_method') == 'CASH':
            if not request.user.is_staff:
                raise PermissionDenied('Customers cannot self-confirm cash deposits. Cash must be verified by parking staff.')

    txn = reservation.transactions.filter(purpose='DEPOSIT', status='PENDING').first()
    if not txn:
        txn = PaymentService.create_deposit_transaction(reservation)

    demo_enabled = DemoPaymentAdapter.is_enabled()
    demo_payment_qr = None
    if txn and demo_enabled:
        demo_payment_qr = generate_demo_payment_qr_base64(
            reference=txn.provider_ref,
            amount=int(txn.amount),
            currency=txn.currency or 'KHR'
        )

    context = {
        'reservation': reservation,
        'transaction': txn,
        'deposit_amount': reservation.daily_rate,
        'demo_enabled': demo_enabled,
        'demo_payment_qr': demo_payment_qr,
        'demo_payment_ref': txn.provider_ref if txn else '',
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

    if txn.purpose == 'EXIT_BALANCE':
        if success:
            res_refresh = Reservation.objects.get(id=reservation.id)
            bill = BillingService.calculate_bill(res_refresh, as_of=timezone.now())
            if bill['balance_due'] == 0:
                messages.success(request, 'Payment successful. You’re ready to leave.')
                return redirect('ticket_code', ticket_code=reservation.ticket_code)
            else:
                messages.info(request, msg)
                return redirect('pay_exit', ticket_code=reservation.ticket_code)
        else:
            if outcome == 'cancel':
                messages.info(request, 'Payment was cancelled. Your vehicle remains checked in.')
                return redirect('ticket_code', ticket_code=reservation.ticket_code)
            else:
                messages.error(request, msg)
                return redirect('pay_exit', ticket_code=reservation.ticket_code)
    else:
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
def pay_exit(request, ticket_code):
    """
    Authenticated customer exit payment review and settlement screen.
    GET: Read-only. Calculates current bill and displays review screen.
         Never creates or cancels payment transactions on GET!
         If exit authorization is already active, redirects to ticket.
    POST: Processes payment submission, developer failure simulation,
          or cancellation atomically without duplicate payable attempts.
    """
    reservation = get_object_or_404(Reservation, ticket_code=ticket_code)

    if reservation.customer != request.user and not request.user.is_staff:
        raise PermissionDenied('Access denied to another user’s exit payment.')

    if reservation.status == 'CONFIRMED':
        messages.info(request, 'Vehicle has not checked in yet. Exit payment is only required when departing.')
        return redirect('ticket_code', ticket_code=reservation.ticket_code)

    if reservation.status in ('EXPIRED', 'CANCELLED'):
        messages.error(request, f'This reservation is {reservation.get_status_display().lower()}. Exit payment cannot be processed.')
        return redirect('dashboard')

    if reservation.status == 'CHECKED_OUT' or reservation.checked_out:
        messages.info(request, 'This parking session is already completed. Here is your final receipt.')
        return redirect('ticket_code', ticket_code=reservation.ticket_code)

    if reservation.status != 'CHECKED_IN':
        messages.error(request, f'Cannot process exit payment for reservation in status: {reservation.status}.')
        return redirect('ticket_code', ticket_code=reservation.ticket_code)

    now = timezone.now()
    exit_window_minutes = getattr(settings, 'EXIT_WINDOW_MINUTES', 5)

    is_exit_authorized = bool(reservation.exit_authorized_until and now <= reservation.exit_authorized_until)
    is_exit_window_expired = bool(reservation.exit_authorized_until and now > reservation.exit_authorized_until)

    # Rule 6: If already authorized with an active exit window, honor the settled bill and redirect to ticket!
    if is_exit_authorized:
        messages.info(request, 'Payment already verified. You’re ready to leave.')
        return redirect('ticket_code', ticket_code=reservation.ticket_code)

    bill = BillingService.calculate_bill(reservation, as_of=now)

    # HANDLE POST: Pay / Simulate Failure / Cancel
    if request.method == 'POST':
        action = request.POST.get('action', 'pay')

        if not DemoPaymentAdapter.is_enabled():
            messages.error(request, 'Online payment is currently unavailable. Please settle balance with staff at the barrier.')
            return redirect('pay_exit', ticket_code=reservation.ticket_code)

        if bill['balance_due'] == 0:
            messages.info(request, 'No balance is due. Please activate your exit authorization pass.')
            return redirect('pay_exit', ticket_code=reservation.ticket_code)

        outcome = 'success' if action == 'pay' else ('failure' if action == 'simulate_failure' else 'cancel')

        with transaction.atomic():
            res_locked = Reservation.objects.select_for_update().get(id=reservation.id)
            current_bill = BillingService.calculate_bill(res_locked, as_of=timezone.now())

            # Find or reuse pending transaction with exact amount
            pending_txn = res_locked.transactions.filter(purpose='EXIT_BALANCE', status='PENDING').first()
            if pending_txn and pending_txn.amount != current_bill['balance_due']:
                pending_txn.status = 'CANCELLED'
                pending_txn.raw_response = {
                    'reason': 'Quote updated due to recalculated bill',
                    'old_amount': pending_txn.amount,
                    'new_amount': current_bill['balance_due'],
                    'cancelled_at': timezone.now().isoformat(),
                }
                pending_txn.save(update_fields=['status', 'raw_response', 'updated_at'])
                pending_txn = None

            if not pending_txn:
                pending_txn = PaymentService.create_exit_transaction(res_locked, amount=current_bill['balance_due'])

            success, msg = DemoPaymentAdapter.simulate_payment(pending_txn.id, outcome=outcome)

        if outcome == 'success':
            res_locked.refresh_from_db()
            post_bill = BillingService.calculate_bill(res_locked, as_of=timezone.now())
            if post_bill['balance_due'] == 0:
                messages.success(request, 'Payment successful. You’re ready to leave.')
                return redirect('ticket_code', ticket_code=reservation.ticket_code)
            else:
                messages.info(request, msg)
                return redirect('pay_exit', ticket_code=reservation.ticket_code)
        elif outcome == 'failure':
            messages.error(request, msg)
            return redirect('pay_exit', ticket_code=reservation.ticket_code)
        else:
            messages.info(request, msg)
            return redirect('ticket_code', ticket_code=reservation.ticket_code)

    # GET REQUEST: Pure read-only view. No transaction creation or cancellation!
    existing_txn = reservation.transactions.filter(purpose='EXIT_BALANCE', status='PENDING').first()
    demo_enabled = DemoPaymentAdapter.is_enabled()
    demo_payment_qr = None
    demo_ref = None
    if bill['balance_due'] > 0 and demo_enabled:
        demo_ref = existing_txn.transaction_reference if existing_txn else f"EXIT-{reservation.ticket_code}"
        demo_payment_qr = generate_demo_payment_qr_base64(
            reference=demo_ref,
            amount=int(bill['balance_due']),
            currency='KHR'
        )

    context = {
        'reservation': reservation,
        'bill': bill,
        'transaction': existing_txn,
        'now': now,
        'exit_window_minutes': exit_window_minutes,
        'is_exit_authorized': is_exit_authorized,
        'is_exit_window_expired': is_exit_window_expired,
        'demo_enabled': demo_enabled,
        'demo_payment_qr': demo_payment_qr,
        'demo_payment_ref': demo_ref,
        'title': f'Pay & Prepare to Leave · Ticket #{reservation.ticket_code} | SomPark',
    }
    return render(request, 'parking_zones/pay_exit.html', context)


@login_required
@require_POST
def renew_exit_authorization(request, ticket_code):
    """
    Allows customer to renew or activate a server-validated exit authorization
    when balance_due == 0 without requiring another payment.
    Repeated clicks while window is active do NOT extend the window.
    """
    reservation = get_object_or_404(Reservation, ticket_code=ticket_code)

    if reservation.customer != request.user and not request.user.is_staff:
        raise PermissionDenied('Access denied to renew this exit pass.')

    if reservation.status != 'CHECKED_IN':
        messages.error(request, 'Exit authorization is only available for vehicles currently checked in.')
        return redirect('ticket_code', ticket_code=reservation.ticket_code)

    now = timezone.now()

    # Rule 7: If window is already active, repeated clicks must NOT extend the deadline
    if reservation.exit_authorized_until and now <= reservation.exit_authorized_until:
        messages.info(request, 'Your exit authorization is already active. You are ready to leave.')
        return redirect('ticket_code', ticket_code=reservation.ticket_code)

    bill = BillingService.calculate_bill(reservation, as_of=now)

    if bill['balance_due'] > 0:
        messages.error(request, f'Outstanding balance of {bill["balance_due"]:,} KHR must be settled before exit.')
        return redirect('pay_exit', ticket_code=reservation.ticket_code)

    exit_mins = getattr(settings, 'EXIT_WINDOW_MINUTES', 5)
    reservation.exit_authorized_until = now + timedelta(minutes=exit_mins)
    reservation.save(update_fields=['exit_authorized_until'])

    messages.success(request, f'Exit pass authorized. You have {exit_mins} minutes to reach the gate barrier.')
    return redirect('ticket_code', ticket_code=reservation.ticket_code)


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

    now = timezone.now()
    reservation.status = 'CANCELLED'
    reservation.cancelled_at = now
    reservation.deposit_forfeited = False  # Forfeiture applies only to no-shows, not operator/user cancellations
    reservation.staff_notes = (reservation.staff_notes + f"\nCancelled by {request.user.username} at {now.isoformat()}").strip()
    reservation.save(update_fields=['status', 'cancelled_at', 'deposit_forfeited', 'staff_notes'])

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

    # Request-time expiry check: ensure expired holds fail and transition immediately
    if reservation.status == 'CONFIRMED' and not reservation.checked_in_at and reservation.arrival_deadline and now >= reservation.arrival_deadline:
        reservation.status = 'EXPIRED'
        if reservation.payment_method == 'DEPOSIT':
            reservation.deposit_forfeited = True
            reservation.staff_notes = (reservation.staff_notes + f"\n[Request-Time Check] 5-hour arrival deadline passed at {now.isoformat()}. First-day deposit retained.").strip()
        else:
            reservation.staff_notes = (reservation.staff_notes + f"\n[Request-Time Check] 3-hour arrival deadline passed at {now.isoformat()}.").strip()
        reservation.save(update_fields=['status', 'deposit_forfeited', 'staff_notes'])
    elif reservation.status == 'PAYMENT_PENDING' and reservation.payment_deadline and now >= reservation.payment_deadline:
        reservation.status = 'EXPIRED'
        reservation.staff_notes = (reservation.staff_notes + f"\n[Request-Time Check] Deposit checkout timeout passed at {now.isoformat()}.").strip()
        reservation.save(update_fields=['status', 'staff_notes'])

    bill = BillingService.calculate_bill(reservation, as_of=now)
    qr_data_uri = generate_access_qr_base64(reservation.access_token)
    is_exit_authorized = bool(reservation.exit_authorized_until and now <= reservation.exit_authorized_until)
    is_exit_window_expired = bool(reservation.exit_authorized_until and now > reservation.exit_authorized_until)

    context = {
        'reservation': reservation,
        'bill': bill,
        'qr_data_uri': qr_data_uri,
        'now': now,
        'is_exit_authorized': is_exit_authorized,
        'is_exit_window_expired': is_exit_window_expired,
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

    now = timezone.now()

    # Request-time expiry check for gate mode
    if reservation.status == 'CONFIRMED' and not reservation.checked_in_at and reservation.arrival_deadline and now >= reservation.arrival_deadline:
        reservation.status = 'EXPIRED'
        if reservation.payment_method == 'DEPOSIT':
            reservation.deposit_forfeited = True
            reservation.staff_notes = (reservation.staff_notes + f"\n[Request-Time Check] 5-hour arrival deadline passed at {now.isoformat()}. Deposit retained.").strip()
        else:
            reservation.staff_notes = (reservation.staff_notes + f"\n[Request-Time Check] 3-hour arrival deadline passed at {now.isoformat()}.").strip()
        reservation.save(update_fields=['status', 'deposit_forfeited', 'staff_notes'])

    mode = request.GET.get('mode', 'entry')
    qr_data_uri = generate_access_qr_base64(reservation.access_token)
    bill = BillingService.calculate_bill(reservation, as_of=now)
    is_exit_authorized = bool(reservation.exit_authorized_until and now <= reservation.exit_authorized_until)

    context = {
        'reservation': reservation,
        'bill': bill,
        'qr_data_uri': qr_data_uri,
        'now': now,
        'mode': mode,
        'is_exit_authorized': is_exit_authorized,
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
        can_exit, reservation, bill, msg = GateService.prepare_exit(token_or_code, zone_id=zone_id)
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
    Validates ticket ownership, enforces settlement, and directs to payment or exit QR.
    Customer endpoints must never mark physical departure or release capacity.
    Physical exit is strictly recorded by gate passage confirmation.
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

    now = timezone.now()
    bill = BillingService.calculate_bill(reservation, as_of=now)
    is_exit_authorized = bool(reservation.exit_authorized_until and now <= reservation.exit_authorized_until)
    is_exit_window_expired = bool(reservation.exit_authorized_until and now > reservation.exit_authorized_until)

    # 1. Outstanding balance: direct to exit payment
    if bill['balance_due'] > 0 and not is_exit_authorized:
        messages.info(
            request,
            f'Outstanding balance of {bill["balance_due"]:,} KHR must be settled before checkout.'
        )
        return redirect('pay_exit', ticket_code=reservation.ticket_code)

    # 2. Expired authorization: direct to existing payment or renewal flow
    if is_exit_window_expired:
        if bill['balance_due'] > 0:
            messages.warning(request, 'Your 5-minute exit window has expired. Please settle your remaining balance.')
            return redirect('pay_exit', ticket_code=reservation.ticket_code)
        else:
            messages.warning(request, 'Your 5-minute exit window has expired. Please renew your exit pass.')
            return redirect('ticket_code', ticket_code=reservation.ticket_code)

    # 3. Valid exit authorization: direct to the exit QR pass
    if is_exit_authorized:
        messages.info(
            request,
            'Your exit pass is active. Please present your exit QR at the gate barrier to depart.'
        )
        return redirect(f"{reverse('ticket_gate_mode', kwargs={'ticket_code': reservation.ticket_code})}?mode=exit")

    # 4. Zero balance due but not yet authorized: direct to ticket to activate departure
    return redirect('ticket_code', ticket_code=reservation.ticket_code)


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


@login_required
@require_POST
def ai_parking_assistant(request):
    """
    Authenticated, rate-limited AI assistant endpoint for finding parking.
    - Requires authentication.
    - Limits queries to 5 requests per user per minute to control API costs.
    - Caps user query length at 500 characters.
    - Scrubs customer PII (phone numbers, license plates, QR tokens) before sending to Gemini.
    - Returns AI recommendations with live zone availability and direct booking links.
    """
    # 1. Rate limiting check (max 5 requests per minute per user)
    if not check_ai_rate_limit(request.user.id, max_requests=5, window_seconds=60):
        return JsonResponse({
            'status': 'error',
            'code': 'RATE_LIMIT_EXCEEDED',
            'message': 'Rate limit reached (max 5 requests per minute). Please wait a moment before asking again.'
        }, status=429)

    # 2. Input validation & length cap
    raw_query = request.POST.get('query', '').strip()
    if not raw_query:
        return JsonResponse({
            'status': 'error',
            'code': 'EMPTY_QUERY',
            'message': 'Please enter a question or parking preference.'
        }, status=400)

    if len(raw_query) > 500:
        return JsonResponse({
            'status': 'error',
            'code': 'QUERY_TOO_LONG',
            'message': 'Query exceeds maximum allowed length of 500 characters.'
        }, status=400)

    # 3. Fetch live available zones with non-sensitive metadata
    zones = ParkingZone.objects.filter(vacant_slots__gt=0).order_by('-vacant_slots', 'price')
    available_zones_data = []
    for z in zones:
        available_zones_data.append({
            'id': z.id,
            'name': z.name,
            'khmer_name': z.khmer_name,
            'slug': z.slug,
            'address': z.address,
            'district': z.district,
            'price': z.price,
            'price_formatted': z.price_khr_formatted,
            'vacant_slots': z.vacant_slots,
            'num_of_slots': z.num_of_slots,
            'operating_hours': z.operating_hours,
            'book_url': reverse('book') + f'?zone={z.slug}',
            'detail_url': reverse('zone_detail', kwargs={'slug': z.slug}),
        })

    # 4. Call Gemini service (safely scrubs PII inside service)
    result = GeminiService.recommend_parking(raw_query, available_zones_data)

    if result.get('success'):
        return JsonResponse({
            'status': 'success',
            'recommendation': result.get('recommendation', ''),
            'zones': available_zones_data[:4]
        })
    else:
        # Graceful fallback response
        return JsonResponse({
            'status': 'fallback',
            'code': result.get('reason', 'FALLBACK'),
            'recommendation': result.get('message', 'AI assistant is currently unavailable. Here are top parking options:'),
            'zones': available_zones_data[:4]
        })

