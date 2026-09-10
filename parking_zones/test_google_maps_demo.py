import json
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from parking_zones.models import ParkingZone


class GoogleMapsDemoIntegrationTest(TestCase):
    """Test suite for Google Maps Demo integration and key isolation."""

    def setUp(self):
        self.client = Client()
        self.zone1 = ParkingZone.objects.create(
            name='Riverside Promenade Lot',
            khmer_name='ចំណតមាត់ទន្លេ ស៊ីសុវត្ថិ',
            slug='riverside-promenade',
            num_of_slots=40,
            occupied_slots=10,
            vacant_slots=30,
            address='Preah Sisowath Quay, Daun Penh',
            district='Riverside / Daun Penh',
            price=3000,
            latitude=11.5683,
            longitude=104.9312
        )
        self.zone2 = ParkingZone.objects.create(
            name='BKK1 Commercial Plaza',
            khmer_name='ចំណតពាណិជ្ជកម្ម បឹងកេងកង១',
            slug='bkk1-commercial',
            num_of_slots=25,
            occupied_slots=25,
            vacant_slots=0,
            address='Street 282, Boeung Keng Kang 1',
            district='BKK1',
            price=4000,
            latitude=11.5510,
            longitude=104.9250
        )

    def test_home_page_renders_map_section_with_demo_label(self):
        """Home page must display the map section labeled Demo."""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)

        html = response.content.decode('utf-8')
        # Check for Demo badge
        self.assertIn('sp-badge-demo', html)
        self.assertIn('Demo', html)
        # Check for map canvas and fallback container
        self.assertIn('id="sompark-map-canvas"', html)
        self.assertIn('id="sompark-map-fallback"', html)

    def test_booking_flow_preserved_in_map_data_and_fallback(self):
        """Map markers and fallback directory must link directly to /book/?zone=<slug>."""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)

        # Check context JSON
        zones_json = response.context.get('zones_map_json')
        self.assertIsNotNone(zones_json)
        zones_data = json.loads(zones_json)
        
        riverside_item = next((z for z in zones_data if z['slug'] == 'riverside-promenade'), None)
        self.assertIsNotNone(riverside_item)
        self.assertEqual(riverside_item['book_url'], f"/book/?zone={self.zone1.slug}")
        self.assertEqual(riverside_item['lat'], 11.5683)
        self.assertEqual(riverside_item['lng'], 104.9312)

        html = response.content.decode('utf-8')
        # Check fallback button link preserving booking flow
        self.assertIn(f'/book/?zone={self.zone1.slug}', html)

    @override_settings(GOOGLE_MAPS_API_KEY='TEST_MAPS_DEMO_KEY_123', GEMINI_API_KEY='SECRET_GEMINI_KEY_DO_NOT_EXPOSE')
    def test_gemini_api_key_is_never_exposed_in_html_or_scripts(self):
        """Strict check: GEMINI_API_KEY must NEVER leak into HTML, scripts, or context."""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)

        html = response.content.decode('utf-8')
        # Google Maps key is allowed in the browser script tag
        self.assertIn('TEST_MAPS_DEMO_KEY_123', html)
        # Gemini key must NEVER be in the response
        self.assertNotIn('SECRET_GEMINI_KEY_DO_NOT_EXPOSE', html)
        self.assertNotIn('GEMINI_API_KEY', html)

        # Also check zone detail view
        detail_response = self.client.get(reverse('zone_detail', kwargs={'slug': self.zone1.slug}))
        self.assertEqual(detail_response.status_code, 200)
        detail_html = detail_response.content.decode('utf-8')
        self.assertIn('TEST_MAPS_DEMO_KEY_123', detail_html)
        self.assertNotIn('SECRET_GEMINI_KEY_DO_NOT_EXPOSE', detail_html)
        self.assertNotIn('GEMINI_API_KEY', detail_html)

    @override_settings(GOOGLE_MAPS_API_KEY='')
    def test_empty_maps_key_triggers_fallback_script(self):
        """When GOOGLE_MAPS_API_KEY is blank, fallback initialization script is rendered."""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')

        # When key is empty, Google Maps script is not requested; fallback is invoked
        self.assertNotIn('maps.googleapis.com/maps/api/js?key=', html)
        self.assertIn('initSomParkMapFallback', html)
