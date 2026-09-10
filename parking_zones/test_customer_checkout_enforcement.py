import datetime
from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User
from parking_zones.models import ParkingZone, Reservation, PaymentTransaction
from parking_zones.services import GateService, BillingService


class CustomerCheckoutEnforcementTests(TestCase):
    """
    Tests enforcing that customer-facing checkout actions cannot mark
    physical departure or release capacity. Only physical gate confirmation
    via GateService.confirm_physical_exit can do so.
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='customer_dara', password='testpassword123')
        self.other_user = User.objects.create_user(username='customer_sokha', password='testpassword123')
        self.staff_user = User.objects.create_user(username='staff_sovann', password='testpassword123', is_staff=True)

        self.zone = ParkingZone.objects.create(
            name='Wat Phnom Riverside Slot',
            khmer_name='ចំណតវត្តភ្នំ',
            slug='wat-phnom-riverside-test',
            num_of_slots=5,
            occupied_slots=1,
            vacant_slots=4,
            address='Street 94, Daun Penh, Phnom Penh',
            price=3000,
        )

        self.now = timezone.now()
        self.today = self.now.date()

        # Reservation actively checked in, deposit paid for 1 day
        self.reservation = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='2AZ-1111',
            phone_number='012345678',
            start_date=self.today,
            finish_date=self.today,
            ticket_code='SPK-ENFORCE-1',
            status='CHECKED_IN',
            deposit_amount=3000,
            payment_status='PAID',
            checked_in_at=self.now - timedelta(hours=1),
            checked_out=False,
            checked_out_at=None,
        )

    def test_direct_customer_checkout_cannot_complete_departure_when_paid_and_authorized(self):
        """
        A paid, exit-authorized customer POSTing to /checkout/ must NOT mark physical
        departure or decrement occupied_slots. It must redirect to the exit QR pass.
        """
        self.reservation.exit_authorized_until = self.now + timedelta(minutes=5)
        self.reservation.save(update_fields=['exit_authorized_until'])

        self.client.login(username='customer_dara', password='testpassword123')
        response = self.client.post(reverse('checkout'), {'ticket_code': self.reservation.ticket_code})

        # Must redirect to fullscreen exit QR mode
        expected_url = f"{reverse('ticket_gate_mode', kwargs={'ticket_code': self.reservation.ticket_code})}?mode=exit"
        self.assertRedirects(response, expected_url)

        # Ensure database record is still CHECKED_IN and NOT checked out
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, 'CHECKED_IN')
        self.assertFalse(self.reservation.checked_out)
        self.assertIsNone(self.reservation.checked_out_at)

        # Capacity remains occupied
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 1)
        self.assertEqual(self.zone.vacant_slots, 4)

    def test_gate_passage_completes_checkout_and_releases_capacity_once(self):
        """
        Only confirmed vehicle passage at the virtual gate triggers physical departure
        and releases capacity. Re-running confirmation must be idempotent.
        """
        self.reservation.exit_authorized_until = self.now + timedelta(minutes=5)
        self.reservation.save(update_fields=['exit_authorized_until'])

        # Passage at gate barrier
        success, res_updated, msg = GateService.confirm_physical_exit(self.reservation.pk, staff_user=self.staff_user)
        self.assertTrue(success)
        self.assertEqual(res_updated.status, 'CHECKED_OUT')
        self.assertTrue(res_updated.checked_out)
        self.assertIsNotNone(res_updated.checked_out_at)

        # Zone capacity decremented
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 0)
        self.assertEqual(self.zone.vacant_slots, 5)

        # Re-confirming departure (double scan) is idempotent and must not decrement capacity again
        success_second, _, msg_second = GateService.confirm_physical_exit(self.reservation.pk, staff_user=self.staff_user)
        self.assertTrue(success_second)
        self.assertEqual(msg_second, 'Reservation already checked out.')
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 0)
        self.assertEqual(self.zone.vacant_slots, 5)

    def test_unpaid_customer_cannot_bypass_payment_via_checkout(self):
        """
        A customer with an outstanding balance cannot bypass payment via /checkout/.
        They must be redirected to pay_exit, remaining CHECKED_IN.
        """
        # Create an overstay: checked in 26 hours ago on a 1-day reservation
        self.reservation.checked_in_at = self.now - timedelta(hours=26)
        self.reservation.exit_authorized_until = None
        self.reservation.save(update_fields=['checked_in_at', 'exit_authorized_until'])

        bill = BillingService.calculate_bill(self.reservation, as_of=self.now)
        self.assertGreater(bill['balance_due'], 0)

        self.client.login(username='customer_dara', password='testpassword123')
        response = self.client.post(reverse('checkout'), {'ticket_code': self.reservation.ticket_code})

        expected_url = reverse('pay_exit', kwargs={'ticket_code': self.reservation.ticket_code})
        self.assertRedirects(response, expected_url)

        # Verify not exited and space not released
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, 'CHECKED_IN')
        self.assertFalse(self.reservation.checked_out)
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 1)

    def test_expired_exit_authorization_routing(self):
        """
        If exit window expired, checkout redirects to pay_exit if balance > 0,
        or ticket_code with renewal prompt if balance == 0.
        """
        # Expired authorization with 0 balance
        self.reservation.exit_authorized_until = self.now - timedelta(minutes=2)
        self.reservation.save(update_fields=['exit_authorized_until'])

        self.client.login(username='customer_dara', password='testpassword123')
        response = self.client.post(reverse('checkout'), {'ticket_code': self.reservation.ticket_code})

        expected_url = reverse('ticket_code', kwargs={'ticket_code': self.reservation.ticket_code})
        self.assertRedirects(response, expected_url)

        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, 'CHECKED_IN')
        self.assertFalse(self.reservation.checked_out)

    def test_customer_ticket_page_renders_only_safe_controls_after_payment(self):
        """
        After payment (when is_exit_authorized is True):
        - Show exit QR (#btn-show-exit-qr) is displayed
        - Print ticket (#btn-print-ticket) is displayed
        - Exit countdown banner (#exit-countdown-card) is displayed
        - 'Proceed to exit' button and form are completely absent
        """
        self.reservation.exit_authorized_until = self.now + timedelta(minutes=5)
        self.reservation.save(update_fields=['exit_authorized_until'])

        self.client.login(username='customer_dara', password='testpassword123')
        response = self.client.get(reverse('ticket_code', kwargs={'ticket_code': self.reservation.ticket_code}))
        self.assertEqual(response.status_code, 200)

        # Must have safe exit controls
        self.assertContains(response, 'id="btn-show-exit-qr"')
        self.assertContains(response, 'Show exit QR (បង្ហាញ QR ចេញ)')
        self.assertContains(response, 'id="btn-print-ticket"')
        self.assertContains(response, 'id="exit-countdown-card"')
        self.assertContains(response, 'Payment verified')

        # Must NOT have redundant or dangerous departure controls
        self.assertNotContains(response, 'Proceed to exit')
        self.assertNotContains(response, 'ចេញពីចំណត')
        self.assertNotContains(response, 'id="btn-checkout-ticket"')
        self.assertNotContains(response, 'id="form-ticket-checkout"')

    def test_checkout_security_ownership_and_state_checks(self):
        """
        Non-owners cannot trigger checkout (403 Forbidden).
        Un-checked-in reservations cannot be checked out.
        """
        # Non-owner test
        self.client.login(username='customer_sokha', password='testpassword123')
        response = self.client.post(reverse('checkout'), {'ticket_code': self.reservation.ticket_code})
        self.assertEqual(response.status_code, 403)

        # State check: CONFIRMED reservation cannot checkout
        self.client.login(username='customer_dara', password='testpassword123')
        confirmed_res = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='2AZ-2222',
            phone_number='012345678',
            start_date=self.today,
            finish_date=self.today,
            ticket_code='SPK-ENFORCE-CONF',
            status='CONFIRMED',
            deposit_amount=3000,
            checked_out=False,
            checked_out_at=None,
        )
        resp_conf = self.client.post(reverse('checkout'), {'ticket_code': confirmed_res.ticket_code})
        self.assertRedirects(resp_conf, reverse('ticket_code', kwargs={'ticket_code': confirmed_res.ticket_code}))
        confirmed_res.refresh_from_db()
        self.assertEqual(confirmed_res.status, 'CONFIRMED')
        self.assertFalse(confirmed_res.checked_out)
