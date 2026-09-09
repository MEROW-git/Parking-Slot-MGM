import math
import secrets
from datetime import timedelta, datetime
from decimal import Decimal
from django.conf import settings
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
    def calculate_bill(reservation: Reservation, as_of: datetime = None) -> dict:
        now = as_of or timezone.now()
        daily_rate = reservation.daily_rate or (reservation.parking_zone.price if reservation.parking_zone_id else 3000)
        overstay_multiplier = Decimal(str(reservation.overstay_multiplier or 2.0))
        overstay_rate = int(round(Decimal(daily_rate) * overstay_multiplier))

        entry_time = reservation.checked_in_at or reservation.effective_start_time
        booked_end = reservation.effective_finish_time

        # If already checked out, use actual checkout timestamp
        exit_time = reservation.checked_out_at or now

        # Ensure exit_time >= entry_time
        if exit_time < entry_time:
            exit_time = entry_time

        # Normal portion: time up to min(exit_time, booked_end)
        normal_end = min(exit_time, booked_end)
        normal_seconds = max(0.0, (normal_end - entry_time).total_seconds())

        # Every started 24-hour period is one billable day, with a 1-day minimum after entry
        if normal_seconds == 0 and exit_time == entry_time:
            normal_days = 1
        else:
            normal_days = max(1, math.ceil(normal_seconds / 86400.0))

        normal_charge = normal_days * daily_rate

        # Overstay portion: time after booked_end
        overstay_seconds = max(0.0, (exit_time - booked_end).total_seconds())
        if overstay_seconds > 0:
            # Positive portion rounded up to 24-hour billing unit
            overstay_days = math.ceil(overstay_seconds / 86400.0)
        else:
            overstay_days = 0

        # Double rate includes the normal charge for that overstay period (i.e. 2x, not 1x + 2x)
        overstay_charge = overstay_days * overstay_rate

        total_charge = normal_charge + overstay_charge
        deposit_paid = reservation.deposit_amount or 0
        balance_paid = reservation.balance_paid or 0

        total_paid = deposit_paid + balance_paid
        balance_due = max(0, total_charge - total_paid)

        # Duration elapsed
        total_parked_seconds = max(0.0, (exit_time - entry_time).total_seconds())
        parked_hours = int(total_parked_seconds // 3600)
        parked_minutes = int((total_parked_seconds % 3600) // 60)
        if parked_hours > 0 and parked_minutes > 0:
            parked_duration_display = f"{parked_hours} hr {parked_minutes} min"
        elif parked_hours > 0:
            parked_duration_display = f"{parked_hours} hr"
        else:
            parked_duration_display = f"{max(1, parked_minutes)} min"

        # Overstay duration elapsed
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

        has_verified_entry = bool(reservation.checked_in_at)
        is_timestamp_inconsistent = bool(reservation.status == 'CHECKED_IN' and not reservation.checked_in_at)

        return {
            'daily_rate': daily_rate,
            'daily_rate_formatted': f"{daily_rate:,} ៛",
            'overstay_multiplier': float(overstay_multiplier),
            'overstay_rate': overstay_rate,
            'overstay_rate_formatted': f"{overstay_rate:,} ៛",
            'entry_time': entry_time,
            'exit_time': exit_time,
            'booked_end': booked_end,
            'calculated_at': now,
            'has_verified_entry': has_verified_entry,
            'is_timestamp_inconsistent': is_timestamp_inconsistent,
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
            'deposit_deducted': deposit_paid,
            'deposit_deducted_formatted': f"{deposit_paid:,} ៛",
            'balance_paid': balance_paid,
            'balance_paid_formatted': f"{balance_paid:,} ៛",
            'total_paid': total_paid,
            'balance_due': balance_due,
            'balance_due_formatted': f"{balance_due:,} ៛",
            'is_overstay': overstay_days > 0,
        }

    @staticmethod
    def estimate_booking_cost(zone: ParkingZone, start_time: datetime, finish_time: datetime) -> dict:
        daily_rate = zone.price
        duration_seconds = max(0.0, (finish_time - start_time).total_seconds())
        days = max(1, math.ceil(duration_seconds / 86400.0))
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
        """Verifies if spaces are available right now, locking the zone row."""
        zone = ParkingZone.objects.select_for_update().get(id=zone_id)
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
    def check_date_range_availability(zone_id: int, start_time: datetime, finish_time: datetime) -> bool:
        """Verifies capacity for a specific date/time window."""
        zone = ParkingZone.objects.select_for_update().get(id=zone_id)
        now = timezone.now()

        # If booking starts today / immediate window, check current availability
        if start_time <= now + timedelta(hours=3):
            if not CapacityService.check_immediate_availability(zone_id):
                return False

        # Overlapping reservations during the window
        overlapping = Reservation.objects.filter(
            parking_zone=zone,
            status__in=['CONFIRMED', 'CHECKED_IN']
        ).exclude(
            finish_time__lte=start_time
        ).exclude(
            start_time__gte=finish_time
        ).count()

        # Include base occupied slots
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
    def confirm_deposit(txn_id: int, provider_ref: str = None) -> tuple[bool, str]:
        """Idempotent deposit confirmation."""
        txn = PaymentTransaction.objects.select_for_update().get(id=txn_id)
        reservation = Reservation.objects.select_for_update().get(id=txn.reservation_id)

        # Idempotency check: if already confirmed
        if txn.status == 'SUCCESS' and reservation.status == 'CONFIRMED':
            return True, 'Deposit payment already confirmed.'

        now = timezone.now()

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
        is_demo = getattr(settings, 'DEMO_PAYMENT_ENABLED', True) if provider == 'DEMO' else False

        ref = provider_ref or f"EXIT-{secrets.token_hex(8).upper()}"
        txn = PaymentTransaction.objects.create(
            reservation=reservation,
            purpose='EXIT_BALANCE',
            amount=amount,
            currency='KHR',
            status='SUCCESS',
            provider=provider,
            provider_ref=ref,
            is_demo=is_demo,
            completed_at=now,
        )

        reservation.balance_paid += amount
        reservation.payment_status = 'PAID'
        exit_mins = getattr(settings, 'EXIT_WINDOW_MINUTES', 5)
        reservation.exit_authorized_until = now + timedelta(minutes=exit_mins)
        reservation.save(update_fields=['balance_paid', 'payment_status', 'exit_authorized_until'])

        return txn


class GateService:
    """
    Gate entry and exit workflows with atomic occupancy transitions
    and hardware simulator hooks.
    """

    @staticmethod
    def validate_entry(token_or_code: str, zone_id: int = None) -> tuple[bool, Reservation | None, str]:
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

        now = timezone.now()

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
        if now >= reservation.effective_finish_time:
            return False, reservation, 'The booked arrival window has ended.'
        if reservation.payment_method == 'DEPOSIT' and reservation.deposit_amount < reservation.daily_rate:
            return False, reservation, 'First-day deposit has not been recorded.'

        # Enforce 3-hour arrival deadline for unpaid holds
        if reservation.payment_method == 'PAY_AT_EXIT' and reservation.arrival_deadline and now >= reservation.arrival_deadline:
            reservation.status = 'EXPIRED'
            reservation.save(update_fields=['status'])
            return False, reservation, 'The 3-hour arrival window for this unpaid booking has expired.'

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

        # 3. Deposited no-shows: booked finish time passed without ever checking in
        no_shows = Reservation.objects.select_for_update().filter(
            payment_method='DEPOSIT',
            status='CONFIRMED',
            finish_time__lt=now,
            checked_in_at__isnull=True
        )
        for res in no_shows:
            res.status = 'EXPIRED'
            res.staff_notes = (res.staff_notes + f"\n[Auto-Expire] No-show at booked end {now.isoformat()}. Deposit retained per policy.").strip()
            res.save(update_fields=['status', 'staff_notes'])
            results['no_shows'] += 1

        return results
