"""
Management command to seed realistic Cambodian parking zones and sample data
into the SomPark database in an idempotent, safe manner.

Usage:
    python manage.py seed_demo
"""

from datetime import timedelta, date
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone

from parking_zones.models import ParkingZone, Reservation, PaymentTransaction


PHNOM_PENH_ZONES = [
    {
        'name': 'Riverside Promenade Parking',
        'khmer_name': 'ចំណតមាត់ទន្លេ ស៊ីសុវត្ថិ',
        'slug': 'riverside-promenade',
        'num_of_slots': 45,
        'occupied_slots': 14,
        'vacant_slots': 31,
        'address': 'Preah Sisowath Quay, Sangkat Chey Chumneah, Khan Daun Penh',
        'district': 'Riverside',
        'price': 3000,
        'operating_hours': '06:00 - 23:30',
        'description': 'Scenic parking along Phnom Penh riverside, convenient for restaurants, river cruises, and Royal Palace visitors.',
    },
    {
        'name': 'BKK1 Commercial Plaza',
        'khmer_name': 'ចំណតពាណិជ្ជកម្ម បឹងកេងកង១',
        'slug': 'bkk1-commercial-plaza',
        'num_of_slots': 50,
        'occupied_slots': 38,
        'vacant_slots': 12,
        'address': 'Street 282 (Corner St 51), Sangkat BKK1, Khan Boeung Keng Kang',
        'district': 'BKK1',
        'price': 4000,
        'operating_hours': '24/7 Covered Access',
        'description': 'Central multi-level covered parking in the vibrant BKK1 business, cafe, and dining district.',
    },
    {
        'name': 'Toul Kork Plaza Hub',
        'khmer_name': 'ចំណតផ្សារទួលគោក ផ្លូវ៣១៥',
        'slug': 'toul-kork-plaza',
        'num_of_slots': 60,
        'occupied_slots': 22,
        'vacant_slots': 38,
        'address': 'Street 315, Sangkat Boeung Kak 1, Khan Toul Kork',
        'district': 'Toul Kork',
        'price': 2500,
        'operating_hours': '06:00 - 22:00',
        'description': 'Spacious parking lot with direct access to TK Avenue and commercial shopping in Toul Kork.',
    },
    {
        'name': 'Sen Sok Central Lot',
        'khmer_name': 'ចំណតសែនសុខ កណ្តាលក្រុង',
        'slug': 'sen-sok-central',
        'num_of_slots': 90,
        'occupied_slots': 40,
        'vacant_slots': 50,
        'address': 'Street 1003, Sangkat Phnom Penh Thmey, Khan Sen Sok',
        'district': 'Sen Sok',
        'price': 3000,
        'operating_hours': '08:00 - 22:30',
        'description': 'High-capacity parking facility serving the growing Sen Sok retail and entertainment area.',
    },
    {
        'name': 'Olympic Stadium Complex',
        'khmer_name': 'ចំណតពហុកីឡដ្ឋានជាតិអូឡាំពិក',
        'slug': 'olympic-stadium-complex',
        'num_of_slots': 80,
        'occupied_slots': 72,
        'vacant_slots': 8,
        'address': 'Preah Sihanouk Blvd, Sangkat Olympic, Khan Boeng Keng Kang',
        'district': 'Olympic',
        'price': 2000,
        'operating_hours': '05:30 - 22:00',
        'description': 'Convenient parking for sports events, fitness activities, and nearby Olympic Market shoppers.',
    },
    {
        'name': 'City Center Vattanac & Canadia',
        'khmer_name': 'ចំណតមជ្ឈមណ្ឌល វឌ្ឍនៈ-កាណាឌីយ៉ា',
        'slug': 'city-center-vattanac',
        'num_of_slots': 70,
        'occupied_slots': 52,
        'vacant_slots': 18,
        'address': 'Preah Monivong Blvd, Sangkat Srah Chak, Khan Daun Penh',
        'district': 'Phnom Penh City Center',
        'price': 5000,
        'operating_hours': '24/7 Security Patrol',
        'description': 'Premium financial district parking featuring automated boom gates and 24-hour security.',
    },
]


