import secrets
from datetime import time, datetime
from django.db import migrations
from django.utils import timezone


def reconcile_existing_reservations(apps, schema_editor):
    Reservation = apps.get_model('parking_zones', 'Reservation')
    tz = timezone.get_current_timezone()

    for res in Reservation.objects.all():
        # Populate access_token
        if not res.access_token:
            res.access_token = secrets.token_hex(32)

        # Snapshot daily rate
        if not res.daily_rate and res.parking_zone:
            res.daily_rate = res.parking_zone.price

        # Synthesize timestamps
        if not res.start_time and res.start_date:
            res.start_time = timezone.make_aware(datetime.combine(res.start_date, time(6, 0)), tz)
        if not res.finish_time and res.finish_date:
            res.finish_time = timezone.make_aware(datetime.combine(res.finish_date, time(22, 0)), tz)

        # Reconcile status and payment
        res.is_legacy = True
        if res.checked_out:
            res.status = 'CHECKED_OUT'
            res.payment_status = 'PAID'
            if not res.checked_out_at:
                res.checked_out_at = res.finish_time or res.created_on
        else:
            res.status = 'CHECKED_IN'
            res.payment_status = 'PAID'
            if not res.checked_in_at:
                res.checked_in_at = res.start_time or res.created_on

        res.save()


def reverse_reconcile(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('parking_zones', '0003_reservation_access_token_and_more'),
    ]

    operations = [
        migrations.RunPython(reconcile_existing_reservations, reverse_reconcile),
    ]
