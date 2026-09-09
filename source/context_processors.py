from django.conf import settings
from django.utils import timezone
from parking_zones.models import Reservation


def sompark_context(request):
    """Global context processor for SomPark Phnom Penh."""
    active_reservation = None
    if request.user.is_authenticated:
        active_reservation = Reservation.objects.filter(
            customer=request.user,
            checked_out=False
        ).select_related('parking_zone').first()

    return {
        'BRAND_NAME': 'SomPark',
        'BRAND_TAGLINE_KHMER': 'ចំណតឆ្លាតវៃ សម្រាប់រាជធានីភ្នំពេញ',
        'BRAND_TAGLINE_EN': 'Smart Parking for Phnom Penh Capital',
        'active_reservation': active_reservation,
        'current_date': timezone.localdate(),
        'ASSET_VERSION': getattr(settings, 'ASSET_VERSION', '1.2.0'),
    }
