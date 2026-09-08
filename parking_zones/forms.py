import re
from django import forms
from django.utils import timezone
from .models import ParkingZone, Reservation


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

    finish_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'sp-input',
            'id': 'id_finish_date',
            'required': 'required',
        }),
        label='Finish Date (កាលបរិច្ឆេទបញ្ចប់)'
    )

    plate_number = forms.CharField(
        max_length=35,
        widget=forms.TextInput(attrs={
            'class': 'sp-input font-mono uppercase',
            'id': 'id_plate_number',
            'placeholder': 'e.g. 2AZ-1234 or Phnom Penh 2BC-5678',
            'required': 'required',
            'autocomplete': 'off',
        }),
        label='Vehicle Plate Number (ស្លាកលេខយានយន្ត)',
        help_text='Accepts standard Cambodian vehicle plates (e.g. 2AZ-1234, Phnom Penh 2B-5678)'
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
        fields = ['parking_zone', 'start_date', 'finish_date', 'plate_number', 'phone_number']

    def clean_plate_number(self):
        raw_plate = self.cleaned_data.get('plate_number', '').strip()
        if not raw_plate:
            raise forms.ValidationError('Please enter a vehicle license plate number.')

        # Sanitize plate
        cleaned = re.sub(r'\s+', ' ', raw_plate).upper()
        # Cambodian plates: typically province (optional) + 1-2 digits + 1-2 letters + dash + 4 digits
        # e.g. 2AZ-1234, 1A-2345, Phnom Penh 2BC-1234, 3C-9999
        plate_regex = r'^[A-Z0-9\s\.\-]{3,30}$'
        if not re.match(plate_regex, cleaned) or not re.search(r'\d', cleaned):
            raise forms.ValidationError(
                'Invalid plate format. Example: 2AZ-1234, 1A-5678, or Phnom Penh 2BC-9999.'
            )
        return cleaned

    def clean_phone_number(self):
        raw_phone = self.cleaned_data.get('phone_number', '').strip()
        if not raw_phone:
            raise forms.ValidationError('Please enter your contact phone number.')

        # Strip spaces and dashes
        digits_only = re.sub(r'[\s\-\(\)]', '', raw_phone)
        # Check Cambodian phone: +855 followed by 8-9 digits, or 0 followed by 8-9 digits
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
        zone = cleaned_data.get('parking_zone')

        today = timezone.localdate()

        if start_date and start_date < today:
            self.add_error('start_date', 'Start date cannot be in the past.')

        if start_date and finish_date and finish_date < start_date:
            self.add_error('finish_date', 'Finish date must be on or after start date.')

        if zone and zone.vacant_slots <= 0:
            self.add_error('parking_zone', f'Zone "{zone.name}" is currently at full capacity.')

        return cleaned_data
