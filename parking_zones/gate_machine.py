"""
Admin virtual parking gate simulator.
Simulates optical QR / physical barrier arm operations for Entrance and Exit.
Passage confirmation delegates to real atomic parking services.
"""
from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core import signing
from django.db import transaction
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import ParkingZone, Reservation
from .services import BillingService, GateService, PaymentService


class GateMachineForm(forms.Form):
    zone = forms.ModelChoiceField(
        queryset=ParkingZone.objects.order_by('name'),
        label='Parking facility',
        empty_label='— Select Parking Facility —'
    )
    mode = forms.ChoiceField(
        choices=[('entry', 'Entrance (ចូល)'), ('exit', 'Exit (ចេញ)')],
        widget=forms.RadioSelect,
        label='Direction'
    )
    code = forms.CharField(
        max_length=128,
        label='Ticket code or access QR token',
        widget=forms.TextInput(
            attrs={
                'placeholder': 'SPK-XXXXXXX or 48-char hex token',
                'autocomplete': 'off',
                'spellcheck': 'false',
                'class': 'vg-code-input'
            }
        )
    )


@require_http_methods(['GET', 'POST'])
def virtual_gate(request):
    """
    Virtual Parking Gate Terminal Simulator for Django Admin.
    Allows staff to simulate physical barrier arm operations with strict
    server-side authorization, cryptographic signed permits, and atomic inventory updates.
    """
    initial = {'mode': request.GET.get('mode', 'entry')}
    if request.GET.get('zone'):
        initial['zone'] = request.GET.get('zone')
    if request.GET.get('code'):
        initial['code'] = request.GET.get('code')

    form = GateMachineForm(request.POST or None, initial=initial)
    demo_enabled = getattr(settings, 'DEMO_PAYMENT_ENABLED', True)

    context = {
        **admin.site.each_context(request),
        'title': 'Virtual Parking Gate Terminal',
        'form': form,
        'demo_enabled': demo_enabled,
        'now': timezone.now(),
        'gate_open': False,
        'passed': False,
    }

    # If GET has valid code and zone, inspect reservation for preview
    if request.method == 'GET' and initial.get('zone') and initial.get('code'):
        zone_id = initial.get('zone')
        code = initial.get('code').strip()
        mode = initial.get('mode', 'entry')
        reservation = (
            Reservation.objects.filter(ticket_code=code).first() or
            Reservation.objects.filter(access_token=code).first()
        )
        if reservation:
            if str(reservation.parking_zone_id) == str(zone_id):
                bill = BillingService.calculate_bill(reservation, as_of=timezone.now()) if mode == 'exit' else None
                context.update(reservation=reservation, bill=bill)

    if request.method == 'POST' and form.is_valid():
        zone = form.cleaned_data['zone']
        mode = form.cleaned_data['mode']
        code = form.cleaned_data['code'].strip()
        action = request.POST.get('action', 'open')

        reservation = Reservation.objects.filter(ticket_code=code).first()
        if reservation is None:
            reservation = Reservation.objects.filter(access_token=code).first()

        if reservation is None:
            form.add_error('code', f'No reservation found matching ticket code or QR token "{code}".')
        elif reservation.parking_zone_id != zone.pk:
            form.add_error(
                'code',
                f'Ticket #{reservation.ticket_code} is registered for facility '
                f'"{reservation.parking_zone.name}", not "{zone.name}".'
            )
        elif action not in ('open', 'close', 'pass', 'settle'):
            form.add_error(None, f'Unknown gate action "{action}".')
        else:
            with transaction.atomic():
                reservation = Reservation.objects.select_for_update().get(pk=reservation.pk)
                ParkingZone.objects.select_for_update().get(pk=zone.pk)

                # Action: Close barrier without passage
                if action == 'close':
                    context['gate_open'] = False
                    context['notice'] = 'Barrier closed without passage. Reservation status and parking capacity remain unchanged.'
                    if mode == 'exit':
                        bill = BillingService.calculate_bill(reservation, as_of=timezone.now())
                        context.update(reservation=reservation, bill=bill)
                    else:
                        context.update(reservation=reservation)
                    return render(request, 'admin/virtual_gate.html', context)

                # Action: Settle exit balance
                if action == 'settle':
                    if mode != 'exit':
                        form.add_error(None, 'Payment settlement is only applicable in Exit mode.')
                    else:
                        bill = BillingService.calculate_bill(reservation, as_of=timezone.now())
                        amount_due = bill['balance_due']
                        if amount_due > 0:
                            provider = request.POST.get('payment_provider', 'CASH')
                            if provider == 'DEMO' and not demo_enabled:
                                provider = 'CASH'
                            PaymentService.record_exit_payment(reservation, amount=amount_due, provider=provider)
                            messages.success(
                                request,
                                f"Exit balance of {amount_due:,} KHR paid via {provider}. "
                                f"5-minute departure window authorized."
                            )
                            reservation.refresh_from_db()

                        allowed, _, bill, notice = GateService.prepare_exit(reservation.ticket_code)
                        context.update(reservation=reservation, bill=bill, notice=notice, gate_open=False)
                    return render(request, 'admin/virtual_gate.html', context)

                # Action: Check ticket & open barrier
                if mode == 'entry':
                    allowed, _, notice = GateService.validate_entry(reservation.ticket_code, zone.pk)
                    bill = None
                else:
                    allowed, _, bill, notice = GateService.prepare_exit(reservation.ticket_code)

                context.update(reservation=reservation, bill=bill, notice=notice)

                # Action: Confirm vehicle passage & close barrier
                if action == 'pass':
                    try:
                        permit = signing.loads(request.POST.get('permit', ''), salt='virtual-gate', max_age=120)
                        expected = [request.user.pk, reservation.pk, zone.pk, mode]
                        if permit != expected:
                            raise signing.BadSignature('Mismatched gate permit')
                    except signing.BadSignature:
                        allowed = False
                        context['notice'] = 'Gate authorization expired or invalid. Check the ticket again.'

                    if allowed:
                        operation = GateService.confirm_entry if mode == 'entry' else GateService.confirm_physical_exit
                        success, reservation, notice = operation(reservation.pk, staff_user=request.user)
                        context.update(reservation=reservation, notice=notice, passed=success, gate_open=False)
                        if success:
                            context['notice'] = 'Vehicle passage recorded. Barrier closed.'
                            messages.success(request, context['notice'])
                    else:
                        context['gate_open'] = False

                elif action == 'open':
                    if allowed:
                        context['gate_open'] = True
                        context['permit'] = signing.dumps(
                            [request.user.pk, reservation.pk, zone.pk, mode], salt='virtual-gate'
                        )
                        context['notice'] = 'Ticket verified. Barrier is OPEN — waiting for vehicle to pass.'
                    else:
                        context['gate_open'] = False

    return render(request, 'admin/virtual_gate.html', context)
