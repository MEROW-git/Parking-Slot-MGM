import json
from django.conf import settings
from django.shortcuts import render
from django.urls import reverse
from django.db.models import Sum
from parking_zones.models import ParkingZone, Reservation


def home(request):
    """
    Homepage and parking availability dashboard.
    Clearly answers:
    - What is this service?
    - Where can I park?
    - How many spaces are available?
    - What does it cost in KHR?
    - How do I reserve?
    - What is my current reservation status?
    """
    query = request.GET.get('q', '').strip()
    district_filter = request.GET.get('district', '').strip()

    zones = ParkingZone.objects.all()
    if district_filter:
        zones = zones.filter(district__iexact=district_filter)
    if query:
        zones = zones.filter(name__icontains=query) | zones.filter(address__icontains=query) | zones.filter(district__icontains=query)

    # Aggregates across Phnom Penh
    all_zones = ParkingZone.objects.all()
    total_slots = all_zones.aggregate(Sum('num_of_slots'))['num_of_slots__sum'] or 0
    total_vacant = all_zones.aggregate(Sum('vacant_slots'))['vacant_slots__sum'] or 0
    total_occupied = all_zones.aggregate(Sum('occupied_slots'))['occupied_slots__sum'] or 0

    districts = ParkingZone.objects.values_list('district', flat=True).distinct()

    zones_map_data = []
    for z in zones:
        coords = z.coordinates
        zones_map_data.append({
            'id': z.id,
            'name': z.name,
            'khmer_name': z.khmer_name,
            'slug': z.slug,
            'address': z.address,
            'district': z.district,
            'price': z.price,
            'price_formatted': z.price_khr_formatted,
            'vacant_slots': z.vacant_slots,
            'num_of_slots': z.num_of_slots,
            'occupied_slots': z.occupied_slots,
            'availability_status': z.availability_status,
            'lat': coords['lat'],
            'lng': coords['lng'],
            'operating_hours': getattr(z, 'operating_hours', '24/7 Access') or '24/7 Access',
            'book_url': reverse('book') + f'?zone={z.slug}',
            'detail_url': reverse('zone_detail', kwargs={'slug': z.slug}),
        })

    context = {
        'all_parking_zones': zones,
        'zones_map_json': json.dumps(zones_map_data),
        'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY,
        'total_slots': total_slots,
        'total_vacant': total_vacant,
        'total_occupied': total_occupied,
        'districts': districts,
        'selected_district': district_filter,
        'search_query': query,
        'title': 'SomPark - Phnom Penh Smart Parking (ចំណតឆ្លាតវៃ ភ្នំពេញ)',
    }
    return render(request, 'source/index.html', context)


def component_showcase(request):
    """Component library showcase demonstrating all states and variants."""
    sample_zone_available = ParkingZone(
        name='Riverside Promenade Lot',
        khmer_name='ចំណតមាត់ទន្លេ ស៊ីសុវត្ថិ',
        slug='riverside-showcase',
        num_of_slots=45,
        occupied_slots=10,
        vacant_slots=35,
        address='Preah Sisowath Quay, Daun Penh',
        district='Riverside / Daun Penh',
        price=3000,
        operating_hours='24/7'
    )
    sample_zone_limited = ParkingZone(
        name='BKK1 Commercial Plaza',
        khmer_name='ចំណតពាណិជ្ជកម្ម បឹងកេងកង១',
        slug='bkk1-showcase',
        num_of_slots=40,
        occupied_slots=37,
        vacant_slots=3,
        address='Street 282, Boeung Keng Kang 1',
        district='BKK1',
        price=4000,
        operating_hours='07:00 - 23:00'
    )
    sample_zone_full = ParkingZone(
        name='Central Market Hub',
        khmer_name='ចំណតផ្សារធំថ្មី',
        slug='central-market-showcase',
        num_of_slots=50,
        occupied_slots=50,
        vacant_slots=0,
        address='Calmette St, Daun Penh',
        district='Phnom Penh City Center',
        price=2500,
        operating_hours='06:00 - 20:00'
    )

    context = {
        'title': 'Component System Showcase | SomPark',
        'sample_zone': sample_zone_available,
        'sample_available': sample_zone_available,
        'sample_limited': sample_zone_limited,
        'sample_full': sample_zone_full,
    }
    return render(request, 'source/components.html', context)
