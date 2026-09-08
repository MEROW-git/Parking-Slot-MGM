from django.db import migrations


def seed_zones(apps, schema_editor):
    ParkingZone = apps.get_model('parking_zones', 'ParkingZone')
    zones_data = [
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

    for item in zones_data:
        ParkingZone.objects.update_or_create(slug=item['slug'], defaults=item)


def unseed_zones(apps, schema_editor):
    ParkingZone = apps.get_model('parking_zones', 'ParkingZone')
    ParkingZone.objects.filter(slug__in=[
        'riverside-promenade',
        'bkk1-commercial-plaza',
        'toul-kork-plaza',
        'sen-sok-central',
        'olympic-stadium-complex',
        'city-center-vattanac'
    ]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('parking_zones', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_zones, unseed_zones),
    ]
