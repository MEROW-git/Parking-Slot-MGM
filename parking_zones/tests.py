import datetime
from datetime import timedelta, date, time
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from parking_zones.models import ParkingZone, Reservation, PaymentTransaction
from parking_zones.forms import ReservationForm, CAMBODIA_PROVINCES
from parking_zones.services import BillingService, CapacityService, PaymentService, GateService, ExpiryService
from parking_zones.payments import DemoPaymentAdapter



class ParkingZoneModelTests(TestCase):
    def setUp(self):
        self.zone = ParkingZone.objects.create(
            name='Test Central Zone',
            khmer_name='ចំណតសាកល្បង',
            slug='test-central-zone',
            num_of_slots=10,
            occupied_slots=2,
            vacant_slots=8,
            address='Street 101, Daun Penh, Phnom Penh',
            district='Riverside',
            price=3000,
            operating_hours='24/7',
        )

    def test_zone_properties(self):
        self.assertEqual(self.zone.price_khr_formatted, '3,000 ៛')
        self.assertEqual(self.zone.availability_status, 'available')
        self.assertFalse(self.zone.is_full)
        self.assertEqual(self.zone.occupancy_percentage, 20)

    def test_atomic_slot_decrement(self):
        self.zone.decrement_slot()
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 3)
        self.assertEqual(self.zone.vacant_slots, 7)

    def test_atomic_slot_increment(self):
        self.zone.increment_slot()
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 1)
        self.assertEqual(self.zone.vacant_slots, 9)

    def test_cannot_decrement_when_full(self):
        self.zone.vacant_slots = 0
        self.zone.occupied_slots = 10
        self.zone.save()
        self.assertTrue(self.zone.is_full)
        with self.assertRaises(ValidationError):
            self.zone.decrement_slot()

    def test_cannot_increment_when_empty(self):
        self.zone.occupied_slots = 0
        self.zone.vacant_slots = 10
        self.zone.save()
        with self.assertRaises(ValidationError):
            self.zone.increment_slot()


