import zoneinfo
from datetime import datetime, timedelta
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from parking_zones.models import ParkingZone, Reservation, PaymentTransaction
from parking_zones.services import BillingService, PaymentService, GateService
from parking_zones.payments import DemoPaymentAdapter


class PayExitSimplificationTests(TestCase):
    def setUp(self):
        self.zone = ParkingZone.objects.create(
            name='Central Park Zone A',
            slug='central-park-zone-a',
            num_of_slots=20,
            occupied_slots=5,
            vacant_slots=15,
            price=4000,
            address='Phnom Penh City Center',
            district='Daun Penh',
        )
        self.owner = User.objects.create_user(
            username='exit_customer',
            email='customer@sompark.test',
            password='testpassword123'
        )
        self.other_user = User.objects.create_user(
            username='other_customer',
            email='other@sompark.test',
            password='testpassword123'
        )
        self.staff_user = User.objects.create_user(
            username='gate_officer',
            email='officer@sompark.test',
            password='testpassword123',
            is_staff=True
        )

    def _create_checked_in_reservation(self, hours_ago=5, booked_hours=24, daily_rate=4000, balance_paid=0, reserved_days=1):
        t0 = timezone.now() - timedelta(hours=hours_ago)
        booked_end = t0 + timedelta(hours=booked_hours)
        return Reservation.objects.create(
            customer=self.owner,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2AZ-9988',
            phone_number='+85512345678',
            start_date=t0.date(),
            start_time=t0,
            finish_date=booked_end.date(),
            finish_time=booked_end,
            daily_rate=daily_rate,
            balance_paid=balance_paid,
            payment_status='PAID' if balance_paid > 0 else 'UNPAID',
            payment_method='PAY_AT_EXIT',
            status='CHECKED_IN',
            checked_in_at=t0,
            reserved_days=reserved_days,
        )

    def test_get_creates_and_cancels_no_payment_records(self):
        """Rule 5: GET renders review only. It must NOT create or cancel payment transactions."""
        res = self._create_checked_in_reservation(hours_ago=5, booked_hours=24)
        self.client.login(username='exit_customer', password='testpassword123')

        # Baseline: zero transactions
        self.assertEqual(PaymentTransaction.objects.filter(reservation=res).count(), 0)

        # GET request
        resp = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        self.assertEqual(resp.status_code, 200)

        # Still zero transactions after GET
        self.assertEqual(PaymentTransaction.objects.filter(reservation=res).count(), 0)

        # Multiple repeated GET requests (refreshing page) must not create transactions
        self.client.get(reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        self.client.get(reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        self.assertEqual(PaymentTransaction.objects.filter(reservation=res).count(), 0)

        # If a pending transaction existed, GET must not cancel it
        txn = PaymentService.create_exit_transaction(res, amount=4000)
        self.assertEqual(txn.status, 'PENDING')
        self.client.get(reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        txn.refresh_from_db()
        self.assertEqual(txn.status, 'PENDING')

    def test_ownership_and_reservation_state_restrictions(self):
        """Only authenticated reservation owner of a CHECKED_IN reservation can view/pay."""
        res = self._create_checked_in_reservation()

        # Anonymous user redirected to login
        resp_anon = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        self.assertEqual(resp_anon.status_code, 302)
        self.assertIn('/login/', resp_anon.url)

        # Non-owner gets 403 Forbidden
        self.client.login(username='other_customer', password='testpassword123')
        resp_other = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        self.assertEqual(resp_other.status_code, 403)

        # Non-owner cannot POST payment (403 Forbidden)
        resp_other_post = self.client.post(
            reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}),
            data={'action': 'pay'}
        )
        self.assertEqual(resp_other_post.status_code, 403)

        # Reservation states other than CHECKED_IN
        self.client.login(username='exit_customer', password='testpassword123')

        # CONFIRMED (not checked in yet) -> redirects to ticket
        res.status = 'CONFIRMED'
        res.save(update_fields=['status'])
        resp_conf = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        self.assertRedirects(resp_conf, reverse('ticket_code', kwargs={'ticket_code': res.ticket_code}))

        # CHECKED_OUT -> redirects to ticket
        res.status = 'CHECKED_OUT'
        res.checked_out = True
        res.save(update_fields=['status', 'checked_out'])
        resp_out = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        self.assertRedirects(resp_out, reverse('ticket_code', kwargs={'ticket_code': res.ticket_code}))

        # CANCELLED -> redirects to dashboard
        res.status = 'CANCELLED'
        res.checked_out = False
        res.save(update_fields=['status', 'checked_out'])
        resp_canc = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        self.assertRedirects(resp_canc, reverse('dashboard'))

    def test_duplicate_payment_submissions_and_idempotency(self):
        """Prevent duplicate payable attempts and handle duplicate confirmation safely."""
        res = self._create_checked_in_reservation(hours_ago=2, booked_hours=24)
        self.client.login(username='exit_customer', password='testpassword123')

        # First payment POST: completes successfully
        resp1 = self.client.post(
            reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}),
            data={'action': 'pay'}
        )
        self.assertRedirects(resp1, reverse('ticket_code', kwargs={'ticket_code': res.ticket_code}))

        res.refresh_from_db()
        self.assertEqual(res.payment_status, 'PAID')
        self.assertEqual(res.balance_paid, 4000)
        self.assertIsNotNone(res.exit_authorized_until)

        # Success transaction exists
        txns = res.transactions.filter(purpose='EXIT_BALANCE', status='SUCCESS')
        self.assertEqual(txns.count(), 1)
        first_txn = txns.first()

        # Re-confirming same transaction is idempotent and does not double credit
        success, msg = PaymentService.confirm_exit_payment(first_txn.id)
        self.assertTrue(success)
        self.assertIn('already verified', msg)
        res.refresh_from_db()
        self.assertEqual(res.balance_paid, 4000)

    def test_success_failure_cancellation_races(self):
        """A completed payment transaction cannot be overwritten by failure or cancellation."""
        res = self._create_checked_in_reservation(hours_ago=2, booked_hours=24)
        txn = PaymentService.create_exit_transaction(res, amount=4000)

        # Confirm payment via simulate_payment
        DemoPaymentAdapter.simulate_payment(txn.id, outcome='success')
        txn.refresh_from_db()
        self.assertEqual(txn.status, 'SUCCESS')

        # Attempt to fail the completed payment (must be ignored, status stays SUCCESS)
        DemoPaymentAdapter.simulate_payment(txn.id, outcome='failure')
        txn.refresh_from_db()
        self.assertEqual(txn.status, 'SUCCESS')

        # Attempt to cancel the completed payment (must be ignored, status stays SUCCESS)
        DemoPaymentAdapter.simulate_payment(txn.id, outcome='cancel')
        txn.refresh_from_db()
        self.assertEqual(txn.status, 'SUCCESS')

    def test_cancellation_returns_to_ticket_and_preserves_checked_in_status(self):
        """Rule 8: Cancelling exit payment returns to ticket, vehicle remains checked in, and copy clarifies."""
        res = self._create_checked_in_reservation(hours_ago=3, booked_hours=24)
        self.client.login(username='exit_customer', password='testpassword123')

        resp_cancel = self.client.post(
            reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}),
            data={'action': 'cancel_payment'}
        )
        self.assertRedirects(resp_cancel, reverse('ticket_code', kwargs={'ticket_code': res.ticket_code}))

        res.refresh_from_db()
        self.assertEqual(res.status, 'CHECKED_IN')
        self.assertFalse(res.checked_out)

        # Check transaction cancelled with correct message
        cancelled_txn = res.transactions.filter(purpose='EXIT_BALANCE', status='CANCELLED').first()
        self.assertIsNotNone(cancelled_txn)

    def test_partial_payment_messaging(self):
        """Partial payment message states 'Payment received; balance remains', not 'Payment failed'."""
        res = self._create_checked_in_reservation(hours_ago=26, booked_hours=24, daily_rate=4000, reserved_days=1)
        # Total charge is 12,000 KHR (4,000 normal + 8,000 overstay for 26h stay on 1-day booking)
        # Create a partial transaction of 6,000 KHR
        txn = PaymentService.create_exit_transaction(res, amount=6000)

        success, msg = PaymentService.confirm_exit_payment(txn.id)
        self.assertTrue(success)
        self.assertIn('Payment received; balance remains', msg)
        self.assertNotIn('Payment failed', msg)

        res.refresh_from_db()
        self.assertEqual(res.payment_status, 'PARTIALLY_PAID')
        self.assertEqual(res.balance_paid, 6000)

    def test_active_exit_window_handling_across_billing_boundary(self):
        """
        Rule 6: During a valid paid exit window, visiting pay_exit redirects to ticket
        and honors the settled bill even if a billing boundary passed.
        """
        res = self._create_checked_in_reservation(hours_ago=23, booked_hours=24)
        # Settle full bill
        res.balance_paid = 4000
        res.payment_status = 'PAID'
        res.exit_authorized_until = timezone.now() + timedelta(minutes=5)
        res.save()

        self.client.login(username='exit_customer', password='testpassword123')

        # Visit pay_exit while exit window is active
        resp = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        self.assertRedirects(resp, reverse('ticket_code', kwargs={'ticket_code': res.ticket_code}))

    def test_renew_exit_authorization_does_not_extend_active_window(self):
        """Rule 7: Repeated clicks/refreshes must NOT extend an already active exit deadline."""
        t_deadline = timezone.now() + timedelta(minutes=5)
        res = self._create_checked_in_reservation(hours_ago=5, booked_hours=24)
        res.balance_paid = 4000
        res.payment_status = 'PAID'
        res.exit_authorized_until = t_deadline
        res.save()

        self.client.login(username='exit_customer', password='testpassword123')

        # Attempt to renew while window is active
        resp = self.client.post(reverse('renew_exit_authorization', kwargs={'ticket_code': res.ticket_code}))
        self.assertRedirects(resp, reverse('ticket_code', kwargs={'ticket_code': res.ticket_code}))

        res.refresh_from_db()
        # Deadline must NOT be extended!
        self.assertEqual(res.exit_authorized_until, t_deadline)

    def test_expired_window_with_and_without_additional_charges(self):
        """
        Expired window handling:
        - If balance_due == 0: renewal succeeds and issues new window.
        - If balance_due > 0: renewal redirects to pay_exit to pay outstanding balance.
        """
        expired_time = timezone.now() - timedelta(minutes=2)
        res = self._create_checked_in_reservation(hours_ago=5, booked_hours=24)
        res.balance_paid = 4000
        res.payment_status = 'PAID'
        res.exit_authorized_until = expired_time
        res.save()

        self.client.login(username='exit_customer', password='testpassword123')

        # Case A: Balance due == 0, renewal issues fresh window
        resp = self.client.post(reverse('renew_exit_authorization', kwargs={'ticket_code': res.ticket_code}))
        self.assertRedirects(resp, reverse('ticket_code', kwargs={'ticket_code': res.ticket_code}))
        res.refresh_from_db()
        self.assertGreater(res.exit_authorized_until, timezone.now())

        # Case B: Expired window with overstay balance
        # Entry was 3 days ago, paid only 4000 KHR
        t_3days = timezone.now() - timedelta(days=3)
        res.checked_in_at = t_3days
        res.start_time = t_3days
        res.finish_time = t_3days + timedelta(days=1)
        res.exit_authorized_until = expired_time
        res.save()

        resp_overstay = self.client.post(reverse('renew_exit_authorization', kwargs={'ticket_code': res.ticket_code}))
        self.assertRedirects(resp_overstay, reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))

    def test_payment_does_not_release_capacity_passage_releases_it_once(self):
        """Exit payment does not release spot. Actual physical gate passage releases it once."""
        initial_occupied = self.zone.occupied_slots
        res = self._create_checked_in_reservation(hours_ago=3, booked_hours=24)

        self.client.login(username='exit_customer', password='testpassword123')

        # POST pay_exit payment
        self.client.post(
            reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}),
            data={'action': 'pay'}
        )

        res.refresh_from_db()
        self.zone.refresh_from_db()
        self.assertEqual(res.status, 'CHECKED_IN')
        self.assertFalse(res.checked_out)
        self.assertEqual(self.zone.occupied_slots, initial_occupied)

        # Gate passage confirmation: releases slot
        success1, r1, msg1 = GateService.confirm_physical_exit(res.id, staff_user=self.staff_user)
        self.assertTrue(success1)
        self.assertEqual(r1.status, 'CHECKED_OUT')
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, initial_occupied - 1)

        # Second passage attempt: idempotent, slot not decremented again
        success2, r2, msg2 = GateService.confirm_physical_exit(res.id, staff_user=self.staff_user)
        self.assertTrue(success2)
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, initial_occupied - 1)

    def test_screenshot_overstay_12000_khr_calculation_and_ui_labels(self):
        """
        Billing explanation and verification of the 12,000 KHR scenario:
        - 4,000 KHR daily rate.
        - Parked for 26 hours, booked for 1 day (24 hours).
        - 1 minimum normal day = 4,000 KHR.
        - Overstayed by 2 hours past 24h = 1 started extra day @ 2x rate = 8,000 KHR.
        - Total = 12,000 KHR.
        - UI shows parking charge, overstay, already paid, and amount to pay.
        - UI details show actual duration vs billable units.
        """
        res = self._create_checked_in_reservation(hours_ago=26, booked_hours=24, daily_rate=4000, reserved_days=1)

        bill = BillingService.calculate_bill(res, as_of=timezone.now())
        self.assertEqual(bill['normal_charge'], 4000)
        self.assertEqual(bill['overstay_charge'], 8000)
        self.assertEqual(bill['total_charge'], 12000)
        self.assertEqual(bill['balance_paid'], 0)
        self.assertEqual(bill['balance_due'], 12000)
        self.assertEqual(bill['overstay_days'], 1)

        self.client.login(username='exit_customer', password='testpassword123')
        resp = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        self.assertEqual(resp.status_code, 200)

        # Check content order and labels
        self.assertContains(resp, 'Back to ticket')
        self.assertContains(resp, 'Pay before you leave')
        self.assertContains(resp, 'Central Park Zone A')
        self.assertContains(resp, 'Phnom Penh 2AZ-9988')
        self.assertContains(resp, '12,000 ៛')
        self.assertContains(resp, 'Parking charge')
        self.assertContains(resp, '4,000 ៛')
        self.assertContains(resp, 'Overstay &mdash; 1 started extra day')
        self.assertContains(resp, '8,000 ៛')
        self.assertContains(resp, 'Already paid')
        self.assertContains(resp, '0 &#x17DB;')
        self.assertContains(resp, 'Pay 12,000 ៛ &mdash; Demo')
        self.assertContains(resp, 'No real money will be charged.')

        # Collapsible details
        self.assertContains(resp, 'View parking times and charge details')
        self.assertContains(resp, 'Developer test controls')
        self.assertContains(resp, 'Calculated at')
        self.assertContains(resp, 'Parked for')
        self.assertContains(resp, 'Overstay duration')

        # Ensure no accounting jargon
        self.assertNotContains(resp, 'Total Gross Charges')
        self.assertNotContains(resp, 'Net Balance Due')

        # Ensure no lightning or decorative emoji
        self.assertNotContains(resp, '⚡')
        self.assertNotContains(resp, '🚗')

    @override_settings(DEMO_PAYMENT_ENABLED=False)
    def test_demo_mode_disabled_shows_staff_instructions(self):
        """When demo mode is disabled and no real provider exists, inform customer to pay staff."""
        res = self._create_checked_in_reservation(hours_ago=2, booked_hours=24)
        self.client.login(username='exit_customer', password='testpassword123')

        resp = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Online payment unavailable')
        self.assertContains(resp, 'Please settle your balance of 4,000 ៛ with staff at the barrier gate.')

        # Submitting POST payment is rejected with clear notice
        resp_post = self.client.post(
            reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}),
            data={'action': 'pay'}
        )
        self.assertRedirects(resp_post, reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
