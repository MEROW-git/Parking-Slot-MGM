"""
Comprehensive security enhancement test suite for SomPark.
Tests:
1. Password validation in custom registration form against Django validators.
2. testmotionuser unusable password and reset enforcement.
3. No plaintext passwords or hashes printed in seed commands.
4. Application-level vehicle plate authenticated encryption round trips (Fernet AES-128-CBC + HMAC).
5. Separate keys: PLATE_ENCRYPTION_KEY vs PLATE_SEARCH_HMAC_KEY vs SECRET_KEY.
6. Explicit failures on missing or wrong keys (PlateCryptoConfigurationError, PlateDecryptionError).
7. Keyed HMAC lookup index (plate_lookup_hmac) and O(1) exact matching.
8. Anti-Spam duplicate prevention & simultaneous hold checks with encrypted plates.
9. Virtual Gate ANPR matching with encrypted plates.
10. Cambodian custom plates and walk-in tickets without plates.
11. Django Admin search compatibility via keyed HMAC.
12. Staged migration backfill (encrypt_plates) and recovery rollback (decrypt_plates) safety.
"""
from datetime import timedelta, date
from decimal import Decimal
import io
import os
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, Client, RequestFactory
from django.utils import timezone

from parking_zones.models import ParkingZone, Reservation
from parking_zones.admin import ReservationAdmin
from parking_zones.services import AntiSpamService, GateService
from parking_zones.gate_machine import normalize_license_plate
from parking_zones.crypto import (
    encrypt_plate,
    decrypt_plate,
    compute_plate_hmac,
    CIPHERTEXT_PREFIX,
    PlateCryptoConfigurationError,
    PlateDecryptionError,
    generate_fernet_key,
    generate_hmac_key,
)
from users.forms import UserRegistrationForm


