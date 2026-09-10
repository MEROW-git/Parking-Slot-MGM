import time
from datetime import timedelta
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import ParkingZone, Reservation, PaymentTransaction
from .payments import DemoPaymentAdapter
from .qr import generate_demo_payment_qr_base64, generate_access_qr_base64
from .services import BillingService, GateService, PaymentService


class PaymentSimulationTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('test-gate-staff', is_staff=True)
        self.customer = User.objects.create_user('test-customer')
        self.other_customer = User.objects.create_user('test-other-customer')
        self.client.force_login(self.staff)

        self.zone = ParkingZone.objects.create(
            name='Test Terminal Zone',
            num_of_slots=5,
            occupied_slots=0,
            vacant_slots=5,
            price=5000,
        )
        self.now = timezone.now()

    def _create_checked_in_reservation(self, payment_method='PAY_AT_EXIT', days=1, deposit_paid=0):
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2B-5555',
            start_date=self.now.date(),
            finish_date=(self.now + timedelta(days=days)).date(),
            start_time=self.now - timedelta(hours=2),
            finish_time=self.now + timedelta(days=days),
            payment_method=payment_method,
            daily_rate=5000,
            deposit_amount=deposit_paid,
            payment_status='PARTIALLY_PAID' if deposit_paid > 0 else 'UNPAID',
            status='CHECKED_IN',
            checked_in_at=self.now - timedelta(hours=2),
        )
        self.zone.occupied_slots += 1
        self.zone.vacant_slots = max(0, self.zone.num_of_slots - self.zone.occupied_slots)
        self.zone.save()
        return res

    # =========================================================================
    # 1. Virtual Exit: Cash and ABA QR Demo Settlements
    # =========================================================================

    def test_virtual_exit_cash_settlement_by_attendant(self):
        """Attendant confirms physical cash money received at exit."""
        res = self._create_checked_in_reservation(payment_method='PAY_AT_EXIT')
        vg_url = reverse('admin_virtual_gate')
        data = {
            'zone': self.zone.pk,
            'code': res.ticket_code,
            'mode': 'exit',
            'action': 'settle',
            'payment_provider': 'CASH',
        }
        resp = self.client.post(vg_url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Cash payment of 5,000 KHR confirmed received by attendant')

        res.refresh_from_db()
        self.assertEqual(res.payment_status, 'PAID')
        self.assertEqual(res.balance_paid, 5000)
        self.assertIsNotNone(res.exit_authorized_until)
        # Occupancy must NOT be released by payment settlement alone
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 1)
        self.assertEqual(res.status, 'CHECKED_IN')

    def test_virtual_exit_aba_qr_demo_success(self):
        """Simulated ABA QR payment success authorizes exit departure window."""
        res = self._create_checked_in_reservation(payment_method='PAY_AT_EXIT')
        vg_url = reverse('admin_virtual_gate')
        data = {
            'zone': self.zone.pk,
            'code': res.ticket_code,
            'mode': 'exit',
            'action': 'settle',
            'payment_provider': 'DEMO',
            'outcome': 'success',
        }
        resp = self.client.post(vg_url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Simulated ABA payment of 5,000 KHR verified')

        res.refresh_from_db()
        self.assertEqual(res.payment_status, 'PAID')
        self.assertEqual(res.balance_paid, 5000)
        self.assertIsNotNone(res.exit_authorized_until)
        txn = res.transactions.filter(purpose='EXIT_BALANCE').first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.status, 'SUCCESS')
        self.assertEqual(txn.provider, 'DEMO')
        self.assertTrue(txn.is_demo)

    def test_virtual_exit_aba_qr_demo_failure(self):
        """Simulated ABA QR payment failure keeps balance unpaid and barrier closed."""
        res = self._create_checked_in_reservation(payment_method='PAY_AT_EXIT')
        vg_url = reverse('admin_virtual_gate')
        data = {
            'zone': self.zone.pk,
            'code': res.ticket_code,
            'mode': 'exit',
            'action': 'settle',
            'payment_provider': 'DEMO',
            'outcome': 'failure',
        }
        resp = self.client.post(vg_url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Simulated ABA payment failed')

        res.refresh_from_db()
        self.assertEqual(res.payment_status, 'UNPAID')
        self.assertEqual(res.balance_paid, 0)
        self.assertIsNone(res.exit_authorized_until)
        self.assertFalse(resp.context['gate_open'])

    def test_virtual_exit_aba_qr_demo_cancellation(self):
        """Simulated ABA QR payment cancellation leaves vehicle checked in and unpaid."""
        res = self._create_checked_in_reservation(payment_method='PAY_AT_EXIT')
        vg_url = reverse('admin_virtual_gate')
        data = {
            'zone': self.zone.pk,
            'code': res.ticket_code,
            'mode': 'exit',
            'action': 'settle',
            'payment_provider': 'DEMO',
            'outcome': 'cancel',
        }
        resp = self.client.post(vg_url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Simulated ABA payment was cancelled')

        res.refresh_from_db()
        self.assertEqual(res.payment_status, 'UNPAID')
        self.assertEqual(res.balance_paid, 0)
        self.assertIsNone(res.exit_authorized_until)

    @override_settings(DEMO_PAYMENT_ENABLED=False)
    def test_virtual_exit_disabled_demo_mode_is_rejected_never_converted_to_cash(self):
        """
        Critical requirement: When DEMO_PAYMENT_ENABLED=False, demo payment attempts
        MUST be rejected with an error, NEVER silently converted into CASH!
        """
        res = self._create_checked_in_reservation(payment_method='PAY_AT_EXIT')
        vg_url = reverse('admin_virtual_gate')
        data = {
            'zone': self.zone.pk,
            'code': res.ticket_code,
            'mode': 'exit',
            'action': 'settle',
            'payment_provider': 'DEMO',
            'outcome': 'success',
        }
        resp = self.client.post(vg_url, data)
        self.assertContains(resp, 'Demo payment simulation is disabled')

        res.refresh_from_db()
        self.assertEqual(res.payment_status, 'UNPAID')
        self.assertEqual(res.balance_paid, 0)
        self.assertEqual(res.transactions.count(), 0)

        # But cash settlement still works when demo is disabled
        cash_resp = self.client.post(vg_url, {**data, 'payment_provider': 'CASH'})
        self.assertEqual(cash_resp.status_code, 200)
        self.assertContains(cash_resp, 'Cash payment of 5,000 KHR confirmed received')
        res.refresh_from_db()
        self.assertEqual(res.payment_status, 'PAID')

    def test_virtual_exit_invalid_payment_method_rejected(self):
        res = self._create_checked_in_reservation(payment_method='PAY_AT_EXIT')
        vg_url = reverse('admin_virtual_gate')
        resp = self.client.post(vg_url, {
            'zone': self.zone.pk,
            'code': res.ticket_code,
            'mode': 'exit',
            'action': 'settle',
            'payment_provider': 'BITCOIN',
        })
        self.assertContains(resp, "Invalid payment method")
        self.assertContains(resp, "Accepted methods are CASH or DEMO")
        res.refresh_from_db()
        self.assertEqual(res.payment_status, 'UNPAID')

    def test_virtual_exit_settle_rejected_for_non_checked_in(self):
        """Settlement cannot be processed on reservations that are not CHECKED_IN."""
        now = timezone.now()
        unconfirmed = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='2B-1111',
            start_date=now.date(),
            finish_date=now.date(),
            start_time=now,
            finish_time=now + timedelta(days=1),
            payment_method='PAY_AT_EXIT',
            status='CONFIRMED',
        )
        vg_url = reverse('admin_virtual_gate')
        resp = self.client.post(vg_url, {
            'zone': self.zone.pk,
            'code': unconfirmed.ticket_code,
            'mode': 'exit',
            'action': 'settle',
            'payment_provider': 'CASH',
        })
        self.assertContains(resp, 'Vehicle must be currently checked in (CHECKED_IN)')

    def test_virtual_exit_settle_rejected_in_entry_mode(self):
        res = self._create_checked_in_reservation()
        vg_url = reverse('admin_virtual_gate')
        resp = self.client.post(vg_url, {
            'zone': self.zone.pk,
            'code': res.ticket_code,
            'mode': 'entry',
            'action': 'settle',
            'payment_provider': 'CASH',
        })
        self.assertContains(resp, 'Payment settlement is only applicable in Exit mode')

    def test_virtual_exit_duplicate_settlement_clicks_idempotent(self):
        """Submitting settlement twice collects only the remaining balance and prevents double billing."""
        res = self._create_checked_in_reservation(payment_method='PAY_AT_EXIT')
        vg_url = reverse('admin_virtual_gate')
        data = {
            'zone': self.zone.pk,
            'code': res.ticket_code,
            'mode': 'exit',
            'action': 'settle',
            'payment_provider': 'CASH',
        }
        # First click
        resp1 = self.client.post(vg_url, data)
        self.assertEqual(resp1.status_code, 200)
        res.refresh_from_db()
        self.assertEqual(res.balance_paid, 5000)

        # Duplicate click
        resp2 = self.client.post(vg_url, data)
        self.assertEqual(resp2.status_code, 200)
        res.refresh_from_db()
        # Balance must remain exactly 5,000 KHR, not 10,000 KHR!
        self.assertEqual(res.balance_paid, 5000)

    def test_virtual_exit_occupancy_preserved_until_passage(self):
        """Payment alone does NOT release space; only vehicle passage releases occupancy."""
        res = self._create_checked_in_reservation(payment_method='PAY_AT_EXIT')
        vg_url = reverse('admin_virtual_gate')
        data = {'zone': self.zone.pk, 'code': res.ticket_code, 'mode': 'exit'}

        # 1. Settle balance
        self.client.post(vg_url, {**data, 'action': 'settle', 'payment_provider': 'CASH'})
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 1)

        # 2. Check ticket & open barrier
        open_resp = self.client.post(vg_url, {**data, 'action': 'open'})
        self.assertTrue(open_resp.context['gate_open'])
        permit = open_resp.context['permit']
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 1)

        # 3. Vehicle passes barrier
        pass_resp = self.client.post(vg_url, {**data, 'action': 'pass', 'permit': permit})
        self.assertTrue(pass_resp.context['passed'])
        self.zone.refresh_from_db()
        res.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 0)
        self.assertEqual(res.status, 'CHECKED_OUT')

    # =========================================================================
    # 2. First-Day Deposit Page: ABA QR Demo and Staff-Only Cash Deposit
    # =========================================================================

    def test_pay_deposit_aba_qr_demo_success(self):
        """Customer simulates ABA QR demo deposit payment successfully."""
        now = timezone.now()
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2AZ-7777',
            start_date=now.date(),
            finish_date=(now + timedelta(days=2)).date(),
            start_time=now + timedelta(hours=1),
            finish_time=now + timedelta(days=2),
            payment_method='DEPOSIT',
            daily_rate=5000,
            status='PAYMENT_PENDING',
            payment_deadline=now + timedelta(minutes=15),
        )
        txn = PaymentService.create_deposit_transaction(res)
        self.client.force_login(self.customer)

        pay_url = reverse('pay_deposit', kwargs={'ticket_code': res.ticket_code})
        resp = self.client.get(pay_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'deposit-demo-qr-card')
        self.assertIsNotNone(resp.context['demo_payment_qr'])

        # Simulate success
        sim_url = reverse('payment_simulate', kwargs={'txn_id': txn.id})
        sim_resp = self.client.post(sim_url, {'outcome': 'success'}, follow=True)
        self.assertEqual(sim_resp.status_code, 200)

        res.refresh_from_db()
        self.assertEqual(res.status, 'CONFIRMED')
        self.assertEqual(res.payment_status, 'PARTIALLY_PAID')
        self.assertEqual(res.deposit_amount, 5000)

    def test_pay_deposit_aba_qr_demo_failure_and_cancellation(self):
        """Simulated failure and cancellation keep reservation in PAYMENT_PENDING."""
        now = timezone.now()
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2AZ-8888',
            start_date=now.date(),
            finish_date=(now + timedelta(days=2)).date(),
            start_time=now + timedelta(hours=1),
            finish_time=now + timedelta(days=2),
            payment_method='DEPOSIT',
            daily_rate=5000,
            status='PAYMENT_PENDING',
            payment_deadline=now + timedelta(minutes=15),
        )
        txn = PaymentService.create_deposit_transaction(res)
        self.client.force_login(self.customer)

        sim_url = reverse('payment_simulate', kwargs={'txn_id': txn.id})

        # Failure
        resp_fail = self.client.post(sim_url, {'outcome': 'failure'}, follow=True)
        self.assertEqual(resp_fail.status_code, 200)
        res.refresh_from_db()
        self.assertEqual(res.status, 'PAYMENT_PENDING')
        self.assertEqual(res.deposit_amount, 0)

        # Cancel
        resp_cancel = self.client.post(sim_url, {'outcome': 'cancel'}, follow=True)
        self.assertEqual(resp_cancel.status_code, 200)
        res.refresh_from_db()
        self.assertEqual(res.status, 'PAYMENT_PENDING')
        self.assertEqual(res.deposit_amount, 0)

    def test_pay_deposit_customer_cannot_self_confirm_cash(self):
        """Customer attempting to self-confirm cash deposit must be denied (HTTP 403)."""
        now = timezone.now()
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2AZ-9999',
            start_date=now.date(),
            finish_date=(now + timedelta(days=2)).date(),
            start_time=now + timedelta(hours=1),
            finish_time=now + timedelta(days=2),
            payment_method='DEPOSIT',
            daily_rate=5000,
            status='PAYMENT_PENDING',
            payment_deadline=now + timedelta(minutes=15),
        )
        self.client.force_login(self.customer)
        pay_url = reverse('pay_deposit', kwargs={'ticket_code': res.ticket_code})

        # Non-staff customer view must not render staff confirmation button
        get_resp = self.client.get(pay_url)
        self.assertNotContains(get_resp, 'btn-staff-confirm-cash')
        self.assertContains(get_resp, 'Customer online self-confirmation is not permitted')

        # Customer attempts POST to confirm cash
        post_resp = self.client.post(pay_url, {'action': 'staff_confirm_cash'})
        self.assertEqual(post_resp.status_code, 403)
        res.refresh_from_db()
        self.assertEqual(res.status, 'PAYMENT_PENDING')
        self.assertEqual(res.deposit_amount, 0)

    def test_pay_deposit_staff_confirms_cash_deposit(self):
        """Staff member can verify and confirm cash deposit in person."""
        now = timezone.now()
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2AZ-1010',
            start_date=now.date(),
            finish_date=(now + timedelta(days=2)).date(),
            start_time=now + timedelta(hours=1),
            finish_time=now + timedelta(days=2),
            payment_method='DEPOSIT',
            daily_rate=5000,
            status='PAYMENT_PENDING',
            payment_deadline=now + timedelta(minutes=15),
        )
        self.client.force_login(self.staff)
        pay_url = reverse('pay_deposit', kwargs={'ticket_code': res.ticket_code})

        get_resp = self.client.get(pay_url)
        self.assertContains(get_resp, 'btn-staff-confirm-cash')

        post_resp = self.client.post(pay_url, {'action': 'staff_confirm_cash'}, follow=True)
        self.assertEqual(post_resp.status_code, 200)

        res.refresh_from_db()
        self.assertEqual(res.status, 'CONFIRMED')
        self.assertEqual(res.payment_status, 'PARTIALLY_PAID')
        self.assertEqual(res.deposit_amount, 5000)
        self.assertIsNone(res.payment_deadline)

    # =========================================================================
    # 3. QR Code Separation & Non-Transfer Safety
    # =========================================================================

    def test_qr_code_separation_and_payload_isolation(self):
        """
        Verify payment QR is strictly separated from parking access QR.
        Demo payment QR payload uses 'sompark:payment:demo:...' and cannot
        be used as an access token or banking transfer payload.
        """
        access_qr = generate_access_qr_base64('SPK-DEMO-1234')
        payment_qr = generate_demo_payment_qr_base64('REF-999', 5000, 'KHR')

        self.assertTrue(access_qr.startswith('data:image/png;base64,'))
        self.assertTrue(payment_qr.startswith('data:image/png;base64,'))

        # Gate service cannot admit with demo payment QR payload
        allowed, _, msg = GateService.validate_entry('sompark:payment:demo:REF-999:5000:KHR', self.zone.pk)
        self.assertFalse(allowed)

    # =========================================================================
    # 4. End-to-End Accounting: Deposit Pays 1 Day, Exit Collects Remaining
    # =========================================================================

    def test_deposit_pays_one_day_exit_collects_only_remaining_balance(self):
        """
        Booking with DEPOSIT:
        1. 5,000 KHR deposit pays exactly 1 day.
        2. Vehicle stays 3 days -> Total bill = 15,000 KHR.
        3. Balance due at exit = 15,000 - 5,000 = 10,000 KHR.
        4. Exit payment settles only the remaining 10,000 KHR.
        """
        res = self._create_checked_in_reservation(payment_method='DEPOSIT', days=3, deposit_paid=5000)
        # Fast-forward virtual clock by simulating entry 3 days ago
        res.checked_in_at = self.now - timedelta(days=2, hours=23)
        res.save()

        bill = BillingService.calculate_bill(res, as_of=self.now)
        self.assertEqual(bill['normal_charge'], 15000)
        self.assertEqual(bill['deposit_paid'], 5000)
        self.assertEqual(bill['balance_due'], 10000)

        vg_url = reverse('admin_virtual_gate')
        resp = self.client.post(vg_url, {
            'zone': self.zone.pk,
            'code': res.ticket_code,
            'mode': 'exit',
            'action': 'settle',
            'payment_provider': 'DEMO',
            'outcome': 'success',
        })
        self.assertEqual(resp.status_code, 200)

        res.refresh_from_db()
        self.assertEqual(res.balance_paid, 10000)
        self.assertEqual(res.payment_status, 'PAID')

        post_bill = BillingService.calculate_bill(res, as_of=self.now)
        self.assertEqual(post_bill['balance_due'], 0)

    # =========================================================================
    # 5. Virtual Gate Animation Elements Preserved
    # =========================================================================

    def test_virtual_gate_animation_elements_preserved(self):
        """Ensure all scene, arm, road, and status animation elements remain intact."""
        vg_url = reverse('admin_virtual_gate')
        resp = self.client.get(vg_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()

        self.assertIn('vg-scene', content)
        self.assertIn('vg-barrier-arm', content)
        self.assertIn('vg-vehicle-object', content)
        self.assertIn('vg-beacon-light', content)
        self.assertIn('vg-gate-status-banner', content)
        self.assertIn('vg-road', content)
