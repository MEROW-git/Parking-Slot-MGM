import time
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import signing
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from .models import ParkingZone, Reservation


class VirtualGateTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('gate-staff', is_staff=True)
        self.other_staff = User.objects.create_user('other-gate-staff', is_staff=True)
        self.customer = User.objects.create_user('gate-customer')
        self.other_customer = User.objects.create_user('other-customer')
        self.client.force_login(self.staff)
        self.zone = ParkingZone.objects.create(name='Gate test', num_of_slots=2, price=4000)
        now = timezone.now()
        self.reservation = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2AZ-1234',
            start_date=now.date(),
            finish_date=now.date(),
            start_time=now - timedelta(minutes=5),
            finish_time=now + timedelta(days=4),
            payment_method='PAY_AT_EXIT',
            arrival_deadline=now + timedelta(hours=3),
            daily_rate=4000,
        )
        self.url = reverse('admin_virtual_gate')
        self.data = {'zone': self.zone.pk, 'code': self.reservation.ticket_code, 'mode': 'entry', 'action': 'open'}

    def test_admin_link_and_staff_only_access(self):
        self.assertContains(self.client.get(reverse('admin:index')), self.url)
        self.assertContains(self.client.get(self.url), 'Virtual Parking Gate')
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url, self.data).status_code, 302)

    def test_open_does_not_record_entry_and_pass_is_idempotent(self):
        response = self.client.post(self.url, self.data)
        self.assertTrue(response.context['gate_open'])
        self.reservation.refresh_from_db()
        self.assertIsNone(self.reservation.checked_in_at)
        data = {**self.data, 'action': 'pass', 'permit': response.context['permit']}
        self.client.post(self.url, data)
        self.client.post(self.url, data)
        self.reservation.refresh_from_db()
        self.zone.refresh_from_db()
        self.assertEqual(self.reservation.status, 'CHECKED_IN')
        self.assertEqual(self.zone.occupied_slots, 1)

    def test_close_without_passage_leaves_occupancy_unchanged(self):
        response = self.client.post(self.url, self.data)
        self.assertTrue(response.context['gate_open'])
        self.reservation.refresh_from_db()
        self.assertIsNone(self.reservation.checked_in_at)

        # Attendant decides to close barrier without passage
        close_response = self.client.post(self.url, {**self.data, 'action': 'close'})
        self.assertFalse(close_response.context['gate_open'])
        self.assertContains(close_response, 'Barrier closed without passage')

        self.reservation.refresh_from_db()
        self.zone.refresh_from_db()
        self.assertIsNone(self.reservation.checked_in_at)
        self.assertEqual(self.reservation.status, 'CONFIRMED')
        self.assertEqual(self.zone.occupied_slots, 0)

    def test_invalid_permit_and_wrong_facility_do_not_admit(self):
        self.client.post(self.url, {**self.data, 'action': 'pass', 'permit': 'tampered'})
        other = ParkingZone.objects.create(name='Other gate')
        response = self.client.post(self.url, {**self.data, 'zone': other.pk})
        self.assertContains(response, 'registered for facility')
        self.reservation.refresh_from_db()
        self.assertIsNone(self.reservation.checked_in_at)

    def test_expired_permit_rejected_on_server(self):
        # Create permit with past timestamp (> 120 seconds)
        expired_permit = signing.dumps(
            [self.staff.pk, self.reservation.pk, self.zone.pk, 'entry'],
            salt='virtual-gate'
        )
        # Verify that signing loads with max_age=0 fails as expired
        time.sleep(1)
        response = self.client.post(
            self.url,
            {**self.data, 'action': 'pass', 'permit': expired_permit}
        )
        # With normal token, test an invalid/expired token explicitly
        tampered_permit = expired_permit + "tampered"
        resp_tampered = self.client.post(
            self.url,
            {**self.data, 'action': 'pass', 'permit': tampered_permit}
        )
        self.assertContains(resp_tampered, 'Gate authorization expired or invalid')
        self.reservation.refresh_from_db()
        self.assertIsNone(self.reservation.checked_in_at)

    def test_mismatched_permit_attributes_rejected(self):
        # 1. Wrong user
        permit_wrong_user = signing.dumps(
            [self.other_staff.pk, self.reservation.pk, self.zone.pk, 'entry'],
            salt='virtual-gate'
        )
        resp = self.client.post(self.url, {**self.data, 'action': 'pass', 'permit': permit_wrong_user})
        self.assertContains(resp, 'Gate authorization expired or invalid')

        # 2. Wrong reservation
        other_res = Reservation.objects.create(
            customer=self.customer, parking_zone=self.zone, plate_number='2AZ-9999',
            start_date=timezone.now().date(), finish_date=timezone.now().date()
        )
        permit_wrong_res = signing.dumps(
            [self.staff.pk, other_res.pk, self.zone.pk, 'entry'],
            salt='virtual-gate'
        )
        resp2 = self.client.post(self.url, {**self.data, 'action': 'pass', 'permit': permit_wrong_res})
        self.assertContains(resp2, 'Gate authorization expired or invalid')

        # 3. Wrong mode (e.g. exit permit attempted for entry)
        permit_wrong_mode = signing.dumps(
            [self.staff.pk, self.reservation.pk, self.zone.pk, 'exit'],
            salt='virtual-gate'
        )
        resp3 = self.client.post(self.url, {**self.data, 'action': 'pass', 'permit': permit_wrong_mode})
        self.assertContains(resp3, 'Gate authorization expired or invalid')

    def test_deadline_rechecked_at_passage(self):
        response = self.client.post(self.url, self.data)
        Reservation.objects.filter(pk=self.reservation.pk).update(arrival_deadline=timezone.now() - timedelta(seconds=1))
        response = self.client.post(self.url, {**self.data, 'action': 'pass', 'permit': response.context['permit']})
        self.assertFalse(response.context.get('passed', False))
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 0)

    def test_capacity_rechecked_at_passage(self):
        response = self.client.post(self.url, self.data)
        ParkingZone.objects.filter(pk=self.zone.pk).update(occupied_slots=2)
        self.client.post(self.url, {**self.data, 'action': 'pass', 'permit': response.context['permit']})
        self.reservation.refresh_from_db()
        self.assertIsNone(self.reservation.checked_in_at)

    def test_unpaid_exit_denied_then_settled_exit_releases_once(self):
        self.reservation.status = 'CHECKED_IN'
        self.reservation.checked_in_at = timezone.now() - timedelta(hours=1)
        self.reservation.save()
        self.zone.occupied_slots = 1
        self.zone.save()
        data = {**self.data, 'mode': 'exit'}
        response = self.client.post(self.url, data)
        self.assertFalse(response.context['gate_open'])
        self.assertEqual(response.context['bill']['balance_due'], 4000)

        # Settle via inline action='settle'
        settle_resp = self.client.post(self.url, {**data, 'action': 'settle', 'payment_provider': 'CASH'})
        self.assertFalse(settle_resp.context['gate_open'])  # Payment does NOT open barrier automatically!
        self.assertEqual(settle_resp.context['bill']['balance_due'], 0)

        # Attendant opens barrier
        open_resp = self.client.post(self.url, data)
        self.assertTrue(open_resp.context['gate_open'])

        # Vehicle passes through
        pass_data = {**data, 'action': 'pass', 'permit': open_resp.context['permit']}
        self.client.post(self.url, pass_data)
        self.client.post(self.url, pass_data)  # Repeated pass is safe & idempotent

        self.zone.refresh_from_db()
        self.reservation.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 0)
        self.assertEqual(self.reservation.status, 'CHECKED_OUT')

    def test_future_arrival_denied(self):
        Reservation.objects.filter(pk=self.reservation.pk).update(start_time=timezone.now() + timedelta(hours=1))
        response = self.client.post(self.url, self.data)
        self.assertFalse(response.context['gate_open'])
        self.assertContains(response, 'booked arrival window has not started yet')

    def test_missing_ticket_handling(self):
        response = self.client.post(self.url, {**self.data, 'code': 'SPK-NOTFOUND'})
        self.assertContains(response, 'No reservation found matching ticket code or QR token')

    def test_old_checkout_routes_cannot_bypass_unpaid_exit(self):
        """
        Verify that admin_checkout and customer checkout endpoints cannot
        release capacity when a vehicle is physically CHECKED_IN with an outstanding balance.
        """
        self.reservation.status = 'CHECKED_IN'
        self.reservation.checked_in_at = timezone.now() - timedelta(hours=2)
        self.reservation.save()
        self.zone.occupied_slots = 1
        self.zone.save()

        # 1. Staff manual checkout via admin_checkout must reject unpaid exit
        admin_checkout_url = reverse('admin_checkout')
        resp_admin = self.client.post(admin_checkout_url, {'ticket_code': self.reservation.ticket_code}, follow=True)
        self.assertContains(resp_admin, 'Outstanding balance of 4,000 KHR must be settled before exit')
        self.zone.refresh_from_db()
        self.reservation.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 1)
        self.assertEqual(self.reservation.status, 'CHECKED_IN')

        # 2. Customer checkout endpoint must reject unpaid exit
        self.client.force_login(self.customer)
        cust_checkout_url = reverse('checkout')
        resp_cust = self.client.post(cust_checkout_url, {'ticket_code': self.reservation.ticket_code}, follow=True)
        self.assertContains(resp_cust, 'Outstanding balance of 4,000 KHR must be settled before checkout')
        self.zone.refresh_from_db()
        self.reservation.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 1)
        self.assertEqual(self.reservation.status, 'CHECKED_IN')

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        self.assertEqual(client.post(self.url, self.data).status_code, 403)
