from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.views.decorators.http import require_POST
from django.utils import timezone
from .models import ParkingZone, Reservation
from .forms import ReservationForm


def zone_detail(request, slug):
    """Display individual parking zone status and details."""
    zone = get_object_or_404(ParkingZone, slug=slug)
    user_active_res = None
    if request.user.is_authenticated:
        user_active_res = Reservation.objects.filter(
            customer=request.user,
            parking_zone=zone,
            checked_out=False
        ).first()

    context = {
        'parking_zone': zone,
        'title': f'{zone.name} - SomPark Phnom Penh',
        'user_active_res': user_active_res,
    }
    return render(request, 'parking_zones/status.html', context)


@login_required
def booking(request):
    """Reserve a parking slot with concurrency protection."""
    # Pre-check active reservation
    active_reservation = Reservation.objects.filter(
        customer=request.user,
        checked_out=False
    ).first()

    if active_reservation:
        messages.warning(
            request,
            f'You already have an active reservation at {active_reservation.parking_zone.name} '
            f'(Ticket: {active_reservation.ticket_code}). Please check out before booking another space.'
        )
        return redirect('home')

    selected_zone_slug = request.GET.get('zone')
    initial_data = {}
    if selected_zone_slug:
        zone = ParkingZone.objects.filter(slug=selected_zone_slug).first()
        if zone and zone.vacant_slots > 0:
            initial_data['parking_zone'] = zone

    if request.method == 'POST':
        form = ReservationForm(request.POST)
        if form.is_valid():
            zone = form.cleaned_data['parking_zone']
            try:
                with transaction.atomic():
                    # Concurrency safety: lock the zone row
                    locked_zone = ParkingZone.objects.select_for_update().get(id=zone.id)

                    # Re-verify active reservation inside the transaction lock
                    if Reservation.objects.filter(customer=request.user, checked_out=False).exists():
                        messages.warning(request, 'You already have an active reservation.')
                        return redirect('home')

                    if locked_zone.vacant_slots <= 0:
                        messages.error(request, f'Sorry, {locked_zone.name} has just run out of vacant spots.')
                        return render(request, 'parking_zones/booking.html', {
                            'form': form,
                            'title': 'Book Parking Spot | SomPark',
                            'active_reservation': active_reservation,
                        })

                    # Decrement vacancy, increment occupancy
                    locked_zone.occupied_slots = min(locked_zone.num_of_slots, locked_zone.occupied_slots + 1)
                    locked_zone.vacant_slots = max(0, locked_zone.num_of_slots - locked_zone.occupied_slots)
                    locked_zone.save()

                    reservation = form.save(commit=False)
                    reservation.customer = request.user
                    reservation.parking_zone = locked_zone
                    reservation.checked_out = False
                    reservation.save()

                    messages.success(
                        request,
                        f'ចំណតត្រូវបានកក់ដោយជោគជ័យ! Parking reserved successfully. '
                        f'Ticket Code: {reservation.ticket_code}'
                    )
                    return redirect('ticket')
            except ParkingZone.DoesNotExist:
                messages.error(request, 'Selected parking zone could not be found.')
                return redirect('book')
    else:
        # Pre-populate today's date
        today = timezone.localdate()
        initial_data.setdefault('start_date', today)
        initial_data.setdefault('finish_date', today)
        form = ReservationForm(initial=initial_data)

    context = {
        'form': form,
        'title': 'Reserve Parking Slot | SomPark',
        'active_reservation': active_reservation,
        'parking_zones': ParkingZone.objects.all(),
    }
    return render(request, 'parking_zones/booking.html', context)


@login_required
def ticket_detail(request, ticket_code=None):
    """View and print a parking ticket."""
    if ticket_code:
        reservation = get_object_or_404(
            Reservation,
            ticket_code=ticket_code,
            customer=request.user
        )
    else:
        # Deterministic: prioritize active reservation, then latest
        reservation = Reservation.objects.filter(
            customer=request.user,
            checked_out=False
        ).order_by('-created_on').first()

        if not reservation:
            reservation = Reservation.objects.filter(
                customer=request.user
            ).order_by('-created_on').first()

    if not reservation:
        messages.info(request, 'No reservation records found. Book your first parking spot below.')
        return redirect('book')

    context = {
        'reservation': reservation,
        'title': f'Ticket #{reservation.ticket_code} - SomPark',
        'today': timezone.localdate(),
    }
    return render(request, 'parking_zones/ticket.html', context)


@login_required
def all_tickets(request):
    """View reservation history."""
    reservations = Reservation.objects.filter(
        customer=request.user
    ).select_related('parking_zone').order_by('-created_on')

    active_reservation = reservations.filter(checked_out=False).first()

    context = {
        'tickets': reservations,
        'reservations': reservations,
        'active_reservation': active_reservation,
        'title': 'My Parking Tickets | SomPark',
    }
    return render(request, 'parking_zones/all_tickets.html', context)


@login_required
@require_POST
def checkout(request):
    """
    POST-only checkout operation with CSRF protection and concurrency safety.
    Prevents changing reservation state via GET requests.
    """
    ticket_code = request.POST.get('ticket_code')

    # Security check: if ticket_code belongs to another user, deny immediately
    if ticket_code and Reservation.objects.filter(ticket_code=ticket_code).exclude(customer=request.user).exists():
        raise PermissionDenied('You do not have permission to check out another user’s ticket.')

    with transaction.atomic():
        query = Reservation.objects.select_for_update().filter(
            customer=request.user,
            checked_out=False
        )
        if ticket_code:
            reservation = query.filter(ticket_code=ticket_code).first()
        else:
            reservation = query.order_by('-created_on').first()

        if not reservation:
            messages.warning(request, 'No active parking reservation found to check out.')
            return redirect('home')

        # Mark checked out
        reservation.checked_out = True
        reservation.save()

        # Update zone inventory
        zone = ParkingZone.objects.select_for_update().get(id=reservation.parking_zone_id)
        zone.occupied_slots = max(0, zone.occupied_slots - 1)
        zone.vacant_slots = min(zone.num_of_slots, zone.num_of_slots - zone.occupied_slots)
        zone.save()

        messages.success(
            request,
            f'ចេញពីចំណតដោយជោគជ័យ! Checked out from {zone.name}. Ticket #{reservation.ticket_code} completed.'
        )

    return redirect('home')
