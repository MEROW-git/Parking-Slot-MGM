import zoneinfo
from datetime import datetime, timedelta
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from django.core.cache import cache

from parking_zones.models import ParkingZone, Reservation, PaymentTransaction
from parking_zones.services import (
    BillingService,
    PaymentService,
    GateService,
    ExpiryService,
    AntiSpamService,
    CapacityService,
)


class SimplifiedBookingAndAntiSpamTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.zone1 = ParkingZone.objects.create(
            name='Central Park Zone A',
            slug='central-park-zone-a',
            num_of_slots=10,
            occupied_slots=2,
            vacant_slots=8,
            price=4000,
            address='Phnom Penh City Center',
            district='Daun Penh',
        )
        self.zone2 = ParkingZone.objects.create(
            name='Riverside Zone B',
            slug='riverside-zone-b',
            num_of_slots=10,
            occupied_slots=1,
            vacant_slots=9,
            price=5000,
            address='Riverside Walk',
            district='Daun Penh',
        )
        self.user1 = User.objects.create_user(
            username='customer_one',
            email='c1@sompark.test',
            password='testpassword123'
        )
        self.user2 = User.objects.create_user(
            username='customer_two',
            email='c2@sompark.test',
            password='testpassword123'
        )
        self.staff_user = User.objects.create_user(
            username='staff_officer',
            email='staff@sompark.test',
            password='testpassword123',
            is_staff=True
        )

    def tearDown(self):
        cache.clear()

    # =========================================================================
    # 1. Pay First Day Now (DEPOSIT) Tests
    # =========================================================================
    def test_deposit_arrival_deadline_set_on_payment_confirmation(self):
        """DEPOSIT allows 15-minute checkout, then sets exact 5-hour arrival deadline on payment."""
        now = timezone.now()
        res = Reservation.objects.create(
            customer=self.user1,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-1111',
            phone_number='+85512345678',
            payment_method='DEPOSIT',
            status='PAYMENT_PENDING',
            reserved_days=2,
            daily_rate=4000,
            deposit_amount=4000,
            payment_deadline=now + timedelta(minutes=15),
        )
        self.assertIsNone(res.arrival_deadline)

        # Confirm payment
        tx = PaymentTransaction.objects.create(
            reservation=res,
            purpose='DEPOSIT',
            amount=4000,
            status='PENDING',
            is_demo=True,
        )
        payment_time = timezone.now()
        success, msg = PaymentService.confirm_deposit(tx.id, confirmed_at=payment_time)
        self.assertTrue(success)

        res.refresh_from_db()
        self.assertEqual(res.status, 'CONFIRMED')
        self.assertEqual(res.payment_status, 'PARTIALLY_PAID')
        self.assertIsNotNone(res.arrival_deadline)

        expected_deadline = payment_time + timedelta(hours=5)
        diff_seconds = abs((res.arrival_deadline - expected_deadline).total_seconds())
        self.assertLess(diff_seconds, 2)

    def test_deposit_arrival_window_crosses_midnight(self):
        """Arrival deadline allows crossing calendar midnight without being shortened."""
        tz = timezone.get_current_timezone()
        # 10:30 PM (22:30) on Day 1
        day1_night = timezone.make_aware(datetime(2026, 9, 10, 22, 30, 0), tz)
        res = Reservation.objects.create(
            customer=self.user1,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-1112',
            phone_number='+85512345678',
            payment_method='DEPOSIT',
            status='PAYMENT_PENDING',
            reserved_days=1,
            daily_rate=4000,
            deposit_amount=4000,
            payment_deadline=day1_night + timedelta(minutes=15),
        )

        tx = PaymentTransaction.objects.create(
            reservation=res,
            purpose='DEPOSIT',
            amount=4000,
            status='PENDING',
            is_demo=True,
        )
        success, msg = PaymentService.confirm_deposit(tx.id, confirmed_at=day1_night)
        self.assertTrue(success)
        res.refresh_from_db()

        # In local time: 22:30 + 5 hours = 03:30 next morning (crossing midnight)
        local_deadline = timezone.localtime(res.arrival_deadline, tz)
        self.assertEqual(local_deadline.day, 11)
        self.assertEqual(local_deadline.hour, 3)
        self.assertEqual(local_deadline.minute, 30)

    def test_duplicate_payment_callback_never_extends_arrival_deadline(self):
        """Deadline is stored once; retries/duplicate callbacks must NEVER extend it."""
        res = Reservation.objects.create(
            customer=self.user1,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-1113',
            phone_number='+85512345678',
            payment_method='DEPOSIT',
            status='PAYMENT_PENDING',
            reserved_days=1,
            daily_rate=4000,
            deposit_amount=4000,
        )
        t0 = timezone.now()
        tx = PaymentTransaction.objects.create(
            reservation=res,
            purpose='DEPOSIT',
            amount=4000,
            status='PENDING',
            is_demo=True,
        )
        PaymentService.confirm_deposit(tx.id, confirmed_at=t0)
        res.refresh_from_db()
        initial_deadline = res.arrival_deadline

        # Simulate second callback 2 hours later
        t_later = t0 + timedelta(hours=2)
        PaymentService.confirm_deposit(tx.id, confirmed_at=t_later)
        res.refresh_from_db()

        # Must strictly match the original deadline
        self.assertEqual(res.arrival_deadline, initial_deadline)

    def test_deposit_entry_before_deadline_succeeds(self):
        """Customer entering within 5 hours is admitted and parking begins."""
        now = timezone.now()
        res = Reservation.objects.create(
            customer=self.user1,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-1114',
            phone_number='+85512345678',
            payment_method='DEPOSIT',
            status='CONFIRMED',
            payment_status='PAID',
            reserved_days=2,
            daily_rate=4000,
            deposit_amount=4000,
            arrival_deadline=now + timedelta(hours=3), # 3h in future
        )
        valid, entry_res, msg = GateService.validate_entry(res.ticket_code)
        self.assertTrue(valid)

        success, confirmed_res, cmsg = GateService.confirm_entry(res.id, staff_user=self.staff_user)
        self.assertTrue(success)
        res.refresh_from_db()
        self.assertEqual(res.status, 'CHECKED_IN')
        self.assertIsNotNone(res.checked_in_at)
        # Parking deadline is entry + 2 days * 24h
        self.assertEqual(res.parking_deadline, res.checked_in_at + timedelta(days=2))

    def test_deposit_no_show_after_deadline_forfeited(self):
        """Customer not entering by 5-hour deadline is expired and first-day deposit forfeited."""
        past = timezone.now() - timedelta(minutes=10)
        res = Reservation.objects.create(
            customer=self.user1,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-1115',
            phone_number='+85512345678',
            payment_method='DEPOSIT',
            status='CONFIRMED',
            payment_status='PAID',
            reserved_days=1,
            daily_rate=4000,
            deposit_amount=4000,
            arrival_deadline=past,
        )
        # Gate QR scan rejected
        valid, entry_res, msg = GateService.validate_entry(res.ticket_code)
        self.assertFalse(valid)
        self.assertIn('expired', msg.lower())

        res.refresh_from_db()
        self.assertEqual(res.status, 'EXPIRED')
        self.assertTrue(res.deposit_forfeited)

        # ExpiryService also handles background sweeps and forfeits deposit
        res2 = Reservation.objects.create(
            customer=self.user2,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-1116',
            phone_number='+85512345678',
            payment_method='DEPOSIT',
            status='CONFIRMED',
            payment_status='PAID',
            reserved_days=1,
            daily_rate=4000,
            deposit_amount=4000,
            arrival_deadline=past,
        )
        expiry_summary = ExpiryService.expire_stale_holds()
        self.assertGreaterEqual(expiry_summary['no_shows'], 1)
        res2.refresh_from_db()
        self.assertEqual(res2.status, 'EXPIRED')
        self.assertTrue(res2.deposit_forfeited)

    def test_deposit_cancellation_does_not_forfeit(self):
        """Voluntary customer cancellation before entry sets cancelled_at but does NOT forfeit deposit."""
        now = timezone.now()
        res = Reservation.objects.create(
            customer=self.user1,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-1117',
            phone_number='+85512345678',
            payment_method='DEPOSIT',
            status='CONFIRMED',
            payment_status='PAID',
            reserved_days=1,
            daily_rate=4000,
            deposit_amount=4000,
            arrival_deadline=now + timedelta(hours=4),
        )
        self.client.login(username='customer_one', password='testpassword123')
        resp = self.client.post(reverse('cancel_booking', args=[res.ticket_code]))
        self.assertEqual(resp.status_code, 302)

        res.refresh_from_db()
        self.assertEqual(res.status, 'CANCELLED')
        self.assertIsNotNone(res.cancelled_at)
        self.assertFalse(res.deposit_forfeited)

    # =========================================================================
    # 2. Pay When You Leave (PAY_AT_EXIT) Tests
    # =========================================================================
    def test_pay_at_exit_deadline_is_3_hours_and_crosses_midnight(self):
        """PAY_AT_EXIT creates confirmed hold with 3-hour arrival deadline, crossing midnight."""
        tz = timezone.get_current_timezone()
        # 11:30 PM
        t_late = timezone.make_aware(datetime(2026, 9, 10, 23, 30, 0), tz)
        res = Reservation.objects.create(
            customer=self.user1,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-2221',
            phone_number='+85512345678',
            payment_method='PAY_AT_EXIT',
            status='CONFIRMED',
            reserved_days=1,
            daily_rate=4000,
            created_on=t_late,
            arrival_deadline=t_late + timedelta(hours=3),
        )
        self.assertEqual(res.arrival_deadline.day, 11)
        self.assertEqual(res.arrival_deadline.hour, 2)
        self.assertEqual(res.arrival_deadline.minute, 30)

        # Before deadline, gate access is valid
        valid1, _, _ = GateService.validate_entry(res.ticket_code, check_time=t_late + timedelta(hours=1))
        self.assertTrue(valid1)

        # After 3 hours, gate access expires
        valid2, _, msg2 = GateService.validate_entry(res.ticket_code, check_time=t_late + timedelta(hours=3, minutes=1))
        self.assertFalse(valid2)
        res.refresh_from_db()
        self.assertEqual(res.status, 'EXPIRED')
        self.assertFalse(res.deposit_forfeited)

    # =========================================================================
    # 3. Actual-Entry Billing & Crediting Tests
    # =========================================================================
    def test_no_charges_accrue_before_physical_entry(self):
        """Never charge parking or overstay before physical gate check-in."""
        res = Reservation.objects.create(
            customer=self.user1,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-3331',
            phone_number='+85512345678',
            payment_method='PAY_AT_EXIT',
            status='CONFIRMED',
            reserved_days=1,
            daily_rate=4000,
            arrival_deadline=timezone.now() + timedelta(hours=2),
            checked_in_at=None,
        )
        bill = BillingService.calculate_bill(res)
        self.assertEqual(bill['normal_days'], 0)
        self.assertEqual(bill['overstay_days'], 0)
        self.assertEqual(bill['total_charge'], 0)
        self.assertEqual(bill['balance_due'], 0)

    def test_deposit_credited_and_overstay_rate_preserved(self):
        """Deposit credited in full; 2x overstay rate applied after reserved_days * 24h."""
        entry_time = timezone.now() - timedelta(hours=28) # 28 hours ago
        res = Reservation.objects.create(
            customer=self.user1,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-3332',
            phone_number='+85512345678',
            payment_method='DEPOSIT',
            status='CHECKED_IN',
            reserved_days=1, # 1 day = 24h
            daily_rate=4000,
            deposit_amount=4000,
            balance_paid=0,
            checked_in_at=entry_time,
        )
        # Parked for 28 hours on a 24-hour reservation:
        # 1 normal day = 4000
        # 4 hours overstay = 1 started overstay day @ 2x (8000)
        # Total charge = 12000
        # Deposit credited = 4000
        # Balance due = 8000
        bill = BillingService.calculate_bill(res, exit_time=timezone.now())
        self.assertEqual(bill['normal_days'], 1)
        self.assertEqual(bill['overstay_days'], 1)
        self.assertEqual(bill['normal_charge'], 4000)
        self.assertEqual(bill['overstay_charge'], 8000)
        self.assertEqual(bill['total_charge'], 12000)
        self.assertEqual(bill['deposit_deducted'], 4000)
        self.assertEqual(bill['balance_due'], 8000)

    # =========================================================================
    # 4. Anti-Spam & Hold Policies Tests
    # =========================================================================
    def test_one_active_reservation_per_account(self):
        """Customer cannot hold multiple active reservations simultaneously (including PAYMENT_PENDING)."""
        # User 1 has active reservation
        active = Reservation.objects.create(
            customer=self.user1,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-4441',
            phone_number='+85512345678',
            payment_method='PAY_AT_EXIT',
            status='CONFIRMED',
            reserved_days=1,
            arrival_deadline=timezone.now() + timedelta(hours=2),
        )
        allowed, active_res, msg = AntiSpamService.check_active_reservation_limit(self.user1)
        self.assertFalse(allowed)
        self.assertIsNotNone(active_res)

        # Form submission through booking view redirects to active ticket with message
        self.client.login(username='customer_one', password='testpassword123')
        resp = self.client.post(reverse('book'), {
            'parking_zone': self.zone2.id,
            'payment_method': 'PAY_AT_EXIT',
            'reserved_days': 1,
            'plate_province': 'Kandal',
            'plate_code': '2B-9999',
            'plate_number': 'Kandal 2B-9999',
            'phone_number': '+85512345678',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already have an active reservation')

    def test_prevent_simultaneous_plate_holds_across_facilities(self):
        """Normalized vehicle plate cannot be reserved simultaneously in any facility."""
        # Zone 1 reserved plate "Phnom Penh 2AZ-5555"
        Reservation.objects.create(
            customer=self.user1,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-5555',
            phone_number='+85512345678',
            payment_method='PAY_AT_EXIT',
            status='CONFIRMED',
            reserved_days=1,
            arrival_deadline=timezone.now() + timedelta(hours=2),
        )

        # User 2 attempts to reserve same plate with different formatting: "phnom-penh 2az5555" at Zone 2
        allowed, held_res, msg = AntiSpamService.check_simultaneous_plate_hold('phnom-penh 2az5555')
        self.assertFalse(allowed)
        self.assertEqual(held_res.parking_zone, self.zone1)

        self.client.login(username='customer_two', password='testpassword123')
        resp = self.client.post(reverse('book'), {
            'parking_zone': self.zone2.id,
            'payment_method': 'PAY_AT_EXIT',
            'reserved_days': 1,
            'plate_province': 'Phnom Penh',
            'plate_code': '2az 5555',
            'plate_number': 'Phnom Penh 2az 5555',
            'phone_number': '+85512345678',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Simultaneous holds for the same vehicle plate are not permitted')

    def test_duplicate_submission_returns_existing_without_extra_capacity(self):
        """Duplicate submissions within 120 seconds return existing booking without extra capacity hold."""
        self.client.login(username='customer_one', password='testpassword123')

        payload = {
            'parking_zone': self.zone1.id,
            'payment_method': 'PAY_AT_EXIT',
            'reserved_days': 1,
            'plate_province': 'Phnom Penh',
            'plate_code': '2AZ-6661',
            'plate_number': 'Phnom Penh 2AZ-6661',
            'phone_number': '+85512345678',
        }

        # First submit
        resp1 = self.client.post(reverse('book'), payload)
        self.assertEqual(resp1.status_code, 302)
        res_first = Reservation.objects.get(plate_number='Phnom Penh 2AZ-6661')

        # Second rapid submit
        resp2 = self.client.post(reverse('book'), payload)
        self.assertEqual(resp2.status_code, 302)
        self.assertIn(res_first.ticket_code, resp2.url)

        # Count of reservations for this plate must be strictly 1
        self.assertEqual(Reservation.objects.filter(plate_number='Phnom Penh 2AZ-6661').count(), 1)

    def test_max_3_pay_later_holds_per_24_hours(self):
        """Account cannot create more than 3 PAY_AT_EXIT holds in a rolling 24-hour window."""
        now = timezone.now()
        # Create 3 cancelled pay-later holds within last 24h
        for i in range(3):
            Reservation.objects.create(
                customer=self.user1,
                parking_zone=self.zone1,
                plate_number=f'Phnom Penh 2AZ-777{i}',
                phone_number='+85512345678',
                payment_method='PAY_AT_EXIT',
                status='CANCELLED',
                reserved_days=1,
                created_on=now - timedelta(hours=i + 1),
                cancelled_at=now - timedelta(hours=i + 1),
            )

        allowed, reason, meta = AntiSpamService.check_pay_later_eligibility(self.user1)
        self.assertFalse(allowed)
        self.assertIn('3 pay-later holds', reason)

    def test_cooldown_after_cancelling_unpaid_hold(self):
        """Cancelling an unpaid hold triggers a 10-minute cooldown before another pay-later hold."""
        now = timezone.now()
        # Cancelled 3 minutes ago
        Reservation.objects.create(
            customer=self.user1,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-8881',
            phone_number='+85512345678',
            payment_method='PAY_AT_EXIT',
            status='CANCELLED',
            reserved_days=1,
            created_on=now - timedelta(minutes=5),
            cancelled_at=now - timedelta(minutes=3),
        )

        allowed, reason, meta = AntiSpamService.check_pay_later_eligibility(self.user1)
        self.assertFalse(allowed)
        self.assertIn('cooldown', reason.lower())
        self.assertIn('cooldown_ends', meta)

    def test_two_unpaid_noshows_disable_pay_later_for_24_hours(self):
        """Two unpaid no-shows within 7 days disables pay-later for 24 hours."""
        now = timezone.now()
        # 2 expired pay-at-exit holds (no-shows)
        for i in range(2):
            Reservation.objects.create(
                customer=self.user1,
                parking_zone=self.zone1,
                plate_number=f'Phnom Penh 2AZ-999{i}',
                phone_number='+85512345678',
                payment_method='PAY_AT_EXIT',
                status='EXPIRED',
                reserved_days=1,
                created_on=now - timedelta(hours=i + 2),
                arrival_deadline=now - timedelta(hours=i + 1),
                checked_in_at=None,
            )

        allowed, reason, meta = AntiSpamService.check_pay_later_eligibility(self.user1)
        self.assertFalse(allowed)
        self.assertIn('2 unpaid no-shows', reason)
        self.assertIn('become available again on', reason)
        self.assertIn('lockout_until', meta)
        self.assertTrue(meta.get('available_at'))
