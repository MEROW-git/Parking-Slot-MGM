"""
Admin virtual parking gate simulator.
Simulates optical QR / physical barrier arm operations for Entrance and Exit.
Passage confirmation delegates to real atomic parking services.
"""
import secrets
import time
from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core import signing
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import ParkingZone, Reservation
from .qr import generate_demo_payment_qr_base64
from .services import BillingService, GateService, PaymentService


def _attach_exit_qr_if_needed(context, reservation, bill, demo_enabled):
    """
    Attaches simulated ABA payment QR to context when an outstanding balance is due.
    QR payload uses 'sompark:payment:demo:...' distinct from parking access pass QR.
    """
    if reservation and bill and bill.get('balance_due', 0) > 0 and demo_enabled:
        ref = f"ABA-EXIT-{reservation.ticket_code}"
        context['demo_payment_qr'] = generate_demo_payment_qr_base64(ref, int(bill['balance_due']), currency='KHR')
        context['demo_payment_ref'] = ref



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
    is_ajax = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        'application/json' in request.headers.get('Accept', '')
    )

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
        'just_passed': False,
        'permit_expires_at': None,
    }

    # If GET has valid code and zone, inspect reservation for preview or telemetry reconciliation
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
                _attach_exit_qr_if_needed(context, reservation, bill, demo_enabled)
                if is_ajax:
                    return JsonResponse({
                        'success': True,
                        'ticket_code': reservation.ticket_code,
                        'plate_number': reservation.plate_number,
                        'status': reservation.status,
                        'status_display': reservation.get_status_display(),
                        'mode': mode,
                        'checked_in_at': reservation.checked_in_at.isoformat() if reservation.checked_in_at else None,
                        'checked_out_at': reservation.checked_out_at.isoformat() if reservation.checked_out_at else None,
                    })

    if request.method == 'POST' and not form.is_valid() and is_ajax:
        return JsonResponse({'success': False, 'notice': form.errors.as_text()}, status=400)

    if request.method == 'POST' and form.is_valid():
        zone = form.cleaned_data['zone']
        mode = form.cleaned_data['mode']
        code = form.cleaned_data['code'].strip()
        action = request.POST.get('action', 'open')

        reservation = Reservation.objects.filter(ticket_code=code).first()
        if reservation is None:
            reservation = Reservation.objects.filter(access_token=code).first()

        if reservation is None:
            err = f'No reservation found matching ticket code or QR token "{code}".'
            if is_ajax:
                return JsonResponse({'success': False, 'notice': err}, status=400)
            form.add_error('code', err)
        elif reservation.parking_zone_id != zone.pk:
            err = (
                f'Ticket #{reservation.ticket_code} is registered for facility '
                f'"{reservation.parking_zone.name}", not "{zone.name}".'
            )
            if is_ajax:
                return JsonResponse({'success': False, 'notice': err}, status=400)
            form.add_error('code', err)
        elif action not in ('open', 'close', 'pass', 'settle'):
            err = f'Unknown gate action "{action}".'
            if is_ajax:
                return JsonResponse({'success': False, 'notice': err}, status=400)
            form.add_error(None, err)
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
                        _attach_exit_qr_if_needed(context, reservation, bill, demo_enabled)
                    else:
                        context.update(reservation=reservation)
                    if is_ajax:
                        return JsonResponse({
                            'success': True,
                            'gate_open': False,
                            'passed': False,
                            'notice': context['notice'],
                        })
                    return render(request, 'admin/virtual_gate.html', context)

                # Action: Settle exit balance
                if action == 'settle':
                    if mode != 'exit':
                        err = 'Payment settlement is only applicable in Exit mode.'
                        if is_ajax:
                            return JsonResponse({'success': False, 'notice': err}, status=400)
                        form.add_error(None, err)
                        context.update(reservation=reservation, gate_open=False)
                        return render(request, 'admin/virtual_gate.html', context)

                    if reservation.status != 'CHECKED_IN':
                        err = (
                            f"Cannot settle exit balance for reservation in status '{reservation.get_status_display()}'. "
                            f"Vehicle must be currently checked in (CHECKED_IN)."
                        )
                        if is_ajax:
                            return JsonResponse({'success': False, 'notice': err}, status=400)
                        form.add_error(None, err)
                        context.update(reservation=reservation, gate_open=False)
                        return render(request, 'admin/virtual_gate.html', context)

                    provider = (request.POST.get('payment_provider') or 'CASH').upper().strip()
                    if provider not in ('CASH', 'DEMO'):
                        err = f"Invalid payment method '{provider}'. Accepted methods are CASH or DEMO."
                        if is_ajax:
                            return JsonResponse({'success': False, 'notice': err}, status=400)
                        form.add_error(None, err)
                        context.update(reservation=reservation, gate_open=False)
                        return render(request, 'admin/virtual_gate.html', context)

                    if provider == 'DEMO' and not demo_enabled:
                        err = 'Demo payment simulation is disabled. Disabled demo payments cannot be processed.'
                        if is_ajax:
                            return JsonResponse({'success': False, 'notice': err}, status=400)
                        form.add_error(None, err)
                        context.update(reservation=reservation, gate_open=False)
                        return render(request, 'admin/virtual_gate.html', context)

                    bill = BillingService.calculate_bill(reservation, as_of=timezone.now())
                    amount_due = bill['balance_due']

                    if amount_due > 0:
                        if provider == 'DEMO':
                            outcome = (request.POST.get('outcome') or request.POST.get('demo_outcome') or 'success').lower().strip()
                            if outcome not in ('success', 'failure', 'cancel'):
                                err = f"Invalid simulation outcome '{outcome}'. Must be success, failure, or cancel."
                                if is_ajax:
                                    return JsonResponse({'success': False, 'notice': err}, status=400)
                                form.add_error(None, err)
                                context.update(reservation=reservation, bill=bill, gate_open=False)
                                _attach_exit_qr_if_needed(context, reservation, bill, demo_enabled)
                                return render(request, 'admin/virtual_gate.html', context)

                            if outcome == 'failure':
                                notice = 'Simulated ABA payment failed: Bank rejected simulation or insufficient funds. Balance remains unpaid.'
                                context['notice'] = notice
                                messages.error(request, notice)
                                allowed, _, bill, _ = GateService.prepare_exit(reservation.ticket_code, zone_id=zone.pk)
                                context.update(reservation=reservation, bill=bill, gate_open=False)
                                _attach_exit_qr_if_needed(context, reservation, bill, demo_enabled)
                                if is_ajax:
                                    return JsonResponse({'success': False, 'notice': notice, 'balance_due': bill['balance_due']}, status=400)
                                return render(request, 'admin/virtual_gate.html', context)

                            elif outcome == 'cancel':
                                notice = 'Simulated ABA payment was cancelled. Balance remains unpaid.'
                                context['notice'] = notice
                                messages.info(request, notice)
                                allowed, _, bill, _ = GateService.prepare_exit(reservation.ticket_code, zone_id=zone.pk)
                                context.update(reservation=reservation, bill=bill, gate_open=False)
                                _attach_exit_qr_if_needed(context, reservation, bill, demo_enabled)
                                if is_ajax:
                                    return JsonResponse({'success': False, 'notice': notice, 'balance_due': bill['balance_due']})
                                return render(request, 'admin/virtual_gate.html', context)

                            else:  # outcome == 'success'
                                ref = f"ABA-DEMO-{secrets.token_hex(4).upper()}"
                                PaymentService.record_exit_payment(reservation, amount=amount_due, provider='DEMO', provider_ref=ref)
                                notice = f"Simulated ABA payment of {amount_due:,} KHR verified. 5-minute departure window authorized."
                                messages.success(request, notice)
                                reservation.refresh_from_db()

                        else:  # provider == 'CASH'
                            attendant = request.user.username if request.user and request.user.is_authenticated else 'ATTENDANT'
                            ref = f"CASH-EXIT-{secrets.token_hex(4).upper()}"
                            PaymentService.record_exit_payment(reservation, amount=amount_due, provider='CASH', provider_ref=ref)
                            notice = f"Cash payment of {amount_due:,} KHR confirmed received by attendant {attendant}. 5-minute departure window authorized."
                            messages.success(request, notice)
                            reservation.refresh_from_db()
                    else:
                        notice = 'No outstanding balance due. Exit authorization is ready.'
                        context['notice'] = notice
                        messages.info(request, notice)

                    allowed, _, bill, prep_notice = GateService.prepare_exit(reservation.ticket_code, zone_id=zone.pk)
                    context.update(reservation=reservation, bill=bill, notice=context.get('notice') or prep_notice, gate_open=False)
                    _attach_exit_qr_if_needed(context, reservation, bill, demo_enabled)
                    if is_ajax:
                        return JsonResponse({
                            'success': True,
                            'settled': True,
                            'balance_due': bill['balance_due'],
                            'notice': context['notice'],
                            'ticket_code': reservation.ticket_code,
                            'status': reservation.status,
                            'payment_status': reservation.payment_status,
                        })
                    return render(request, 'admin/virtual_gate.html', context)

                # Action: Check ticket & open barrier
                if mode == 'entry':
                    allowed, _, notice = GateService.validate_entry(reservation.ticket_code, zone.pk)
                    bill = None
                else:
                    allowed, _, bill, notice = GateService.prepare_exit(reservation.ticket_code, zone_id=zone.pk)

                context.update(reservation=reservation, bill=bill, notice=notice)
                _attach_exit_qr_if_needed(context, reservation, bill, demo_enabled)


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
                        context.update(reservation=reservation, notice=notice, passed=success, gate_open=False, just_passed=success)
                        if success:
                            zone.refresh_from_db()
                            context['notice'] = 'Vehicle passage recorded. Barrier closed.'
                            messages.success(request, context['notice'])
                            if is_ajax:
                                return JsonResponse({
                                    'success': True,
                                    'passed': True,
                                    'gate_open': False,
                                    'mode': mode,
                                    'ticket_code': reservation.ticket_code,
                                    'plate_number': reservation.plate_number,
                                    'status': reservation.status,
                                    'status_display': reservation.get_status_display(),
                                    'notice': context['notice'],
                                    'occupied_slots': zone.occupied_slots,
                                    'checked_in_at': reservation.checked_in_at.isoformat() if reservation.checked_in_at else None,
                                    'checked_out_at': reservation.checked_out_at.isoformat() if reservation.checked_out_at else None,
                                })
                        else:
                            if is_ajax:
                                return JsonResponse({
                                    'success': False,
                                    'passed': False,
                                    'gate_open': False,
                                    'mode': mode,
                                    'notice': notice or 'Passage confirmation rejected by gate service.',
                                }, status=400)
                    else:
                        context['gate_open'] = False
                        if is_ajax:
                            return JsonResponse({
                                'success': False,
                                'passed': False,
                                'gate_open': False,
                                'mode': mode,
                                'notice': context['notice'],
                            }, status=400)

                elif action == 'open':
                    if allowed:
                        context['gate_open'] = True
                        context['permit'] = signing.dumps(
                            [request.user.pk, reservation.pk, zone.pk, mode], salt='virtual-gate'
                        )
                        context['permit_expires_at'] = int(time.time()) + 120
                        context['notice'] = 'Ticket verified. Barrier is OPEN — waiting for vehicle to pass.'
                    else:
                        context['gate_open'] = False

    return render(request, 'admin/virtual_gate.html', context)