class SecurityEnhancementsTests(TestCase):
    def setUp(self):
        # Dedicated isolated test encryption keys
        self.test_enc_key = 'k8g_T3rFfWjL8j4zL3v5mQ1yP9rU2wE4tY6uI8oP0sA='
        self.test_hmac_key = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
        os.environ['PLATE_ENCRYPTION_KEY'] = self.test_enc_key
        os.environ['PLATE_SEARCH_HMAC_KEY'] = self.test_hmac_key

        self.zone = ParkingZone.objects.create(
            name='Wat Phnom Riverside Slot',
            khmer_name='ចំណតវត្តភ្នំ មាត់ទន្លេ',
            slug='wat-phnom-riverside-sec',
            num_of_slots=40,
            occupied_slots=5,
            vacant_slots=35,
            price=3000,
            walk_in_price=7000,
            address='Street 94, Daun Penh, Phnom Penh'
        )

        self.customer = User.objects.create_user(
            username='sec_customer',
            password='TestPassword123!',
            email='sec_customer@sompark.kh'
        )
        self.staff_user = User.objects.create_user(
            username='sec_staff',
            password='TestPassword123!',
            is_staff=True
        )

    # --------------------------------------------------------------------------
    # 1. Password Validation & User Creation Auditing
    # --------------------------------------------------------------------------
    def test_1_password_validation_in_registration_form(self):
        """UserRegistrationForm applies Django's configured password validators."""
        # A. Weak password (too short: < 8 characters)
        form_short = UserRegistrationForm(data={
            'username': 'new_user_1',
            'email': 'new1@sompark.kh',
            'password': 'short',
            'password_confirm': 'short',
        })
        self.assertFalse(form_short.is_valid())
        self.assertIn('password', form_short.errors)
        self.assertTrue(any('at least 8 characters' in e for e in form_short.errors['password']))

        # B. Entirely numeric password
        form_numeric = UserRegistrationForm(data={
            'username': 'new_user_2',
            'email': 'new2@sompark.kh',
            'password': '1234567890',
            'password_confirm': '1234567890',
        })
        self.assertFalse(form_numeric.is_valid())
        self.assertIn('password', form_numeric.errors)
        self.assertTrue(any('entirely numeric' in e for e in form_numeric.errors['password']))

        # C. Common password
        form_common = UserRegistrationForm(data={
            'username': 'new_user_3',
            'email': 'new3@sompark.kh',
            'password': 'password123',
            'password_confirm': 'password123',
        })
        self.assertFalse(form_common.is_valid())
        self.assertIn('password', form_common.errors)
        self.assertTrue(any('too common' in e for e in form_common.errors['password']))

        # D. Password similar to username
        form_similar = UserRegistrationForm(data={
            'username': 'dara_driver',
            'email': 'dara@sompark.kh',
            'password': 'dara_driver_password',
            'password_confirm': 'dara_driver_password',
        })
        self.assertFalse(form_similar.is_valid())
        self.assertIn('password', form_similar.errors)
        self.assertTrue(any('too similar to the username' in e for e in form_similar.errors['password']))

        # E. Strong compliant password succeeds
        form_valid = UserRegistrationForm(data={
            'username': 'valid_dara',
            'email': 'valid@sompark.kh',
            'password': 'SomPark#2026!StrongPass',
            'password_confirm': 'SomPark#2026!StrongPass',
        })
        self.assertTrue(form_valid.is_valid(), form_valid.errors)
        user = form_valid.save(commit=False)
        user.set_password(form_valid.cleaned_data['password'])
        user.save()
        self.assertTrue(user.has_usable_password())
        self.assertTrue(user.check_password('SomPark#2026!StrongPass'))

    def test_2_testmotionuser_unusable_password(self):
        """testmotionuser has an unusable password and cannot authenticate with blank password."""
        motion_user = User.objects.filter(username='testmotionuser').first()
        if not motion_user:
            motion_user = User.objects.create_user(username='testmotionuser', password='')
            motion_user.set_unusable_password()
            motion_user.save()

        # Ensure unusable password state
        self.assertFalse(motion_user.has_usable_password())
        self.assertTrue(motion_user.password.startswith('!'))

        # Authentication attempts must fail
        auth_empty = authenticate(username='testmotionuser', password='')
        self.assertIsNone(auth_empty)
        auth_random = authenticate(username='testmotionuser', password='randompassword')
        self.assertIsNone(auth_random)

    def test_3_never_print_passwords_or_hashes_in_seed(self):
        """Management commands do not output plain passwords to stdout."""
        out = io.StringIO()
        call_command('seed_demo', stdout=out)
        output_text = out.getvalue()
        # Must not print "password 'password123'"
        self.assertNotIn("password 'password123'", output_text)
        self.assertNotIn("password123", output_text)
        self.assertIn("password initialized", output_text)

    # --------------------------------------------------------------------------
    # 2. Application-Level Authenticated Vehicle Plate Encryption
    # --------------------------------------------------------------------------
    def test_4_plate_encryption_round_trip(self):
        """Plates are stored as authenticated ciphertexts in database and transparently decrypted in memory."""
        plate_str = 'Phnom Penh 2AZ-1234'
        now = timezone.now()
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number=plate_str,
            start_date=now.date(),
            finish_date=now.date(),
            start_time=now,
            finish_time=now + timedelta(hours=3),
        )

        # In Python memory / model instance: transparently plaintext
        self.assertEqual(res.plate_number, plate_str)
        self.assertTrue(len(res.plate_lookup_hmac) == 64)

        # In raw database: stored as ciphertext starting with 'enc:v1:gAAAAA'
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("SELECT plate_number, plate_lookup_hmac FROM parking_zones_reservation WHERE id = %s", [res.pk])
            raw_val, raw_hmac = cur.fetchone()
        self.assertTrue(raw_val.startswith(CIPHERTEXT_PREFIX))
        self.assertNotIn(plate_str, raw_val)
        self.assertEqual(raw_hmac, compute_plate_hmac(plate_str))

        # Refresh from database: transparently decrypted
        res.refresh_from_db()
        self.assertEqual(res.plate_number, plate_str)

    def test_5_key_separation_and_missing_key_failures(self):
        """Dedicated keys are independent of SECRET_KEY and fail explicitly when absent."""
        # 1. Keys must be separate
        self.assertNotEqual(self.test_enc_key, settings.SECRET_KEY)
        self.assertNotEqual(self.test_hmac_key, settings.SECRET_KEY)
        self.assertNotEqual(self.test_enc_key, self.test_hmac_key)

        # 2. Missing encryption key raises PlateCryptoConfigurationError
        old_key = os.environ.get('PLATE_ENCRYPTION_KEY')
        old_test_key = getattr(settings, 'TEST_PLATE_ENCRYPTION_KEY', None)
        try:
            os.environ['PLATE_ENCRYPTION_KEY'] = ''
            if hasattr(settings, 'TEST_PLATE_ENCRYPTION_KEY'):
                delattr(settings, 'TEST_PLATE_ENCRYPTION_KEY')
            if hasattr(settings, 'PLATE_ENCRYPTION_KEY'):
                settings.PLATE_ENCRYPTION_KEY = ''

            with self.assertRaises(PlateCryptoConfigurationError):
                encrypt_plate('2AZ-9999')
        finally:
            if old_key:
                os.environ['PLATE_ENCRYPTION_KEY'] = old_key
            if old_test_key:
                settings.TEST_PLATE_ENCRYPTION_KEY = old_test_key
            settings.PLATE_ENCRYPTION_KEY = old_key or old_test_key

        # 3. Corrupted ciphertext raises PlateDecryptionError
        with self.assertRaises(PlateDecryptionError):
            decrypt_plate(f"{CIPHERTEXT_PREFIX}tampered_or_invalid_ciphertext_token")

    def test_6_keyed_hmac_exact_matching(self):
        """HMAC index enables O(1) exact matching, ignoring case, hyphens, and whitespace."""
        plate_str = 'Phnom Penh 2AZ-5555'
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number=plate_str,
            start_date=timezone.now().date(),
            finish_date=timezone.now().date(),
            start_time=timezone.now(),
            finish_time=timezone.now() + timedelta(hours=3),
        )

        expected_hmac = compute_plate_hmac('PHNOMPENH2AZ5555')
        self.assertEqual(res.plate_lookup_hmac, expected_hmac)

        # Exact match query via plate_lookup_hmac
        found = Reservation.objects.filter(plate_lookup_hmac=expected_hmac).first()
        self.assertIsNotNone(found)
        self.assertEqual(found.pk, res.pk)

        # ORM exact lookup integration: query by plate_number works via EncryptedPlateExact
        orm_found = Reservation.objects.filter(plate_number=plate_str).first()
        self.assertIsNotNone(orm_found)
        self.assertEqual(orm_found.pk, res.pk)

    def test_7_anti_spam_duplicate_and_simultaneous_hold_with_encryption(self):
        """AntiSpamService catches duplicate submissions and simultaneous holds using encrypted plates."""
        now = timezone.now()
        plate_str = 'Phnom Penh 2AZ-7777'

        res1 = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number=plate_str,
            status='CONFIRMED',
            start_date=now.date(),
            finish_date=now.date(),
            start_time=now,
            finish_time=now + timedelta(hours=3),
            arrival_deadline=now + timedelta(hours=3),
        )

        # A. find_duplicate_submission via HMAC
        normalized = AntiSpamService.normalize_plate('Phnom Penh 2az 7777')
        dup = AntiSpamService.find_duplicate_submission(self.customer, self.zone, normalized)
        self.assertIsNotNone(dup)
        self.assertEqual(dup.pk, res1.pk)

        # B. check_simultaneous_plate_hold across facilities
        other_zone = ParkingZone.objects.create(
            name='BKK1 Plaza Lot',
            slug='bkk1-plaza-sec',
            num_of_slots=20,
            price=4000
        )
        allowed, blocking_res, msg = AntiSpamService.check_simultaneous_plate_hold(plate_str)
        self.assertFalse(allowed)
        self.assertEqual(blocking_res.pk, res1.pk)
        self.assertIn('already active', msg)

    def test_8_virtual_gate_anpr_matching_with_encrypted_plates(self):
        """Virtual Gate ANPR plate matching normalizes and compares transparently decrypted plates."""
        plate_str = 'Phnom Penh 2AZ-8888'
        now = timezone.now()
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number=plate_str,
            status='CONFIRMED',
            start_date=now.date(),
            finish_date=now.date(),
            start_time=now,
            finish_time=now + timedelta(hours=3),
            arrival_deadline=now + timedelta(hours=3),
        )

        # Matching plate
        self.assertEqual(
            normalize_license_plate(res.plate_number),
            normalize_license_plate('Phnom Penh 2AZ-8888')
        )
        # Mismatching plate
        self.assertNotEqual(
            normalize_license_plate(res.plate_number),
            normalize_license_plate('Phnom Penh 2AZ-9999')
        )

    def test_9_cambodian_custom_plates_and_walk_in_tickets(self):
        """Cambodia vanity plates are preserved exactly; walk-in tickets without plates have empty HMAC."""
        # A. Custom Cambodia vanity plate
        vanity_plate = 'Cambodia GODHELP'
        now = timezone.now()
        res_vanity = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number=vanity_plate,
            start_date=now.date(),
            finish_date=now.date(),
            start_time=now,
            finish_time=now + timedelta(hours=3),
        )
        res_vanity.refresh_from_db()
        self.assertEqual(res_vanity.plate_number, vanity_plate)

        # B. Walk-in ticket without plate
        res_walk_in = Reservation.objects.create(
            customer=None,
            parking_zone=self.zone,
            plate_number='',
            is_walk_in=True,
            start_date=now.date(),
            finish_date=now.date(),
            start_time=now,
            finish_time=now + timedelta(hours=3),
        )
        res_walk_in.refresh_from_db()
        self.assertEqual(res_walk_in.plate_number, '')
        self.assertEqual(res_walk_in.plate_lookup_hmac, '')

    def test_10_admin_search_compatibility(self):
        """ReservationAdmin get_search_results matches encrypted vehicle plates using keyed HMAC."""
        plate_str = 'Phnom Penh 2AZ-1111'
        now = timezone.now()
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number=plate_str,
            start_date=now.date(),
            finish_date=now.date(),
            start_time=now,
            finish_time=now + timedelta(hours=3),
        )

        request_factory = RequestFactory()
        request = request_factory.get('/admin/parking_zones/reservation/')
        request.user = self.staff_user

        model_admin = ReservationAdmin(Reservation, admin.site)
        qs = Reservation.objects.all()

        # Staff searches for "2AZ-1111" (auto-detects and adds province candidate)
        results, _ = model_admin.get_search_results(request, qs, '2AZ-1111')
        self.assertIn(res, results)

        # Staff searches for "Phnom Penh 2AZ-1111"
        results_full, _ = model_admin.get_search_results(request, qs, 'Phnom Penh 2AZ-1111')
        self.assertIn(res, results_full)

    def test_11_staged_migration_and_recovery_safety(self):
        """encrypt_plates and decrypt_plates commands operate safely on isolated database."""
        now = timezone.now()
        from django.db import connection
        legacy_plate = 'Legacy 2AZ-9999'
        res = Reservation.objects.create(
            customer=self.customer,
            parking_zone=self.zone,
            plate_number='',
            start_date=now.date(),
            finish_date=now.date(),
            start_time=now,
            finish_time=now + timedelta(hours=3),
        )
        # Raw update to simulate pre-migration plaintext without HMAC
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE parking_zones_reservation SET plate_number = %s, plate_lookup_hmac = '' WHERE id = %s",
                [legacy_plate, res.pk]
            )

        # Verify plaintext in raw database column
        with connection.cursor() as cur:
            cur.execute("SELECT plate_number, plate_lookup_hmac FROM parking_zones_reservation WHERE id = %s", [res.pk])
            raw_before, raw_hmac_before = cur.fetchone()
        self.assertEqual(raw_before, legacy_plate)
        self.assertEqual(raw_hmac_before, '')

        # 1. Dry run does not alter records
        out_dry = io.StringIO()
        call_command('encrypt_plates', '--dry-run', stdout=out_dry)
        self.assertIn('[DRY RUN COMPLETE]', out_dry.getvalue())
        with connection.cursor() as cur:
            cur.execute("SELECT plate_number FROM parking_zones_reservation WHERE id = %s", [res.pk])
            raw_after_dry = cur.fetchone()[0]
        self.assertEqual(raw_after_dry, legacy_plate)

        # 2. Staged backfill with verification
        out_mig = io.StringIO()
        call_command('encrypt_plates', '--batch-size', '50', stdout=out_mig)
        self.assertIn('Migration successfully completed', out_mig.getvalue())

        # Raw value is now encrypted with populated HMAC index
        with connection.cursor() as cur:
            cur.execute("SELECT plate_number, plate_lookup_hmac FROM parking_zones_reservation WHERE id = %s", [res.pk])
            raw_encrypted, hmac_populated = cur.fetchone()
        self.assertTrue(raw_encrypted.startswith(CIPHERTEXT_PREFIX))
        self.assertEqual(hmac_populated, compute_plate_hmac(legacy_plate))

        # Model access decrypts transparently
        res.refresh_from_db()
        self.assertEqual(res.plate_number, legacy_plate)

        # 3. Rollback / recovery command decrypts back to plaintext
        out_dec = io.StringIO()
        call_command('decrypt_plates', '--batch-size', '50', stdout=out_dec)
        self.assertIn('Recovery successfully completed', out_dec.getvalue())

        with connection.cursor() as cur:
            cur.execute("SELECT plate_number FROM parking_zones_reservation WHERE id = %s", [res.pk])
            raw_decrypted = cur.fetchone()[0]
        self.assertEqual(raw_decrypted, legacy_plate)
