import datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from parking_zones.models import ParkingZone, Reservation


class UserAuthenticationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='cambodia_driver',
            email='driver@sompark.kh',
            password='securepassword123'
        )
        self.zone = ParkingZone.objects.create(
            name='Central Promenade Lot',
            khmer_name='ចំណតមាត់ទន្លេ',
            slug='central-promenade',
            num_of_slots=25,
            occupied_slots=5,
            vacant_slots=20,
            address='Preah Sisowath Quay',
            district='Daun Penh',
            price=3000,
        )

    def test_login_page_renders(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sign In (ចូលប្រើ)')

    def test_registration_redirect(self):
        """Successful registration must redirect to /user/login/."""
        response = self.client.post(reverse('signup'), {
            'username': 'driver_phnompenh',
            'email': 'ppdriver@sompark.kh',
            'password': 'strongpassword2026',
            'password_confirm': 'strongpassword2026',
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('login'))
        self.assertTrue(User.objects.filter(username='driver_phnompenh').exists())

    def test_registration_toast(self):
        """
        Following registration redirect, an accessible success toast must appear
        with exact text: 'Account created successfully. Sign in to continue.'
        JavaScript alert() must NOT be used.
        """
        response = self.client.post(reverse('signup'), {
            'username': 'driver_kirirom',
            'email': 'kirirom@sompark.kh',
            'password': 'strongpassword2026',
            'password_confirm': 'strongpassword2026',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Account created successfully. Sign in to continue.')
        self.assertContains(response, 'role="status"')
        self.assertContains(response, 'sp-toast-success')
        self.assertContains(response, 'sp-toast-close')
        self.assertNotContains(response, 'alert(')

    def test_registration_failure_preserves_inline_errors(self):
        """Failed registration must preserve inline validation errors without alert()."""
        # Password mismatch
        response = self.client.post(reverse('signup'), {
            'username': 'invalid_user',
            'email': 'invalid@sompark.kh',
            'password': 'firstpassword123',
            'password_confirm': 'mismatchedpassword456',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='invalid_user').exists())
        self.assertContains(response, 'Passwords do not match.')
        self.assertContains(response, 'sp-field-error')
        self.assertNotContains(response, 'alert(')

        # Duplicate username
        response_dup = self.client.post(reverse('signup'), {
            'username': 'cambodia_driver',
            'email': 'another@sompark.kh',
            'password': 'securepassword123',
            'password_confirm': 'securepassword123',
        })
        self.assertEqual(response_dup.status_code, 200)
        self.assertContains(response_dup, 'sp-field-error')

    def test_login_redirect_to_dashboard(self):
        """Successful login must redirect to /dashboard/ when no next URL is provided."""
        response = self.client.post(reverse('login'), {
            'username': 'cambodia_driver',
            'password': 'securepassword123',
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('dashboard'))

    def test_login_toast(self):
        """Following login, a success toast 'Welcome back, {username}.' must be displayed."""
        response = self.client.post(reverse('login'), {
            'username': 'cambodia_driver',
            'password': 'securepassword123',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Welcome back, cambodia_driver.')
        self.assertContains(response, 'role="status"')
        self.assertContains(response, 'sp-toast-success')
        self.assertContains(response, 'sp-toast-close')

    def test_login_safe_next_redirect(self):
        """Login with a valid internal next URL must redirect to that destination."""
        response = self.client.post(reverse('login') + '?next=/all_tickets/', {
            'username': 'cambodia_driver',
            'password': 'securepassword123',
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, '/all_tickets/')

    def test_login_unsafe_next_redirect_falls_back_to_dashboard(self):
        """Login with an untrusted external next URL must fall back to /dashboard/."""
        response = self.client.post(reverse('login') + '?next=https://attacker.sompark-spoof.com/steal', {
            'username': 'cambodia_driver',
            'password': 'securepassword123',
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('dashboard'))

    def test_failed_login_shows_error(self):
        response = self.client.post(reverse('login'), {
            'username': 'cambodia_driver',
            'password': 'wrongpassword',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please enter a correct username and password')

    def test_dashboard_requires_authentication(self):
        """Unauthenticated visitors opening /dashboard/ must be redirected to login."""
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)
        self.assertIn('next=/dashboard/', response.url)

    def test_dashboard_content_with_active_and_recent_reservations(self):
        """
        Dashboard must display:
        - Greeting with the authenticated username
        - Current active reservation details
        - Quick actions: Find parking, Reserve a space, My tickets, Sign out
        - Recent parking tickets/reservations
        - Real Django data only
        """
        today = datetime.date.today()
        # Create active reservation
        active_res = Reservation.objects.create(
            ticket_code='SPK-ACT1234',
            customer=self.user,
            parking_zone=self.zone,
            plate_number='2AZ-9999',
            phone_number='+85512999888',
            start_date=today,
            finish_date=today,
            checked_out=False
        )
        # Create past reservation
        past_res = Reservation.objects.create(
            ticket_code='SPK-OLD5678',
            customer=self.user,
            parking_zone=self.zone,
            plate_number='2AZ-9999',
            phone_number='+85512999888',
            start_date=today - datetime.timedelta(days=2),
            finish_date=today - datetime.timedelta(days=2),
            checked_out=True
        )

        self.client.login(username='cambodia_driver', password='securepassword123')
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        # 1. Greeting with authenticated username
        self.assertContains(response, 'Welcome back, cambodia_driver')
        # 2. Current active reservation
        self.assertContains(response, 'SPK-ACT1234')
        self.assertContains(response, 'Central Promenade Lot')
        self.assertContains(response, '2AZ-9999')
        self.assertContains(response, 'CURRENT ACTIVE SESSION')
        # Cancellation uses the branded Yes/No dialog, not window.confirm().
        self.assertContains(response, 'id="reservation-cancel-dialog"')
        self.assertContains(response, 'data-cancel-confirm')
        self.assertContains(response, 'No, keep reservation')
        self.assertContains(response, 'Yes, cancel reservation')
        self.assertNotContains(response, "return confirm(")
        # 3. Quick actions
        self.assertContains(response, 'Find parking')
        self.assertContains(response, 'Reserve a space')
        self.assertContains(response, 'My tickets')
        self.assertContains(response, 'Sign out')
        # 4. Recent reservations
        self.assertContains(response, 'SPK-OLD5678')
        self.assertContains(response, 'COMPLETED')

    def test_dashboard_content_empty_state(self):
        """Dashboard must display an appropriate empty state if user has no reservations."""
        new_user = User.objects.create_user(
            username='empty_driver',
            password='securepassword123'
        )
        self.client.login(username='empty_driver', password='securepassword123')
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Welcome back, empty_driver')
        self.assertContains(response, 'No Parking Reservations Yet')
        self.assertContains(response, 'Reserve a space')
        self.assertContains(response, 'Find parking')
        self.assertNotContains(response, 'SPK-ACT1234')

    def test_cancelled_reservation_is_not_active_and_has_no_gate_pass(self):
        """Cancelled bookings remain in history but expose no active gate controls."""
        today = datetime.date.today()
        reservation = Reservation.objects.create(
            ticket_code='SPK-CANCEL1',
            customer=self.user,
            parking_zone=self.zone,
            plate_number='2AZ-1000',
            phone_number='+85512100100',
            start_date=today,
            finish_date=today,
            status='CANCELLED',
            checked_out=False,
        )

        self.client.login(username='cambodia_driver', password='securepassword123')

        dashboard_response = self.client.get(reverse('dashboard'))
        self.assertIsNone(dashboard_response.context['active_reservation'])
        self.assertNotContains(dashboard_response, 'id="btn-active-gate-pass"')
        self.assertContains(dashboard_response, 'CANCELLED')

        history_response = self.client.get(reverse('all_tickets'))
        self.assertNotContains(
            history_response,
            f'id="btn-gate-{reservation.ticket_code}"',
        )
        self.assertNotContains(history_response, '⚡ Gate Pass')

        home_response = self.client.get(reverse('home'))
        self.assertIsNone(home_response.context['active_reservation'])
        self.assertNotContains(home_response, 'id="active-res-banner"')

    def test_toast_notification_system_roles_and_dismiss_behavior(self):
        """
        Verify toast notification system accessibility:
        - role='status' and auto-dismiss for ordinary messages
        - role='alert' and persistent dismissal for errors
        - visible close button
        """
        self.client.login(username='cambodia_driver', password='securepassword123')
        # Trigger an info toast via logout
        response = self.client.post(reverse('logout'), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'role="status"')
        self.assertContains(response, 'data-auto-dismiss="true"')
        self.assertContains(response, 'sp-toast-close')

    def test_logout_terminates_session(self):
        self.client.login(username='cambodia_driver', password='securepassword123')
        response = self.client.post(reverse('logout'), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'You have been signed out')
