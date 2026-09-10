from django.test import TestCase, override_settings, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.conf import settings
from parking_zones.models import ParkingZone

User = get_user_model()

class GeminiAiEnvFlagTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='password123')
        self.zone = ParkingZone.objects.create(
            name='Riverside Lot',
            slug='riverside-lot',
            address='Preah Sisowath Quay',
            district='Daun Penh',
            price=3000,
            num_of_slots=20,
            occupied_slots=5,
            vacant_slots=15,
            latitude=11.56,
            longitude=104.93,
        )

    def test_current_env_setting_disabled(self):
        """With gemini_ai=false in .env, settings.GEMINI_AI_ENABLED must be False."""
        # Note: .env currently has gemini_ai=false
        self.assertFalse(settings.GEMINI_AI_ENABLED)

    @override_settings(GEMINI_AI_ENABLED=False)
    def test_home_page_hides_ai_assistant_when_disabled(self):
        """When GEMINI_AI_ENABLED is False, AI assistant card and script must NOT be rendered in HTML."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertNotIn('id="ai-assistant-section"', content)
        self.assertNotIn('sp-ai-assistant-section', content)
        self.assertNotIn('Smart Parking Assistant', content)
        self.assertNotIn('Ask Gemini', content)
        self.assertNotIn('id="ai-assistant-form"', content)
        self.assertFalse(response.context.get('gemini_ai_enabled'))

    @override_settings(GEMINI_AI_ENABLED=True)
    def test_home_page_shows_ai_assistant_when_enabled(self):
        """When GEMINI_AI_ENABLED is True, AI assistant card is rendered in HTML."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('id="ai-assistant-section"', content)
        self.assertIn('Smart Parking Assistant', content)
        self.assertIn('Ask Gemini', content)
        self.assertTrue(response.context.get('gemini_ai_enabled'))

    @override_settings(GEMINI_AI_ENABLED=False)
    def test_api_endpoint_blocked_when_disabled(self):
        """When GEMINI_AI_ENABLED is False, calling the API endpoint returns 403 Forbidden."""
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('ai_parking_assistant'),
            {'query': 'Where can I park?'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertEqual(data.get('code'), 'AI_ASSISTANT_DISABLED')
