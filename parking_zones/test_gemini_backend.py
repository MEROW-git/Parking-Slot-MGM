import json
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.cache import cache
from parking_zones.models import ParkingZone
from parking_zones.ai import (
    sanitize_input,
    set_mock_gemini_adapter,
    clear_mock_gemini_adapter,
    GeminiService,
)


class GeminiBackendSecurityAndAssistantTest(TestCase):
    """
    Test suite for backend-only Gemini AI Assistant:
    - Authentication enforcement
    - Rate limiting
    - Input & output bounds
    - Customer PII scrubbing (phone numbers, plates, QR tokens)
    - Zero real API quota spent (mocked adapter)
    - Safe fallback handling
    """

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user(
            username='driver_tester',
            password='TestPassword123!',
            email='driver@example.com'
        )

        self.zone = ParkingZone.objects.create(
            name='Riverside Promenade Lot',
            khmer_name='ចំណតមាត់ទន្លេ ស៊ីសុវត្ថិ',
            slug='riverside-promenade',
            num_of_slots=40,
            occupied_slots=10,
            vacant_slots=30,
            address='Preah Sisowath Quay, Daun Penh',
            district='Riverside',
            price=3000,
            operating_hours='24/7'
        )

        # Default test mock: echoes back safe answer without calling real Google API
        def mock_adapter(prompt, zones):
            return {
                "success": True,
                "recommendation": f"Mock recommendation: We recommend {zones[0]['name']} ({zones[0]['price']} KHR/day)."
            }
        set_mock_gemini_adapter(mock_adapter)

    def tearDown(self):
        clear_mock_gemini_adapter()
        cache.clear()

    def test_unauthenticated_request_is_rejected(self):
        """Unauthenticated visitors cannot access the AI assistant endpoint."""
        response = self.client.post(
            reverse('ai_parking_assistant'),
            {'query': 'Where can I park near Riverside?'}
        )
        # Should redirect to login or reject
        self.assertIn(response.status_code, [302, 401, 403])

    def test_authenticated_request_succeeds_with_mock(self):
        """Authenticated customer receives recommendation with zero real API quota spent."""
        self.client.login(username='driver_tester', password='TestPassword123!')
        response = self.client.post(
            reverse('ai_parking_assistant'),
            {'query': 'Where can I park near Riverside?'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('Riverside Promenade Lot', data['recommendation'])
        self.assertTrue(len(data['zones']) > 0)

    def test_rate_limiting_enforced(self):
        """Requests beyond 5 per minute per user are blocked with HTTP 429."""
        self.client.login(username='driver_tester', password='TestPassword123!')

        # First 5 requests should succeed
        for i in range(5):
            res = self.client.post(
                reverse('ai_parking_assistant'),
                {'query': f'Query {i}'}
            )
            self.assertEqual(res.status_code, 200)

        # 6th request should hit rate limit
        res_limit = self.client.post(
            reverse('ai_parking_assistant'),
            {'query': 'Query 6 should be blocked'}
        )
        self.assertEqual(res_limit.status_code, 429)
        data = res_limit.json()
        self.assertEqual(data['code'], 'RATE_LIMIT_EXCEEDED')

    def test_query_length_capped_at_500_characters(self):
        """Queries exceeding 500 characters are rejected with HTTP 400."""
        self.client.login(username='driver_tester', password='TestPassword123!')
        long_query = 'A' * 501
        response = self.client.post(
            reverse('ai_parking_assistant'),
            {'query': long_query}
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data['code'], 'QUERY_TOO_LONG')

    def test_empty_query_rejected(self):
        """Empty or whitespace-only query returns HTTP 400."""
        self.client.login(username='driver_tester', password='TestPassword123!')
        response = self.client.post(
            reverse('ai_parking_assistant'),
            {'query': '   '}
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data['code'], 'EMPTY_QUERY')

    def test_privacy_sanitizer_scrubs_phone_plate_and_qr_tokens(self):
        """Customer phone numbers, license plates, and QR tokens must be scrubbed."""
        test_input = (
            "My phone is 012345678 or +85598765432, "
            "car plate 2A-1234, and my ticket is SPK-ABC1234. "
            "Where can I park?"
        )
        scrubbed = sanitize_input(test_input)

        # Ensure no raw PII remains
        self.assertNotIn('012345678', scrubbed)
        self.assertNotIn('+85598765432', scrubbed)
        self.assertNotIn('2A-1234', scrubbed)
        self.assertNotIn('SPK-ABC1234', scrubbed)

        # Check redaction placeholders
        self.assertIn('[REDACTED_PHONE]', scrubbed)
        self.assertIn('[REDACTED_PLATE]', scrubbed)
        self.assertIn('[REDACTED_TOKEN]', scrubbed)

    def test_sanitizer_in_ai_dispatch(self):
        """Verify the mock adapter receives scrubbed text during actual view execution."""
        received_prompts = []

        def tracking_adapter(prompt, zones):
            received_prompts.append(prompt)
            return {"success": True, "recommendation": "Safe response"}

        set_mock_gemini_adapter(tracking_adapter)

        self.client.login(username='driver_tester', password='TestPassword123!')
        self.client.post(
            reverse('ai_parking_assistant'),
            {'query': 'Plate 1AB-9999 phone 012888999 reservation SPK-TEST99'}
        )

        self.assertEqual(len(received_prompts), 1)
        dispatched_prompt = received_prompts[0]
        self.assertNotIn('1AB-9999', dispatched_prompt)
        self.assertNotIn('012888999', dispatched_prompt)
        self.assertNotIn('SPK-TEST99', dispatched_prompt)

    def test_graceful_failure_handling_on_api_error(self):
        """When Gemini fails or quota is exhausted, view returns polite fallback."""
        def failing_adapter(prompt, zones):
            return {
                "success": False,
                "reason": "QUOTA_EXCEEDED",
                "message": "AI assistant is experiencing high demand. Please select an available zone from the map."
            }

        set_mock_gemini_adapter(failing_adapter)

        self.client.login(username='driver_tester', password='TestPassword123!')
        response = self.client.post(
            reverse('ai_parking_assistant'),
            {'query': 'Can I park in Daun Penh?'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'fallback')
        self.assertEqual(data['code'], 'QUOTA_EXCEEDED')
        self.assertIn('high demand', data['recommendation'])
        self.assertTrue(len(data['zones']) > 0)
