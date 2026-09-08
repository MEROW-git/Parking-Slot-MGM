from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST, require_http_methods
from django.utils.http import url_has_allowed_host_and_scheme
from parking_zones.models import Reservation
from .forms import UserRegistrationForm, SomParkLoginForm


def register_user(request):
    """Register a new customer account."""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()

            messages.success(
                request,
                'Account created successfully. Sign in to continue.'
            )
            return redirect('login')
    else:
        form = UserRegistrationForm()

    return render(request, 'users/signup.html', {
        'form': form,
        'title': 'Create SomPark Account | Phnom Penh',
    })


def login_user(request):
    """Authenticate existing customer with safe next-redirect."""
    if request.user.is_authenticated:
        return redirect('dashboard')

    next_url = request.GET.get('next') or request.POST.get('next')

    if request.method == 'POST':
        form = SomParkLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(
                request,
                f'Welcome back, {user.username}.'
            )

            # Validate next URL safety
            if next_url and url_has_allowed_host_and_scheme(url=next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect('dashboard')
    else:
        form = SomParkLoginForm(request)

    return render(request, 'users/login.html', {
        'form': form,
        'next': next_url or '',
        'title': 'Sign In | SomPark Phnom Penh',
    })


@login_required
def dashboard(request):
    """
    Dedicated authenticated customer dashboard.
    Displays real Django data: greeting, active reservation, quick actions,
    recent reservations, and appropriate empty state.
    """
    user_reservations = Reservation.objects.filter(
        customer=request.user
    ).select_related('parking_zone').order_by('-created_on')

    active_reservation = user_reservations.filter(checked_out=False).first()
    recent_reservations = user_reservations[:5]
    has_reservations = user_reservations.exists()

    return render(request, 'users/dashboard.html', {
        'active_reservation': active_reservation,
        'recent_reservations': recent_reservations,
        'has_reservations': has_reservations,
        'total_reservations': user_reservations.count(),
        'title': f'Dashboard - {request.user.username} | SomPark Phnom Penh',
    })


@require_http_methods(['GET', 'POST'])
def logout_user(request):
    """
    Log out user. Enforces safe logout flow.
    Supports POST with CSRF, with fallback for standard links.
    """
    if request.user.is_authenticated:
        username = request.user.username
        logout(request)
        messages.info(request, f'អ្នកបានចាកចេញដោយជោគជ័យ។ You have been signed out. Have a safe drive, {username}!')
    return redirect('home')

