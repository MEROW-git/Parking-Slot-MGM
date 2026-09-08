from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.views.decorators.http import require_POST, require_http_methods
from django.utils.http import url_has_allowed_host_and_scheme
from .forms import UserRegistrationForm, SomParkLoginForm


def register_user(request):
    """Register a new customer account."""
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()

            messages.success(
                request,
                f'សូមស្វាគមន៍! Welcome, {user.username}! Account created successfully. You can now log in.'
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
        return redirect('home')

    next_url = request.GET.get('next') or request.POST.get('next') or 'home'

    if request.method == 'POST':
        form = SomParkLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(
                request,
                f'ស្វាគមន៍មកកាន់ SomPark! Welcome back, {user.username}.'
            )

            # Validate next URL safety
            if not url_has_allowed_host_and_scheme(url=next_url, allowed_hosts={request.get_host()}):
                next_url = 'home'
            return redirect(next_url)
    else:
        form = SomParkLoginForm(request)

    return render(request, 'users/login.html', {
        'form': form,
        'next': next_url,
        'title': 'Sign In | SomPark Phnom Penh',
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