class ReservationFormValidationTests(TestCase):
    def setUp(self):
        self.zone = ParkingZone.objects.create(
            name='Valid Zone',
            slug='valid-zone',
            num_of_slots=10,
            occupied_slots=0,
            vacant_slots=10,
            address='Phnom Penh',
            district='BKK1',
            price=2500,
        )

    def test_valid_cambodian_plates_and_phones(self):
        valid_samples = [
            ('2AZ-1234', '+85512345678'),
            ('Phnom Penh 2BC-5678', '012345678'),
            ('1A-9999', '+855 98 765 432'),
            ('2M-1010', '098 765 432'),
        ]
        today = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)

        for plate, phone in valid_samples:
            form = ReservationForm(data={
                'parking_zone': self.zone.id,
                'start_date': today,
                'finish_date': tomorrow,
                'plate_number': plate,
                'phone_number': phone,
            })
            self.assertTrue(form.is_valid(), f"Failed for {plate} and {phone}: {form.errors}")

    def test_invalid_plate_format(self):
        today = datetime.date.today()
        form = ReservationForm(data={
            'parking_zone': self.zone.id,
            'start_date': today,
            'finish_date': today + datetime.timedelta(days=1),
            'plate_number': 'NOT-A-PLATE',
            'phone_number': '012345678',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('plate_number', form.errors)

    def test_invalid_phone_format(self):
        today = datetime.date.today()
        form = ReservationForm(data={
            'parking_zone': self.zone.id,
            'start_date': today,
            'finish_date': today + datetime.timedelta(days=1),
            'plate_number': '2AZ-1234',
            'phone_number': '12345',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('phone_number', form.errors)

    def test_finish_date_before_start_date(self):
        today = datetime.date.today()
        form = ReservationForm(data={
            'parking_zone': self.zone.id,
            'start_date': today,
            'finish_date': today - datetime.timedelta(days=1),
            'plate_number': '2AZ-1234',
            'phone_number': '012345678',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('finish_date', form.errors)


class BookingAndCheckoutWorkflowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='dara', password='secretpassword')
        self.other_user = User.objects.create_user(username='sokha', password='secretpassword')
        self.zone = ParkingZone.objects.create(
            name='Central Riverside',
            slug='central-riverside',
            num_of_slots=5,
            occupied_slots=1,
            vacant_slots=4,
            address='Sisowath Quay',
            district='Riverside',
            price=3000,
        )

    def test_homepage_renders(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'SomPark')
        self.assertContains(response, 'Central Riverside')

    def test_component_showcase_renders(self):
        response = self.client.get(reverse('component_showcase'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'SomPark Design System')

    def test_booking_requires_authentication(self):
        response = self.client.get(reverse('book'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/user/login/', response.url)

    def test_successful_booking_decrements_slot_and_creates_ticket(self):
        self.client.login(username='dara', password='secretpassword')
        today = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=2)

        response = self.client.post(reverse('book'), {
            'parking_zone': self.zone.id,
            'start_date': today.strftime('%Y-%m-%d'),
            'finish_date': tomorrow.strftime('%Y-%m-%d'),
            'plate_number': '2AZ-9988',
            'phone_number': '012345678',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.zone.refresh_from_db()
        # Creating a reservation holds capacity for arrival, but does not mark physically occupied until gate entry
        self.assertEqual(self.zone.occupied_slots, 1)
        self.assertEqual(self.zone.available_capacity_now, 3)

        reservation = Reservation.objects.get(customer=self.user, checked_out=False)
        self.assertEqual(reservation.plate_number, '2AZ-9988')
        self.assertTrue(reservation.ticket_code.startswith('SPK-'))

    def test_prevention_of_duplicate_active_reservations(self):
        self.client.login(username='dara', password='secretpassword')
        today = datetime.date.today()

        # First booking
        Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='2AZ-1111',
            phone_number='012345678',
            start_date=today,
            finish_date=today,
            ticket_code='SPK-TEST1',
            checked_out=False
        )

        # Attempt second booking while first is active
        response = self.client.post(reverse('book'), {
            'parking_zone': self.zone.id,
            'start_date': today.strftime('%Y-%m-%d'),
            'finish_date': today.strftime('%Y-%m-%d'),
            'plate_number': '2AZ-2222',
            'phone_number': '012345678',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already have an active reservation')
        # Total active reservations should still be 1
        self.assertEqual(Reservation.objects.filter(customer=self.user, checked_out=False).count(), 1)

    def test_rejection_when_zone_is_full(self):
        self.zone.vacant_slots = 0
        self.zone.occupied_slots = 5
        self.zone.save()

        self.client.login(username='dara', password='secretpassword')
        today = datetime.date.today()

        response = self.client.post(reverse('book'), {
            'parking_zone': self.zone.id,
            'start_date': today.strftime('%Y-%m-%d'),
            'finish_date': today.strftime('%Y-%m-%d'),
            'plate_number': '2AZ-3333',
            'phone_number': '012345678',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'currently at full capacity')
        self.assertEqual(Reservation.objects.count(), 0)

    def test_checkout_authorization_and_slot_increment(self):
        today = datetime.date.today()
        reservation = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='2AZ-4444',
            phone_number='012345678',
            start_date=today,
            finish_date=today,
            ticket_code='SPK-CHECKOUT1',
            status='CHECKED_IN',
            deposit_amount=self.zone.price,
            checked_out=False
        )
        self.assertEqual(self.zone.occupied_slots, 1)

        # Other user cannot checkout Dara's ticket
        self.client.login(username='sokha', password='secretpassword')
        res_forbidden = self.client.post(reverse('checkout'), {'ticket_code': reservation.ticket_code})
        self.assertEqual(res_forbidden.status_code, 403)

        # GET request is rejected (POST-only enforced)
        res_get = self.client.get(reverse('checkout'))
        self.assertEqual(res_get.status_code, 405)

        # Owner Dara requests checkout - customer endpoint cannot mark departure or release space
        self.client.login(username='dara', password='secretpassword')
        res_ok = self.client.post(reverse('checkout'), {'ticket_code': reservation.ticket_code}, follow=True)
        self.assertEqual(res_ok.status_code, 200)

        reservation.refresh_from_db()
        self.assertFalse(reservation.checked_out)
        self.assertEqual(reservation.status, 'CHECKED_IN')
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 1)
        self.assertEqual(self.zone.vacant_slots, 4)

        # Only physical gate confirmation records exit and releases capacity
        success, reservation, msg = GateService.confirm_physical_exit(reservation.pk)
        self.assertTrue(success)
        reservation.refresh_from_db()
        self.assertTrue(reservation.checked_out)
        self.assertEqual(reservation.status, 'CHECKED_OUT')
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 0)
        self.assertEqual(self.zone.vacant_slots, 5)


class TicketViewBrandingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='dara', password='secretpassword')
        self.zone = ParkingZone.objects.create(
            name='Wat Phnom Riverside Slot',
            slug='wat-phnom-riverside',
            num_of_slots=10,
            occupied_slots=1,
            vacant_slots=9,
            address='Street 94, Daun Penh, Phnom Penh',
            price=2500,
        )
        self.today = datetime.date.today()
        self.now = timezone.now()
        self.reservation = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='2AZ-9999',
            phone_number='012345678',
            start_date=self.today,
            finish_date=self.today,
            ticket_code='SPK-TESTBRAND',
            status='CONFIRMED',
            payment_method='PAY_AT_EXIT',
            arrival_deadline=self.now + datetime.timedelta(hours=3),
            checked_out=False
        )

    def test_ticket_header_branding(self):
        self.client.login(username='dara', password='secretpassword')
        response = self.client.get(reverse('ticket_code', args=[self.reservation.ticket_code]))
        self.assertEqual(response.status_code, 200)

        # Confirm single centered container and layout order
        self.assertContains(response, 'id="ticket-page-container"')
        self.assertContains(response, 'id="ticket-nav-bar"')
        self.assertContains(response, '← Ticket History')
        self.assertContains(response, 'id="ticket-actions-bar"')
        self.assertContains(response, 'id="arrival-countdown-card"')
        self.assertContains(response, 'id="parking-ticket-sheet"')
        self.assertContains(response, 'id="ticket-brand"')
        self.assertContains(response, '<span class="sp-brand-mark" aria-hidden="true">P</span>')
        self.assertContains(response, '<strong>SomPark</strong>')
        self.assertContains(response, '<small>PHNOM PENH</small>')
        self.assertContains(response, 'id="ticket-khmer-tagline"')
        self.assertContains(response, 'ចំណតឆ្លាតវៃ សម្រាប់រាជធានីភ្នំពេញ')

        # Confirm old adult-site-like split badge with Khmer text inside orange rectangle is removed
        self.assertNotContains(response, '<span class="sp-brand-badge">ភ្នំពេញ</span>')

        # Confirm ticket functionality and layout preserved
        self.assertContains(response, '* SPK-TESTBRAND *')
        self.assertContains(response, 'Wat Phnom Riverside Slot')
        self.assertContains(response, '2AZ-9999')
        self.assertContains(response, 'Print ticket (បោះពុម្ព)')
        self.assertContains(response, 'Show at Gate (បង្ហាញនៅរបាំង)')
        self.assertContains(response, 'Cancel reservation (បោះបង់)')

        # Confirm checkout is NOT shown for a CONFIRMED hold waiting for entry
        self.assertNotContains(response, 'Proceed to exit (ចេញពីចំណត)')
        self.assertNotContains(response, 'id="btn-checkout-ticket"')

        # Confirm accessible cancel confirmation dialog exists
        self.assertContains(response, 'id="cancel-reservation-dialog"')
        self.assertContains(response, 'id="btn-confirm-cancel"')

    def test_ticket_state_checked_in_actions(self):
        self.reservation.status = 'CHECKED_IN'
        self.reservation.checked_in_at = self.now
        self.reservation.save()

        self.client.login(username='dara', password='secretpassword')
        response = self.client.get(reverse('ticket_code', args=[self.reservation.ticket_code]))
        self.assertEqual(response.status_code, 200)

        # Checked in with balance due: show at gate, print ticket, pay & prepare to leave
        self.assertContains(response, 'Show at Gate (បង្ហាញនៅរបាំង)')
        self.assertContains(response, 'Print ticket (បោះពុម្ព)')
        self.assertContains(response, 'Pay & prepare to leave')
        self.assertContains(response, 'id="btn-pay-exit"')

        # No Cancel Hold button for checked in vehicle
        self.assertNotContains(response, 'id="btn-open-cancel-dialog"')
        self.assertNotContains(response, 'Cancel reservation (បោះបង់)')

        # Arrival banner must be hidden after check-in
        self.assertNotContains(response, 'id="arrival-countdown-card"')

    def test_ticket_state_payment_pending_actions(self):
        self.reservation.status = 'PAYMENT_PENDING'
        self.reservation.save()

        self.client.login(username='dara', password='secretpassword')
        response = self.client.get(reverse('ticket_code', args=[self.reservation.ticket_code]))
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, 'Continue payment (បន្តទៅការទូទាត់)')
        self.assertContains(response, 'id="btn-continue-payment"')
        self.assertContains(response, 'Cancel reservation (បោះបង់)')
        self.assertContains(response, 'Pass Inactive')
        self.assertContains(response, 'Payment Required')
        self.assertNotContains(response, 'id="btn-checkout-ticket"')

    def test_ticket_state_checked_out_actions(self):
        self.reservation.status = 'CHECKED_OUT'
        self.reservation.checked_out = True
        self.reservation.save()

        self.client.login(username='dara', password='secretpassword')
        response = self.client.get(reverse('ticket_code', args=[self.reservation.ticket_code]))
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, 'View / Print receipt (បោះពុម្ពបង្កាន់ដៃ)')
        self.assertContains(response, 'id="btn-print-receipt"')
        self.assertNotContains(response, 'id="btn-checkout-ticket"')
        self.assertNotContains(response, 'id="btn-show-gate-mode"')
        self.assertNotContains(response, 'id="btn-open-cancel-dialog"')

    def test_ticket_state_cancelled_or_expired_actions(self):
        self.reservation.status = 'EXPIRED'
        self.reservation.save()

        self.client.login(username='dara', password='secretpassword')
        response = self.client.get(reverse('ticket_code', args=[self.reservation.ticket_code]))
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, 'Reserve again (កក់ម្តងទៀត)')
        self.assertContains(response, 'id="btn-reserve-again"')
        self.assertNotContains(response, 'id="btn-checkout-ticket"')
        self.assertNotContains(response, 'id="btn-show-gate-mode"')

    def test_arrival_banner_concise_copy_and_no_emoji(self):
        self.client.login(username='dara', password='secretpassword')
        response = self.client.get(reverse('ticket_code', args=[self.reservation.ticket_code]))
        self.assertEqual(response.status_code, 200)

        # Banner copy
        self.assertContains(response, 'Enter within 3 hours after booking. Pay when you leave.')
        self.assertContains(response, 'Enter before')
        self.assertContains(response, 'Time remaining:')
        self.assertContains(response, 'id="arrival-timer"')

        # No decorative emoji
        self.assertNotContains(response, '🚗')

    def test_server_checkout_rejected_when_not_checked_in(self):
        # Confirmed hold attempting checkout
        self.client.login(username='dara', password='secretpassword')
        resp = self.client.post(reverse('checkout'), {'ticket_code': self.reservation.ticket_code}, follow=True)
        self.assertContains(resp, 'Cannot check out a reservation that has not checked in')
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.status, 'CONFIRMED')
        self.assertFalse(self.reservation.checked_out)


class VehiclePlateAndBookingFormTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='customer1', password='pass1234')
        self.staff_user = User.objects.create_user(username='staff1', password='pass1234', is_staff=True)
        self.zone = ParkingZone.objects.create(
            name='Wat Botum Park Spot',
            khmer_name='ចំណតវត្តបទុម',
            slug='wat-botum-park-spot',
            num_of_slots=5,
            occupied_slots=0,
            vacant_slots=5,
            address='Oknha Suor Srun St 7, Phnom Penh',
            district='Daun Penh',
            price=2000,
        )
        self.today = datetime.date.today()
        self.tomorrow = self.today + datetime.timedelta(days=1)

    def test_cambodia_provinces_constant(self):
        # 1 custom Cambodia option + 1 capital + 24 provinces = 26 total
        self.assertEqual(len(CAMBODIA_PROVINCES), 26)
        self.assertEqual(CAMBODIA_PROVINCES[0][0], 'Cambodia')
        self.assertEqual(CAMBODIA_PROVINCES[1][0], 'Phnom Penh')

    def test_booking_page_renders_province_and_code_fields(self):
        self.client.login(username='customer1', password='pass1234')
        response = self.client.get(reverse('book'))
        self.assertEqual(response.status_code, 200)

        # Date input elements present
        self.assertContains(response, 'id="id_start_date"')
        self.assertContains(response, 'id="id_finish_date"')

        # Form group and legend
        self.assertContains(response, 'Vehicle Plate Number (ស្លាកលេខយានយន្ត)')
        self.assertContains(response, 'City / Province (រាជធានី / ខេត្ត)')
        self.assertContains(response, 'Plate Number (លេខផ្លាក)')

        # Province selector and code input
        self.assertContains(response, 'name="plate_province"')
        self.assertContains(response, 'id="id_plate_province"')
        self.assertContains(response, 'name="plate_code"')
        self.assertContains(response, 'id="id_plate_code"')

        # Phnom Penh option present
        self.assertContains(response, 'Cambodia / កម្ពុជា — Custom plate')
        self.assertContains(response, 'Phnom Penh / ភ្នំពេញ')
        self.assertContains(response, 'Siem Reap / សៀមរាប')

        # Live preview element
        self.assertContains(response, 'id="plate-preview-box"')
        self.assertContains(response, 'Plate preview (ការមើលស្លាកលេខជាមុន):')
        self.assertContains(response, 'id="plate-preview-text"')
        self.assertContains(response, 'Enter your plate number to preview (សូមបញ្ចូលលេខផ្លាកដើម្បីមើលជាមុន)')

        # Accessibility attributes
        self.assertContains(response, 'autocapitalize="characters"')
        self.assertContains(response, 'spellcheck="false"')
        self.assertContains(response, 'autocomplete="off"')

    def test_booking_page_redesigned_payment_section(self):
        self.client.login(username='customer1', password='pass1234')
        response = self.client.get(reverse('book'))
        self.assertEqual(response.status_code, 200)

        # 1. Simplified Payment Heading & Dynamic Facility Rate
        self.assertContains(response, 'How would you like to pay? (តើអ្នកចង់ទូទាត់ប្រាក់ដោយរបៀបណា?)')
        self.assertContains(response, 'Daily parking rate:')
        self.assertContains(response, 'id="facility-rate-amount"')

        # 2. Card A: Pay first day now
        self.assertContains(response, 'id="card-pay-deposit"')
        self.assertContains(response, 'Pay first day now')
        self.assertContains(response, 'បង់ប្រាក់១ថ្ងៃដំបូងឥឡូវនេះ')
        self.assertContains(response, 'Pay the remaining balance when you leave. Your first payment is deducted from the total.')
        self.assertContains(response, 'Within your booked arrival window.')

        # 3. Card B: Pay when you leave
        self.assertContains(response, 'id="card-pay-exit"')
        self.assertContains(response, 'Pay when you leave')
        self.assertContains(response, 'បង់ប្រាក់នៅពេលអ្នកចេញ')
        self.assertContains(response, '0 ៛')
        self.assertContains(response, 'Pay for your actual parking time at exit.')
        self.assertContains(response, 'Enter within 3 hours after booking. Pay when you leave.')

        # Verify removal of old badges and technical phrases
        self.assertNotContains(response, 'RECOMMENDED')
        self.assertNotContains(response, 'Select Payment Policy')
        self.assertNotContains(response, 'Phnom Penh 2AZ-1234')

        # 4. Compact Pricing Box & Accessible Disclosure
        self.assertContains(response, 'Leave early? Pay only for the time you parked.')
        self.assertContains(response, 'Stay past your booked end? Extra days cost 2× the daily rate.')
        self.assertContains(response, 'Normal day (ថ្ងៃធម្មតា)')
        self.assertContains(response, 'Each overstay day (រាល់ថ្ងៃលើសម៉ោង)')
        self.assertContains(response, 'includes the normal daily charge.')
        self.assertContains(response, 'How charges are calculated (របៀបគណនាថ្លៃសេវា)')

        # 5. Pre-Submit Summary
        self.assertContains(response, 'id="booking-submit-summary"')
        self.assertContains(response, 'Due now (ចំនួនត្រូវបង់ឥឡូវនេះ):')
        self.assertContains(response, 'Remaining parking charges are paid at exit.')
        self.assertContains(response, 'Continue to payment (បន្តទៅការទូទាត់) →')

        # 6. Dynamic JSON Data
        self.assertContains(response, 'id="parking-zones-data"')

    def test_unbound_form_defaults_to_phnom_penh(self):
        form = ReservationForm()
        self.assertEqual(form.fields['plate_province'].initial, 'Phnom Penh')

        self.client.login(username='customer1', password='pass1234')
        response = self.client.get(reverse('book'))
        self.assertContains(response, '<option value="Phnom Penh" selected>Phnom Penh / ភ្នំពេញ</option>')

    def test_valid_split_input_saves_combined_plate(self):
        self.client.login(username='customer1', password='pass1234')
        post_data = {
            'parking_zone': self.zone.id,
            'start_date': self.today,
            'finish_date': self.tomorrow,
            'plate_province': 'Phnom Penh',
            'plate_code': '2AZ-1234',
            'phone_number': '012345678',
        }
        response = self.client.post(reverse('book'), post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        reservation = Reservation.objects.filter(customer=self.user).first()
        self.assertIsNotNone(reservation)
        self.assertEqual(reservation.plate_number, 'Phnom Penh 2AZ-1234')

    def test_province_and_code_remain_bound_when_another_field_fails(self):
        self.client.login(username='customer1', password='pass1234')
        # Submitting with an invalid phone number to force form failure
        post_data = {
            'parking_zone': self.zone.id,
            'start_date': self.today,
            'finish_date': self.tomorrow,
            'plate_province': 'Siem Reap',
            'plate_code': '2az-1234',
            'phone_number': 'invalid-phone',
        }
        response = self.client.post(reverse('book'), post_data)
        self.assertEqual(response.status_code, 200)

        form = response.context['form']
        self.assertEqual(form['plate_province'].value(), 'Siem Reap')
        self.assertEqual(form['plate_code'].value(), '2az-1234')
        self.assertContains(response, 'value="2az-1234"')

    def test_missing_province_is_rejected(self):
        form = ReservationForm(data={
            'parking_zone': self.zone.id,
            'start_date': self.today,
            'finish_date': self.tomorrow,
            'plate_province': '',
            'plate_code': '2AZ-1234',
            'phone_number': '012345678',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('plate_province', form.errors)

    def test_missing_plate_code_is_rejected(self):
        form = ReservationForm(data={
            'parking_zone': self.zone.id,
            'start_date': self.today,
            'finish_date': self.tomorrow,
            'plate_province': 'Phnom Penh',
            'plate_code': '',
            'phone_number': '012345678',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('plate_code', form.errors)

    def test_lowercase_plate_letters_normalized_to_uppercase(self):
        form = ReservationForm(data={
            'parking_zone': self.zone.id,
            'start_date': self.today,
            'finish_date': self.tomorrow,
            'plate_province': 'Battambang',
            'plate_code': '2az-9999',
            'phone_number': '012345678',
        })
        self.assertTrue(form.is_valid(), f"Errors: {form.errors}")
        self.assertEqual(form.cleaned_data['plate_number'], 'Battambang 2AZ-9999')

    def test_extra_spaces_are_normalized(self):
        form = ReservationForm(data={
            'parking_zone': self.zone.id,
            'start_date': self.today,
            'finish_date': self.tomorrow,
            'plate_province': 'Kandal',
            'plate_code': '   2AZ    1234   ',
            'phone_number': '012345678',
        })
        self.assertTrue(form.is_valid(), f"Errors: {form.errors}")
        self.assertEqual(form.cleaned_data['plate_number'], 'Kandal 2AZ-1234')

    def test_cambodia_custom_plate_allows_text_without_digits(self):
        form = ReservationForm(data={
            'parking_zone': self.zone.id,
            'start_date': self.today,
            'finish_date': self.tomorrow,
            'plate_province': 'Cambodia',
            'plate_code': 'my car',
            'phone_number': '012345678',
        })
        self.assertTrue(form.is_valid(), f"Errors: {form.errors}")
        self.assertEqual(form.cleaned_data['plate_number'], 'Cambodia MY CAR')

    def test_standard_plate_space_is_saved_as_hyphen(self):
        form = ReservationForm(data={
            'parking_zone': self.zone.id,
            'start_date': self.today,
            'finish_date': self.tomorrow,
            'plate_province': 'Phnom Penh',
            'plate_code': '2az 1234',
            'phone_number': '012345678',
        })
        self.assertTrue(form.is_valid(), f"Errors: {form.errors}")
        self.assertEqual(form.cleaned_data['plate_number'], 'Phnom Penh 2AZ-1234')

    def test_invalid_characters_are_rejected(self):
        form = ReservationForm(data={
            'parking_zone': self.zone.id,
            'start_date': self.today,
            'finish_date': self.tomorrow,
            'plate_province': 'Phnom Penh',
            'plate_code': '2AZ@1234#',
            'phone_number': '012345678',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('plate_code', form.errors)

    def test_code_without_digit_is_rejected(self):
        form = ReservationForm(data={
            'parking_zone': self.zone.id,
            'start_date': self.today,
            'finish_date': self.tomorrow,
            'plate_province': 'Phnom Penh',
            'plate_code': 'ABC-XYZ',
            'phone_number': '012345678',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('plate_code', form.errors)

    def test_existing_legacy_plate_values_and_reservations_continue_to_work(self):
        # Direct submission using legacy plate_number
        form = ReservationForm(data={
            'parking_zone': self.zone.id,
            'start_date': self.today,
            'finish_date': self.tomorrow,
            'plate_number': '2AZ-5555',
            'phone_number': '012345678',
        })
        self.assertTrue(form.is_valid(), f"Errors: {form.errors}")
        self.assertEqual(form.cleaned_data['plate_number'], '2AZ-5555')

        # Existing reservation created directly with legacy plate
        res = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='LEGACY-1234',
            phone_number='012345678',
            start_date=self.today,
            finish_date=self.tomorrow,
            ticket_code='SPK-LEGACY1',
            checked_out=False
        )
        self.client.login(username='customer1', password='pass1234')
        response = self.client.get(reverse('ticket_code', args=[res.ticket_code]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'LEGACY-1234')

    def test_booking_decrements_available_parking_capacity_correctly(self):
        self.assertEqual(self.zone.vacant_slots, 5)
        self.assertEqual(self.zone.occupied_slots, 0)

        self.client.login(username='customer1', password='pass1234')
        post_data = {
            'parking_zone': self.zone.id,
            'start_date': self.today,
            'finish_date': self.tomorrow,
            'plate_province': 'Kampot',
            'plate_code': '3A-5678',
            'phone_number': '012345678',
        }
        response = self.client.post(reverse('book'), post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        self.zone.refresh_from_db()
        # Reservation holds spot for arrival without incrementing physical occupancy before gate check-in
        self.assertEqual(self.zone.occupied_slots, 0)
        self.assertEqual(self.zone.available_capacity_now, 4)

    def test_existing_date_validation_still_passes(self):
        # Past start date rejected
        past_date = self.today - datetime.timedelta(days=2)
        form_past = ReservationForm(data={
            'parking_zone': self.zone.id,
            'start_date': past_date,
            'finish_date': self.tomorrow,
            'plate_province': 'Phnom Penh',
            'plate_code': '2AZ-1234',
            'phone_number': '012345678',
        })
        self.assertFalse(form_past.is_valid())
        self.assertIn('start_date', form_past.errors)

        # Finish date before start date rejected
        form_reversed = ReservationForm(data={
            'parking_zone': self.zone.id,
            'start_date': self.tomorrow,
            'finish_date': self.today,
            'plate_province': 'Phnom Penh',
            'plate_code': '2AZ-1234',
            'phone_number': '012345678',
        })
        self.assertFalse(form_reversed.is_valid())
        self.assertIn('finish_date', form_reversed.errors)

    def test_ticket_dashboard_and_admin_pages_display_combined_plate(self):
        res = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='Siem Reap 2AZ-7777',
            phone_number='012345678',
            start_date=self.today,
            finish_date=self.tomorrow,
            ticket_code='SPK-SR7777',
            checked_out=False
        )

        # 1. Customer Ticket page
        self.client.login(username='customer1', password='pass1234')
        ticket_res = self.client.get(reverse('ticket_code', args=[res.ticket_code]))
        self.assertEqual(ticket_res.status_code, 200)
        self.assertContains(ticket_res, 'Siem Reap 2AZ-7777')

        # 2. Customer Dashboard page
        dash_res = self.client.get(reverse('dashboard'))
        self.assertEqual(dash_res.status_code, 200)
        self.assertContains(dash_res, 'Siem Reap 2AZ-7777')

        # 3. Staff Admin Operations Dashboard page
        self.client.login(username='staff1', password='pass1234')
        admin_res = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(admin_res.status_code, 200)
        self.assertContains(admin_res, 'Siem Reap 2AZ-7777')


class WorkflowBillingAndGateTests(TestCase):
    """
    Exhaustive verification of billing calculations, overstay penalty,
    arrival holds, payment timeouts, QR entry/exit, capacity, and security.
    """
    def setUp(self):
        self.user = User.objects.create_user(username='tester_driver', password='testpass123')
        self.staff = User.objects.create_user(username='gate_officer', password='staffpass123', is_staff=True)
        self.other_user = User.objects.create_user(username='other_driver', password='testpass123')

        self.zone = ParkingZone.objects.create(
            name='Central Riverside Garage',
            khmer_name='ចំណតមាត់ទន្លេកណ្តាល',
            slug='central-riverside-garage',
            num_of_slots=5,
            occupied_slots=1,
            vacant_slots=4,
            address='Preah Sisowath Quay, Phnom Penh',
            district='Daun Penh',
            price=4000,  # 4,000 KHR per day
            operating_hours='24/7'
        )

        self.client = Client()

    # -------------------------------------------------------------
    # 1. BILLING CALCULATIONS (Prompt Exact Examples at 4,000 KHR/day)
    # -------------------------------------------------------------
    def test_billing_example_1_book_4_days_stay_2_days(self):
        """
        Book 4 days, stay 2:
        Total = 8,000 KHR
        With 4,000 KHR deposit: balance = 4,000 KHR
        """
        t0 = timezone.now()
        res = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2AZ-1111',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=4)).date(),
            finish_time=t0 + timedelta(days=4),
            daily_rate=4000,
            overstay_multiplier=2.0,
            payment_method='DEPOSIT',
            deposit_amount=4000,
            payment_status='PARTIALLY_PAID',
            status='CHECKED_IN',
            checked_in_at=t0
        )

        actual_exit = t0 + timedelta(days=2)
        bill = BillingService.calculate_bill(res, as_of=actual_exit)

        self.assertEqual(bill['normal_days'], 2)
        self.assertEqual(bill['overstay_days'], 0)
        self.assertEqual(bill['normal_charge'], 8000)
        self.assertEqual(bill['overstay_charge'], 0)
        self.assertEqual(bill['total_amount'], 8000)
        self.assertEqual(bill['deposit_deducted'], 4000)
        self.assertEqual(bill['balance_due'], 4000)

    def test_billing_example_2_book_4_days_stay_4_days(self):
        """
        Book 4 days, stay 4:
        Total = 16,000 KHR
        With deposit: balance = 12,000 KHR
        """
        t0 = timezone.now()
        res = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2AZ-2222',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=4)).date(),
            finish_time=t0 + timedelta(days=4),
            daily_rate=4000,
            overstay_multiplier=2.0,
            payment_method='DEPOSIT',
            deposit_amount=4000,
            payment_status='PARTIALLY_PAID',
            status='CHECKED_IN',
            checked_in_at=t0
        )

        actual_exit = t0 + timedelta(days=4)
        bill = BillingService.calculate_bill(res, as_of=actual_exit)

        self.assertEqual(bill['normal_days'], 4)
        self.assertEqual(bill['overstay_days'], 0)
        self.assertEqual(bill['normal_charge'], 16000)
        self.assertEqual(bill['overstay_charge'], 0)
        self.assertEqual(bill['total_amount'], 16000)
        self.assertEqual(bill['deposit_deducted'], 4000)
        self.assertEqual(bill['balance_due'], 12000)

    def test_billing_example_3_book_4_days_stay_5_days_double_rate(self):
        """
        Book 4 days, stay 5:
        Normal portion = 4 × 4,000 = 16,000 KHR
        Overstay portion = 1 × 8,000 = 8,000 KHR
        Total = 24,000 KHR
        With deposit: balance = 20,000 KHR

        The double rate INCLUDES the normal charge for that overstay period (strictly 2x, not 3x).
        """
        t0 = timezone.now()
        res = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2AZ-3333',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=4)).date(),
            finish_time=t0 + timedelta(days=4),
            daily_rate=4000,
            overstay_multiplier=2.0,
            payment_method='DEPOSIT',
            deposit_amount=4000,
            payment_status='PARTIALLY_PAID',
            status='CHECKED_IN',
            checked_in_at=t0
        )

        actual_exit = t0 + timedelta(days=5)
        bill = BillingService.calculate_bill(res, as_of=actual_exit)

        self.assertEqual(bill['normal_days'], 4)
        self.assertEqual(bill['overstay_days'], 1)
        self.assertEqual(bill['normal_charge'], 16000)
        self.assertEqual(bill['overstay_charge'], 8000)
        self.assertEqual(bill['total_amount'], 24000)
        self.assertEqual(bill['deposit_deducted'], 4000)
        self.assertEqual(bill['balance_due'], 20000)

    def test_billing_example_4_book_4_days_stay_6_days(self):
        """
        Book 4 days, stay 6:
        Total = 16,000 + 16,000 = 32,000 KHR
        With deposit: balance = 28,000 KHR
        """
        t0 = timezone.now()
        res = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2AZ-4444',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=4)).date(),
            finish_time=t0 + timedelta(days=4),
            daily_rate=4000,
            overstay_multiplier=2.0,
            payment_method='DEPOSIT',
            deposit_amount=4000,
            payment_status='PARTIALLY_PAID',
            status='CHECKED_IN',
            checked_in_at=t0
        )

        actual_exit = t0 + timedelta(days=6)
        bill = BillingService.calculate_bill(res, as_of=actual_exit)

        self.assertEqual(bill['normal_days'], 4)
        self.assertEqual(bill['overstay_days'], 2)
        self.assertEqual(bill['normal_charge'], 16000)
        self.assertEqual(bill['overstay_charge'], 16000)
        self.assertEqual(bill['total_amount'], 32000)
        self.assertEqual(bill['deposit_deducted'], 4000)
        self.assertEqual(bill['balance_due'], 28000)

    def test_partial_days_and_exact_boundaries(self):
        """
        1-day minimum after entry.
        Exact booked end exit has no overstay.
        Partial overstay rounds up to started 24-hour block.
        """
        t0 = timezone.now()
        res = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='Kandal 2B-5555',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=1)).date(),
            finish_time=t0 + timedelta(days=1),
            daily_rate=4000,
            overstay_multiplier=2.0,
            payment_method='PAY_AT_EXIT',
            status='CHECKED_IN',
            checked_in_at=t0
        )

        # 1. Parked only 2 hours: minimum 1 billable day
        bill_2h = BillingService.calculate_bill(res, as_of=t0 + timedelta(hours=2))
        self.assertEqual(bill_2h['normal_days'], 1)
        self.assertEqual(bill_2h['overstay_days'], 0)
        self.assertEqual(bill_2h['total_amount'], 4000)

        # 2. Exact finish time exit: 0 overstay
        bill_exact = BillingService.calculate_bill(res, as_of=t0 + timedelta(days=1))
        self.assertEqual(bill_exact['normal_days'], 1)
        self.assertEqual(bill_exact['overstay_days'], 0)
        self.assertEqual(bill_exact['total_amount'], 4000)

        # 3. 1 minute past booked finish: rounds up to 1 full started overstay day (2x rate)
        bill_over_1m = BillingService.calculate_bill(res, as_of=t0 + timedelta(days=1, minutes=1))
        self.assertEqual(bill_over_1m['normal_days'], 1)
        self.assertEqual(bill_over_1m['overstay_days'], 1)
        self.assertEqual(bill_over_1m['total_amount'], 12000)  # 4000 + 8000

    def test_price_snapshotting_protects_existing_bookings(self):
        """
        Changing the zone's daily rate later does NOT affect already created reservations.
        """
        t0 = timezone.now()
        res = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2AZ-9999',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=2)).date(),
            finish_time=t0 + timedelta(days=2),
            daily_rate=4000,
            payment_method='PAY_AT_EXIT',
            status='CHECKED_IN',
            checked_in_at=t0
        )

        # Zone price increases dramatically to 10,000 KHR
        self.zone.price = 10000
        self.zone.save()

        bill = BillingService.calculate_bill(res, as_of=t0 + timedelta(days=2))
        self.assertEqual(bill['daily_rate'], 4000)
        self.assertEqual(bill['total_amount'], 8000)

    # -------------------------------------------------------------
    # 2. ARRIVAL EXPIRY & CAPACITY LIFECYCLE
    # -------------------------------------------------------------
    def test_three_hour_expiry_before_entry_but_never_after_entry(self):
        """
        Pay at exit holds expire after 3 hours if un-checked-in.
        Once checked in, the 3-hour expiry stops applying forever.
        """
        t0 = timezone.now() - timedelta(hours=4)
        res_unattended = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2AZ-0001',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=1)).date(),
            finish_time=t0 + timedelta(days=1),
            payment_method='PAY_AT_EXIT',
            arrival_deadline=t0 + timedelta(hours=3),
            status='CONFIRMED',
            created_on=t0
        )

        res_parked = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2AZ-0002',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=1)).date(),
            finish_time=t0 + timedelta(days=1),
            payment_method='PAY_AT_EXIT',
            arrival_deadline=t0 + timedelta(hours=3),
            status='CHECKED_IN',
            checked_in_at=t0 + timedelta(minutes=30),
            created_on=t0
        )

        expired_count = ExpiryService.expire_unpaid_holds()
        self.assertGreaterEqual(expired_count, 1)

        res_unattended.refresh_from_db()
        self.assertEqual(res_unattended.status, 'EXPIRED')

        res_parked.refresh_from_db()
        self.assertEqual(res_parked.status, 'CHECKED_IN')

    def test_deposit_payment_failure_cancel_and_success(self):
        """
        Deposit payment failure and cancellation allow safe retry.
        Successful payment confirms reservation and records transaction.
        """
        t0 = timezone.now()
        res = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='Phnom Penh 2AZ-7771',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=2)).date(),
            finish_time=t0 + timedelta(days=2),
            payment_method='DEPOSIT',
            status='PAYMENT_PENDING'
        )

        txn = PaymentService.create_deposit_transaction(res)
        self.assertEqual(txn.status, 'PENDING')

        # 1. Simulate failure
        success, msg = DemoPaymentAdapter.simulate_payment(txn.id, 'failure')
        self.assertFalse(success)
        txn.refresh_from_db()
        self.assertEqual(txn.status, 'FAILED')
        res.refresh_from_db()
        self.assertEqual(res.status, 'PAYMENT_PENDING')

        # 2. Simulate cancellation
        txn2 = PaymentService.create_deposit_transaction(res)
        success, msg = DemoPaymentAdapter.simulate_payment(txn2.id, 'cancel')
        self.assertFalse(success)
        txn2.refresh_from_db()
        self.assertEqual(txn2.status, 'CANCELLED')
        res.refresh_from_db()
        self.assertEqual(res.status, 'PAYMENT_PENDING')

        # 3. Simulate success
        txn3 = PaymentService.create_deposit_transaction(res)
        success, msg = DemoPaymentAdapter.simulate_payment(txn3.id, 'success')
        self.assertTrue(success)
        txn3.refresh_from_db()
        self.assertEqual(txn3.status, 'SUCCESS')
        res.refresh_from_db()
        self.assertEqual(res.status, 'CONFIRMED')
        self.assertEqual(res.payment_status, 'PARTIALLY_PAID')

    # -------------------------------------------------------------
    # 3. GATE ENTRY & EXIT WORKFLOW
    # -------------------------------------------------------------
    def test_gate_entry_and_duplicate_scan_prevention(self):
        """
        Entry converts hold to physical occupancy atomically.
        Repeated scans do not alter capacity or record duplicate check-ins.
        """
        initial_occupied = self.zone.occupied_slots
        t0 = timezone.now()
        res = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='Siem Reap 2A-8888',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=1)).date(),
            finish_time=t0 + timedelta(days=1),
            payment_method='PAY_AT_EXIT',
            arrival_deadline=t0 + timedelta(hours=3),
            status='CONFIRMED'
        )

        # 1. First entry scan: Success
        is_valid, validated_res, msg = GateService.validate_entry(res.access_token, zone_id=self.zone.id)
        self.assertTrue(is_valid)

        success, confirmed_res, msg = GateService.confirm_entry(res.id, staff_user=self.staff)
        self.assertTrue(success)
        self.assertEqual(confirmed_res.status, 'CHECKED_IN')
        self.assertIsNotNone(confirmed_res.checked_in_at)

        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, initial_occupied + 1)

        # 2. Duplicate entry scan: Rejected
        is_valid2, validated_res2, msg2 = GateService.validate_entry(res.access_token, zone_id=self.zone.id)
        self.assertFalse(is_valid2)
        self.assertIn('already checked in', msg2)

        # Ensure capacity was not altered again
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, initial_occupied + 1)

    def test_gate_exit_settlement_and_departure_window(self):
        """
        Exit requires balance settlement.
        Payment grants 5-minute departure window.
        Physical exit releases space atomically.
        """
        t0 = timezone.now() - timedelta(hours=40)
        initial_occupied = self.zone.occupied_slots
        res = Reservation.objects.create(
            customer=self.user,
            parking_zone=self.zone,
            plate_number='Takeo 2A-9999',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=3)).date(),
            finish_time=t0 + timedelta(days=3),
            daily_rate=4000,
            payment_method='PAY_AT_EXIT',
            status='CHECKED_IN',
            checked_in_at=t0
        )

        # Prepare exit: balance due is 8,000 KHR
        can_exit, r, bill, msg = GateService.prepare_exit(res.ticket_code)
        self.assertFalse(can_exit)
        self.assertEqual(bill['balance_due'], 8000)

        # Attempting physical exit before payment fails
        success, r, msg = GateService.confirm_physical_exit(res.id, staff_user=self.staff)
        self.assertFalse(success)

        # Settle payment at exit
        PaymentService.record_exit_payment(res, amount=8000, provider='CASH')
        res.refresh_from_db()
        self.assertEqual(res.payment_status, 'PAID')
        self.assertIsNotNone(res.exit_authorized_until)

        # Now can exit
        can_exit2, r2, bill2, msg2 = GateService.prepare_exit(res.ticket_code)
        self.assertTrue(can_exit2)

        # Confirm physical exit
        success2, r_out, msg_out = GateService.confirm_physical_exit(res.id, staff_user=self.staff)
        self.assertTrue(success2)
        self.assertEqual(r_out.status, 'CHECKED_OUT')
        self.assertTrue(r_out.checked_out)

        # Capacity released
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, initial_occupied - 1)

    def test_unauthorized_staff_scanner_access(self):
        """
        Regular customers cannot access the staff gate scanner.
        """
        self.client.login(username='tester_driver', password='testpass123')
        res = self.client.get(reverse('staff_gate_scanner'))
        # Regular user raised PermissionDenied (HTTP 403)
        self.assertEqual(res.status_code, 403)

        # Staff can access
        self.client.login(username='gate_officer', password='staffpass123')
        res_staff = self.client.get(reverse('staff_gate_scanner'))
        self.assertEqual(res_staff.status_code, 200)


