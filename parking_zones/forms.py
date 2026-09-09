import re
from datetime import time, datetime, timedelta
from django import forms
from django.conf import settings
from django.utils import timezone
from .models import ParkingZone, Reservation
from .services import CapacityService

# Centralized constant of Phnom Penh Capital and all 24 Cambodian Provinces
CAMBODIA_PROVINCES = (
    ('Phnom Penh', 'Phnom Penh / ភ្នំពេញ'),
    ('Banteay Meanchey', 'Banteay Meanchey / បន្ទាយមានជ័យ'),
    ('Battambang', 'Battambang / បាត់ដំបង'),
    ('Kampong Cham', 'Kampong Cham / កំពង់ចាម'),
    ('Kampong Chhnang', 'Kampong Chhnang / កំពង់ឆ្នាំង'),
    ('Kampong Speu', 'Kampong Speu / កំពង់ស្ពឺ'),
    ('Kampong Thom', 'Kampong Thom / កំពង់ធំ'),
    ('Kampot', 'Kampot / កំពត'),
    ('Kandal', 'Kandal / កណ្តាល'),
    ('Kep', 'Kep / កែប'),
    ('Koh Kong', 'Koh Kong / កោះកុង'),
    ('Kratie', 'Kratie / ក្រចេះ'),
    ('Mondulkiri', 'Mondulkiri / មណ្ឌលគិរី'),
    ('Oddar Meanchey', 'Oddar Meanchey / ឧត្តរមានជ័យ'),
    ('Pailin', 'Pailin / ប៉ៃលិន'),
    ('Preah Sihanouk', 'Preah Sihanouk / ព្រះសីហនុ'),
    ('Preah Vihear', 'Preah Vihear / ព្រះវិហារ'),
    ('Prey Veng', 'Prey Veng / ព្រៃវែង'),
    ('Pursat', 'Pursat / ពោធិ៍សាត់'),
    ('Ratanakiri', 'Ratanakiri / រតនគិរី'),
    ('Siem Reap', 'Siem Reap / សៀមរាប'),
    ('Stung Treng', 'Stung Treng / ស្ទឹងត្រែង'),
    ('Svay Rieng', 'Svay Rieng / ស្វាយរៀង'),
    ('Takeo', 'Takeo / តាកែវ'),
    ('Tboung Khmum', 'Tboung Khmum / ត្បូងឃ្មុំ'),
)


