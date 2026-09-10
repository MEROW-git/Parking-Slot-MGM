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
        # Generate genuine cryptographically signed permit with timestamp 200s in the past
        from django.core.signing import TimestampSigner, b62_encode, b64_encode, JSONSerializer
        val = [self.staff.pk, self.reservation.pk, self.zone.pk, 'entry']
        signer = TimestampSigner(salt='virtual-gate')
        base_data = b64_encode(JSONSerializer().dumps(val)).decode()
        old_ts = b62_encode(int(time.time()) - 200)
        value_with_ts = f'{base_data}:{old_ts}'
        expired_token = f'{value_with_ts}:{signer.signature(value_with_ts)}'

        resp = self.client.post(
            self.url,
            {**self.data, 'action': 'pass', 'permit': expired_token}
        )
        self.assertContains(resp, 'Gate authorization expired or invalid')
        self.reservation.refresh_from_db()
        self.assertIsNone(self.reservation.checked_in_at)
        self.assertEqual(self.zone.occupied_slots, 0)

        # Test tampered/corrupted signature
        resp_tampered = self.client.post(
            self.url,
            {**self.data, 'action': 'pass', 'permit': 'tampered-signature-data'}
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

        # Settle via inline action='settle' -> directly opens barrier with signed permit (no duplicate check needed)
        settle_resp = self.client.post(self.url, {**data, 'action': 'settle', 'payment_provider': 'CASH'})
        self.assertTrue(settle_resp.context['gate_open'])
        self.assertEqual(settle_resp.context['bill']['balance_due'], 0)
        self.assertIsNotNone(settle_resp.context['permit'])
        permit = settle_resp.context['permit']

        # Vehicle passes through directly using permit from settle step
        pass_data = {**data, 'action': 'pass', 'permit': permit}
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

    def test_open_provides_permit_expires_at_timestamp(self):
        resp = self.client.post(self.url, self.data)
        self.assertTrue(resp.context['gate_open'])
        self.assertIsNotNone(resp.context['permit_expires_at'])
        self.assertGreater(resp.context['permit_expires_at'], int(time.time()))

    def test_ajax_passage_returns_structured_json_and_updates_occupancy(self):
        open_resp = self.client.post(self.url, self.data)
        permit = open_resp.context['permit']

        # Send AJAX passage confirmation
        pass_data = {**self.data, 'action': 'pass', 'permit': permit}
        ajax_resp = self.client.post(
            self.url,
            pass_data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(ajax_resp.status_code, 200)
        self.assertEqual(ajax_resp['Content-Type'], 'application/json')
        payload = ajax_resp.json()
        self.assertTrue(payload['success'])
        self.assertTrue(payload['passed'])
        self.assertFalse(payload['gate_open'])
        self.assertEqual(payload['status'], 'CHECKED_IN')
        self.assertEqual(payload['occupied_slots'], 1)
        self.assertEqual(payload['ticket_code'], self.reservation.ticket_code)

        self.reservation.refresh_from_db()
        self.zone.refresh_from_db()
        self.assertEqual(self.reservation.status, 'CHECKED_IN')
        self.assertEqual(self.zone.occupied_slots, 1)

    def test_ajax_passage_invalid_permit_returns_400_json(self):
        ajax_resp = self.client.post(
            self.url,
            {**self.data, 'action': 'pass', 'permit': 'invalid-permit-token'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(ajax_resp.status_code, 400)
        payload = ajax_resp.json()
        self.assertFalse(payload['success'])
        self.assertFalse(payload['passed'])
        self.assertIn('expired or invalid', payload['notice'])

        self.reservation.refresh_from_db()
        self.assertIsNone(self.reservation.checked_in_at)
        self.assertEqual(self.zone.occupied_slots, 0)

    def test_ajax_telemetry_get_reconciliation(self):
        get_url = f"{self.url}?zone={self.zone.pk}&code={self.reservation.ticket_code}&mode=entry"
        resp = self.client.get(get_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['ticket_code'], self.reservation.ticket_code)
        self.assertEqual(payload['status'], 'CONFIRMED')

    def test_missing_required_fields_in_passage_request_rejected(self):
        """
        Verify that if controls are disabled before FormData creation (causing zone,
        code, or mode to be missing), the server rejects the request with a 400 error.
        """
        open_resp = self.client.post(self.url, self.data)
        permit = open_resp.context['permit']

        # Missing 'code'
        bad_payload = {'zone': self.zone.pk, 'mode': 'entry', 'action': 'pass', 'permit': permit}
        resp = self.client.post(self.url, bad_payload, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['success'])

        # Missing 'zone'
        bad_payload2 = {'code': self.reservation.ticket_code, 'mode': 'entry', 'action': 'pass', 'permit': permit}
        resp2 = self.client.post(self.url, bad_payload2, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp2.status_code, 400)
        self.assertFalse(resp2.json()['success'])

    def test_template_renders_car_track_and_asset_versioning(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('virtual-gate.css?v=2.1.0', content)
        self.assertIn('virtual-gate.js?v=2.1.0', content)
        self.assertIn('vg-car-track', content)
        self.assertIn('data-direction="entry"', content)
        self.assertIn('data-just-passed="false"', content)

    def test_html_fallback_sets_just_passed_and_renders_replay_button(self):
        open_resp = self.client.post(self.url, self.data)
        permit = open_resp.context['permit']

        # Normal HTML POST passage
        pass_data = {**self.data, 'action': 'pass', 'permit': permit}
        resp = self.client.post(self.url, pass_data)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['passed'])
        self.assertTrue(resp.context['just_passed'])
        content = resp.content.decode()
        self.assertIn('data-just-passed="true"', content)
        self.assertIn('vg-replay-animation', content)

    # =========================================================================
    # ANPR License Plate Camera Simulator Tests
    # =========================================================================
    def test_anpr_plate_normalization_function(self):
        from .gate_machine import normalize_license_plate
        self.assertEqual(normalize_license_plate('Phnom Penh 2AZ-1234'), 'PHNOMPENH2AZ1234')
        self.assertEqual(normalize_license_plate('phnom penh  2az_1234.'), 'PHNOMPENH2AZ1234')
        self.assertEqual(normalize_license_plate(' 2B-5555 '), '2B5555')
        self.assertEqual(normalize_license_plate('2b 5555'), '2B5555')
        self.assertEqual(normalize_license_plate(''), '')
        self.assertEqual(normalize_license_plate(None), '')

    def test_anpr_plate_match_allows_entry_barrier_to_open(self):
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['gate_open'])
        self.assertTrue(response.context['plate_matched'])
        self.assertEqual(response.context['detected_plate'], 'Phnom Penh 2AZ-1234')
        self.assertEqual(response.context['expected_plate'], 'Phnom Penh 2AZ-1234')
        self.assertIsNotNone(response.context['permit'])
        content = response.content.decode()
        self.assertIn('PLATE MATCH', content)
        self.assertIn('Phnom Penh 2AZ-1234', content)

    def test_anpr_plate_normalization_matches_varied_casing_and_hyphens(self):
        # Detected plate with different spacing, hyphens, and casing
        data = {
            **self.data,
            'detected_plate': 'phnom penh 2az 1234',
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['plate_matched'])
        self.assertTrue(response.context['gate_open'])
        self.assertIsNotNone(response.context['permit'])

    def test_anpr_plate_mismatch_denies_entry_and_keeps_barrier_closed(self):
        # Simulate mismatch via developer checkbox and custom mismatch plate
        data = {
            **self.data,
            'simulate_plate_mismatch': 'true',
            'custom_detected_plate': '2X-9999',
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['gate_open'])
        self.assertFalse(response.context['plate_matched'])
        self.assertEqual(response.context['detected_plate'], '2X-9999')
        self.assertEqual(response.context['expected_plate'], 'Phnom Penh 2AZ-1234')
        self.assertIsNone(response.context.get('permit'))

        content = response.content.decode()
        self.assertIn('PLATE MISMATCH', content)
        self.assertIn('2X-9999', content)
        self.assertIn('ANPR Plate Mismatch', response.context['notice'])

        # Verify gate was not opened and reservation not checked in
        self.reservation.refresh_from_db()
        self.assertIsNone(self.reservation.checked_in_at)
        self.assertEqual(self.zone.occupied_slots, 0)

    def test_anpr_plate_mismatch_denies_exit_settlement(self):
        self.reservation.status = 'CHECKED_IN'
        self.reservation.checked_in_at = timezone.now() - timedelta(hours=1)
        self.reservation.save()
        self.zone.occupied_slots = 1
        self.zone.save()

        data = {
            **self.data,
            'mode': 'exit',
            'action': 'settle',
            'payment_provider': 'CASH',
            'simulate_plate_mismatch': 'true',
            'custom_detected_plate': '2X-9999',
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['gate_open'])
        self.assertFalse(response.context['plate_matched'])
        self.assertEqual(response.context['detected_plate'], '2X-9999')
        self.assertIn('ANPR Plate Mismatch', response.context['notice'])

        # Reservation must remain checked in and unpaid
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, 'CHECKED_IN')
        self.assertEqual(self.zone.occupied_slots, 1)

    def test_anpr_plate_result_preserved_during_three_step_exit_flow(self):
        self.reservation.status = 'CHECKED_IN'
        self.reservation.checked_in_at = timezone.now() - timedelta(hours=1)
        self.reservation.save()
        self.zone.occupied_slots = 1
        self.zone.save()

        data = {**self.data, 'mode': 'exit'}

        # Step 1: Check ticket in exit mode
        step1_resp = self.client.post(self.url, data)
        self.assertEqual(step1_resp.status_code, 200)
        self.assertTrue(step1_resp.context['plate_matched'])
        self.assertEqual(step1_resp.context['detected_plate'], 'Phnom Penh 2AZ-1234')
        self.assertFalse(step1_resp.context['gate_open'])  # Balance due 4000 KHR

        # Step 2: Settle balance with preserved detected_plate
        settle_data = {
            **data,
            'action': 'settle',
            'payment_provider': 'CASH',
            'detected_plate': step1_resp.context['detected_plate'],
        }
        step2_resp = self.client.post(self.url, settle_data)
        self.assertEqual(step2_resp.status_code, 200)
        self.assertTrue(step2_resp.context['plate_matched'])
        self.assertEqual(step2_resp.context['detected_plate'], 'Phnom Penh 2AZ-1234')
        self.assertTrue(step2_resp.context['gate_open'])
        permit = step2_resp.context['permit']
        self.assertIsNotNone(permit)

        # Step 3: Passage confirmed with permit
        pass_data = {
            **data,
            'action': 'pass',
            'permit': permit,
            'detected_plate': step2_resp.context['detected_plate'],
        }
        step3_resp = self.client.post(self.url, pass_data)
        self.assertEqual(step3_resp.status_code, 200)
        self.assertTrue(step3_resp.context['passed'])
        self.assertFalse(step3_resp.context['gate_open'])

        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, 'CHECKED_OUT')
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 0)

    def test_ui_anpr_camera_elements_and_direction_placement(self):
        # 1. Entrance mode GET
        resp_entry = self.client.get(f"{self.url}?mode=entry")
        self.assertEqual(resp_entry.status_code, 200)
        content_entry = resp_entry.content.decode()
        self.assertIn('vg-anpr-camera-unit', content_entry)
        self.assertIn('vg-anpr-beam', content_entry)
        self.assertIn('vg-anpr-hud', content_entry)
        self.assertIn('ANPR', content_entry)
        self.assertIn('data-direction="entry"', content_entry)
        self.assertIn('simulate_plate_mismatch', content_entry)
        self.assertIn('custom_detected_plate', content_entry)
        self.assertIn('ANPR SIMULATOR', content_entry)

        # 2. Exit mode GET
        resp_exit = self.client.get(f"{self.url}?mode=exit")
        self.assertEqual(resp_exit.status_code, 200)
        content_exit = resp_exit.content.decode()
        self.assertIn('data-direction="exit"', content_exit)
        self.assertIn('vg-anpr-camera-unit', content_exit)

        # 3. CSS stylesheet checks for direction-based camera positioning and rotation
        import os
        css_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'css', 'virtual-gate.css')
        with open(css_path, 'r', encoding='utf-8') as f:
            css_content = f.read()

        self.assertIn('.vg-scene[data-direction="entry"] .vg-anpr-camera-unit', css_content)
        self.assertIn('.vg-scene[data-direction="exit"] .vg-anpr-camera-unit', css_content)
        self.assertIn('left: calc(50% + 115px);', css_content)
        self.assertIn('.vg-car-plate', css_content)

    def test_ui_virtual_car_displays_license_plate(self):
        # Load reservation into virtual gate terminal
        resp = self.client.get(f"{self.url}?zone={self.zone.pk}&code={self.reservation.ticket_code}&mode=entry")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('vg-car-plate', content)
        self.assertIn('Phnom Penh 2AZ-1234', content)



