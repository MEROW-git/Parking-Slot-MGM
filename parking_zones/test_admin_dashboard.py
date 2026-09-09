import datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from parking_zones.models import ParkingZone, Reservation


class AdminDashboardAccessAndSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username='sompark_admin',
            email='admin@sompark.kh',
            password='staffpassword2026',
            is_staff=True
        )
        self.customer_user = User.objects.create_user(
            username='cambodia_driver',
            email='driver@sompark.kh',
            password='customerpassword2026',
            is_staff=False
        )
        self.zone = ParkingZone.objects.create(
            name='Central Quay Zone',
            khmer_name='ចំណតមាត់ទន្លេកណ្តាល',
            slug='central-quay-zone',
            num_of_slots=20,
            occupied_slots=5,
            vacant_slots=15,
            address='Preah Sisowath Quay, Daun Penh',
            district='Daun Penh',
            price=3000,
        )

    def test_1_anonymous_users_cannot_access_admin_dashboard(self):
        """Anonymous visitors must be redirected to the login page."""
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)
        self.assertIn('next=/staff/dashboard/', response.url)

    def test_2_normal_authenticated_users_cannot_access_admin_dashboard(self):
        """Authenticated non-staff accounts must be denied access with HTTP 403 Forbidden."""
        self.client.login(username='cambodia_driver', password='customerpassword2026')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 403)

    def test_3_staff_users_can_access_admin_dashboard(self):
        """Users with is_staff=True can successfully access the operations workbench."""
        self.client.login(username='sompark_admin', password='staffpassword2026')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Operations Dashboard')
        self.assertContains(response, 'Central Operations Workbench')
        self.assertContains(response, 'Central Quay Zone')
        self.assertContains(response, reverse('admin:index'))

    def test_6_admin_checkout_rejects_get_requests(self):
        """Admin checkout endpoint must strictly reject GET requests (HTTP 405 Method Not Allowed)."""
        self.client.login(username='sompark_admin', password='staffpassword2026')
        response = self.client.get(reverse('admin_checkout'))
        self.assertEqual(response.status_code, 405)

    def test_7_non_staff_users_cannot_call_checkout_endpoint(self):
        """Non-staff authenticated users must receive HTTP 403 Forbidden when calling checkout."""
        today = datetime.date.today()
        reservation = Reservation.objects.create(
            ticket_code='SPK-STAFF01',
            customer=self.customer_user,
            parking_zone=self.zone,
            plate_number='2AZ-5555',
            phone_number='012345678',
            start_date=today,
            finish_date=today,
            checked_out=False,
        )
        self.client.login(username='cambodia_driver', password='customerpassword2026')
        response = self.client.post(reverse('admin_checkout'), {'ticket_code': reservation.ticket_code})
        self.assertEqual(response.status_code, 403)
        reservation.refresh_from_db()
        self.assertFalse(reservation.checked_out)

    def test_navigation_link_visibility_based_on_staff_status(self):
        """
        Verify 'Admin dashboard' link appears in navigation only for staff users,
        and is completely hidden from non-staff and anonymous visitors.
        """
        # Anonymous
        res_anon = self.client.get(reverse('home'))
        self.assertNotContains(res_anon, 'Admin dashboard')
        self.assertNotContains(res_anon, reverse('admin_dashboard'))

        # Customer (non-staff)
        self.client.login(username='cambodia_driver', password='customerpassword2026')
        res_cust = self.client.get(reverse('home'))
        self.assertNotContains(res_cust, 'Admin dashboard')
        self.assertNotContains(res_cust, reverse('admin_dashboard'))

        # Staff
        self.client.login(username='sompark_admin', password='staffpassword2026')
        res_staff = self.client.get(reverse('home'))
        self.assertContains(res_staff, 'Admin dashboard')
        self.assertContains(res_staff, reverse('admin_dashboard'))


class AdminDashboardDataAndStatisticsTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Clean existing seeded records for exact calculation tests
        ParkingZone.objects.all().delete()
        Reservation.objects.all().delete()

        self.staff_user = User.objects.create_user(
            username='staff_analyst',
            email='analyst@sompark.kh',
            password='securepassword',
            is_staff=True
        )
        self.customer1 = User.objects.create_user(
            username='customer_one',
            password='securepassword',
            is_staff=False
        )
        self.customer2 = User.objects.create_user(
            username='customer_two',
            password='securepassword',
            is_staff=False
        )
        self.client.login(username='staff_analyst', password='securepassword')

    def test_4_dashboard_statistics_use_real_database_data(self):
        """Summary cards must calculate authentic values from the database."""
        today = datetime.date.today()

        # Zone A: 30 capacity, 10 occupied, 20 vacant
        zone_a = ParkingZone.objects.create(
            name='Zone Riverside',
            khmer_name='ចំណតទន្លេ',
            slug='zone-riverside',
            num_of_slots=30,
            occupied_slots=10,
            vacant_slots=20,
            district='Daun Penh',
            price=3000
        )
        # Zone B: 20 capacity, 15 occupied, 5 vacant
        zone_b = ParkingZone.objects.create(
            name='Zone BKK1 Prime',
            khmer_name='ចំណតបឹងកេងកង',
            slug='zone-bkk1-prime',
            num_of_slots=20,
            occupied_slots=15,
            vacant_slots=5,
            district='Boeung Keng Kang',
            price=4000
        )

        # Total capacity = 50, occupied = 25, vacant = 25 -> overall occupancy = 50%
        # Reservations: 2 active, 1 completed
        Reservation.objects.create(
            ticket_code='SPK-REAL01',
            customer=self.customer1,
            parking_zone=zone_a,
            plate_number='2AZ-1111',
            phone_number='012111111',
            start_date=today,
            finish_date=today,
            checked_out=False
        )
        Reservation.objects.create(
            ticket_code='SPK-REAL02',
            customer=self.customer2,
            parking_zone=zone_b,
            plate_number='2AZ-2222',
            phone_number='012222222',
            start_date=today,
            finish_date=today,
            checked_out=False
        )
        Reservation.objects.create(
            ticket_code='SPK-REAL03',
            customer=self.customer1,
            parking_zone=zone_a,
            plate_number='2AZ-3333',
            phone_number='012333333',
            start_date=today - datetime.timedelta(days=1),
            finish_date=today - datetime.timedelta(days=1),
            checked_out=True
        )

        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Verify context values
        self.assertEqual(response.context['total_zones'], 2)
        self.assertEqual(response.context['total_capacity'], 50)
        self.assertEqual(response.context['total_occupied'], 25)
        self.assertEqual(response.context['total_vacant'], 25)
        self.assertEqual(response.context['overall_occupancy_pct'], 50)
        self.assertEqual(response.context['active_reservations_count'], 2)
        self.assertEqual(response.context['completed_reservations_count'], 1)
        # Registered customers excluding staff: customer1 and customer2 = 2
        self.assertEqual(response.context['registered_customers_count'], 2)

        # Verify HTML contains rendered stats
        self.assertContains(response, 'id="stat-total-zones">2<')
        self.assertContains(response, 'id="stat-total-capacity">50<')
        self.assertContains(response, 'id="stat-occupied-slots">25<')
        self.assertContains(response, 'id="stat-vacant-slots">25<')
        self.assertContains(response, '50%')
        self.assertContains(response, 'id="stat-active-reservations">2<')
        self.assertContains(response, 'id="stat-completed-reservations">1<')
        self.assertContains(response, 'id="stat-registered-customers">2<')

        # Verify zone ordering: zone_b (15 occupied) must appear before zone_a (10 occupied)
        content = response.content.decode('utf-8')
        pos_b = content.find('Zone BKK1 Prime')
        pos_a = content.find('Zone Riverside')
        self.assertTrue(pos_b < pos_a, "Most occupied zone should be visible first.")

    def test_5_zero_capacity_and_empty_database_does_not_cause_error(self):
        """Empty database or zero total capacity must render gracefully without division-by-zero."""
        # No parking zones created
        self.assertEqual(ParkingZone.objects.count(), 0)

        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_zones'], 0)
        self.assertEqual(response.context['total_capacity'], 0)
        self.assertEqual(response.context['total_occupied'], 0)
        self.assertEqual(response.context['total_vacant'], 0)
        self.assertEqual(response.context['overall_occupancy_pct'], 0)
        self.assertEqual(response.context['active_reservations_count'], 0)
        self.assertEqual(response.context['completed_reservations_count'], 0)
        self.assertContains(response, '0%')
        self.assertContains(response, 'No parking zones currently registered')


class AdminCheckoutWorkflowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username='staff_officer',
            email='officer@sompark.kh',
            password='securepassword',
            is_staff=True
        )
        self.customer = User.objects.create_user(
            username='dara_driver',
            password='securepassword',
            is_staff=False
        )
        self.zone = ParkingZone.objects.create(
            name='Central Station Lot',
            slug='central-station-lot',
            num_of_slots=10,
            occupied_slots=4,
            vacant_slots=6,
            district='Daun Penh',
            price=3000
        )
        self.today = datetime.date.today()
        self.reservation = Reservation.objects.create(
            ticket_code='SPK-TESTOP01',
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='2AZ-7777',
            phone_number='+85512777888',
            start_date=self.today,
            finish_date=self.today,
            checked_out=False
        )
        self.client.login(username='staff_officer', password='securepassword')

    def test_8_and_9_successful_checkout_marks_completed_and_updates_counts(self):
        """Successful admin checkout marks reservation completed, decrements occupied, increments vacant."""
        self.assertEqual(self.zone.occupied_slots, 4)
        self.assertEqual(self.zone.vacant_slots, 6)

        response = self.client.post(reverse('admin_checkout'), {
            'ticket_code': self.reservation.ticket_code
        }, follow=True)

        self.assertEqual(response.status_code, 200)

        # 8. Reservation marked as checked out
        self.reservation.refresh_from_db()
        self.assertTrue(self.reservation.checked_out)

        # 9. Zone occupied count decreased, vacant count updated
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 3)
        self.assertEqual(self.zone.vacant_slots, 7)

        # 11. Success Django message generated
        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any('checked out successfully' in str(m) for m in messages))
        self.assertContains(response, 'checked out successfully')
        self.assertContains(response, 'SPK-TESTOP01')

    def test_10_repeating_checkout_does_not_decrement_occupancy_twice(self):
        """Submitting checkout on an already completed reservation must not decrement occupancy again."""
        # First checkout
        self.client.post(reverse('admin_checkout'), {
            'ticket_code': self.reservation.ticket_code
        }, follow=True)

        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 3)
        self.assertEqual(self.zone.vacant_slots, 7)

        # Attempt repeated checkout on same ticket
        repeat_response = self.client.post(reverse('admin_checkout'), {
            'ticket_code': self.reservation.ticket_code
        }, follow=True)

        self.assertEqual(repeat_response.status_code, 200)

        # Occupancy must NOT decrement a second time
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 3)
        self.assertEqual(self.zone.vacant_slots, 7)

        # 11. Warning Django message generated
        messages = list(get_messages(repeat_response.wsgi_request))
        self.assertTrue(any('already checked out' in str(m) for m in messages))
        self.assertContains(repeat_response, 'already checked out')

    def test_checkout_nonexistent_ticket_handles_gracefully(self):
        """Attempting to check out an invalid ticket produces an error message without crashing."""
        response = self.client.post(reverse('admin_checkout'), {
            'ticket_code': 'SPK-NONEXISTENT'
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any('could not be found' in str(m) for m in messages))
        self.assertContains(response, 'could not be found')

    def test_12_existing_customer_dashboard_and_auth_routes_still_work(self):
        """Verify existing customer dashboard and authentication routes continue to function normally."""
        # Customer logs in
        self.client.logout()
        self.client.login(username='dara_driver', password='securepassword')

        # Customer dashboard loads
        dash_res = self.client.get(reverse('dashboard'))
        self.assertEqual(dash_res.status_code, 200)
        self.assertContains(dash_res, 'Welcome back, dara_driver')
        self.assertContains(dash_res, 'Recent Reservations')

        # Customer tickets view loads
        tickets_res = self.client.get(reverse('all_tickets'))
        self.assertEqual(tickets_res.status_code, 200)
        self.assertContains(tickets_res, 'My Parking Reservations')
