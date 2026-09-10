from datetime import timedelta

from django.contrib.auth.models import User
from django.core import signing
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import ParkingZone, Reservation, PaymentTransaction
from .services import GateService


class GateExitRenewalTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('renewal-staff', is_staff=True)
        self.client.force_login(self.staff)
        self.zone = ParkingZone.objects.create(name='Renewal test', num_of_slots=3, occupied_slots=1, price=4000)
        now = timezone.now()
        self.ticket = Reservation.objects.create(
            customer=self.staff, parking_zone=self.zone, plate_number='2AR-2154',
            start_date=now.date(), finish_date=now.date(), payment_method='PAY_AT_EXIT',
            status='CHECKED_IN', checked_in_at=now - timedelta(hours=1),
            daily_rate=4000, balance_paid=4000, payment_status='PAID',
            exit_authorized_until=now - timedelta(minutes=1),
        )
        self.original_deadline = self.ticket.exit_authorized_until
        self.url = reverse('admin_virtual_gate')
        self.data = dict(zone=self.zone.pk, code=self.ticket.ticket_code, mode='exit', action='open')

    def post(self, **changes):
        return self.client.post(self.url, {**self.data, **changes}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_paid_expired_exit_opens_then_waits_for_explicit_passage(self):
        opened = self.post().json()
        self.assertTrue(opened['gate_open'])
        self.assertTrue(opened['permit'])
        self.ticket.refresh_from_db()
        self.zone.refresh_from_db()
        self.assertGreater(self.ticket.exit_authorized_until, timezone.now())
        self.assertEqual(self.ticket.status, 'CHECKED_IN')
        self.assertIsNone(self.ticket.checked_out_at)
        self.assertEqual(self.zone.occupied_slots, 1)
        self.assertEqual(self.ticket.balance_paid, 4000)
        self.assertFalse(PaymentTransaction.objects.exists())
        # Reopening with an active window must not extend it indefinitely.
        deadline = self.ticket.exit_authorized_until
        self.post()
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.exit_authorized_until, deadline)
        passed = self.post(action='pass', permit=opened['permit']).json()
        self.assertTrue(passed['passed'])
        self.assertFalse(passed['gate_open'])
        self.post(action='pass', permit=opened['permit'])
        self.ticket.refresh_from_db()
        self.zone.refresh_from_db()
        self.assertEqual(self.ticket.status, 'CHECKED_OUT')
        self.assertEqual(self.zone.occupied_slots, 0)

    def test_zero_balance_settle_renews_without_another_payment(self):
        result = self.post(action='settle', payment_provider='CASH').json()
        self.assertTrue(result['settled'])
        self.assertTrue(result['gate_open'])
        self.assertFalse(PaymentTransaction.objects.exists())

    def test_new_charges_block_renewal(self):
        Reservation.objects.filter(pk=self.ticket.pk).update(checked_in_at=timezone.now() - timedelta(days=2))
        response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['gate_open'])
        self.assertGreater(response.json()['balance_due'], 0)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.exit_authorized_until, self.original_deadline)

    def test_mismatch_cannot_renew(self):
        response = self.post(simulate_plate_mismatch='true', custom_detected_plate='2X-9999')
        self.assertFalse(response.json()['gate_open'])
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.exit_authorized_until, self.original_deadline)

    def test_pass_and_read_only_checks_do_not_renew_expired_authorization(self):
        allowed, _, _, _ = GateService.prepare_exit(self.ticket.ticket_code, self.zone.pk)
        self.assertFalse(allowed)
        permit = signing.dumps([self.staff.pk, self.ticket.pk, self.zone.pk, 'exit'], salt='virtual-gate')
        self.assertFalse(self.post(action='pass', permit=permit).json()['passed'])
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.exit_authorized_until, self.original_deadline)
        self.assertIsNone(self.ticket.checked_out_at)

    def test_wrong_facility_and_customer_rejected(self):
        other = ParkingZone.objects.create(name='Other facility')
        self.assertEqual(self.post(zone=other.pk).status_code, 400)
        customer = User.objects.create_user('renewal-customer')
        self.client.force_login(customer)
        self.assertEqual(self.post().status_code, 302)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.exit_authorized_until, self.original_deadline)

    def test_closed_without_passage_keeps_vehicle_parked(self):
        self.post()
        result = self.post(action='close').json()
        self.assertFalse(result['gate_open'])
        self.ticket.refresh_from_db()
        self.zone.refresh_from_db()
        self.assertEqual(self.ticket.status, 'CHECKED_IN')
        self.assertEqual(self.zone.occupied_slots, 1)

    def test_closed_step_does_not_claim_vehicle_is_waiting_at_open_gate(self):
        response = self.client.post(self.url, {**self.data, 'action': 'close'})
        self.assertContains(response, 'Barrier closed &middot; Open to continue')
        self.assertContains(response, 'Exit passage')
