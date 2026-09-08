import datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from parking_zones.models import ParkingZone, Reservation
from parking_zones.forms import ReservationForm


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
        self.assertEqual(self.zone.occupied_slots, 2)
        self.assertEqual(self.zone.vacant_slots, 3)

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

        # Owner Dara checks out
        self.client.login(username='dara', password='secretpassword')
        res_ok = self.client.post(reverse('checkout'), {'ticket_code': reservation.ticket_code}, follow=True)
        self.assertEqual(res_ok.status_code, 200)

        reservation.refresh_from_db()
        self.assertTrue(reservation.checked_out)
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.occupied_slots, 0)
        self.assertEqual(self.zone.vacant_slots, 5)