class Command(BaseCommand):
    help = 'Idempotently seeds Phnom Penh parking zones, sample customer data, and demo reservations.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=== SomPark Idempotent Demo Seeder ==="))

        # 1. Seed Parking Zones
        self.stdout.write("Checking Phnom Penh parking facilities...")
        zones_created = 0
        zones_existing = 0

        for zone_data in PHNOM_PENH_ZONES:
            zone, created = ParkingZone.objects.get_or_create(
                slug=zone_data['slug'],
                defaults=zone_data
            )
            if created:
                zones_created += 1
                self.stdout.write(self.style.SUCCESS(f"  + Created zone: {zone.name} ({zone.khmer_name})"))
            else:
                zones_existing += 1
                self.stdout.write(self.style.NOTICE(f"  - Zone already exists (preserved): {zone.name}"))

        self.stdout.write(f"Zones summary: {zones_created} created, {zones_existing} already present.")

        # 2. Seed Sample Customer Account
        self.stdout.write("\nChecking sample customer account...")
        demo_user, user_created = User.objects.get_or_create(
            username='demo',
            defaults={
                'first_name': 'Dara',
                'last_name': 'Sok',
                'email': 'demo@sompark.kh',
            }
        )
        if user_created:
            demo_user.set_password('password123')
            demo_user.save()
            self.stdout.write(self.style.SUCCESS("  + Created demo customer: username 'demo' / password 'password123'"))
        else:
            self.stdout.write(self.style.NOTICE("  - Demo customer 'demo' already exists (password preserved)"))

        # 3. Seed Sample Reservations in Consistent Lifecycle States
        self.stdout.write("\nChecking sample reservations...")
        now = timezone.now()

        # A. Sample CONFIRMED arrival hold (unpaid, 3-hour arrival window)
        res1_code = 'SPK-DEMO001'
        if not Reservation.objects.filter(ticket_code=res1_code).exists():
            zone_bkk1 = ParkingZone.objects.filter(slug='bkk1-commercial-plaza').first()
            if zone_bkk1:
                r1 = Reservation.objects.create(
                    ticket_code=res1_code,
                    customer=demo_user,
                    parking_zone=zone_bkk1,
                    plate_number='2AZ-1234',
                    phone_number='+855 12 345 678',
                    start_date=date.today(),
                    finish_date=date.today(),
                    start_time=now,
                    finish_time=now + timedelta(hours=8),
                    daily_rate=zone_bkk1.price,
                    overstay_multiplier=2.0,
                    payment_method='PAY_AT_EXIT',
                    payment_status='UNPAID',
                    status='CONFIRMED',
                    arrival_deadline=now + timedelta(hours=3),
                    access_token='demo_access_token_hold_001',
                )
                self.stdout.write(self.style.SUCCESS(f"  + Created sample CONFIRMED hold: #{r1.ticket_code} ({r1.plate_number})"))
        else:
            self.stdout.write(self.style.NOTICE(f"  - Sample ticket #{res1_code} already exists (preserved)"))

        # B. Sample CHECKED_IN parked vehicle (deposit paid, entered facility)
        res2_code = 'SPK-DEMO002'
        if not Reservation.objects.filter(ticket_code=res2_code).exists():
            zone_river = ParkingZone.objects.filter(slug='riverside-promenade').first()
            if zone_river:
                r2 = Reservation.objects.create(
                    ticket_code=res2_code,
                    customer=demo_user,
                    parking_zone=zone_river,
                    plate_number='2BC-5678',
                    phone_number='+855 98 765 432',
                    start_date=date.today(),
                    finish_date=date.today(),
                    start_time=now - timedelta(hours=2),
                    finish_time=now + timedelta(hours=4),
                    daily_rate=zone_river.price,
                    overstay_multiplier=2.0,
                    payment_method='DEPOSIT',
                    payment_status='PARTIALLY_PAID',
                    deposit_amount=zone_river.price,
                    status='CHECKED_IN',
                    checked_in_at=now - timedelta(hours=2),
                    access_token='demo_access_token_parked_002',
                )
                PaymentTransaction.objects.create(
                    reservation=r2,
                    amount=zone_river.price,
                    currency='KHR',
                    provider='DEMO',
                    provider_ref='TXN-DEMO-DEP-002',
                    status='SUCCESS',
                    purpose='DEPOSIT',
                    completed_at=now - timedelta(hours=2),
                    is_demo=True,
                )
                self.stdout.write(self.style.SUCCESS(f"  + Created sample CHECKED_IN stay: #{r2.ticket_code} ({r2.plate_number})"))
        else:
            self.stdout.write(self.style.NOTICE(f"  - Sample ticket #{res2_code} already exists (preserved)"))

        # C. Sample CHECKED_OUT completed historical stay
        res3_code = 'SPK-DEMO003'
        if not Reservation.objects.filter(ticket_code=res3_code).exists():
            zone_tk = ParkingZone.objects.filter(slug='toul-kork-plaza').first()
            if zone_tk:
                r3 = Reservation.objects.create(
                    ticket_code=res3_code,
                    customer=demo_user,
                    parking_zone=zone_tk,
                    plate_number='1A-9999',
                    phone_number='+855 77 112 233',
                    start_date=date.today() - timedelta(days=1),
                    finish_date=date.today() - timedelta(days=1),
                    start_time=now - timedelta(days=1, hours=5),
                    finish_time=now - timedelta(days=1),
                    daily_rate=zone_tk.price,
                    overstay_multiplier=2.0,
                    payment_method='PAY_AT_EXIT',
                    payment_status='PAID',
                    status='CHECKED_OUT',
                    checked_out=True,
                    total_amount=zone_tk.price,
                    balance_paid=zone_tk.price,
                    checked_in_at=now - timedelta(days=1, hours=5),
                    checked_out_at=now - timedelta(days=1, hours=1),
                    access_token='demo_access_token_done_003',
                )
                PaymentTransaction.objects.create(
                    reservation=r3,
                    amount=zone_tk.price,
                    currency='KHR',
                    provider='DEMO',
                    provider_ref='TXN-DEMO-EXIT-003',
                    status='SUCCESS',
                    purpose='EXIT_BALANCE',
                    completed_at=now - timedelta(days=1, hours=1),
                    is_demo=True,
                )
                self.stdout.write(self.style.SUCCESS(f"  + Created sample CHECKED_OUT stay: #{r3.ticket_code} ({r3.plate_number})"))
        else:
            self.stdout.write(self.style.NOTICE(f"  - Sample ticket #{res3_code} already exists (preserved)"))

        self.stdout.write(self.style.SUCCESS("\nSeeding complete!"))
        self.stdout.write(
            "To access the Django Admin or Operations Workbench, create a superuser:\n"
            "    python manage.py createsuperuser\n"
        )
