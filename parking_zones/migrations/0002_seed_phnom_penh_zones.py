from django.db import migrations


def seed_zones(apps, schema_editor):
    # Seeding is decoupled from migrations and handled explicitly via 'python manage.py seed_demo'
    pass


def unseed_zones(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('parking_zones', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_zones, unseed_zones),
    ]

