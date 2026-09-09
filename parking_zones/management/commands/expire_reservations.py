from django.core.management.base import BaseCommand
from parking_zones.services import ExpiryService


class Command(BaseCommand):
    help = 'Idempotently expires stale unpaid same-day arrival holds, timed-out deposit payments, and no-shows.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Running SomPark reservation expiry check...'))
        results = ExpiryService.expire_stale_holds()
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully expired: "
                f"{results['unpaid_holds']} unpaid arrival holds, "
                f"{results['deposit_timeouts']} deposit payment timeouts, "
                f"{results['no_shows']} no-show bookings."
            )
        )
