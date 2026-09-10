"""
Rollback and recovery management command to decrypt vehicle plates back to plaintext.

Usage:
    python manage.py decrypt_plates --dry-run
    python manage.py decrypt_plates --batch-size 100 --verify
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from parking_zones.models import Reservation
from parking_zones.crypto import (
    decrypt_plate,
    compute_plate_hmac,
    CIPHERTEXT_PREFIX,
    PlateCryptoConfigurationError,
    PlateDecryptionError,
)


class Command(BaseCommand):
    help = 'Recovery command: decrypts encrypted vehicle plates back to plaintext.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Scans and reports encrypted records without modifying the database.'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Number of records to process per atomic transaction (default: 100).'
        )
        parser.add_argument(
            '--verify',
            action='store_true',
            default=True,
            help='Verifies decrypted plate against plate_lookup_hmac before writing.'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        batch_size = max(1, options['batch_size'])
        verify = options['verify']

        self.stdout.write(self.style.MIGRATE_HEADING("=== SomPark Plate Decryption & Recovery ==="))

        from django.db import connection
        encrypted_candidates = []
        with connection.cursor() as cur:
            cur.execute("SELECT id, ticket_code, plate_number, plate_lookup_hmac FROM parking_zones_reservation")
            raw_rows = cur.fetchall()

        for res_id, ticket_code, raw_plate, raw_hmac in raw_rows:
            raw_plate = raw_plate or ''
            if raw_plate and raw_plate.startswith(CIPHERTEXT_PREFIX):
                encrypted_candidates.append((res_id, ticket_code, raw_plate, raw_hmac or ''))

        self.stdout.write(f"Total reservations scanned: {len(raw_rows)}")
        self.stdout.write(f"Encrypted plates found: {len(encrypted_candidates)}")

        if dry_run:
            self.stdout.write(self.style.WARNING(
                "\n[DRY RUN COMPLETE] No database changes were made. "
                "Run without --dry-run to decrypt records."
            ))
            return

        if not encrypted_candidates:
            self.stdout.write(self.style.SUCCESS("No encrypted plates found to decrypt."))
            return

        decrypted_count = 0
        for i in range(0, len(encrypted_candidates), batch_size):
            batch = encrypted_candidates[i:i + batch_size]
            with transaction.atomic():
                with connection.cursor() as cur:
                    for res_id, ticket_code, ciphertext, expected_hmac in batch:
                        plaintext = decrypt_plate(ciphertext)
                        if verify and expected_hmac:
                            computed_hmac = compute_plate_hmac(plaintext)
                            if computed_hmac != expected_hmac:
                                raise CommandError(
                                    f"Integrity check failed during rollback for ticket #{ticket_code}! "
                                    f"Decrypted plate HMAC did not match stored HMAC index."
                                )

                        cur.execute(
                            "UPDATE parking_zones_reservation SET plate_number = %s WHERE id = %s",
                            [plaintext, res_id]
                        )
                        decrypted_count += 1

            self.stdout.write(f"  Processed batch: {min(i + batch_size, len(encrypted_candidates))}/{len(encrypted_candidates)}")

        self.stdout.write(self.style.SUCCESS(
            f"\nRecovery successfully completed: {decrypted_count} plates restored to plaintext."
        ))
