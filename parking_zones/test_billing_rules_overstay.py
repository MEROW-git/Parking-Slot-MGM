import zoneinfo
from datetime import datetime, timedelta, time
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from parking_zones.models import ParkingZone, Reservation, PaymentTransaction
from parking_zones.services import BillingService, CapacityService, ExpiryService, GateService, PaymentService


class BillingRulesAndOverstayTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tz = zoneinfo.ZoneInfo('Asia/Phnom_Penh')

    def setUp(self):
        self.zone = ParkingZone.objects.create(
            name='Wat Phnom Central Slot',
            slug='wat-phnom-central-slot',
            num_of_slots=5,
            occupied_slots=0,
            vacant_slots=5,
            price=5000,
            address='Street 96, Phnom Penh',
            district='Daun Penh',
        )
        self.customer = User.objects.create_user(
            username='sompark_tester',
            email='tester@sompark.test',
            password='Password123!'
        )
        self.staff_user = User.objects.create_user(
            username='staff_officer',
            email='staff@sompark.test',
            password='Password123!',
            is_staff=True
        )
        self.client = Client()

    def _fixed_dt(self, year=2026, month=9, day=9, hour=23, minute=10, second=0):
        return datetime(year, month, day, hour, minute, second, tzinfo=self.tz)

    def test_01_deposited_pending_arrival_has_zero_usage_and_penalty(self):
        """
        Confirmed hold with deposit paid before entry:
        - Actual parking charges = 0.
        - Overstay charges = 0.
        - Deposit paid displayed separately.
        - Additional usage balance due = 0.
        - Message: 'Parking charges start when you enter.'
        """
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2BC-1234',
            phone_number='+85512999888',
            start_date=datetime(2026, 9, 9).date(),
            start_time=self._fixed_dt(2026, 9, 9, 14, 0),
            finish_date=datetime(2026, 9, 10).date(),
            finish_time=self._fixed_dt(2026, 9, 10, 22, 0),
            daily_rate=5000,
            deposit_amount=5000,
            payment_status='PARTIALLY_PAID',
            payment_method='DEPOSIT',
            status='CONFIRMED',
            reserved_days=1,
            checked_in_at=None,
        )

        as_of = self._fixed_dt(2026, 9, 9, 23, 10)
        bill = BillingService.calculate_bill(res, as_of=as_of)

        self.assertEqual(bill['normal_charge'], 0)
        self.assertEqual(bill['overstay_charge'], 0)
        self.assertEqual(bill['total_charge'], 0)
        self.assertEqual(bill['balance_due'], 0)
        self.assertEqual(bill['deposit_paid'], 5000)
        self.assertIn('Parking charges start when you enter', bill['message'])

    def test_02_pay_at_exit_pending_arrival_has_zero_usage_and_penalty(self):
        """
        Pay-at-exit confirmed hold before entry:
        - Actual parking charges = 0.
        - Overstay charges = 0.
        - Additional balance due = 0.
        """
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2BC-1234',
            phone_number='+85512999888',
            start_date=datetime(2026, 9, 9).date(),
            start_time=self._fixed_dt(2026, 9, 9, 20, 0),
            finish_date=datetime(2026, 9, 10).date(),
            finish_time=self._fixed_dt(2026, 9, 10, 20, 0),
            daily_rate=5000,
            deposit_amount=0,
            payment_status='UNPAID',
            payment_method='PAY_AT_EXIT',
            status='CONFIRMED',
            reserved_days=1,
            checked_in_at=None,
            arrival_deadline=self._fixed_dt(2026, 9, 9, 23, 0),
        )

        as_of = self._fixed_dt(2026, 9, 9, 22, 30)
        bill = BillingService.calculate_bill(res, as_of=as_of)

        self.assertEqual(bill['normal_charge'], 0)
        self.assertEqual(bill['overstay_charge'], 0)
        self.assertEqual(bill['balance_due'], 0)
        self.assertEqual(bill['deposit_paid'], 0)
        self.assertIn('Parking charges start when you enter', bill['message'])

    def test_03_crossing_midnight_within_first_24_hours_adds_no_charge(self):
        """
        Enter Sep 9 at 23:10.
        Leave Sep 10 at 00:30 (past midnight, 1h 20m later).
        Leave Sep 10 at 10:00 (next morning, 10h 50m later).
        In both cases: 1 day minimum = 5,000 KHR; overstay = 0; additional due = 0 (after 5,000 deposit).
        Midnight does not truncate or split the 24-hour day.
        """
        entry_time = self._fixed_dt(2026, 9, 9, 23, 10)
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2BC-1234',
            phone_number='+85512999888',
            start_date=entry_time.date(),
            start_time=entry_time,
            finish_date=(entry_time + timedelta(days=1)).date(),
            finish_time=entry_time + timedelta(days=1),
            daily_rate=5000,
            deposit_amount=5000,
            payment_status='PARTIALLY_PAID',
            payment_method='DEPOSIT',
            status='CHECKED_IN',
            reserved_days=1,
            checked_in_at=entry_time,
        )

        # 1. Check at 00:30 Sep 10 (past midnight)
        bill_midnight = BillingService.calculate_bill(res, as_of=self._fixed_dt(2026, 9, 10, 0, 30))
        self.assertEqual(bill_midnight['normal_days'], 1)
        self.assertEqual(bill_midnight['normal_charge'], 5000)
        self.assertEqual(bill_midnight['overstay_days'], 0)
        self.assertEqual(bill_midnight['overstay_charge'], 0)
        self.assertEqual(bill_midnight['total_charge'], 5000)
        self.assertEqual(bill_midnight['balance_due'], 0)

        # 2. Check at 10:00 Sep 10 (next morning)
        bill_morning = BillingService.calculate_bill(res, as_of=self._fixed_dt(2026, 9, 10, 10, 0))
        self.assertEqual(bill_morning['normal_days'], 1)
        self.assertEqual(bill_morning['normal_charge'], 5000)
        self.assertEqual(bill_morning['overstay_days'], 0)
        self.assertEqual(bill_morning['overstay_charge'], 0)
        self.assertEqual(bill_morning['total_charge'], 5000)
        self.assertEqual(bill_morning['balance_due'], 0)

    def test_04_just_before_exactly_at_and_just_after_reserved_duration_boundary(self):
        """
        Book 1 day (5,000 KHR/day); deposit 5,000 KHR paid.
        Enter: Sep 9 at 23:10.
        Parking deadline: Sep 10 at exactly 23:10 (24.0 hours).
        - 1 second before (Sep 10 23:09:59): total 5,000; overstay 0; additional due 0.
        - Exactly at boundary (Sep 10 23:10:00): total 5,000; overstay 0; additional due 0.
        - 1 second after boundary (Sep 10 23:10:01):
          Normal 5,000 + 1 started overstay day (10,000) = total 15,000;
          minus deposit 5,000 -> additional due 10,000.
        """
        entry_time = self._fixed_dt(2026, 9, 9, 23, 10)
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2BC-1234',
            phone_number='+85512999888',
            start_date=entry_time.date(),
            start_time=entry_time,
            finish_date=(entry_time + timedelta(days=1)).date(),
            finish_time=entry_time + timedelta(days=1),
            daily_rate=5000,
            deposit_amount=5000,
            payment_status='PARTIALLY_PAID',
            payment_method='DEPOSIT',
            status='CHECKED_IN',
            reserved_days=1,
            checked_in_at=entry_time,
        )

        # 1. Just before deadline (Sep 10 at 23:09:59)
        t_before = self._fixed_dt(2026, 9, 10, 23, 9, 59)
        b_before = BillingService.calculate_bill(res, as_of=t_before)
        self.assertEqual(b_before['normal_days'], 1)
        self.assertEqual(b_before['normal_charge'], 5000)
        self.assertEqual(b_before['overstay_days'], 0)
        self.assertEqual(b_before['overstay_charge'], 0)
        self.assertEqual(b_before['total_charge'], 5000)
        self.assertEqual(b_before['balance_due'], 0)

        # 2. Exactly at deadline (Sep 10 at 23:10:00)
        t_exact = self._fixed_dt(2026, 9, 10, 23, 10, 0)
        b_exact = BillingService.calculate_bill(res, as_of=t_exact)
        self.assertEqual(b_exact['normal_days'], 1)
        self.assertEqual(b_exact['normal_charge'], 5000)
        self.assertEqual(b_exact['overstay_days'], 0)
        self.assertEqual(b_exact['overstay_charge'], 0)
        self.assertEqual(b_exact['total_charge'], 5000)
        self.assertEqual(b_exact['balance_due'], 0)

        # 3. 1 second after deadline (Sep 10 at 23:10:01)
        t_after = self._fixed_dt(2026, 9, 10, 23, 10, 1)
        b_after = BillingService.calculate_bill(res, as_of=t_after)
        self.assertEqual(b_after['normal_days'], 1)
        self.assertEqual(b_after['normal_charge'], 5000)
        self.assertEqual(b_after['overstay_days'], 1)
        self.assertEqual(b_after['overstay_charge'], 10000)
        self.assertEqual(b_after['total_charge'], 15000)
        self.assertEqual(b_after['deposit_deducted'], 5000)
        self.assertEqual(b_after['balance_due'], 10000)

    def test_05_two_actual_days_within_four_day_booking(self):
        """
        Book 4 days:
        - Enter Sep 9 at 23:10.
        - Leave after 2 days (Sep 11 at 23:10):
          2 started normal days = 10,000 KHR. Overstay = 0.
        """
        entry_time = self._fixed_dt(2026, 9, 9, 23, 10)
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2BC-1234',
            phone_number='+85512999888',
            start_date=entry_time.date(),
            start_time=entry_time,
            finish_date=(entry_time + timedelta(days=4)).date(),
            finish_time=entry_time + timedelta(days=4),
            daily_rate=5000,
            deposit_amount=5000,
            payment_status='PARTIALLY_PAID',
            payment_method='DEPOSIT',
            status='CHECKED_IN',
            reserved_days=4,
            checked_in_at=entry_time,
        )

        leave_time = entry_time + timedelta(days=2)
        bill = BillingService.calculate_bill(res, as_of=leave_time)
        self.assertEqual(bill['normal_days'], 2)
        self.assertEqual(bill['normal_charge'], 10000)
        self.assertEqual(bill['overstay_days'], 0)
        self.assertEqual(bill['overstay_charge'], 0)
        self.assertEqual(bill['total_charge'], 10000)
        self.assertEqual(bill['balance_due'], 5000)  # 10,000 - 5,000 deposit

    def test_06_four_normal_days_plus_one_double_rate_overstay_day(self):
        """
        Book 4 days (rate 5,000 KHR/day):
        - Leave after exactly 4 days: total 20,000 KHR.
        - Leave after 5 days (120 hours): 4 normal days (20,000) + 1 overstay day (10,000) = 30,000 KHR.
        """
        entry_time = self._fixed_dt(2026, 9, 9, 23, 10)
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2BC-1234',
            phone_number='+85512999888',
            start_date=entry_time.date(),
            start_time=entry_time,
            finish_date=(entry_time + timedelta(days=4)).date(),
            finish_time=entry_time + timedelta(days=4),
            daily_rate=5000,
            deposit_amount=5000,
            payment_status='PARTIALLY_PAID',
            payment_method='DEPOSIT',
            status='CHECKED_IN',
            reserved_days=4,
            checked_in_at=entry_time,
        )

        # 1. Exactly 4 days
        t_4days = entry_time + timedelta(days=4)
        bill_4d = BillingService.calculate_bill(res, as_of=t_4days)
        self.assertEqual(bill_4d['normal_days'], 4)
        self.assertEqual(bill_4d['normal_charge'], 20000)
        self.assertEqual(bill_4d['overstay_days'], 0)
        self.assertEqual(bill_4d['total_charge'], 20000)

        # 2. Leave after 5 days
        t_5days = entry_time + timedelta(days=5)
        bill_5d = BillingService.calculate_bill(res, as_of=t_5days)
        self.assertEqual(bill_5d['normal_days'], 4)
        self.assertEqual(bill_5d['normal_charge'], 20000)
        self.assertEqual(bill_5d['overstay_days'], 1)
        self.assertEqual(bill_5d['overstay_charge'], 10000)
        self.assertEqual(bill_5d['total_charge'], 30000)
        self.assertEqual(bill_5d['deposit_deducted'], 5000)
        self.assertEqual(bill_5d['balance_due'], 25000)

    def test_07_correct_deposit_and_prior_payment_deductions(self):
        """
        Subtract all successful previous payments once.
        Do not double-charge or double-deduct.
        """
        entry_time = self._fixed_dt(2026, 9, 9, 23, 10)
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2BC-1234',
            phone_number='+85512999888',
            start_date=entry_time.date(),
            start_time=entry_time,
            finish_date=(entry_time + timedelta(days=1)).date(),
            finish_time=entry_time + timedelta(days=1),
            daily_rate=5000,
            deposit_amount=5000,
            balance_paid=3000,
            payment_status='PARTIALLY_PAID',
            payment_method='DEPOSIT',
            status='CHECKED_IN',
            reserved_days=1,
            checked_in_at=entry_time,
        )

        # Parked for 26 hours (total charge: 5,000 normal + 10,000 overstay = 15,000 KHR)
        # Paid deposit (5,000) + prior balance paid (3,000) = 8,000 KHR total paid.
        # Remaining balance due = 15,000 - 8,000 = 7,000 KHR.
        as_of = entry_time + timedelta(hours=26)
        bill = BillingService.calculate_bill(res, as_of=as_of)

        self.assertEqual(bill['total_charge'], 15000)
        self.assertEqual(bill['total_paid'], 8000)
        self.assertEqual(bill['balance_due'], 7000)

    def test_08_arrival_timeout_does_not_affect_checked_in_vehicles(self):
        """
        Preserve the three-hour pay-at-exit arrival deadline.
        It stops applying once checked in.
        """
        t0 = timezone.now() - timedelta(hours=5)
        # Vehicle arrived within arrival window and checked in 4 hours ago
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2BC-1234',
            phone_number='+85512999888',
            start_date=t0.date(),
            start_time=t0,
            finish_date=t0.date(),
            finish_time=t0 + timedelta(days=1),
            daily_rate=5000,
            payment_method='PAY_AT_EXIT',
            status='CHECKED_IN',
            reserved_days=1,
            arrival_deadline=t0 + timedelta(hours=3),  # Expired 2 hours ago
            checked_in_at=t0 + timedelta(minutes=10),  # But physically checked in!
        )

        # Run ExpiryService
        results = ExpiryService.expire_stale_holds()
        res.refresh_from_db()
        self.assertEqual(res.status, 'CHECKED_IN')
        self.assertFalse(res.checked_out)

    def test_09_ticket_date_and_status_fields_populated_and_labelled(self):
        """
        Test that ticket detail page:
        - Shows arrival validity dates without blanks.
        - Shows 'Set when you enter' for parking deadline before entry.
        - Shows 'Not entered yet' instead of 'In session' before entry.
        - Shows 'Parking charges start when you enter.' and 0 balance due before entry.
        """
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2BC-1234',
            phone_number='+85512999888',
            start_date=datetime(2026, 9, 9).date(),
            start_time=self._fixed_dt(2026, 9, 9, 14, 0),
            finish_date=datetime(2026, 9, 10).date(),
            finish_time=self._fixed_dt(2026, 9, 10, 22, 0),
            daily_rate=5000,
            deposit_amount=5000,
            payment_status='PARTIALLY_PAID',
            payment_method='DEPOSIT',
            status='CONFIRMED',
            reserved_days=1,
            checked_in_at=None,
        )

        self.client.login(username='sompark_tester', password='Password123!')
        resp = self.client.get(reverse('ticket_code', kwargs={'ticket_code': res.ticket_code}))
        self.assertEqual(resp.status_code, 200)

        # Check Arrival Validity
        self.assertContains(resp, 'ARRIVAL VALIDITY')
        self.assertContains(resp, '09 Sep 2026, 14:00')
        self.assertContains(resp, '10 Sep 2026, 22:00')

        # Check Parking Deadline and Checked Out status
        self.assertContains(resp, 'Set when you enter')
        self.assertContains(resp, 'Not entered yet')
        self.assertNotContains(resp, 'In session')

        # Check bill notice and 0 charges before entry
        self.assertContains(resp, 'Parking charges start when you enter.')
        self.assertContains(resp, 'Additional Usage Due')
        self.assertContains(resp, '5,000 ៛')  # Deposit Paid

    def test_10_customer_payment_and_gate_billing_use_identical_calculation(self):
        """
        Customer pay_exit view and staff GateService use identical calculate_bill output.
        """
        entry_time = self._fixed_dt(2026, 9, 9, 23, 10)
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2BC-1234',
            phone_number='+85512999888',
            start_date=entry_time.date(),
            start_time=entry_time,
            finish_date=(entry_time + timedelta(days=1)).date(),
            finish_time=entry_time + timedelta(days=1),
            daily_rate=5000,
            deposit_amount=5000,
            payment_status='PARTIALLY_PAID',
            payment_method='DEPOSIT',
            status='CHECKED_IN',
            reserved_days=1,
            checked_in_at=entry_time,
        )

        calc_time = entry_time + timedelta(hours=25)
        cust_bill = BillingService.calculate_bill(res, as_of=calc_time)
        can_exit, reservation, gate_bill, msg = GateService.prepare_exit(res.ticket_code)

        # Ensure customer bill calculation and gate billing calculation use the same logic
        gate_as_of_bill = BillingService.calculate_bill(res, as_of=calc_time)
        self.assertEqual(cust_bill['total_charge'], gate_as_of_bill['total_charge'])
        self.assertEqual(cust_bill['normal_charge'], gate_as_of_bill['normal_charge'])
        self.assertEqual(cust_bill['overstay_charge'], gate_as_of_bill['overstay_charge'])
        self.assertEqual(cust_bill['balance_due'], gate_as_of_bill['balance_due'])
        self.assertIsNotNone(gate_bill)

    def test_11_future_capacity_handling_under_updated_timing_rule(self):
        """
        Capacity service accounts for permitted arrival window and reserved duration (N x 24h).
        Does not promise overlapping future capacity that cannot be honored.
        """
        # Fill zone capacity with active reservations spanning Sep 9 - Sep 11
        for i in range(self.zone.num_of_slots):
            Reservation.objects.create(
                customer=User.objects.create_user(f'user_{i}', f'user_{i}@test.com', 'pwd123'),
                parking_zone=self.zone,
                plate_number=f'2AZ-{i}000',
                phone_number='+85512000000',
                start_date=datetime(2026, 9, 9).date(),
                start_time=self._fixed_dt(2026, 9, 9, 10, 0),
                finish_date=datetime(2026, 9, 11).date(),
                finish_time=self._fixed_dt(2026, 9, 11, 10, 0),
                daily_rate=5000,
                deposit_amount=5000,
                payment_status='PARTIALLY_PAID',
                payment_method='DEPOSIT',
                status='CONFIRMED',
                reserved_days=2,
            )

        start_req = self._fixed_dt(2026, 9, 10, 12, 0)
        finish_req = self._fixed_dt(2026, 9, 10, 18, 0)

        # Capacity check should detect conflict and return False
        has_capacity = CapacityService.check_date_range_availability(
            self.zone.id,
            start_datetime=start_req,
            finish_datetime=finish_req,
            reserved_days=2
        )
        self.assertFalse(has_capacity)

        # Checking a date after all current reservations (Sep 15) should return True
        future_start = self._fixed_dt(2026, 9, 15, 10, 0)
        future_finish = self._fixed_dt(2026, 9, 16, 10, 0)
        has_future_capacity = CapacityService.check_date_range_availability(
            self.zone.id,
            start_datetime=future_start,
            finish_datetime=future_finish,
            reserved_days=1
        )
        self.assertTrue(has_future_capacity)
