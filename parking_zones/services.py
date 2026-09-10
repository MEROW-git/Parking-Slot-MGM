import math
import re
import secrets
import time
from datetime import timedelta, datetime
from decimal import Decimal
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from .models import ParkingZone, Reservation, PaymentTransaction


class BillingService:
    """
    Centralized billing engine for SomPark parking reservations.
    Enforces exact 24-hour block billing, deposit deduction,
    and double-rate overstay penalties (including the standard rate).
    """

    @staticmethod
    def calculate_bill(reservation: Reservation, as_of: datetime = None, exit_time: datetime = None) -> dict:
        now = exit_time or as_of or timezone.now()
        daily_rate = reservation.daily_rate or (reservation.parking_zone.price if reservation.parking_zone_id else 3000)
        overstay_multiplier = Decimal(str(reservation.overstay_multiplier or 2.0))
        overstay_rate = int(round(Decimal(daily_rate) * overstay_multiplier))

        deposit_paid = reservation.deposit_amount or 0
        balance_paid = reservation.balance_paid or 0
        total_paid = deposit_paid + balance_paid

        has_verified_entry = bool(reservation.checked_in_at)
        reserved_days = reservation.effective_reserved_days

        is_walk_in = getattr(reservation, 'is_walk_in', False)
        rate_label = 'Walk-in rate' if is_walk_in else 'Daily rate'

        # BEFORE CHECK-IN (or unentered states: CONFIRMED, PAYMENT_PENDING, CANCELLED, EXPIRED without actual entry)
        if not reservation.checked_in_at:
            return {
                'daily_rate': daily_rate,
                'daily_rate_formatted': f"{daily_rate:,} ៛",
                'rate_label': rate_label,
                'is_walk_in': is_walk_in,
                'overstay_multiplier': 1.0 if is_walk_in else float(overstay_multiplier),
                'overstay_rate': daily_rate if is_walk_in else overstay_rate,
                'overstay_rate_formatted': f"{daily_rate:,} ៛" if is_walk_in else f"{overstay_rate:,} ៛",
                'entry_time': None,
                'exit_time': None,
                'booked_end': reservation.effective_finish_time,
                'parking_deadline': None,
                'parking_deadline_formatted': 'Set when you enter',
                'calculated_at': now,
                'has_verified_entry': False,
                'is_timestamp_inconsistent': (reservation.status == 'CHECKED_IN'),
                'total_parked_seconds': 0.0,
                'parked_duration_display': 'Parking charges start when you enter.',
                'normal_seconds': 0.0,
                'normal_hours': 0.0,
                'normal_days': 0,
                'normal_charge': 0,
                'normal_charge_formatted': "0 ៛",
                'overstay_seconds': 0.0,
                'overstay_hours': 0.0,
                'overstay_days': 0,
                'overstay_duration_display': "0 min",
                'overstay_charge': 0,
                'overstay_charge_formatted': "0 ៛",
                'total_charge': 0,
                'total_charge_formatted': "0 ៛",
                'total_amount': 0,
                'deposit_paid': deposit_paid,
                'deposit_deducted': 0,
                'deposit_deducted_formatted': "0 ៛",
                'balance_paid': balance_paid,
                'balance_paid_formatted': f"{balance_paid:,} ៛",
                'total_paid': total_paid,
                'total_paid_formatted': f"{total_paid:,} ៛",
                'balance_due': 0,
                'balance_due_formatted': "0 ៛",
                'is_overstay': False,
                'message': 'Parking charges start when you enter.',
            }

        # AFTER CHECK-IN:
        # A parking day means a full 24-hour period starting at actual check-in.
        entry_time = reservation.checked_in_at
        parking_deadline = entry_time + timedelta(days=reserved_days)
        exit_time = reservation.checked_out_at or now

        if exit_time < entry_time:
            exit_time = entry_time

        total_parked_seconds = max(0.0, (exit_time - entry_time).total_seconds())

        if is_walk_in:
            # Walk-in: 24-hour block billing from actual entry, minimum 1 day.
            # No reserved-duration overstay penalty.
            if total_parked_seconds == 0:
                normal_days = 1
            else:
                normal_days = max(1, math.ceil(total_parked_seconds / 86400.0))
            normal_seconds = total_parked_seconds
            normal_charge = normal_days * daily_rate
            overstay_seconds = 0.0
            overstay_days = 0
            overstay_charge = 0
            parking_deadline = entry_time + timedelta(days=normal_days)
        elif exit_time <= parking_deadline:
            # Within reserved duration
            overstay_seconds = 0.0
            overstay_days = 0
            overstay_charge = 0
            if total_parked_seconds == 0:
                normal_days = 1
            else:
                normal_days = max(1, math.ceil(total_parked_seconds / 86400.0))
            normal_days = min(reserved_days, normal_days)
            normal_seconds = total_parked_seconds
            normal_charge = normal_days * daily_rate
        else:
            # Overstay starts only after full reserved duration ends
            normal_days = reserved_days
            normal_seconds = reserved_days * 86400.0
            normal_charge = normal_days * daily_rate

            overstay_seconds = (exit_time - parking_deadline).total_seconds()
            overstay_days = max(1, math.ceil(overstay_seconds / 86400.0))
            overstay_charge = overstay_days * overstay_rate

        total_charge = normal_charge + overstay_charge
        deposit_deducted = min(deposit_paid, total_charge)
        balance_due = max(0, total_charge - total_paid)

        # Elapsed formatting
        parked_hours = int(total_parked_seconds // 3600)
        parked_minutes = int((total_parked_seconds % 3600) // 60)
        if parked_hours > 0 and parked_minutes > 0:
            parked_duration_display = f"{parked_hours} hr {parked_minutes} min"
        elif parked_hours > 0:
            parked_duration_display = f"{parked_hours} hr"
        else:
            parked_duration_display = f"{max(1, parked_minutes)} min"

        overstay_hours_int = int(overstay_seconds // 3600)
        overstay_minutes_int = int((overstay_seconds % 3600) // 60)
        if overstay_hours_int > 0 and overstay_minutes_int > 0:
            overstay_duration_display = f"{overstay_hours_int} hr {overstay_minutes_int} min"
        elif overstay_hours_int > 0:
            overstay_duration_display = f"{overstay_hours_int} hr"
        elif overstay_minutes_int > 0:
            overstay_duration_display = f"{overstay_minutes_int} min"
        else:
            overstay_duration_display = "0 min"

        return {
            'daily_rate': daily_rate,
            'daily_rate_formatted': f"{daily_rate:,} ៛",
            'rate_label': rate_label,
            'is_walk_in': is_walk_in,
            'overstay_multiplier': 1.0 if is_walk_in else float(overstay_multiplier),
            'overstay_rate': daily_rate if is_walk_in else overstay_rate,
            'overstay_rate_formatted': f"{daily_rate:,} ៛" if is_walk_in else f"{overstay_rate:,} ៛",
            'entry_time': entry_time,
            'exit_time': exit_time,
            'booked_end': reservation.effective_finish_time,
            'parking_deadline': parking_deadline,
            'parking_deadline_formatted': parking_deadline.strftime('%d %b %Y, %H:%M'),
            'calculated_at': now,
            'has_verified_entry': True,
            'is_timestamp_inconsistent': False,
            'total_parked_seconds': total_parked_seconds,
            'parked_duration_display': parked_duration_display,
            'normal_seconds': normal_seconds,
            'normal_hours': round(normal_seconds / 3600.0, 2),
            'normal_days': normal_days,
            'normal_charge': normal_charge,
            'normal_charge_formatted': f"{normal_charge:,} ៛",
            'overstay_seconds': overstay_seconds,
            'overstay_hours': round(overstay_seconds / 3600.0, 2),
            'overstay_days': overstay_days,
            'overstay_duration_display': overstay_duration_display,
            'overstay_charge': overstay_charge,
            'overstay_charge_formatted': f"{overstay_charge:,} ៛",
            'total_charge': total_charge,
            'total_charge_formatted': f"{total_charge:,} ៛",
            'total_amount': total_charge,
            'deposit_paid': deposit_paid,
            'deposit_deducted': deposit_deducted,
            'deposit_deducted_formatted': f"{deposit_deducted:,} ៛",
            'balance_paid': balance_paid,
            'balance_paid_formatted': f"{balance_paid:,} ៛",
            'total_paid': total_paid,
            'total_paid_formatted': f"{total_paid:,} ៛",
            'balance_due': balance_due,
            'balance_due_formatted': f"{balance_due:,} ៛",
            'is_overstay': overstay_days > 0,
            'message': 'Parking charges active.',
        }

    @staticmethod
    def estimate_booking_cost(zone: ParkingZone, days: int = 1, start_time: datetime = None, finish_time: datetime = None) -> dict:
        daily_rate = zone.price
        if finish_time and start_time:
            duration_seconds = max(0.0, (finish_time - start_time).total_seconds())
            days = max(1, math.ceil(duration_seconds / 86400.0))
        days = max(1, days)
        estimated_total = days * daily_rate
        deposit_amount = daily_rate  # 1 day standard deposit
        return {
            'daily_rate': daily_rate,
            'days': days,
            'estimated_total': estimated_total,
            'deposit_amount': deposit_amount,
            'overstay_rate': daily_rate * 2,
        }


class CapacityService:
    """
    Capacity & inventory allocation service.
    Distinguishes physically occupied, active arrival holds, and future bookings.
    """

    @staticmethod
    def check_immediate_availability(zone_id: int) -> bool:
        """Verifies if spaces are available right now, locking the zone row if inside a transaction."""
        if transaction.get_connection().in_atomic_block:
            zone = ParkingZone.objects.select_for_update().get(id=zone_id)
        else:
            zone = ParkingZone.objects.get(id=zone_id)
        now = timezone.now()

        # Count active arrival holds
        active_holds = Reservation.objects.filter(
            parking_zone=zone,
            status='CONFIRMED',
            payment_method='PAY_AT_EXIT',
            arrival_deadline__gt=now
        ).count()

        pending_deposits = Reservation.objects.filter(
            parking_zone=zone,
            status='PAYMENT_PENDING',
            payment_deadline__gt=now
        ).count()

        occupied = zone.occupied_slots
        available = zone.num_of_slots - (occupied + active_holds + pending_deposits)
        return available > 0

    @staticmethod
    def get_unreserved_capacity(zone_id: int) -> int:
        """
        Returns number of unreserved spaces remaining for immediate walk-in allocation.
        Accounts for physical occupancy, active arrival holds, and pending deposits.
        Locks zone row if inside an atomic transaction block.
        """
        if transaction.get_connection().in_atomic_block:
            zone = ParkingZone.objects.select_for_update().get(id=zone_id)
        else:
            zone = ParkingZone.objects.get(id=zone_id)
        now = timezone.now()
        active_holds = Reservation.objects.filter(
            parking_zone=zone,
            status='CONFIRMED',
            arrival_deadline__gt=now,
            checked_in_at__isnull=True
        ).count()
        pending_deposits = Reservation.objects.filter(
            parking_zone=zone,
            status='PAYMENT_PENDING',
            payment_deadline__gt=now
        ).count()
        used = zone.occupied_slots + active_holds + pending_deposits
        return max(0, zone.num_of_slots - used)

    @staticmethod
    def check_date_range_availability(
        zone_id: int,
        start_time: datetime = None,
        finish_time: datetime = None,
        reserved_days: int = 1,
        start_datetime: datetime = None,
        finish_datetime: datetime = None
    ) -> bool:
        """
        Verifies capacity for a specific date/time window.
        Accounts for permitted arrival window and full reserved duration (N x 24h)
        to prevent overbooking capacity that cannot be honored.
        """
        start_time = start_time or start_datetime
        finish_time = finish_time or finish_datetime
        zone = ParkingZone.objects.select_for_update().get(id=zone_id)
        now = timezone.now()

        # If booking starts today / immediate window, check current availability
        if start_time <= now + timedelta(hours=3):
            if not CapacityService.check_immediate_availability(zone_id):
                return False

        req_start = start_time
        req_end = finish_time + timedelta(days=reserved_days)

        active_res = Reservation.objects.filter(
            parking_zone=zone,
            status__in=['CONFIRMED', 'CHECKED_IN']
        )

        overlapping = 0
        for res in active_res:
            res_days = res.effective_reserved_days
            if res.status == 'CHECKED_IN':
                res_start = res.checked_in_at or res.effective_start_time
                res_deadline = res_start + timedelta(days=res_days)
                res_end = max(now, res_deadline)
            else:
                # Arrival hold prior to physical entry
                if res.arrival_deadline and now >= res.arrival_deadline:
                    continue
                res_start = res.start_time or res.effective_start_time
                res_arrival_end = res.arrival_deadline or res.effective_finish_time
                res_end = res_arrival_end + timedelta(days=res_days)

            # Check overlap between [req_start, req_end] and [res_start, res_end]
            if not (res_end <= req_start or res_start >= req_end):
                overlapping += 1

        total_demand = overlapping + zone.occupied_slots
        return total_demand < zone.num_of_slots


class PaymentService:
    """
    Handles payment transaction lifecycle, demo simulation,
    and idempotent confirmations.
    """

    @staticmethod
    def create_deposit_transaction(reservation: Reservation) -> PaymentTransaction:
        timeout_minutes = getattr(settings, 'PAYMENT_TIMEOUT_MINUTES', 15)
        now = timezone.now()
        reservation.payment_deadline = now + timedelta(minutes=timeout_minutes)
        reservation.status = 'PAYMENT_PENDING'
        reservation.save(update_fields=['payment_deadline', 'status'])

        txn = PaymentTransaction.objects.create(
            reservation=reservation,
            purpose='DEPOSIT',
            amount=reservation.daily_rate,
            currency='KHR',
            status='PENDING',
            provider='DEMO' if getattr(settings, 'DEMO_PAYMENT_ENABLED', True) else 'BAKONG_KHQR',
            is_demo=getattr(settings, 'DEMO_PAYMENT_ENABLED', True),
        )
        return txn

    @staticmethod
    @transaction.atomic
    def confirm_deposit(txn_id: int, provider_ref: str = None, confirmed_at: datetime = None) -> tuple[bool, str]:
        """Idempotent deposit confirmation."""
        txn = PaymentTransaction.objects.select_for_update().get(id=txn_id)
        reservation = Reservation.objects.select_for_update().get(id=txn.reservation_id)

        # Idempotency check: if already confirmed
        if txn.status == 'SUCCESS' and reservation.status == 'CONFIRMED':
            return True, 'Deposit payment already confirmed.'

        now = confirmed_at or timezone.now()

        # Late confirmation check: if reservation expired while payment was in-flight
        if reservation.status == 'EXPIRED' or (reservation.payment_deadline and now > reservation.payment_deadline):
            txn.status = 'FAILED'
            txn.raw_response = {'error': 'Late confirmation after hold expiry. Marked for reconciliation.'}
            txn.save(update_fields=['status', 'raw_response', 'updated_at'])
            return False, 'Reservation hold has expired. Payment marked for customer reconciliation/refund.'

        # Successful confirmation
        txn.status = 'SUCCESS'
        if provider_ref:
            txn.provider_ref = provider_ref
        txn.completed_at = now
        txn.save()

        # Store arrival deadline once (exactly 5 hours after verified payment).
        # Refreshes, retries, and duplicate payment callbacks must never extend it.
        if not reservation.arrival_deadline:
            deposit_hold_hours = getattr(settings, 'DEPOSIT_ARRIVAL_HOLD_HOURS', 5)
            reservation.arrival_deadline = now + timedelta(hours=deposit_hold_hours)
            reservation.finish_time = reservation.arrival_deadline
            reservation.finish_date = timezone.localdate(reservation.arrival_deadline)

        reservation.deposit_amount = txn.amount
        reservation.payment_status = 'PARTIALLY_PAID'
        reservation.status = 'CONFIRMED'
        reservation.payment_deadline = None
        reservation.save()

        return True, 'Deposit payment successfully verified.'

    @staticmethod
    def create_exit_transaction(reservation: Reservation, amount: int) -> PaymentTransaction:
        demo_enabled = getattr(settings, 'DEMO_PAYMENT_ENABLED', True)
        txn = PaymentTransaction.objects.create(
            reservation=reservation,
            purpose='EXIT_BALANCE',
            amount=amount,
            currency='KHR',
            status='PENDING',
            provider='DEMO' if demo_enabled else 'BAKONG_KHQR',
            is_demo=demo_enabled,
        )
        return txn

    @staticmethod
    @transaction.atomic
    def confirm_exit_payment(txn_id: int, provider_ref: str = None) -> tuple[bool, str]:
        """
        Idempotent exit balance payment confirmation.
        Verifies pending transaction, credits balance_paid, and authorizes departure window.
        Keeps reservation in CHECKED_IN status and space physically occupied until gate passage.
        """
        txn = PaymentTransaction.objects.select_for_update().get(id=txn_id)
        reservation = Reservation.objects.select_for_update().get(id=txn.reservation_id)

        # Idempotency check: if already confirmed
        if txn.status == 'SUCCESS':
            return True, 'Exit balance payment already verified.'

        if txn.status in ('CANCELLED', 'FAILED'):
            return False, f'Cannot confirm transaction in status {txn.status}. Please initiate a new payment.'

        now = timezone.now()

        # Mark txn SUCCESS
        txn.status = 'SUCCESS'
        if provider_ref:
            txn.provider_ref = provider_ref
        txn.completed_at = now
        txn.save()

        # Credit payment towards reservation balance_paid
        reservation.balance_paid += txn.amount

        # Check whether updated balance due is 0
        updated_bill = BillingService.calculate_bill(reservation, as_of=now)
        exit_mins = getattr(settings, 'EXIT_WINDOW_MINUTES', 5)

        if updated_bill['balance_due'] == 0:
            reservation.payment_status = 'PAID'
            reservation.exit_authorized_until = now + timedelta(minutes=exit_mins)
            reservation.save(update_fields=['balance_paid', 'payment_status', 'exit_authorized_until'])
            return True, f'Exit payment successfully verified. {exit_mins}-minute departure window authorized.'
        else:
            reservation.payment_status = 'PARTIALLY_PAID'
            reservation.save(update_fields=['balance_paid', 'payment_status'])
            return True, f'Payment received; balance remains of {updated_bill["balance_due"]:,} ៛.'

    @staticmethod
    @transaction.atomic
    def record_exit_payment(reservation: Reservation, amount: int, provider: str = 'CASH', provider_ref: str = None) -> PaymentTransaction:
        now = timezone.now()
        exit_mins = getattr(settings, 'EXIT_WINDOW_MINUTES', 5)

        # Idempotency check: if already fully settled
        current_bill = BillingService.calculate_bill(reservation, as_of=now)
        if current_bill['balance_due'] <= 0 and reservation.payment_status == 'PAID':
            if not reservation.exit_authorized_until or now > reservation.exit_authorized_until:
                reservation.exit_authorized_until = now + timedelta(minutes=exit_mins)
                reservation.save(update_fields=['exit_authorized_until'])
            existing_txn = reservation.transactions.filter(purpose='EXIT_BALANCE', status='SUCCESS').first()
            if existing_txn:
                return existing_txn

        # Collect only the remaining balance due
        actual_amount = min(amount, current_bill['balance_due']) if current_bill['balance_due'] > 0 else amount
        is_demo = getattr(settings, 'DEMO_PAYMENT_ENABLED', True) if provider == 'DEMO' else False

        ref = provider_ref or f"EXIT-{secrets.token_hex(8).upper()}"
        txn = PaymentTransaction.objects.create(
            reservation=reservation,
            purpose='EXIT_BALANCE',
            amount=actual_amount,
            currency='KHR',
            status='SUCCESS',
            provider=provider,
            provider_ref=ref,
            is_demo=is_demo,
            completed_at=now,
        )

        reservation.balance_paid += actual_amount
        reservation.payment_status = 'PAID'
        reservation.exit_authorized_until = now + timedelta(minutes=exit_mins)
        reservation.save(update_fields=['balance_paid', 'payment_status', 'exit_authorized_until'])

        return txn

    @staticmethod
    @transaction.atomic
    def record_cash_deposit(reservation: Reservation, staff_user=None) -> tuple[bool, str]:
        """
        Allows staff to confirm a cash deposit received in person.
        Customers cannot self-confirm cash deposits.
        """
        now = timezone.now()
        if reservation.status == 'CONFIRMED' and reservation.payment_status == 'PARTIALLY_PAID':
            return True, 'Deposit payment already confirmed.'

        if reservation.status in ('EXPIRED', 'CANCELLED'):
            return False, f'Cannot accept deposit for {reservation.status.lower()} reservation.'

        txn = reservation.transactions.filter(purpose='DEPOSIT', status='PENDING').first()
        staff_tag = staff_user.username if staff_user else 'STAFF'
        ref = f"CASH-DEP-{secrets.token_hex(4).upper()}"

        if txn:
            txn.status = 'SUCCESS'
            txn.provider = 'CASH'
            txn.is_demo = False
            txn.provider_ref = ref
            txn.completed_at = now
            txn.raw_response = {'confirmed_by': staff_tag, 'confirmed_at': now.isoformat()}
            txn.save()
        else:
            txn = PaymentTransaction.objects.create(
                reservation=reservation,
                purpose='DEPOSIT',
                amount=reservation.daily_rate,
                currency='KHR',
                status='SUCCESS',
                provider='CASH',
                provider_ref=ref,
                is_demo=False,
                completed_at=now,
                raw_response={'confirmed_by': staff_tag, 'confirmed_at': now.isoformat()}
            )

        # Store arrival deadline once (exactly 5 hours after verified payment).
        # Refreshes, retries, and duplicate payment callbacks must never extend it.
        if not reservation.arrival_deadline:
            deposit_hold_hours = getattr(settings, 'DEPOSIT_ARRIVAL_HOLD_HOURS', 5)
            reservation.arrival_deadline = now + timedelta(hours=deposit_hold_hours)
            reservation.finish_time = reservation.arrival_deadline
            reservation.finish_date = timezone.localdate(reservation.arrival_deadline)

        reservation.deposit_amount = txn.amount
        reservation.payment_status = 'PARTIALLY_PAID'
        reservation.status = 'CONFIRMED'
        reservation.payment_deadline = None
        reservation.save()

        return True, f'Cash deposit of {txn.amount:,} KHR confirmed by staff ({staff_tag}).'


class GateService:
    """
    Gate entry and exit workflows with atomic occupancy transitions
    and hardware simulator hooks.
    """

    @staticmethod
    def validate_entry(token_or_code: str, zone_id: int = None, check_time: datetime = None) -> tuple[bool, Reservation | None, str]:
        token_or_code = token_or_code.strip()
        reservation = (
            Reservation.objects
            .select_related('parking_zone', 'customer')
            .filter(access_token=token_or_code)
            .first()
        )
        if not reservation:
            reservation = (
                Reservation.objects
                .select_related('parking_zone', 'customer')
                .filter(ticket_code=token_or_code)
                .first()
            )

        if not reservation:
            return False, None, 'No reservation record found for this ticket code or access token.'

        if zone_id and reservation.parking_zone_id != zone_id:
            return False, reservation, f'Ticket is for "{reservation.parking_zone.name}", not this parking facility.'

        now = check_time or timezone.now()

        if reservation.status == 'CHECKED_IN':
            return False, reservation, 'Vehicle is already checked into the facility.'

        if reservation.status == 'CHECKED_OUT':
            return False, reservation, 'This parking ticket has already been used and checked out.'

        if reservation.status == 'CANCELLED':
            return False, reservation, 'This reservation has been cancelled.'

        if reservation.status == 'EXPIRED':
            return False, reservation, 'This reservation has expired and is no longer valid.'

        if reservation.status == 'PAYMENT_PENDING':
            return False, reservation, 'First-day deposit payment is still pending. Ticket not activated.'

        if now < reservation.effective_start_time:
            return False, reservation, 'The booked arrival window has not started yet.'

        if reservation.payment_method == 'PAY_AT_EXIT':
            # For PAY_AT_EXIT:
            # - Arrival starts immediately upon server booking
            # - Arrival deadline is booking time + configured hold duration (default 3 hours)
            # - Deadline can cross midnight
            deadline = reservation.arrival_deadline or reservation.effective_finish_time
            if deadline and now >= deadline:
                reservation.status = 'EXPIRED'
                if reservation.is_walk_in:
                    reservation.staff_notes = (reservation.staff_notes + f"\n[Walk-In No-Show] Walk-in arrival window expired at {now.isoformat()}.").strip()
                else:
                    reservation.staff_notes = (reservation.staff_notes + f"\n[No-Show] 3-hour arrival window expired at {now.isoformat()}.").strip()
                reservation.save(update_fields=['status', 'staff_notes'])
                if reservation.is_walk_in:
                    return False, reservation, 'The walk-in ticket arrival window has expired.'
                return False, reservation, 'The 3-hour arrival window for this unpaid booking has expired.'
        else:
            # For DEPOSIT:
            # - 5 hours after server-verified payment
            # - Reject QR on expiry, release capacity, retain first-day payment for customer no-show
            deadline = reservation.arrival_deadline or reservation.effective_finish_time
            if deadline and now >= deadline:
                reservation.status = 'EXPIRED'
                reservation.deposit_forfeited = True
                reservation.staff_notes = (reservation.staff_notes + f"\n[No-Show] 5-hour arrival deadline passed at {now.isoformat()}. First-day deposit forfeited per policy.").strip()
                reservation.save(update_fields=['status', 'deposit_forfeited', 'staff_notes'])
                return False, reservation, 'The 5-hour arrival window has expired. Reservation is marked as no-show and first-day deposit is forfeited per policy.'
            if reservation.deposit_amount < reservation.daily_rate:
                return False, reservation, 'First-day deposit has not been recorded.'

        # Capacity check
        zone = reservation.parking_zone
        if zone.occupied_slots >= zone.num_of_slots:
            return False, reservation, f'Facility "{zone.name}" is currently at maximum physical capacity.'

        return True, reservation, 'Ticket verified and ready for gate entry.'

    @staticmethod
    @transaction.atomic
    def confirm_entry(reservation_id: int, staff_user=None) -> tuple[bool, Reservation, str]:
        reservation = Reservation.objects.select_for_update().select_related('parking_zone').get(id=reservation_id)
        zone = ParkingZone.objects.select_for_update().get(id=reservation.parking_zone_id)

        now = timezone.now()

        if reservation.status == 'CHECKED_IN':
            return True, reservation, 'Vehicle already checked in.'

        if reservation.status != 'CONFIRMED':
            return False, reservation, f'Cannot check in reservation with status: {reservation.status}.'

        allowed, _, message = GateService.validate_entry(reservation.ticket_code, zone.pk)
        if not allowed:
            return False, reservation, message

        # Atomic check-in
        reservation.status = 'CHECKED_IN'
        reservation.checked_in_at = now
        reservation.checked_out = False
        if staff_user:
            reservation.staff_notes = (reservation.staff_notes + f"\nEntry verified by staff {staff_user.username} at {now.isoformat()}").strip()
        reservation.save()

        # Increment physical occupancy
        zone.occupied_slots = min(zone.num_of_slots, zone.occupied_slots + 1)
        zone.vacant_slots = max(0, zone.num_of_slots - zone.occupied_slots)
        zone.save()

        return True, reservation, f'Entry confirmed! Barrier opened. Space occupied in {zone.name}.'

    @staticmethod
    def prepare_exit(token_or_code: str, zone_id: int = None) -> tuple[bool, Reservation | None, dict | None, str]:
        token_or_code = token_or_code.strip()
        reservation = (
            Reservation.objects
            .select_related('parking_zone', 'customer')
            .filter(access_token=token_or_code)
            .first()
        )
        if not reservation:
            reservation = (
                Reservation.objects
                .select_related('parking_zone', 'customer')
                .filter(ticket_code=token_or_code)
                .first()
            )

        if not reservation:
            return False, None, None, 'No reservation record found for this ticket code or access token.'

        if zone_id and reservation.parking_zone_id != zone_id:
            return False, reservation, None, f'Ticket is for "{reservation.parking_zone.name}", not this parking facility.'

        if reservation.status != 'CHECKED_IN':
            return False, reservation, None, f'Reservation is in status "{reservation.status}". Must be CHECKED_IN to process exit.'

        now = timezone.now()
        bill = BillingService.calculate_bill(reservation, as_of=now)

        # 1. If exit authorization window was set and is active:
        if reservation.exit_authorized_until and now <= reservation.exit_authorized_until:
            return True, reservation, bill, 'Exit authorized. Barrier ready to open.'

        # 2. If exit authorization window was set and has expired:
        if reservation.exit_authorized_until and now > reservation.exit_authorized_until:
            if bill['balance_due'] > 0:
                msg = f"Exit window expired. Outstanding balance of {bill['balance_due']:,} KHR must be settled before exit."
            else:
                msg = 'Exit window expired. Please renew exit authorization before exit.'
            return False, reservation, bill, msg

        # 3. If exit_authorized_until was not set (e.g. prepaid deposit covering stay or at-barrier settlement):
        if bill['balance_due'] == 0:
            return True, reservation, bill, 'Exit authorized. Barrier ready to open.'

        return False, reservation, bill, f"Outstanding balance of {bill['balance_due']:,} KHR must be settled before exit."

    @staticmethod
    @transaction.atomic
    def authorize_exit_at_gate(reservation_id: int, zone_id: int):
        """Explicit gate action: renew a settled exit, without recording passage.

        Keep prepare_exit read-only: an expired permit must never renew itself
        while confirming passage or merely viewing the ticket.
        """
        reservation = Reservation.objects.select_for_update().get(pk=reservation_id)
        allowed, _, bill, notice = GateService.prepare_exit(reservation.ticket_code, zone_id)
        if reservation.parking_zone_id != zone_id or reservation.status != 'CHECKED_IN':
            return False, reservation, bill, notice
        now = timezone.now()
        if bill and bill['balance_due'] == 0 and (
            not reservation.exit_authorized_until or reservation.exit_authorized_until < now
        ):
            reservation.exit_authorized_until = now + timedelta(
                minutes=getattr(settings, 'EXIT_WINDOW_MINUTES', 5)
            )
            reservation.save(update_fields=['exit_authorized_until'])
            return True, reservation, bill, 'Exit authorization renewed. No additional payment required.'
        return allowed, reservation, bill, notice

    @staticmethod
    @transaction.atomic
    def confirm_physical_exit(reservation_id: int, staff_user=None) -> tuple[bool, Reservation, str]:
        reservation = Reservation.objects.select_for_update().select_related('parking_zone').get(id=reservation_id)
        zone = ParkingZone.objects.select_for_update().get(id=reservation.parking_zone_id)

        now = timezone.now()

        if reservation.status == 'CHECKED_OUT':
            return True, reservation, 'Reservation already checked out.'

        if reservation.status != 'CHECKED_IN':
            return False, reservation, f'Cannot check out reservation in status {reservation.status}.'

        bill = BillingService.calculate_bill(reservation, as_of=now)

        # Check authorization
        if reservation.exit_authorized_until and now > reservation.exit_authorized_until:
            return False, reservation, 'Exit window expired. Please renew exit authorization or settle balance.'

        if bill['balance_due'] > 0 and not (reservation.exit_authorized_until and now <= reservation.exit_authorized_until):
            return False, reservation, f'Outstanding balance of {bill["balance_due"]:,} KHR must be settled before exit.'

        # Finalize checkout
        reservation.status = 'CHECKED_OUT'
        reservation.checked_out = True
        reservation.checked_out_at = now
        reservation.total_amount = bill['total_charge']
        if staff_user:
            reservation.staff_notes = (reservation.staff_notes + f"\nExit verified by staff {staff_user.username} at {now.isoformat()}").strip()
        reservation.save()

        # Release physical space exactly once
        zone.occupied_slots = max(0, zone.occupied_slots - 1)
        zone.vacant_slots = min(zone.num_of_slots, max(0, zone.num_of_slots - zone.occupied_slots))
        zone.save()

        return True, reservation, f'Exit confirmed! Barrier opened. Space released in {zone.name}.'


class ExpiryService:
    """
    Background and on-the-fly expiration of unpaid holds,
    deposit timeouts, and no-show bookings.
    """

    @classmethod
    def expire_unpaid_holds(cls) -> int:
        return cls.expire_stale_holds()['unpaid_holds']

    @classmethod
    def expire_pending_deposit_holds(cls) -> int:
        return cls.expire_stale_holds()['deposit_timeouts']

    @classmethod
    def expire_no_shows(cls) -> int:
        return cls.expire_stale_holds()['no_shows']

    @staticmethod
    @transaction.atomic
    def expire_stale_holds() -> dict:
        now = timezone.now()
        results = {'unpaid_holds': 0, 'deposit_timeouts': 0, 'no_shows': 0}

        # 1. Same-day unpaid arrival holds past 3 hours
        stale_unpaid = Reservation.objects.select_for_update().filter(
            payment_method='PAY_AT_EXIT',
            status='CONFIRMED',
            arrival_deadline__lt=now,
            checked_in_at__isnull=True
        )
        for res in stale_unpaid:
            res.status = 'EXPIRED'
            if getattr(res, 'is_walk_in', False):
                res.staff_notes = (res.staff_notes + f"\n[Auto-Expire] Walk-in ticket hold expired at {now.isoformat()}").strip()
            else:
                res.staff_notes = (res.staff_notes + f"\n[Auto-Expire] 3-hour arrival deadline passed at {now.isoformat()}").strip()
            res.save(update_fields=['status', 'staff_notes'])
            results['unpaid_holds'] += 1

        # 2. Deposit payment timeouts (15 minutes without payment)
        timed_out_deposits = Reservation.objects.select_for_update().filter(
            status='PAYMENT_PENDING',
            payment_deadline__lt=now
        )
        for res in timed_out_deposits:
            res.status = 'EXPIRED'
            res.staff_notes = (res.staff_notes + f"\n[Auto-Expire] Deposit checkout timeout passed at {now.isoformat()}").strip()
            res.save(update_fields=['status', 'staff_notes'])
            results['deposit_timeouts'] += 1

        # 3. Deposited no-shows: 5-hour arrival deadline passed without entry
        no_shows = Reservation.objects.select_for_update().filter(
            payment_method='DEPOSIT',
            status='CONFIRMED',
            checked_in_at__isnull=True
        )
        for res in no_shows:
            deadline = res.arrival_deadline or res.finish_time
            if deadline and deadline < now:
                res.status = 'EXPIRED'
                res.deposit_forfeited = True
                res.staff_notes = (res.staff_notes + f"\n[Auto-Expire] No-show at arrival deadline {now.isoformat()}. Deposit retained per policy.").strip()
                res.save(update_fields=['status', 'deposit_forfeited', 'staff_notes'])
                results['no_shows'] += 1

        return results


class AntiSpamService:
    """
    Protects parking facilities against unpaid-hold spam, plate squatting,
    rapid automated submissions, and excessive unpaid no-shows.
    """

    @staticmethod
    def normalize_plate(plate: str) -> str:
        """
        Normalizes full vehicle license plate by stripping spaces, hyphens, periods,
        and uppercase. Example: 'Phnom Penh 2AZ-1234' -> 'PHNOMPENH2AZ1234'
        """
        if not plate:
            return ''
        return re.sub(r'[\s\-_.]+', '', str(plate)).upper()

    @staticmethod
    def check_request_throttling(request, user=None) -> tuple[bool, str]:
        """
        Enforces tiered request throttling:
        - Primary signal: Account-based throttling (default 10 requests per minute).
        - Secondary signal: IP-based throttling (default 30 requests per minute, accommodating shared Wi-Fi/NAT).
        """
        user_limit = getattr(settings, 'BOOKING_RATE_LIMIT_PER_MINUTE', 10)
        ip_limit = getattr(settings, 'BOOKING_IP_RATE_LIMIT_PER_MINUTE', 30)

        now_epoch = int(time.time())
        window = now_epoch // 60

        # Primary user-based throttle
        target_user = user or (request.user if request and request.user.is_authenticated else None)
        if target_user:
            user_key = f"throttle_booking_usr_{target_user.pk}_{window}"
            user_count = cache.get(user_key, 0)
            if user_count >= user_limit:
                return False, "Too many booking requests from this account. Please wait a minute before trying again."
            cache.set(user_key, user_count + 1, timeout=70)

        # Secondary IP-based throttle
        client_ip = ''
        if request:
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                client_ip = x_forwarded_for.split(',')[0].strip()
            else:
                client_ip = request.META.get('REMOTE_ADDR', '')

        if client_ip:
            ip_key = f"throttle_booking_ip_{client_ip}_{window}"
            ip_count = cache.get(ip_key, 0)
            if ip_count >= ip_limit:
                return False, "Too many booking requests from your network. Please wait a minute before trying again."
            cache.set(ip_key, ip_count + 1, timeout=70)

        return True, ""

    @staticmethod
    def find_duplicate_submission(user, zone, normalized_plate: str, payment_method: str = None, within_seconds: int = 120) -> Reservation | None:
        """
        Detects idempotent duplicate submissions (e.g. double-clicks, network retries)
        from the same customer for the same vehicle plate & facility within a short window.
        Uses plate_lookup_hmac index for O(1) matching with fallback to legacy rows.
        """
        cutoff = timezone.now() - timedelta(seconds=within_seconds)
        qs = Reservation.objects.filter(
            customer=user,
            parking_zone=zone,
            created_on__gte=cutoff,
            status__in=['CONFIRMED', 'PAYMENT_PENDING']
        )
        if payment_method:
            qs = qs.filter(payment_method=payment_method)

        target_hmac = ''
        if normalized_plate:
            try:
                from .crypto import compute_plate_hmac
                target_hmac = compute_plate_hmac(normalized_plate)
            except Exception:
                pass

        if target_hmac:
            candidate = qs.filter(plate_lookup_hmac=target_hmac).first()
            if candidate:
                return candidate

        for res in qs:
            if AntiSpamService.normalize_plate(res.plate_number) == normalized_plate:
                return res
        return None

    @staticmethod
    def check_active_reservation_limit(user) -> tuple[bool, Reservation | None, str]:
        """
        Enforces one active reservation per account, including PAYMENT_PENDING.
        Automatically expires any stale holds first so legitimate customers aren't falsely blocked.
        """
        now = timezone.now()
        active_candidates = Reservation.objects.filter(
            customer=user,
            status__in=['CONFIRMED', 'CHECKED_IN', 'PAYMENT_PENDING'],
            checked_out=False
        )

        for res in active_candidates:
            # Check on-the-fly expiration
            if res.status == 'PAYMENT_PENDING' and res.payment_deadline and now >= res.payment_deadline:
                res.status = 'EXPIRED'
                res.staff_notes = (res.staff_notes + f"\n[Auto-Expire] Deposit checkout timeout at {now.isoformat()}").strip()
                res.save(update_fields=['status', 'staff_notes'])
                continue

            if res.status == 'CONFIRMED' and not res.checked_in_at and res.arrival_deadline and now >= res.arrival_deadline:
                res.status = 'EXPIRED'
                if res.payment_method == 'DEPOSIT':
                    res.deposit_forfeited = True
                res.staff_notes = (res.staff_notes + f"\n[Auto-Expire] Arrival deadline passed at {now.isoformat()}").strip()
                res.save(update_fields=['status', 'deposit_forfeited', 'staff_notes'])
                continue

            # Found an active valid reservation
            msg = (
                f"You already have an active reservation at {res.parking_zone.name} "
                f"(Ticket #{res.ticket_code}, Status: {res.get_status_display()}). "
                f"Only one active reservation is permitted per account."
            )
            return False, res, msg

        return True, None, ""

    @staticmethod
    def check_simultaneous_plate_hold(plate: str, exclude_reservation_id: int = None) -> tuple[bool, Reservation | None, str]:
        """
        Prevents simultaneous holds for the same normalized full vehicle plate across all facilities.
        """
        norm_target = AntiSpamService.normalize_plate(plate)
        now = timezone.now()
        active_candidates = Reservation.objects.filter(
            status__in=['CONFIRMED', 'CHECKED_IN', 'PAYMENT_PENDING'],
            checked_out=False
        )
        if exclude_reservation_id:
            active_candidates = active_candidates.exclude(id=exclude_reservation_id)

        target_hmac = ''
        if norm_target:
            try:
                from .crypto import compute_plate_hmac
                target_hmac = compute_plate_hmac(norm_target)
            except Exception:
                pass

        for res in active_candidates:
            # Check on-the-fly expiration for candidates
            if res.status == 'PAYMENT_PENDING' and res.payment_deadline and now >= res.payment_deadline:
                res.status = 'EXPIRED'
                res.save(update_fields=['status'])
                continue
            if res.status == 'CONFIRMED' and not res.checked_in_at and res.arrival_deadline and now >= res.arrival_deadline:
                res.status = 'EXPIRED'
                if res.payment_method == 'DEPOSIT':
                    res.deposit_forfeited = True
                res.save(update_fields=['status', 'deposit_forfeited'])
                continue

            matches = False
            if target_hmac and res.plate_lookup_hmac:
                matches = (res.plate_lookup_hmac == target_hmac)
            else:
                matches = (AntiSpamService.normalize_plate(res.plate_number) == norm_target)

            if matches:
                msg = (
                    f"A reservation is already active for vehicle plate '{res.plate_number}' at {res.parking_zone.name} "
                    f"(Ticket #{res.ticket_code}). Simultaneous holds for the same vehicle plate are not permitted."
                )
                return False, res, msg

        return True, None, ""

    @staticmethod
    def check_pay_later_eligibility(user) -> tuple[bool, str, dict]:
        """
        Validates whether user is allowed to book with PAY_AT_EXIT:
        1. 10-minute cooldown after cancelling an unpaid hold.
        2. Two unpaid no-shows within 7 days disable pay-later for 24 hours (with available-at timestamp).
        3. Maximum 3 new pay-later holds per account in rolling 24 hours.
        """
        now = timezone.now()
        meta = {}

        # 1. 10-minute cancellation cooldown
        cooldown_mins = getattr(settings, 'UNPAID_CANCEL_COOLDOWN_MINUTES', 10)
        recent_cancel = Reservation.objects.filter(
            customer=user,
            payment_method='PAY_AT_EXIT',
            status='CANCELLED',
            cancelled_at__isnull=False,
            cancelled_at__gte=now - timedelta(minutes=cooldown_mins)
        ).order_by('-cancelled_at').first()

        if recent_cancel:
            cooldown_ends = recent_cancel.cancelled_at + timedelta(minutes=cooldown_mins)
            remaining_secs = max(0, (cooldown_ends - now).total_seconds())
            remaining_mins = int(math.ceil(remaining_secs / 60.0))
            meta['cooldown_ends'] = cooldown_ends
            meta['cooldown_minutes_remaining'] = remaining_mins
            msg = (
                f"Please wait {remaining_mins} minute{'s' if remaining_mins != 1 else ''} before creating another pay-later hold "
                f"({cooldown_mins}-minute cooldown after cancelling an unpaid hold). You can still book using 'Pay first day now'."
            )
            return False, msg, meta

        # 2. Two unpaid no-shows within 7 days -> 24-hour lockout
        noshow_threshold = getattr(settings, 'UNPAID_NOSHOW_THRESHOLD', 2)
        penalty_hours = getattr(settings, 'UNPAID_NOSHOW_PENALTY_HOURS', 24)

        recent_noshows = list(Reservation.objects.filter(
            customer=user,
            payment_method='PAY_AT_EXIT',
            status='EXPIRED',
            checked_in_at__isnull=True,
            created_on__gte=now - timedelta(days=7)
        ).order_by('-created_on')[:noshow_threshold])

        if len(recent_noshows) >= noshow_threshold:
            # Determine lockout anchor: the arrival deadline or creation of the second (most recent) no-show
            latest_noshow = recent_noshows[0]
            noshow_anchor = latest_noshow.arrival_deadline or (latest_noshow.created_on + timedelta(hours=3))
            lockout_until = noshow_anchor + timedelta(hours=penalty_hours)

            if now < lockout_until:
                avail_str = lockout_until.strftime('%b %d, %Y at %I:%M %p')
                meta['lockout_until'] = lockout_until
                meta['available_at'] = avail_str
                msg = (
                    f"Pay when you leave is temporarily disabled due to {noshow_threshold} unpaid no-shows in the last 7 days. "
                    f"It will become available again on {avail_str}. You can still reserve using 'Pay first day now'."
                )
                return False, msg, meta

        # 3. Maximum 3 new pay-later holds in rolling 24 hours
        max_daily_holds = getattr(settings, 'MAX_PAY_LATER_HOLDS_PER_24H', 3)
        holds_last_24h = Reservation.objects.filter(
            customer=user,
            payment_method='PAY_AT_EXIT',
            created_on__gte=now - timedelta(hours=24)
        ).count()

        if holds_last_24h >= max_daily_holds:
            meta['max_holds_reached'] = True
            msg = (
                f"You have reached the maximum limit of {max_daily_holds} pay-later holds in a 24-hour period. "
                f"Please choose 'Pay first day now' or try again later."
            )
            return False, msg, meta

        return True, "", meta