class ReservationForm(forms.ModelForm):
    parking_zone = forms.ModelChoiceField(
        queryset=ParkingZone.objects.all(),
        empty_label='-- ជ្រើសរើសចំណត / Select Parking Zone --',
        widget=forms.Select(attrs={
            'class': 'sp-input sp-select',
            'id': 'id_parking_zone',
            'required': 'required',
        }),
        label='Parking Zone (ទីតាំងចំណត)'
    )

    start_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'sp-input',
            'id': 'id_start_date',
            'required': 'required',
        }),
        label='Start Date (កាលបរិច្ឆេទចាប់ផ្តើម)'
    )

    start_time = forms.TimeField(
        initial='07:00',
        required=False,
        widget=forms.TimeInput(attrs={
            'type': 'time',
            'class': 'sp-input',
            'id': 'id_start_time',
        }),
        label='Arrival Time (ម៉ោងមកដល់)'
    )

    finish_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'sp-input',
            'id': 'id_finish_date',
            'required': 'required',
        }),
        label='Finish Date (កាលបរិច្ឆេទបញ្ចប់)'
    )

    finish_time = forms.TimeField(
        initial='22:00',
        required=False,
        widget=forms.TimeInput(attrs={
            'type': 'time',
            'class': 'sp-input',
            'id': 'id_finish_time',
        }),
        label='Exit Time (ម៉ោងចេញ)'
    )

    payment_method = forms.ChoiceField(
        choices=Reservation.PAYMENT_METHOD_CHOICES,
        initial='DEPOSIT',
        required=False,
        widget=forms.RadioSelect(attrs={
            'class': 'sp-payment-radio',
        }),
        label='Payment Choice (ជម្រើសទូទាត់)',
        help_text='Deposit pays 1st day now and counts toward bill. Pay at exit is available for same-day booking with 3-hour arrival hold.'
    )

    plate_province = forms.ChoiceField(
        choices=CAMBODIA_PROVINCES,
        initial='Phnom Penh',
        required=False,
        widget=forms.Select(attrs={
            'class': 'sp-input sp-select',
            'id': 'id_plate_province',
            'aria-label': 'City or Province (រាជធានី ឬខេត្ត)',
            'aria-describedby': 'plate-preview-box',
        }),
        label='City / Province (រាជធានី / ខេត្ត)'
    )

    plate_code = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'sp-input font-mono uppercase',
            'id': 'id_plate_code',
            'placeholder': 'e.g. 2AZ-1234',
            'autocapitalize': 'characters',
            'spellcheck': 'false',
            'autocomplete': 'off',
            'aria-label': 'Plate Number (លេខផ្លាក)',
            'aria-describedby': 'plate-preview-box',
        }),
        label='Plate Number (លេខផ្លាក)'
    )

    plate_number = forms.CharField(
        max_length=40,
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'id_plate_number'}),
        label='Vehicle Plate Number (ស្លាកលេខយានយន្ត)'
    )

    phone_number = forms.CharField(
        max_length=25,
        widget=forms.TextInput(attrs={
            'class': 'sp-input',
            'id': 'id_phone_number',
            'placeholder': 'e.g. +855 12 345 678 or 012 345 678',
            'required': 'required',
            'autocomplete': 'tel',
        }),
        label='Phone Number (លេខទូរស័ព្ទ)',
        help_text='Cambodian format: +855 XX XXX XXX or local 0XX XXX XXX'
    )

    class Meta:
        model = Reservation
        fields = ['parking_zone', 'start_date', 'finish_date', 'plate_number', 'phone_number', 'payment_method']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['plate_province'].initial = 'Phnom Penh'
        self.fields['plate_number'].required = False
        self.fields['payment_method'].initial = 'DEPOSIT'

        # If editing an existing reservation instance, extract province and code
        if self.instance and self.instance.pk and self.instance.plate_number:
            plate = self.instance.plate_number.strip()
            matched = False
            for prov_val, _ in CAMBODIA_PROVINCES:
                if plate.startswith(prov_val + ' '):
                    self.fields['plate_province'].initial = prov_val
                    self.fields['plate_code'].initial = plate[len(prov_val) + 1:].strip()
                    matched = True
                    break
            if not matched:
                self.fields['plate_code'].initial = plate

        if self.instance and self.instance.pk and self.instance.start_time:
            self.fields['start_time'].initial = self.instance.start_time.strftime('%H:%M')
        if self.instance and self.instance.pk and self.instance.finish_time:
            self.fields['finish_time'].initial = self.instance.finish_time.strftime('%H:%M')

    def clean_phone_number(self):
        raw_phone = self.cleaned_data.get('phone_number', '').strip()
        if not raw_phone:
            raise forms.ValidationError('Please enter your contact phone number.')

        digits_only = re.sub(r'[\s\-\(\)]', '', raw_phone)
        valid_cam = re.match(r'^(\+855|855|0)[1-9]\d{7,8}$', digits_only)
        if not valid_cam:
            raise forms.ValidationError(
                'Invalid Cambodian phone number. Use +855 XX XXX XXX or 0XX XXX XXX.'
            )
        return raw_phone

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        finish_date = cleaned_data.get('finish_date')
        raw_start_time = cleaned_data.get('start_time') or time(7, 0)
        raw_finish_time = cleaned_data.get('finish_time') or time(22, 0)
        payment_method = cleaned_data.get('payment_method') or 'DEPOSIT'
        zone = cleaned_data.get('parking_zone')

        today = timezone.localdate()
        tz = timezone.get_current_timezone()

        if start_date and start_date < today:
            self.add_error('start_date', 'Start date cannot be in the past.')

        if start_date and finish_date and finish_date < start_date:
            self.add_error('finish_date', 'Finish date must be on or after start date.')

        # Construct timezone-aware start and finish datetimes
        start_dt = None
        finish_dt = None
        if start_date and finish_date:
            start_dt = timezone.make_aware(datetime.combine(start_date, raw_start_time), tz)
            finish_dt = timezone.make_aware(datetime.combine(finish_date, raw_finish_time), tz)

            if finish_dt <= start_dt:
                self.add_error('finish_time', 'Finish time must be after start time.')

            cleaned_data['start_datetime'] = start_dt
            cleaned_data['finish_datetime'] = finish_dt

        # Business Rule: Pay at exit is only available for same-day immediate arrival
        if payment_method == 'PAY_AT_EXIT':
            if start_date and start_date > today:
                self.add_error(
                    'payment_method',
                    'Pay at exit (3-hour hold) is only available for immediate same-day arrival. '
                    'For future dates, please select "Pay first day now" to secure your guaranteed spot.'
                )

        if zone and zone.vacant_slots <= 0:
            self.add_error('parking_zone', f'Zone "{zone.name}" is currently at full capacity.')

        # Vehicle Plate Validation & Normalization
        raw_province = self.data.get('plate_province', '').strip() if self.data else ''
        raw_code = self.data.get('plate_code', '').strip() if self.data else ''
        raw_plate = self.data.get('plate_number', '').strip() if self.data else ''

        valid_provinces = [p[0] for p in CAMBODIA_PROVINCES]

        if 'plate_code' in self.data or 'plate_province' in self.data:
            has_plate_error = False

            if not raw_province:
                self.add_error('plate_province', 'Please select a city or province (សូមជ្រើសរើសរាជធានី ឬខេត្ត).')
                has_plate_error = True
            elif raw_province not in valid_provinces:
                self.add_error('plate_province', 'Invalid city or province selected.')
                has_plate_error = True

            if not raw_code:
                self.add_error('plate_code', 'Please enter a vehicle plate number (សូមបញ្ចូលលេខផ្លាកលេខ).')
                has_plate_error = True
            else:
                cleaned_code = re.sub(r'\s+', ' ', raw_code).upper()

                if not re.match(r'^[A-Z0-9\s\.\-]{2,15}$', cleaned_code):
                    self.add_error(
                        'plate_code',
                        'Invalid plate format. Allowed characters: Latin letters, numbers, spaces, periods, and hyphens.'
                    )
                    has_plate_error = True
                elif not re.search(r'\d', cleaned_code):
                    self.add_error(
                        'plate_code',
                        'Plate number must include at least one digit (ត្រូវមានលេខយ៉ាងតិចមួយខ្ទង់).'
                    )
                    has_plate_error = True

            if not has_plate_error:
                combined_plate = f"{raw_province} {cleaned_code}"
                cleaned_data['plate_province'] = raw_province
                cleaned_data['plate_code'] = cleaned_code
                cleaned_data['plate_number'] = combined_plate
                self.instance.plate_number = combined_plate

        elif raw_plate:
            cleaned = re.sub(r'\s+', ' ', raw_plate).upper()
            plate_regex = r'^[A-Z0-9\s\.\-]{3,40}$'
            if not re.match(plate_regex, cleaned) or not re.search(r'\d', cleaned):
                self.add_error('plate_number', 'Invalid plate format. Example: 2AZ-1234 or Phnom Penh 2BC-9999.')
            else:
                cleaned_data['plate_number'] = cleaned
                self.instance.plate_number = cleaned
        else:
            self.add_error('plate_code', 'Please enter a vehicle plate number (សូមបញ្ចូលលេខផ្លាកលេខ).')

        # Accessibility attributes update
        if 'plate_province' in self.errors:
            self.fields['plate_province'].widget.attrs['aria-invalid'] = 'true'
            self.fields['plate_province'].widget.attrs['aria-describedby'] = 'error_plate_province plate-preview-box'
            p_class = self.fields['plate_province'].widget.attrs.get('class', '')
            if 'is-invalid' not in p_class:
                self.fields['plate_province'].widget.attrs['class'] = f'{p_class} is-invalid'.strip()
        else:
            self.fields['plate_province'].widget.attrs.pop('aria-invalid', None)
            self.fields['plate_province'].widget.attrs['aria-describedby'] = 'plate-preview-box'

        if 'plate_code' in self.errors:
            self.fields['plate_code'].widget.attrs['aria-invalid'] = 'true'
            self.fields['plate_code'].widget.attrs['aria-describedby'] = 'error_plate_code plate-preview-box'
            c_class = self.fields['plate_code'].widget.attrs.get('class', '')
            if 'is-invalid' not in c_class:
                self.fields['plate_code'].widget.attrs['class'] = f'{c_class} is-invalid'.strip()
        else:
            self.fields['plate_code'].widget.attrs.pop('aria-invalid', None)
            self.fields['plate_code'].widget.attrs['aria-describedby'] = 'plate-preview-box'

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        if 'plate_number' in self.cleaned_data and self.cleaned_data['plate_number']:
            instance.plate_number = self.cleaned_data['plate_number']

        if 'start_datetime' in self.cleaned_data:
            instance.start_time = self.cleaned_data['start_datetime']
        if 'finish_datetime' in self.cleaned_data:
            instance.finish_time = self.cleaned_data['finish_datetime']

        # Price snapshot
        if instance.parking_zone_id:
            instance.daily_rate = instance.parking_zone.price
        instance.overstay_multiplier = getattr(settings, 'DEFAULT_OVERSTAY_MULTIPLIER', 2.0)

        # Payment & status initialization
        payment_method = self.cleaned_data.get('payment_method') or 'DEPOSIT'
        instance.payment_method = payment_method
        now = timezone.now()

        if payment_method == 'PAY_AT_EXIT':
            instance.status = 'CONFIRMED'
            instance.payment_status = 'UNPAID'
            hold_hours = getattr(settings, 'ARRIVAL_HOLD_HOURS', 3)
            instance.arrival_deadline = now + timedelta(hours=hold_hours)
            instance.payment_deadline = None
        else:
            instance.status = 'PAYMENT_PENDING'
            instance.payment_status = 'UNPAID'
            timeout_mins = getattr(settings, 'PAYMENT_TIMEOUT_MINUTES', 15)
            instance.payment_deadline = now + timedelta(minutes=timeout_mins)
            instance.arrival_deadline = None

        if commit:
            instance.save()
        return instance