class CustomerExitPaymentTests(TestCase):
    def setUp(self):
        self.zone1 = ParkingZone.objects.create(
            name='Central Park Zone A',
            slug='central-park-zone-a',
            num_of_slots=20,
            occupied_slots=5,
            vacant_slots=15,
            price=3000,
            address='Phnom Penh City Center',
            district='Daun Penh',
        )
        self.zone2 = ParkingZone.objects.create(
            name='Riverside Zone B',
            slug='riverside-zone-b',
            num_of_slots=20,
            occupied_slots=2,
            vacant_slots=18,
            price=4000,
            address='Riverside Walk',
            district='Daun Penh',
        )
        self.owner = User.objects.create_user(
            username='car_owner',
            email='owner@sompark.test',
            password='testpass123'
        )
        self.other_user = User.objects.create_user(
            username='stranger_driver',
            email='stranger@sompark.test',
            password='testpass123'
        )
        self.staff_user = User.objects.create_user(
            username='staff_officer',
            email='staff@sompark.test',
            password='testpass123',
            is_staff=True
        )

    def test_exit_payment_ownership_restriction(self):
        """User B cannot view or process exit payment for User A's reservation (HTTP 403)."""
        t0 = timezone.now() - timedelta(hours=5)
        res = Reservation.objects.create(
            customer=self.owner,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-1111',
            phone_number='+85512111222',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=1)).date(),
            finish_time=t0 + timedelta(days=1),
            daily_rate=3000,
            status='CHECKED_IN',
            checked_in_at=t0,
        )

        # Non-owner gets 403 Forbidden
        self.client.login(username='stranger_driver', password='testpass123')
        resp = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        self.assertEqual(resp.status_code, 403)

        # Owner gets 200 OK
        self.client.login(username='car_owner', password='testpass123')
        resp_owner = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        self.assertEqual(resp_owner.status_code, 200)
        self.assertContains(resp_owner, res.ticket_code)
        self.assertContains(resp_owner, 'Central Park Zone A')

    def test_exit_payment_only_after_checkin(self):
        """Confirmed but un-checked-in, expired, cancelled, or completed reservations cannot access exit payment."""
        now = timezone.now()
        self.client.login(username='car_owner', password='testpass123')

        # 1. CONFIRMED (not checked in yet)
        res_conf = Reservation.objects.create(
            customer=self.owner,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-2222',
            start_date=now.date(),
            finish_date=(now + timedelta(days=1)).date(),
            status='CONFIRMED',
        )
        resp_conf = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res_conf.ticket_code}))
        self.assertRedirects(resp_conf, reverse('ticket_code', kwargs={'ticket_code': res_conf.ticket_code}))

        # 2. CANCELLED
        res_canc = Reservation.objects.create(
            customer=self.owner,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-3333',
            start_date=now.date(),
            finish_date=(now + timedelta(days=1)).date(),
            status='CANCELLED',
        )
        resp_canc = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res_canc.ticket_code}))
        self.assertRedirects(resp_canc, reverse('dashboard'))

        # 3. EXPIRED
        res_exp = Reservation.objects.create(
            customer=self.owner,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-4444',
            start_date=now.date(),
            finish_date=(now + timedelta(days=1)).date(),
            status='EXPIRED',
        )
        resp_exp = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res_exp.ticket_code}))
        self.assertRedirects(resp_exp, reverse('dashboard'))

        # 4. CHECKED_OUT
        res_out = Reservation.objects.create(
            customer=self.owner,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-5555',
            start_date=now.date(),
            finish_date=(now + timedelta(days=1)).date(),
            status='CHECKED_OUT',
            checked_out=True,
        )
        resp_out = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res_out.ticket_code}))
        self.assertRedirects(resp_out, reverse('ticket_code', kwargs={'ticket_code': res_out.ticket_code}))

    def test_normal_and_overstay_billing_and_deposit_deduction(self):
        """Itemizes normal charges, 2x overstay charges, and deducts prepaid deposit."""
        # Entry 60 hours ago, booked for 24 hours (1 day), stayed 60 hours (1 normal day + 2 overstay days)
        t0 = timezone.now() - timedelta(hours=60)
        booked_end = t0 + timedelta(hours=24)
        res = Reservation.objects.create(
            customer=self.owner,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-6666',
            start_date=t0.date(),
            start_time=t0,
            finish_date=booked_end.date(),
            finish_time=booked_end,
            daily_rate=3000,
            deposit_amount=3000,
            payment_method='DEPOSIT',
            payment_status='PARTIALLY_PAID',
            status='CHECKED_IN',
            checked_in_at=t0,
        )

        bill = BillingService.calculate_bill(res, as_of=timezone.now())
        # Normal 1 day: 3,000 KHR
        self.assertEqual(bill['normal_days'], 1)
        self.assertEqual(bill['normal_charge'], 3000)
        # Overstay 2 days @ 2x (6,000 KHR / day): 12,000 KHR
        self.assertEqual(bill['overstay_days'], 2)
        self.assertEqual(bill['overstay_charge'], 12000)
        # Total charge: 15,000 KHR
        self.assertEqual(bill['total_charge'], 15000)
        # Deposit credited: 3,000 KHR
        self.assertEqual(bill['deposit_deducted'], 3000)
        # Net balance due: 12,000 KHR
        self.assertEqual(bill['balance_due'], 12000)

        # Check view output
        self.client.login(username='car_owner', password='testpass123')
        resp = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '12,000 ៛')
        self.assertContains(resp, '3,000 ៛')

    def test_payment_simulation_lifecycle_and_idempotency(self):
        """Simulate success, failure, cancel, and prevent duplicate payments."""
        t0 = timezone.now() - timedelta(hours=10)
        initial_occupied = self.zone1.occupied_slots
        res = Reservation.objects.create(
            customer=self.owner,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-7777',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=1)).date(),
            finish_time=t0 + timedelta(days=1),
            daily_rate=3000,
            payment_method='PAY_AT_EXIT',
            status='CHECKED_IN',
            checked_in_at=t0,
        )

        self.client.login(username='car_owner', password='testpass123')
        # 1. GET is read-only and creates no transactions
        resp = self.client.get(reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(res.transactions.filter(purpose='EXIT_BALANCE').count(), 0)

        # 2. Simulate failure via POST action
        resp_fail = self.client.post(
            reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}),
            data={'action': 'simulate_failure'}
        )
        self.assertRedirects(resp_fail, reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))
        txn = res.transactions.filter(purpose='EXIT_BALANCE', status='FAILED').first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.amount, 3000)
        res.refresh_from_db()
        self.assertEqual(res.status, 'CHECKED_IN')
        self.assertIsNone(res.exit_authorized_until)

        # 3. Simulate cancel via POST action returns to ticket with vehicle still checked in
        resp_cancel = self.client.post(
            reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}),
            data={'action': 'cancel_payment'}
        )
        self.assertRedirects(resp_cancel, reverse('ticket_code', kwargs={'ticket_code': res.ticket_code}))
        txn2 = res.transactions.filter(purpose='EXIT_BALANCE', status='CANCELLED').first()
        self.assertIsNotNone(txn2)
        self.assertNotEqual(txn.id, txn2.id)
        res.refresh_from_db()
        self.assertEqual(res.status, 'CHECKED_IN')

        # 4. Simulate success via POST pay
        resp_success = self.client.post(
            reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}),
            data={'action': 'pay'}
        )
        self.assertRedirects(resp_success, reverse('ticket_code', kwargs={'ticket_code': res.ticket_code}))

        # Assert post-payment invariants:
        res.refresh_from_db()
        txn3 = res.transactions.filter(purpose='EXIT_BALANCE', status='SUCCESS').first()
        self.assertIsNotNone(txn3)
        self.assertEqual(txn3.status, 'SUCCESS')
        self.assertEqual(res.status, 'CHECKED_IN')
        self.assertFalse(res.checked_out)
        self.assertEqual(res.payment_status, 'PAID')
        self.assertEqual(res.balance_paid, 3000)
        self.assertIsNotNone(res.exit_authorized_until)
        # Capacity remains occupied!
        self.zone1.refresh_from_db()
        self.assertEqual(self.zone1.occupied_slots, initial_occupied)

        # 6. Duplicate confirmation attempt is idempotent
        success, msg = PaymentService.confirm_exit_payment(txn3.id)
        self.assertTrue(success)
        self.assertIn('already verified', msg)
        res.refresh_from_db()
        self.assertEqual(res.balance_paid, 3000)  # NOT double-credited!

    def test_qr_refresh_does_not_extend_exit_window(self):
        """Refreshing or reopening ticket/QR page does not extend the 5-minute deadline."""
        t0 = timezone.now() - timedelta(hours=2)
        res = Reservation.objects.create(
            customer=self.owner,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-8888',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=1)).date(),
            finish_time=t0 + timedelta(days=1),
            daily_rate=3000,
            status='CHECKED_IN',
            checked_in_at=t0,
            exit_authorized_until=timezone.now() + timedelta(minutes=5)
        )
        initial_deadline = res.exit_authorized_until

        self.client.login(username='car_owner', password='testpass123')
        # Visit ticket page multiple times
        self.client.get(reverse('ticket_code', kwargs={'ticket_code': res.ticket_code}))
        self.client.get(reverse('ticket_gate_mode', kwargs={'ticket_code': res.ticket_code}))
        self.client.get(reverse('ticket_code', kwargs={'ticket_code': res.ticket_code}))

        res.refresh_from_db()
        self.assertEqual(res.exit_authorized_until, initial_deadline)

    def test_gate_facility_verification_for_exit(self):
        """Paid QR authorizes exit only at the matching facility and is rejected at other facilities."""
        t0 = timezone.now() - timedelta(hours=2)
        res = Reservation.objects.create(
            customer=self.owner,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-9999',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=1)).date(),
            finish_time=t0 + timedelta(days=1),
            daily_rate=3000,
            status='CHECKED_IN',
            checked_in_at=t0,
            exit_authorized_until=timezone.now() + timedelta(minutes=5)
        )

        # 1. Matching facility: Authorized
        can_exit, r, bill, msg = GateService.prepare_exit(res.access_token, zone_id=self.zone1.id)
        self.assertTrue(can_exit)
        self.assertIn('Exit authorized', msg)

        # 2. Different facility: Rejected
        can_exit_wrong, r_wrong, bill_wrong, msg_wrong = GateService.prepare_exit(res.access_token, zone_id=self.zone2.id)
        self.assertFalse(can_exit_wrong)
        self.assertIn('not this parking facility', msg_wrong)

    def test_expired_exit_window_with_and_without_additional_charges(self):
        """
        When exit window expires:
        A. If balance_due == 0: gate rejects, but renewal succeeds without extra fee.
        B. If balance_due > 0: gate rejects, renewal requires paying additional balance.
        """
        t0 = timezone.now() - timedelta(hours=10)
        # Expired window (authorized until 10 minutes ago)
        expired_window = timezone.now() - timedelta(minutes=10)
        res = Reservation.objects.create(
            customer=self.owner,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-0000',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=1)).date(),
            finish_time=t0 + timedelta(days=1),
            daily_rate=3000,
            balance_paid=3000,
            payment_status='PAID',
            status='CHECKED_IN',
            checked_in_at=t0,
            exit_authorized_until=expired_window,
        )

        # Gate check: Expired window is not authorized
        can_exit, r, bill, msg = GateService.prepare_exit(res.ticket_code, zone_id=self.zone1.id)
        self.assertFalse(can_exit)
        self.assertIn('Exit window expired', msg)
        self.assertEqual(bill['balance_due'], 0)

        # A. Renew exit authorization without extra fee
        self.client.login(username='car_owner', password='testpass123')
        resp_renew = self.client.post(reverse('renew_exit_authorization', kwargs={'ticket_code': res.ticket_code}))
        self.assertRedirects(resp_renew, reverse('ticket_code', kwargs={'ticket_code': res.ticket_code}))
        res.refresh_from_db()
        self.assertGreater(res.exit_authorized_until, timezone.now())

        # Now gate authorizes
        can_exit2, _, _, _ = GateService.prepare_exit(res.ticket_code, zone_id=self.zone1.id)
        self.assertTrue(can_exit2)

        # B. Expired window with overstay / additional balance
        # Simulate rolling over into 2x overstay (3 days ago entry)
        t_overstay = timezone.now() - timedelta(days=2)
        res.checked_in_at = t_overstay
        res.start_time = t_overstay
        res.finish_time = t_overstay + timedelta(days=1)
        res.exit_authorized_until = expired_window
        res.save()

        # Bill now has balance due
        bill_overstay = BillingService.calculate_bill(res)
        self.assertGreater(bill_overstay['balance_due'], 0)

        # Renewal attempts reject and redirect to pay_exit
        resp_renew_fail = self.client.post(reverse('renew_exit_authorization', kwargs={'ticket_code': res.ticket_code}))
        self.assertRedirects(resp_renew_fail, reverse('pay_exit', kwargs={'ticket_code': res.ticket_code}))

    def test_vehicle_passage_releases_capacity_exactly_once(self):
        """Passage confirmation updates to CHECKED_OUT and decrements occupied_slots once."""
        t0 = timezone.now() - timedelta(hours=3)
        initial_occupied = self.zone1.occupied_slots
        res = Reservation.objects.create(
            customer=self.owner,
            parking_zone=self.zone1,
            plate_number='Phnom Penh 2AZ-1234',
            start_date=t0.date(),
            start_time=t0,
            finish_date=(t0 + timedelta(days=1)).date(),
            finish_time=t0 + timedelta(days=1),
            daily_rate=3000,
            balance_paid=3000,
            payment_status='PAID',
            status='CHECKED_IN',
            checked_in_at=t0,
            exit_authorized_until=timezone.now() + timedelta(minutes=5),
        )

        # First passage confirmation: Success, space released
        success1, r1, msg1 = GateService.confirm_physical_exit(res.id, staff_user=self.staff_user)
        self.assertTrue(success1)
        self.assertEqual(r1.status, 'CHECKED_OUT')
        self.assertTrue(r1.checked_out)
        self.zone1.refresh_from_db()
        self.assertEqual(self.zone1.occupied_slots, initial_occupied - 1)

        # Duplicate passage confirmation: Idempotent, space NOT decremented again!
        success2, r2, msg2 = GateService.confirm_physical_exit(res.id, staff_user=self.staff_user)
        self.assertTrue(success2)
        self.assertEqual(r2.status, 'CHECKED_OUT')
        self.zone1.refresh_from_db()
        self.assertEqual(self.zone1.occupied_slots, initial_occupied - 1)






