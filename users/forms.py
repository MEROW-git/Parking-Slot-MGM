from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm


class UserRegistrationForm(forms.ModelForm):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'sp-input',
            'placeholder': 'Choose username (e.g. sokha_pp)',
            'required': 'required',
            'autocomplete': 'username',
        }),
        label='Username (ឈ្មោះគណនី)'
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'sp-input',
            'placeholder': 'Optional email for receipt copies',
            'autocomplete': 'email',
        }),
        label='Email Address (ស្រេចចិត្ត / Optional)'
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'sp-input',
            'placeholder': 'Create secure password (min 6 characters)',
            'required': 'required',
            'autocomplete': 'new-password',
        }),
        label='Password (ពាក្យសម្ងាត់)'
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'sp-input',
            'placeholder': 'Re-enter password to confirm',
            'required': 'required',
            'autocomplete': 'new-password',
        }),
        label='Confirm Password (បញ្ជាក់ពាក្យសម្ងាត់)'
    )

    class Meta:
        model = User
        fields = ['username', 'email']

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('This username is already registered. Please choose another or log in.')
        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        if password and password_confirm and password != password_confirm:
            self.add_error('password_confirm', 'Passwords do not match. Please verify.')
        return cleaned_data


class SomParkLoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'sp-input',
            'placeholder': 'Enter your username',
            'required': 'required',
            'autocomplete': 'username',
            'autofocus': 'autofocus',
        }),
        label='Username (ឈ្មោះអ្នកប្រើ)'
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'sp-input',
            'placeholder': 'Enter your password',
            'required': 'required',
            'autocomplete': 'current-password',
        }),
        label='Password (ពាក្យសម្ងាត់)'
    )
