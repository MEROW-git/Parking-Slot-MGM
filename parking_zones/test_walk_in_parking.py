import time
from datetime import timedelta
from decimal import Decimal
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import ParkingZone, Reservation
from .services import BillingService, CapacityService, ExpiryService, GateService


class WalkInParkingTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff-attendant', is_staff=True)
        self.client.force_login(self.staff)
        self.zone = ParkingZone.objects.create(
            name='Central Riverside',
            num_of_slots=2,
            price=4000,
            walk_in_price=7000  # Default 7,000 KHR per facility
        )
        self.url = reverse('admin_virtual_gate')

    def test_default_walk_in_price_and_custom_configuration(self):
        """Verify default walk-in rate is 7,000 KHR and facility-configurable."""
        z_default = ParkingZone.objects.create(name='Default Rate Zone', num_of_slots=5)
        self.assertEqual(z_default.walk_in_price, 7000)
        self.assertEqual(z_default.walk_in_price_khr_formatted, '7,000 ៛')

        z_custom = ParkingZone.objects.create(name='Custom Rate Zone', num_of_slots=5, walk_in_price=10000)
        self.assertEqual(z_custom.walk_in_price, 10000)
        self.assertEqual(z_custom.walk_in_price_khr_formatted, '10,000 ៛')

    def test_walk_in_ticket_issuance_creates_unbilled_hold(self):
        """
        Issuing a walk-in ticket:
        - Requires no customer account or phone number.
        - Captures optional vehicle plate.
        - Snapshots walk-in rate.
        - Opens simulated barrier with valid signed permit.
        - Does NOT start billing (checked_in_at is None).
        - Does NOT increment physical occupancy (occupied_slots is 0).
        - Holds 1 unreserved capacity space via arrival_deadline.
        """
        self.assertEqual(self.zone.occupied_slots, 0)
        self.assertEqual(CapacityService.get_unreserved_capacity(self.zone.pk), 2)

        data = {
            'zone': self.zone.pk,
            'mode': 'entry',
            'action': 'walk_in_issue',
            'walk_in_plate': 'Phnom Penh 2AZ-1234',
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['gate_open'])
        self.assertIsNotNone(response.context['permit'])
        self.assertIsNotNone(response.context['ticket_qr_base64'])

        res = response.context['reservation']
        self.assertIsNotNone(res)
        self.assertTrue(res.is_walk_in)
        self.assertIsNone(res.customer)
        self.assertEqual(res.phone_number, '')
        self.assertEqual(res.plate_number, 'Phnom Penh 2AZ-1234')
        self.assertEqual(res.daily_rate, 7000)
        self.assertEqual(res.overstay_multiplier, Decimal('1.0'))
        self.assertEqual(res.status, 'CONFIRMED')
        self.assertIsNone(res.checked_in_at)  # Billing has not started

        # Physical occupancy remains 0
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 0)

        # Unreserved capacity is now 1 because active ticket hold takes 1 slot
        self.assertEqual(CapacityService.get_unreserved_capacity(self.zone.pk), 1)

    def test_full_capacity_and_reservation_holds_reject_walk_in(self):
        """Server-side capacity check: rejects walk-in if no unreserved space remains."""
        # 1 slot occupied physically
        self.zone.occupied_slots = 1
        self.zone.save()

        # 1 slot held by active app reservation
        now = timezone.now()
        Reservation.objects.create(
            parking_zone=self.zone,
            plate_number='2B-1111',
            start_date=now.date(),
            finish_date=now.date(),
            payment_method='PAY_AT_EXIT',
            status='CONFIRMED',
            arrival_deadline=now + timedelta(hours=2)
        )

        # Unreserved capacity is 0
        self.assertEqual(CapacityService.get_unreserved_capacity(self.zone.pk), 0)

        # Walk-in issuance must be rejected
        data = {
            'zone': self.zone.pk,
            'mode': 'entry',
            'action': 'walk_in_issue',
        }
        resp = self.client.post(self.url, data)
        self.assertFalse(resp.context.get('gate_open', False))
        self.assertContains(resp, 'no available unreserved spaces')
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 1)

    def test_confirmed_passage_starts_session_and_increments_occupancy(self):
        """Physical occupancy increments and session starts ONLY when vehicle passes."""
        # Issue ticket
        resp = self.client.post(self.url, {
            'zone': self.zone.pk,
            'mode': 'entry',
            'action': 'walk_in_issue',
            'walk_in_plate': '2AZ-8888',
        })
        res = resp.context['reservation']
        permit = resp.context['permit']

        # Confirm passage
        pass_data = {
            'zone': self.zone.pk,
            'code': res.ticket_code,
            'mode': 'entry',
            'action': 'pass',
            'permit': permit,
        }
        pass_resp = self.client.post(self.url, pass_data)
        self.assertTrue(pass_resp.context['passed'])
        self.assertFalse(pass_resp.context['gate_open'])

        res.refresh_from_db()
        self.assertEqual(res.status, 'CHECKED_IN')
        self.assertIsNotNone(res.checked_in_at)

        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 1)

    def test_abandoned_walk_in_ticket_released_on_close(self):
        """If attendant closes barrier without vehicle passage, unused ticket hold is released."""
        resp = self.client.post(self.url, {
            'zone': self.zone.pk,
            'mode': 'entry',
            'action': 'walk_in_issue',
        })
        res = resp.context['reservation']
        self.assertEqual(CapacityService.get_unreserved_capacity(self.zone.pk), 1)

        # Close without passage
        close_resp = self.client.post(self.url, {
            'zone': self.zone.pk,
            'code': res.ticket_code,
            'mode': 'entry',
            'action': 'close',
        })
        self.assertFalse(close_resp.context['gate_open'])

        res.refresh_from_db()
        self.assertEqual(res.status, 'CANCELLED')
        self.assertIsNone(res.checked_in_at)

        # Capacity hold released immediately
        self.assertEqual(CapacityService.get_unreserved_capacity(self.zone.pk), 2)
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 0)

    def test_expired_walk_in_hold_released_after_timeout(self):
        """Unused walk-in ticket holds expire after arrival deadline timeout."""
        resp = self.client.post(self.url, {
            'zone': self.zone.pk,
            'mode': 'entry',
            'action': 'walk_in_issue',
        })
        res = resp.context['reservation']

        # Simulate timeout expiry (5 minutes past arrival deadline)
        res.arrival_deadline = timezone.now() - timedelta(seconds=10)
        res.save()

        summary = ExpiryService.expire_stale_holds()
        self.assertGreaterEqual(summary.get('unpaid_holds', 0), 1)

        res.refresh_from_db()
        self.assertEqual(res.status, 'EXPIRED')
        self.assertEqual(CapacityService.get_unreserved_capacity(self.zone.pk), 2)

    def test_24_hour_block_billing_boundaries_and_walk_in_rate_label(self):
        """
        Billing boundaries for walk-in tickets:
        - 1-day minimum after entry (e.g. 15 minutes = 7,000 KHR).
        - 23 hours 59 minutes = 1 day = 7,000 KHR.
        - 24 hours 1 minute = 2 days = 14,000 KHR.
        - 48 hours 1 minute = 3 days = 21,000 KHR.
        - Label is 'Walk-in rate', not an overstay penalty (overstay_charge is 0).
        """
        entry = timezone.now() - timedelta(hours=1)
        res = Reservation.objects.create(
            parking_zone=self.zone,
            is_walk_in=True,
            daily_rate=7000,
            overstay_multiplier=Decimal('1.0'),
            start_date=entry.date(),
            finish_date=entry.date(),
            start_time=entry,
            finish_time=entry + timedelta(days=1),
            status='CHECKED_IN',
            checked_in_at=entry,
        )

        # 1. 15 minutes parked -> 1 day minimum (7,000 KHR)
        as_of_15m = entry + timedelta(minutes=15)
        bill_15m = BillingService.calculate_bill(res, as_of=as_of_15m)
        self.assertEqual(bill_15m['rate_label'], 'Walk-in rate')
        self.assertEqual(bill_15m['normal_days'], 1)
        self.assertEqual(bill_15m['normal_charge'], 7000)
        self.assertEqual(bill_15m['overstay_charge'], 0)
        self.assertEqual(bill_15m['total_charge'], 7000)
        self.assertEqual(bill_15m['balance_due'], 7000)

        # 2. 23 hours 59 minutes -> 1 day (7,000 KHR)
        as_of_24h = entry + timedelta(hours=23, minutes=59)
        bill_24h = BillingService.calculate_bill(res, as_of=as_of_24h)
        self.assertEqual(bill_24h['normal_days'], 1)
        self.assertEqual(bill_24h['total_charge'], 7000)
        self.assertEqual(bill_24h['overstay_charge'], 0)

        # 3. 24 hours 1 minute -> 2 days (14,000 KHR)
        as_of_25h = entry + timedelta(hours=24, minutes=1)
        bill_25h = BillingService.calculate_bill(res, as_of=as_of_25h)
        self.assertEqual(bill_25h['normal_days'], 2)
        self.assertEqual(bill_25h['total_charge'], 14000)
        self.assertEqual(bill_25h['overstay_charge'], 0)
        self.assertEqual(bill_25h['balance_due'], 14000)

        # 4. 48 hours 1 minute -> 3 days (21,000 KHR)
        as_of_49h = entry + timedelta(hours=48, minutes=1)
        bill_49h = BillingService.calculate_bill(res, as_of=as_of_49h)
        self.assertEqual(bill_49h['normal_days'], 3)
        self.assertEqual(bill_49h['total_charge'], 21000)
        self.assertEqual(bill_49h['overstay_charge'], 0)

    def test_exit_cash_settlement_direct_passage(self):
        """
        At exit:
        - Cash settlement completes payment.
        - Directly opens barrier without asking staff to scan again.
        - Marks checked out and releases physical occupancy only after vehicle passage.
        """
        entry = timezone.now() - timedelta(hours=2)
        res = Reservation.objects.create(
            parking_zone=self.zone,
            is_walk_in=True,
            daily_rate=7000,
            overstay_multiplier=Decimal('1.0'),
            start_date=entry.date(),
            finish_date=entry.date(),
            status='CHECKED_IN',
            checked_in_at=entry,
            plate_number='2AZ-5555'
        )
        self.zone.occupied_slots = 1
        self.zone.save()

        # Attendant inspects at exit
        inspect_data = {'zone': self.zone.pk, 'code': res.ticket_code, 'mode': 'exit', 'action': 'open'}
        inspect_resp = self.client.post(self.url, inspect_data)
        self.assertFalse(inspect_resp.context['gate_open'])
        self.assertEqual(inspect_resp.context['bill']['balance_due'], 7000)

        # Attendant settles cash payment
        settle_data = {
            'zone': self.zone.pk,
            'code': res.ticket_code,
            'mode': 'exit',
            'action': 'settle',
            'payment_provider': 'CASH',
        }
        settle_resp = self.client.post(self.url, settle_data)
        self.assertTrue(settle_resp.context['gate_open'])
        self.assertEqual(settle_resp.context['bill']['balance_due'], 0)
        permit = settle_resp.context['permit']
        self.assertIsNotNone(permit)

        # Vehicle passage confirmation
        pass_data = {
            'zone': self.zone.pk,
            'code': res.ticket_code,
            'mode': 'exit',
            'action': 'pass',
            'permit': permit,
        }
        pass_resp = self.client.post(self.url, pass_data)
        self.assertTrue(pass_resp.context['passed'])
        self.assertFalse(pass_resp.context['gate_open'])

        res.refresh_from_db()
        self.assertEqual(res.status, 'CHECKED_OUT')
        self.assertIsNotNone(res.checked_out_at)

        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 0)

    def test_exit_demo_aba_payment_success_failure_retry(self):
        """Test demo ABA payment simulation: failure retains balance; success authorizes passage."""
        entry = timezone.now() - timedelta(hours=3)
        res = Reservation.objects.create(
            parking_zone=self.zone,
            is_walk_in=True,
            daily_rate=7000,
            status='CHECKED_IN',
            checked_in_at=entry,
            plate_number='2B-7777'
        )
        self.zone.occupied_slots = 1
        self.zone.save()

        # 1. Simulated ABA Failure
        fail_resp = self.client.post(self.url, {
            'zone': self.zone.pk,
            'code': res.ticket_code,
            'mode': 'exit',
            'action': 'settle',
            'payment_provider': 'DEMO',
            'outcome': 'failure',
        })
        self.assertFalse(fail_resp.context['gate_open'])
        self.assertEqual(fail_resp.context['bill']['balance_due'], 7000)
        res.refresh_from_db()
        self.assertEqual(res.payment_status, 'UNPAID')

        # 2. Attendant / Driver retries with Demo Success
        succ_resp = self.client.post(self.url, {
            'zone': self.zone.pk,
            'code': res.ticket_code,
            'mode': 'exit',
            'action': 'settle',
            'payment_provider': 'DEMO',
            'outcome': 'success',
        })
        self.assertTrue(succ_resp.context['gate_open'])
        self.assertEqual(succ_resp.context['bill']['balance_due'], 0)
        permit = succ_resp.context['permit']

        # 3. Vehicle passes exit barrier directly
        pass_resp = self.client.post(self.url, {
            'zone': self.zone.pk,
            'code': res.ticket_code,
            'mode': 'exit',
            'action': 'pass',
            'permit': permit,
        })
        self.assertTrue(pass_resp.context['passed'])
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 0)

    def test_duplicate_issuance_idempotency_prevents_duplicate_tickets(self):
        """Retrying issuance with same idempotency key returns existing reservation."""
        idemp_key = 'test_retry_key_12345'
        data = {
            'zone': self.zone.pk,
            'mode': 'entry',
            'action': 'walk_in_issue',
            'idempotency_key': idemp_key,
        }

        resp1 = self.client.post(self.url, data)
        res1 = resp1.context['reservation']

        # Immediate retry
        resp2 = self.client.post(self.url, data)
        res2 = resp2.context['reservation']

        self.assertEqual(res1.pk, res2.pk)
        self.assertEqual(res1.ticket_code, res2.ticket_code)
        self.assertEqual(Reservation.objects.filter(parking_zone=self.zone, is_walk_in=True).count(), 1)
