import math
from django.core.management.base import BaseCommand
from django.db import transaction
from parking_zones.models import Reservation


class Command(BaseCommand):
    help = (
        'Audits and reconciles legacy reservations where reserved duration is ambiguous. '
        'Preserves settled receipts and never invents historical entry times. '
        'Runs in DRY-RUN mode by default; pass --apply to commit changes.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            dest='apply_changes',
            default=False,
            help='Actually apply proposed reserved_days updates to active reservations. Defaults to False (dry-run).',
        )
        parser.add_argument(
            '--zone',
            type=str,
            dest='zone_slug',
            default=None,
            help='Filter reservations by parking zone slug.',
        )

    def handle(self, *args, **options):
        apply_changes = options['apply_changes']
        zone_slug = options.get('zone_slug')

        mode_str = self.style.WARNING('[APPLY MODE - LIVE UPDATES]') if apply_changes else self.style.NOTICE('[DRY-RUN MODE - NO MODIFICATIONS]')
        self.stdout.write(f"\nSomPark Reservation Duration Reconciliation {mode_str}\n")

        qs = Reservation.objects.all().order_by('id')
        if zone_slug:
            qs = qs.filter(parking_zone__slug=zone_slug)

        total_checked = 0
        settled_skipped = 0
        ambiguous_found = 0
        updated_count = 0

        self.stdout.write(f"Scanning {qs.count()} reservation records...\n")

        records_to_update = []

        for res in qs:
            total_checked += 1
            # Check if settled
            is_settled = res.status == 'CHECKED_OUT' or res.checked_out

            # Calculate inferred days from dates or times
            inferred_days = 1
            is_ambiguous = False

            if res.start_date and res.finish_date:
                calendar_diff = (res.finish_date - res.start_date).days
                if calendar_diff > 1:
                    inferred_days = calendar_diff
                    if res.reserved_days != inferred_days:
                        is_ambiguous = True

            if res.start_time and res.finish_time:
                secs = (res.finish_time - res.start_time).total_seconds()
                hours = secs / 3600.0
                if hours > 24.0:
                    time_days = math.ceil(secs / 86400.0)
                    if time_days != res.reserved_days:
                        inferred_days = max(inferred_days, time_days)
                        is_ambiguous = True

            if is_settled:
                # Rule: Never rewrite settled receipts!
                settled_skipped += 1
                if is_ambiguous:
                    self.stdout.write(
                        f"  [SETTLED - IMMUTABLE] Ticket #{res.ticket_code} (ID: {res.id}): "
                        f"Current reserved_days={res.reserved_days}, inferred={inferred_days}. Preserving settled audit receipt."
                    )
                continue

            if is_ambiguous:
                ambiguous_found += 1
                self.stdout.write(
                    f"  [AMBIGUOUS ACTIVE] Ticket #{res.ticket_code} (Status: {res.status}): "
                    f"Current reserved_days={res.reserved_days} -> Proposed={inferred_days} (Dates: {res.start_date} to {res.finish_date})"
                )
                records_to_update.append((res, inferred_days))

        if apply_changes and records_to_update:
            with transaction.atomic():
                for res, new_days in records_to_update:
                    res.reserved_days = new_days
                    res.is_legacy = True
                    note = f"Reconciled reserved_days from {res.reserved_days} to {new_days} via management command."
                    res.staff_notes = (res.staff_notes + f"\n{note}").strip()
                    res.save(update_fields=['reserved_days', 'is_legacy', 'staff_notes'])
                    updated_count += 1
            self.stdout.write(self.style.SUCCESS(f"\nSuccessfully applied updates to {updated_count} active reservations."))
        elif not apply_changes and records_to_update:
            self.stdout.write(self.style.NOTICE(f"\nDRY-RUN completed. Found {len(records_to_update)} active reservations requiring reconciliation."))
            self.stdout.write("Run with --apply to commit these changes to active reservations.")
        else:
            self.stdout.write(self.style.SUCCESS("\nAll reservation durations are consistent. No reconciliation needed."))

        self.stdout.write(
            f"\nSummary:\n"
            f"  - Total scanned: {total_checked}\n"
            f"  - Settled records preserved (immutable): {settled_skipped}\n"
            f"  - Ambiguous active records: {ambiguous_found}\n"
            f"  - Records updated: {updated_count}\n"
        )
