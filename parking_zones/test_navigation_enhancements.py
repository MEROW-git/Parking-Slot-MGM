from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

from parking_zones.models import ParkingZone, Reservation, PaymentTransaction


class BackNavigationAuditTestCase(TestCase):
    """
    Automated regression tests verifying the Back navigation link audit across SomPark.
    Tests explicit safe routes, touch target classes, bilingual labeling,
    unsaved confirmation flags, and absence on top-level pages.
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='navtestuser',
            email='navtest@example.com',
            password='ComplexTestPass123!'
        )
        self.staff_user = User.objects.create_user(
            username='navstaffuser',
            email='navstaff@example.com',
            password='ComplexTestPass123!',
            is_staff=True
        )

        self.zone = ParkingZone.objects.create(
            name='Central Market Plaza',
            khmer_name='ផ្សារធំថ្មី',
            slug='central-market-plaza',
            address='Street 128, Daun Penh, Phnom Penh',
            district='Daun Penh',
            num_of_slots=50,
            occupied_slots=10,
            price=3000,
            walk_in_price=3500,
            latitude=11.5696,
            longitude=104.9210
        )

        self.reservation = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2AZ-9999',
            phone_number='+85512345678',
            ticket_code='SPK-NAV-001',
            status='CONFIRMED',
            payment_status='PAID',
            payment_method='DEPOSIT',
            arrival_deadline=timezone.now() + timedelta(hours=5),
            start_date=timezone.now().date(),
            finish_date=(timezone.now() + timedelta(days=1)).date(),
        )

    def test_zone_detail_has_back_to_find_parking(self):
        """Zone detail page must feature a Back link to Find parking (#parking-zones)."""
        response = self.client.get(reverse('zone_detail', kwargs={'slug': self.zone.slug}))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('btn-back-find-parking', content)
        self.assertIn('sp-back-link', content)
        self.assertIn(f"{reverse('home')}#parking-zones", content)
        self.assertIn('Find parking', content)
        self.assertIn('ស្វែងរកចំណត', content)

    def test_booking_has_back_to_selected_facility_with_unsaved_guard(self):
        """Booking page with preselected zone must link back to that facility and have unsaved guard."""
        self.client.force_login(self.user)
        # Clear active reservation so user can access booking
        self.reservation.status = 'CHECKED_OUT'
        self.reservation.checked_out = True
        self.reservation.save()

        response = self.client.get(f"{reverse('book')}?zone={self.zone.slug}")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('btn-back-facility', content)
        self.assertIn(reverse('zone_detail', kwargs={'slug': self.zone.slug}), content)
        self.assertIn(self.zone.name, content)
        self.assertIn('data-confirm-unsaved="true"', content)

    def test_booking_without_zone_links_to_find_parking(self):
        """Booking page without preselected zone links to Find parking."""
        self.client.force_login(self.user)
        self.reservation.status = 'CHECKED_OUT'
        self.reservation.checked_out = True
        self.reservation.save()

        response = self.client.get(reverse('book'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('btn-back-facility', content)
        self.assertIn(f"{reverse('home')}#parking-zones", content)
        self.assertIn('data-confirm-unsaved="true"', content)

    def test_ticket_detail_has_back_to_my_tickets(self):
        """Ticket detail page must link back to My tickets (all_tickets)."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('ticket_code', kwargs={'ticket_code': self.reservation.ticket_code}))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('btn-back-history', content)
        self.assertIn(reverse('all_tickets'), content)
        self.assertIn('My tickets', content)
        self.assertIn('សំបុត្ររបស់ខ្ញុំ', content)

    def test_pay_deposit_has_back_to_related_ticket(self):
        """Deposit payment page must link back to the related ticket."""
        self.client.force_login(self.user)
        self.reservation.status = 'PAYMENT_PENDING'
        self.reservation.save()

        response = self.client.get(reverse('pay_deposit', kwargs={'ticket_code': self.reservation.ticket_code}))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('btn-back-ticket', content)
        self.assertIn(reverse('ticket_code', kwargs={'ticket_code': self.reservation.ticket_code}), content)
        self.assertIn('Ticket details', content)
        self.assertIn('ព័ត៌មានសំបុត្រ', content)

    def test_pay_exit_has_back_to_related_ticket(self):
        """Pay exit page must link back to the related ticket."""
        self.client.force_login(self.user)
        self.reservation.status = 'CHECKED_IN'
        self.reservation.checked_in_at = timezone.now() - timedelta(hours=2)
        self.reservation.save()

        response = self.client.get(reverse('pay_exit', kwargs={'ticket_code': self.reservation.ticket_code}))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('btn-back-to-ticket', content)
        self.assertIn(reverse('ticket_code', kwargs={'ticket_code': self.reservation.ticket_code}), content)
        self.assertIn('Back to ticket', content)
        self.assertIn('ត្រឡប់ទៅសំបុត្រ', content)

    def test_gate_pass_fullscreen_has_close_pass_button(self):
        """Gate pass fullscreen must have an accessible close pass button with ticket destination."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('ticket_gate_mode', kwargs={'ticket_code': self.reservation.ticket_code}))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('btn-gate-back', content)
        self.assertIn(reverse('ticket_code', kwargs={'ticket_code': self.reservation.ticket_code}), content)
        self.assertIn('Close pass', content)
        self.assertIn('ត្រឡប់ទៅសំបុត្រ', content)

    def test_staff_gate_scanner_has_back_to_admin_dashboard(self):
        """Staff gate scanner must link back to the operations dashboard."""
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse('staff_gate_scanner'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('btn-return-admin-dash', content)
        self.assertIn(reverse('admin_dashboard'), content)
        self.assertIn('Operations dashboard', content)
        self.assertIn('ផ្ទាំងគ្រប់គ្រងបុគ្គលិក', content)

    def test_login_has_back_to_home(self):
        """Login page must have a Back to Home link."""
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('btn-back-home', content)
        self.assertIn(reverse('home'), content)
        self.assertIn('Home', content)
        self.assertIn('ទំព័រដើម', content)

    def test_signup_has_back_to_login(self):
        """Signup page must have a Back to Sign In link."""
        response = self.client.get(reverse('signup'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('btn-back-login', content)
        self.assertIn(reverse('login'), content)
        self.assertIn('Sign in', content)
        self.assertIn('ចូលប្រើប្រាស់', content)

    def test_top_level_pages_omit_redundant_back_links(self):
        """Top-level pages (Home, Customer Dashboard, All Tickets, Admin Dashboard) do NOT feature Back links."""
        self.client.force_login(self.staff_user)

        # 1. Home
        res_home = self.client.get(reverse('home'))
        self.assertNotIn('sp-back-nav', res_home.content.decode('utf-8'))

        # 2. Customer Dashboard
        res_dash = self.client.get(reverse('dashboard'))
        self.assertNotIn('sp-back-nav', res_dash.content.decode('utf-8'))

        # 3. All Tickets History
        res_all = self.client.get(reverse('all_tickets'))
        self.assertNotIn('sp-back-nav', res_all.content.decode('utf-8'))

        # 4. Staff Admin Dashboard
        res_admin = self.client.get(reverse('admin_dashboard'))
        self.assertNotIn('sp-back-nav', res_admin.content.decode('utf-8'))

    def test_back_navigation_never_mutates_state(self):
        """Invoking GET on Back navigation targets never modifies reservation status or cancels holds."""
        self.client.force_login(self.user)
        initial_status = self.reservation.status
        initial_checked_out = self.reservation.checked_out

        # Simulate user clicking back to all tickets
        self.client.get(reverse('all_tickets'))
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, initial_status)
        self.assertEqual(self.reservation.checked_out, initial_checked_out)

        # Simulate user clicking back to facility
        self.client.get(reverse('zone_detail', kwargs={'slug': self.zone.slug}))
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, initial_status)

        # Simulate user clicking back to ticket details
        self.client.get(reverse('ticket_code', kwargs={'ticket_code': self.reservation.ticket_code}))
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, initial_status)
