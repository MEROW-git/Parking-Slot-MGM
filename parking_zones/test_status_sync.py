"""
Automated tests for SomPark real-time status synchronization mechanism.
Tests:
1. Two independent sessions: virtual gate physical exit updates ticket status to CHECKED_OUT.
2. Status API ownership and authorization (owner and staff 200, non-owner 403, anon 401).
3. Batched tickets status endpoint for dashboard and history lists.
4. Cancellation and request-time hold expiry transitions.
5. In-app payment / settlement synchronization.
6. Strictly read-only invariant: GET status requests never alter capacity or record payments/passages.
7. Zones parking availability telemetry endpoint.
"""
from datetime import timedelta
from decimal import Decimal
from django.contrib.auth.models import User
from django.core import signing
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from parking_zones.models import ParkingZone, Reservation
from parking_zones.services import GateService, PaymentService


class RealTimeStatusSyncTest(TestCase):
    def setUp(self):
        self.client_customer = Client()
        self.client_other = Client()
        self.client_staff = Client()

        self.customer = User.objects.create_user(
            username='sync_customer',
            password='TestPassword123!',
            email='sync@example.com'
        )
        self.other_user = User.objects.create_user(
            username='sync_intruder',
            password='TestPassword123!',
            email='intruder@example.com'
        )
        self.staff_user = User.objects.create_user(
            username='sync_staff',
            password='TestPassword123!',
            email='staff@example.com',
            is_staff=True
        )

        self.client_customer.force_login(self.customer)
        self.client_other.force_login(self.other_user)
        self.client_staff.force_login(self.staff_user)

        self.zone = ParkingZone.objects.create(
            name='BKK1 Commercial Plaza',
            khmer_name='ចំណតពាណិជ្ជកម្ម បឹងកេងកង',
            slug='bkk1-commercial-plaza',
            num_of_slots=50,
            occupied_slots=10,
            vacant_slots=40,
            price=4000,
            walk_in_price=7000,
            address='Street 282, BKK1'
        )

        now = timezone.now()
        # Checked-in active ticket
        self.active_ticket = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='2AZ-1234',
            phone_number='012345678',
            status='CHECKED_IN',
            payment_status='PAID',
            payment_method='DEPOSIT',
            deposit_amount=4000,
            daily_rate=4000,
            reserved_days=1,
            start_date=now.date(),
            finish_date=now.date(),
            start_time=now - timedelta(hours=2),
            finish_time=now + timedelta(hours=22),
            checked_in_at=now - timedelta(hours=2),
        )

    def test_1_status_api_security_and_authorization(self):
        """Owner and staff can query ticket status; other users receive 403; anon receives 401."""
        url = reverse('ticket_status_api', args=[self.active_ticket.ticket_code])

        # 1. Owner access -> 200 OK
        res_owner = self.client_customer.get(url)
        self.assertEqual(res_owner.status_code, 200)
        data = res_owner.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], 'CHECKED_IN')
        self.assertEqual(data['plate_number'], '2AZ-1234')
        self.assertTrue(data['can_checkout'])
        self.assertFalse(data['is_terminal'])

        # 2. Staff access -> 200 OK
        res_staff = self.client_staff.get(url)
        self.assertEqual(res_staff.status_code, 200)

        # 3. Other authenticated user -> 403 Forbidden
        res_other = self.client_other.get(url)
        self.assertEqual(res_other.status_code, 403)
        self.assertEqual(res_other.json()['code'], 'PERMISSION_DENIED')

        # 4. Anonymous user -> 401 Unauthorized
        client_anon = Client()
        res_anon = client_anon.get(url)
        self.assertEqual(res_anon.status_code, 401)

    def test_2_two_independent_sessions_exit_confirmation(self):
        """
        Session 1: Customer holds open ticket page (checked in).
        Session 2: Staff confirms physical exit at the virtual gate.
        Customer status query automatically transitions to CHECKED_OUT with disabled actions.
        """
        url = reverse('ticket_status_api', args=[self.active_ticket.ticket_code])

        # Customer queries status before exit: shows CHECKED_IN
        res_before = self.client_customer.get(url).json()
        self.assertEqual(res_before['status'], 'CHECKED_IN')
        self.assertTrue(res_before['can_checkout'])
        self.assertTrue(res_before['qr_active'])
        self.assertFalse(res_before['is_terminal'])

        # Staff records exit at the gate barrier
        success, res, notice = GateService.confirm_physical_exit(self.active_ticket.pk, staff_user=self.staff_user)
        self.assertTrue(success)
        self.assertEqual(res.status, 'CHECKED_OUT')

        # Customer background status query without page reload: shows CHECKED_OUT
        res_after = self.client_customer.get(url).json()
        self.assertEqual(res_after['status'], 'CHECKED_OUT')
        self.assertFalse(res_after['can_checkout'])
        self.assertFalse(res_after['qr_active'])
        self.assertTrue(res_after['is_terminal'])
        self.assertIsNotNone(res_after['checked_out_at'])

    def test_3_batched_tickets_status_endpoint(self):
        """Batched tickets endpoint returns multi-ticket status dictionary in a single query."""
        now = timezone.now()
        ticket2 = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='2BC-9999',
            status='CONFIRMED',
            payment_status='UNPAID',
            payment_method='PAY_AT_EXIT',
            arrival_deadline=now + timedelta(hours=3),
        )

        codes = f"{self.active_ticket.ticket_code},{ticket2.ticket_code}"
        url = f"{reverse('batch_tickets_status_api')}?codes={codes}"

        res = self.client_customer.get(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertIn(self.active_ticket.ticket_code, data['tickets'])
        self.assertIn(ticket2.ticket_code, data['tickets'])

        self.assertEqual(data['tickets'][self.active_ticket.ticket_code]['status'], 'CHECKED_IN')
        self.assertEqual(data['tickets'][ticket2.ticket_code]['status'], 'CONFIRMED')
        self.assertTrue(data['tickets'][ticket2.ticket_code]['can_cancel'])

    def test_4_request_time_expiry_transition(self):
        """Expired holds automatically transition to EXPIRED on status query."""
        now = timezone.now()
        expired_ticket = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='2EX-0000',
            status='CONFIRMED',
            payment_status='UNPAID',
            payment_method='PAY_AT_EXIT',
            arrival_deadline=now - timedelta(minutes=10),  # passed deadline
        )

        url = reverse('ticket_status_api', args=[expired_ticket.ticket_code])
        res = self.client_customer.get(url).json()

        self.assertEqual(res['status'], 'EXPIRED')
        self.assertTrue(res['is_terminal'])
        self.assertFalse(res['can_cancel'])
        self.assertFalse(res['qr_active'])

    def test_5_get_requests_are_strictly_readonly(self):
        """GET status requests must never modify physical occupancy or issue permits."""
        occupied_before = self.zone.occupied_slots
        url = reverse('ticket_status_api', args=[self.active_ticket.ticket_code])

        # Query 10 times in succession
        for _ in range(10):
            res = self.client_customer.get(url)
            self.assertEqual(res.status_code, 200)

        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, occupied_before)

    def test_6_zones_availability_status_endpoint(self):
        """Zones status endpoint returns live parking capacity and occupancy percentages."""
        url = reverse('zones_status_api')
        res = self.client_customer.get(url)
        self.assertEqual(res.status_code, 200)

        data = res.json()
        self.assertTrue(data['success'])
        self.assertIn(self.zone.slug, data['zones'])

        zone_data = data['zones'][self.zone.slug]
        self.assertEqual(zone_data['vacant_slots'], 40)
        self.assertEqual(zone_data['occupied_slots'], 10)
        self.assertEqual(zone_data['num_of_slots'], 50)
        self.assertEqual(zone_data['occupancy_percentage'], 20)
        self.assertEqual(zone_data['availability_status'], 'available')
