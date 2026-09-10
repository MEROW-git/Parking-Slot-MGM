"""
Staged, verified backfill management command to encrypt legacy plaintext vehicle plates
and populate the keyed HMAC lookup index.

Usage:
    python manage.py encrypt_plates --dry-run
    python manage.py encrypt_plates --batch-size 100 --verify
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from parking_zones.models import Reservation
from parking_zones.crypto import (
    encrypt_plate,
    decrypt_plate,
    compute_plate_hmac,
    CIPHERTEXT_PREFIX,
    PlateCryptoConfigurationError,
    PlateDecryptionError,
)


class Command(BaseCommand):
    help = 'Safely encrypts legacy plaintext vehicle plates and populates plate_lookup_hmac.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Scans and reports unencrypted records without modifying the database.'
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
            help='Immediately reads back and verifies decryption and HMAC equivalence for every row.'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        batch_size = max(1, options['batch_size'])
        verify = options['verify']

        self.stdout.write(self.style.MIGRATE_HEADING("=== SomPark Vehicle Plate Migration / Backfill ==="))

        # Pre-flight check: Verify encryption & HMAC keys
        try:
            test_token = encrypt_plate('TEST-KEY-CHECK')
            test_plain = decrypt_plate(test_token)
            test_hmac = compute_plate_hmac('TEST-KEY-CHECK')
            if test_plain != 'TEST-KEY-CHECK' or len(test_hmac) != 64:
                raise CommandError("Key self-test failed: encryption or HMAC round-trip mismatch.")
        except PlateCryptoConfigurationError as e:
            raise CommandError(f"Crypto configuration error: {e}")
        except Exception as e:
            raise CommandError(f"Failed to initialize cryptography cipher: {e}")

        # Query records needing backfill:
        # 1. Non-empty plate that does NOT start with CIPHERTEXT_PREFIX
        # 2. OR plate is encrypted but plate_lookup_hmac is missing
        all_reservations = Reservation.objects.all()
        total_count = all_reservations.count()

        # In raw database, we check directly
        unencrypted_candidates = []
        missing_hmac_candidates = []

        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("SELECT id, ticket_code, plate_number, plate_lookup_hmac FROM parking_zones_reservation")
            raw_rows = cur.fetchall()

        for res_id, ticket_code, raw_plate, raw_hmac in raw_rows:
            raw_plate = raw_plate or ''
            raw_hmac = raw_hmac or ''

            if raw_plate and not raw_plate.startswith(CIPHERTEXT_PREFIX):
                unencrypted_candidates.append((res_id, ticket_code, raw_plate))
            elif raw_plate and raw_plate.startswith(CIPHERTEXT_PREFIX) and not raw_hmac:
                missing_hmac_candidates.append((res_id, ticket_code, raw_plate))

        self.stdout.write(f"Total reservations in database: {total_count}")
        self.stdout.write(f"Unencrypted plaintext plates found: {len(unencrypted_candidates)}")
        self.stdout.write(f"Encrypted plates needing HMAC index backfill: {len(missing_hmac_candidates)}")

        if dry_run:
            self.stdout.write(self.style.WARNING(
                "\n[DRY RUN COMPLETE] No database changes were made. "
                "Run without --dry-run to perform the backfill."
            ))
            return

        if not unencrypted_candidates and not missing_hmac_candidates:
            self.stdout.write(self.style.SUCCESS("All vehicle plates are already encrypted with populated HMAC indexes."))
            return

        # 1. Process unencrypted plaintext records
        encrypted_count = 0
        if unencrypted_candidates:
            self.stdout.write(f"\nEncrypting {len(unencrypted_candidates)} plaintext records in batches of {batch_size}...")

            for i in range(0, len(unencrypted_candidates), batch_size):
                batch = unencrypted_candidates[i:i + batch_size]
                with transaction.atomic():
                    with connection.cursor() as cur:
                        for res_id, ticket_code, plaintext_plate in batch:
                            ciphertext = encrypt_plate(plaintext_plate)
                            hmac_digest = compute_plate_hmac(plaintext_plate)

                            # Verification prior to update
                            if verify:
                                check_plain = decrypt_plate(ciphertext)
                                if check_plain != plaintext_plate:
                                    raise CommandError(
                                        f"Verification failed on ticket #{ticket_code}! "
                                        f"Decrypted '{check_plain}' did not match original '{plaintext_plate}'."
                                    )
                                check_hmac = compute_plate_hmac(check_plain)
                                if check_hmac != hmac_digest:
                                    raise CommandError(
                                        f"HMAC verification failed on ticket #{ticket_code}!"
                                    )

                            cur.execute(
                                "UPDATE parking_zones_reservation SET plate_number = %s, plate_lookup_hmac = %s WHERE id = %s",
                                [ciphertext, hmac_digest, res_id]
                            )
                            encrypted_count += 1

                self.stdout.write(f"  Processed batch: {min(i + batch_size, len(unencrypted_candidates))}/{len(unencrypted_candidates)}")

        # 2. Process encrypted records with missing HMAC
        hmac_backfilled = 0
        if missing_hmac_candidates:
            self.stdout.write(f"\nBackfilling HMAC for {len(missing_hmac_candidates)} records...")
            for i in range(0, len(missing_hmac_candidates), batch_size):
                batch = missing_hmac_candidates[i:i + batch_size]
                with transaction.atomic():
                    with connection.cursor() as cur:
                        for res_id, ticket_code, ciphertext in batch:
                            plain = decrypt_plate(ciphertext)
                            hmac_digest = compute_plate_hmac(plain)
                            cur.execute(
                                "UPDATE parking_zones_reservation SET plate_lookup_hmac = %s WHERE id = %s",
                                [hmac_digest, res_id]
                            )
                            hmac_backfilled += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nMigration successfully completed!\n"
            f"- {encrypted_count} plates encrypted and verified.\n"
            f"- {hmac_backfilled} HMAC indexes populated."
        ))
