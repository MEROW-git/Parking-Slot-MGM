from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User


class UserAuthenticationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='cambodia_driver',
            email='driver@sompark.kh',
            password='securepassword123'
        )

    def test_login_page_renders(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sign In (ចូលប្រើ)')

    def test_successful_login(self):
        response = self.client.post(reverse('login'), {
            'username': 'cambodia_driver',
            'password': 'securepassword123',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'cambodia_driver')

    def test_failed_login(self):
        response = self.client.post(reverse('login'), {
            'username': 'cambodia_driver',
            'password': 'wrongpassword',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please enter a correct username and password')

    def test_signup_creates_new_user_and_logs_in(self):
        response = self.client.post(reverse('signup'), {
            'username': 'new_commuter',
            'email': 'commuter@sompark.kh',
            'password': 'phnompenh2026',
            'password_confirm': 'phnompenh2026',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(username='new_commuter').exists())
        self.assertContains(response, 'new_commuter')

    def test_logout_terminates_session(self):
        self.client.login(username='cambodia_driver', password='securepassword123')
        response = self.client.post(reverse('logout'), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'You have been signed out')
