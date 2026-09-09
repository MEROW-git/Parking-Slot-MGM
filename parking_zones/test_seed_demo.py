"""
Unit tests for the idempotent seed_demo management command.
"""

from io import StringIO
from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth.models import User

from parking_zones.models import ParkingZone, Reservation, PaymentTransaction


class SeedDemoCommandTests(TestCase):
    """
    Validates that python manage.py seed_demo:
    1. Successfully seeds Phnom Penh zones, demo user, and sample tickets.
    2. Is fully idempotent on repeated execution (zero duplicates, no resets).
    3. Never deletes existing records or resets user passwords.
    """

    def test_seed_demo_idempotency_and_integrity(self):
        out1 = StringIO()
        call_command('seed_demo', stdout=out1)
        output1 = out1.getvalue()

        self.assertIn("=== SomPark Idempotent Demo Seeder ===", output1)
        self.assertIn("Seeding complete!", output1)

        # Verify zones
        zone_count_after_first_run = ParkingZone.objects.count()
        self.assertEqual(zone_count_after_first_run, 6)

        riverside = ParkingZone.objects.get(slug='riverside-promenade')
        self.assertEqual(riverside.price, 3000)
        self.assertEqual(riverside.num_of_slots, 45)

        # Verify demo user
        demo_user = User.objects.get(username='demo')
        self.assertTrue(demo_user.check_password('password123'))

        # Change demo user password to ensure it is NOT reset on subsequent runs
        demo_user.set_password('teacher_custom_password')
        demo_user.save()

        # Verify sample reservations
        self.assertEqual(Reservation.objects.filter(ticket_code='SPK-DEMO001', status='CONFIRMED').count(), 1)
        self.assertEqual(Reservation.objects.filter(ticket_code='SPK-DEMO002', status='CHECKED_IN').count(), 1)
        self.assertEqual(Reservation.objects.filter(ticket_code='SPK-DEMO003', status='CHECKED_OUT').count(), 1)

        res_count_1 = Reservation.objects.count()
        txn_count_1 = PaymentTransaction.objects.count()

        # RUN SEED_DEMO A SECOND TIME
        out2 = StringIO()
        call_command('seed_demo', stdout=out2)
        output2 = out2.getvalue()

        # Ensure no duplicates were created
        self.assertEqual(ParkingZone.objects.count(), zone_count_after_first_run)
        self.assertEqual(Reservation.objects.count(), res_count_1)
        self.assertEqual(PaymentTransaction.objects.count(), txn_count_1)

        # Ensure custom password was PRESERVED and not overwritten
        demo_user.refresh_from_db()
        self.assertTrue(
            demo_user.check_password('teacher_custom_password'),
            "Existing demo user password was unexpectedly reset on second seed run!"
        )
        self.assertFalse(demo_user.check_password('password123'))
