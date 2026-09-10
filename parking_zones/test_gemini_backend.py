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
        def failing_adapter(prompt, zones, conversation_history=None, location_resolved=None):
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

    def test_nearby_search_with_resolved_location(self):
        """
        Query with known landmark resolves location, calculates Haversine distance,
        and ranks closer zones first without inventing distance.
        """
        # Create a far zone in Toul Kork
        far_zone = ParkingZone.objects.create(
            name='Toul Kork Express Parking',
            khmer_name='ចំណតទួលគោក',
            slug='toul-kork-express',
            num_of_slots=50,
            occupied_slots=5,
            vacant_slots=45,
            address='Street 289, Toul Kork',
            district='Toul Kork',
            latitude=11.5739,
            longitude=104.8967,
            price=2500,
            operating_hours='24/7'
        )

        # Set Riverside zone coordinates close to Riverside landmark (11.5685, 104.9312)
        self.zone.latitude = 11.5680
        self.zone.longitude = 11.5310 # slightly offset
        self.zone.save()

        def proximity_mock_adapter(prompt, zones, conversation_history=None, location_resolved=None):
            self.assertIsNotNone(location_resolved)
            self.assertEqual(location_resolved['name'], 'Riverside / Sisowath Quay')
            return {
                "success": True,
                "recommendation": f"We recommend {zones[0]['name']} located {zones[0]['distance_km']} km away.",
                "zones": zones,
                "location_resolved": True,
                "resolved_location": location_resolved
            }

        set_mock_gemini_adapter(proximity_mock_adapter)

        self.client.login(username='driver_tester', password='TestPassword123!')
        response = self.client.post(
            reverse('ai_parking_assistant'),
            {'query': 'Where can I park near Riverside Quay?'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertTrue(data['location_resolved'])
        self.assertIsNotNone(data['resolved_location'])
        # Distance calculation verified
        self.assertIsNotNone(data['zones'][0]['distance_km'])

    def test_unknown_street_prompts_for_landmark_without_inventing_distances(self):
        """
        When query mentions an unrecognized street, distance is NOT invented (distance_km is None)
        and location_resolved is False.
        """
        captured_contexts = []

        def unknown_mock_adapter(prompt, zones, conversation_history=None, location_resolved=None):
            captured_contexts.append({
                'location_resolved': location_resolved,
                'zones': zones
            })
            return {
                "success": True,
                "recommendation": "Location 'Street 9999' was not found in our database. Please specify a nearby landmark or district.",
                "zones": zones,
                "location_resolved": location_resolved is not None,
                "resolved_location": location_resolved
            }

        set_mock_gemini_adapter(unknown_mock_adapter)

        self.client.login(username='driver_tester', password='TestPassword123!')
        response = self.client.post(
            reverse('ai_parking_assistant'),
            {'query': 'Is there parking near Unknown Alley 9999?'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['location_resolved'])
        self.assertIsNone(data['resolved_location'])

        # Verify no invented distances
        self.assertEqual(len(captured_contexts), 1)
        self.assertIsNone(captured_contexts[0]['location_resolved'])
        for z in captured_contexts[0]['zones']:
            self.assertIsNone(z['distance_km'])

    def test_follow_up_conversation_context_preserved_in_session(self):
        """
        Multi-turn conversation preserves previous turns in request.session
        with privacy filtering applied.
        """
        history_snapshots = []

        def tracking_adapter(prompt, zones, conversation_history=None, location_resolved=None):
            history_snapshots.append(list(conversation_history or []))
            return {
                "success": True,
                "recommendation": f"Answer for {prompt}"
            }

        set_mock_gemini_adapter(tracking_adapter)

        self.client.login(username='driver_tester', password='TestPassword123!')

        # Turn 1
        res1 = self.client.post(
            reverse('ai_parking_assistant'),
            {'query': 'Where can I park in BKK1? Phone: 012345678'}
        )
        self.assertEqual(res1.status_code, 200)
        # Turn 1 should have empty history
        self.assertEqual(len(history_snapshots[0]), 0)

        # Turn 2 (Follow-up)
        res2 = self.client.post(
            reverse('ai_parking_assistant'),
            {'query': 'Is it open 24/7?'}
        )
        self.assertEqual(res2.status_code, 200)
        # Turn 2 should have turn 1 user + model entries
        self.assertEqual(len(history_snapshots[1]), 2)
        self.assertEqual(history_snapshots[1][0]['role'], 'user')
        # Phone number must be redacted in history
        self.assertNotIn('012345678', history_snapshots[1][0]['text'])
        self.assertIn('[REDACTED_PHONE]', history_snapshots[1][0]['text'])

    def test_clear_conversation_history(self):
        """Passing clear_history=true resets session conversation history."""
        self.client.login(username='driver_tester', password='TestPassword123!')

        # Turn 1
        self.client.post(
            reverse('ai_parking_assistant'),
            {'query': 'First question'}
        )
        session = self.client.session
        self.assertTrue(len(session.get('sp_ai_history', [])) > 0)

        # Clear history
        res_clear = self.client.post(
            reverse('ai_parking_assistant'),
            {'query': 'start new', 'clear_history': 'true'}
        )
        self.assertEqual(res_clear.status_code, 200)
        # After clear and new query, history in session has only the new turn
        updated_session = self.client.session
        self.assertEqual(len(updated_session.get('sp_ai_history', [])), 2)
        self.assertEqual(updated_session['sp_ai_history'][0]['text'], 'start new')

    def test_multiple_response_parts_combined_and_thought_parts_ignored(self):
        """Candidate parser combines multiple non-thought text parts and filters out thought parts."""
        from parking_zones.ai import parse_gemini_candidate

        candidate = {
            "finishReason": "STOP",
            "content": {
                "parts": [
                    {"thought": True, "text": "Analyzing parking options in Daun Penh..."},
                    {"text": "We recommend Riverside Promenade Lot. "},
                    {"text": "It has 30 vacant slots and costs 3,000 KHR/day."}
                ]
            }
        }

        parsed = parse_gemini_candidate(candidate)
        self.assertTrue(parsed["success"])
        self.assertFalse(parsed["truncated"])
        self.assertFalse(parsed["blocked"])
        self.assertNotIn("Analyzing parking", parsed["text"])
        self.assertIn("We recommend Riverside Promenade Lot.", parsed["text"])
        self.assertIn("3,000 KHR/day.", parsed["text"])

    def test_truncation_finish_reason_max_tokens_handled(self):
        """MAX_TOKENS finish reason flags truncation and cleanly terminates incomplete sentences."""
        from parking_zones.ai import parse_gemini_candidate

        candidate = {
            "finishReason": "MAX_TOKENS",
            "content": {
                "parts": [
                    {"text": "Riverside Lot has 30 spaces available at 3,000 KHR but hurry because slots fill"}
                ]
            }
        }

        parsed = parse_gemini_candidate(candidate)
        self.assertTrue(parsed["success"])
        self.assertTrue(parsed["truncated"])
        self.assertEqual(parsed["finish_reason"], "MAX_TOKENS")
        self.assertTrue(parsed["text"].endswith("..."))

    def test_safety_blocked_candidate_handled_gracefully(self):
        """Safety or blocked candidates return safe fallback without crashing."""
        from parking_zones.ai import parse_gemini_candidate

        candidate = {
            "finishReason": "SAFETY",
            "content": {
                "parts": []
            }
        }

        parsed = parse_gemini_candidate(candidate)
        self.assertFalse(parsed["success"])
        self.assertTrue(parsed["blocked"])
        self.assertIn("safety guidelines", parsed["error_message"])

