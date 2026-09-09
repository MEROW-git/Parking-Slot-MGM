import secrets
import string
from datetime import time, datetime
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from django.utils import timezone


def generate_ticket_code():
    chars = string.ascii_uppercase + string.digits
    suffix = ''.join(secrets.choice(chars) for _ in range(7))
    return f"SPK-{suffix}"


def generate_access_token():
    return secrets.token_hex(32)


def generate_payment_ref():
    return f"TXN-{secrets.token_hex(8).upper()}"


class ParkingZone(models.Model):
    name = models.CharField(max_length=120)
    khmer_name = models.CharField(max_length=150, blank=True)
    slug = models.SlugField(max_length=150, unique=True, blank=True)
    num_of_slots = models.PositiveIntegerField(default=30)
    occupied_slots = models.PositiveIntegerField(default=0)
    vacant_slots = models.PositiveIntegerField(default=30)
    address = models.CharField(max_length=255)
    district = models.CharField(max_length=100, default='Phnom Penh')
    price = models.PositiveIntegerField(default=3000, help_text='Price in KHR (Riel) per session/day')
    description = models.TextField(blank=True)
    operating_hours = models.CharField(max_length=100, default='06:00 - 22:00')

    class Meta:
        ordering = ['name']
        verbose_name = 'Parking Zone'
        verbose_name_plural = 'Parking Zones'

    def __str__(self):
        return f"{self.name} ({self.vacant_slots} spots left)"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        # Ensure occupied_slots stays within [0, num_of_slots]
        if self.occupied_slots < 0:
            self.occupied_slots = 0
        elif self.occupied_slots > self.num_of_slots:
            self.occupied_slots = self.num_of_slots
        self.vacant_slots = max(0, self.num_of_slots - self.occupied_slots)
        super().save(*args, **kwargs)

    @property
    def price_khr_formatted(self):
        return f"{self.price:,} ៛"

    @property
    def is_full(self):
        return self.vacant_slots <= 0

    @property
    def is_nearly_full(self):
        return not self.is_full and (self.vacant_slots <= max(3, int(self.num_of_slots * 0.15)))

    @property
    def availability_status(self):
        if self.is_full:
            return 'full'
        if self.is_nearly_full:
            return 'limited'
        return 'available'

    @property
    def occupancy_percentage(self):
        if not self.num_of_slots:
            return 0
        return int((self.occupied_slots / self.num_of_slots) * 100)

    @property
    def physically_occupied_count(self):
        """Count of vehicles physically checked-in, plus any un-reconciled legacy occupancy."""
        db_parked = self.reservations.filter(status='CHECKED_IN').count()
        return max(self.occupied_slots, db_parked)

    @property
    def active_holds_count(self):
        """Count of active arrival holds and pending deposits holding capacity."""
        now = timezone.now()
        unpaid_holds = self.reservations.filter(
            payment_method='PAY_AT_EXIT',
            status='CONFIRMED',
            arrival_deadline__gt=now
        ).count()
        pending_deposits = self.reservations.filter(
            status='PAYMENT_PENDING',
            payment_deadline__gt=now
        ).count()
        return unpaid_holds + pending_deposits

    @property
    def available_capacity_now(self):
        """Spaces available right now considering physical occupancy and active holds."""
        used = self.occupied_slots + self.active_holds_count
        return max(0, self.num_of_slots - used)

    def decrement_slot(self):
        if self.vacant_slots <= 0 or self.occupied_slots >= self.num_of_slots:
            raise ValidationError('Parking zone is full.')
        self.occupied_slots += 1
        self.save()

    def increment_slot(self):
        if self.occupied_slots <= 0:
            raise ValidationError('No occupied slots to release.')
        self.occupied_slots -= 1
        self.save()


class Reservation(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('DEPOSIT', 'Pay first day now (កក់ប្រាក់ថ្ងៃដំបូង)'),
        ('PAY_AT_EXIT', 'Pay at exit (ទូទាត់ពេលចេញ)'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('UNPAID', 'Unpaid (មិនទាន់ទូទាត់)'),
        ('PARTIALLY_PAID', 'Partially Paid / Deposit (បានកក់ប្រាក់)'),
        ('PAID', 'Fully Paid (បានទូទាត់រួច)'),
    ]

    RESERVATION_STATUS_CHOICES = [
        ('PAYMENT_PENDING', 'Payment Pending (រង់ចាំការបង់ប្រាក់)'),
        ('CONFIRMED', 'Confirmed Hold (បានបញ្ជាក់ការកក់)'),
        ('CHECKED_IN', 'Checked In (បានចូលចំណត)'),
        ('CHECKED_OUT', 'Checked Out (បានចេញពីចំណត)'),
        ('EXPIRED', 'Expired (ផុតកំណត់)'),
        ('CANCELLED', 'Cancelled (បានបោះបង់)'),
    ]

    ticket_code = models.CharField(max_length=20, default=generate_ticket_code, unique=True)
    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reservations')
    parking_zone = models.ForeignKey(ParkingZone, on_delete=models.CASCADE, related_name='reservations')
    plate_number = models.CharField(max_length=40, help_text='Cambodian vehicle plate e.g. 2AZ-1234')
    phone_number = models.CharField(max_length=30, help_text='Contact phone e.g. +855 12 345 678')

    # Date fields (legacy and query compatibility)
    start_date = models.DateField()
    finish_date = models.DateField()

    # Timezone-aware explicit start/end timestamps
    start_time = models.DateTimeField(null=True, blank=True, help_text='Booked arrival window start')
    finish_time = models.DateTimeField(null=True, blank=True, help_text='Booked exit deadline')

    # Immutable price snapshot at reservation creation
    daily_rate = models.PositiveIntegerField(default=3000, help_text='Snapshotted rate in KHR per day')
    overstay_multiplier = models.DecimalField(max_digits=3, decimal_places=1, default=2.0, help_text='Overstay multiplier, default 2x')

    # Workflow & payment state
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='DEPOSIT')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='UNPAID')
    status = models.CharField(max_length=20, choices=RESERVATION_STATUS_CHOICES, default='CONFIRMED')

    # Financial tracking (all in integer KHR)
    deposit_amount = models.PositiveIntegerField(default=0, help_text='Deposit paid in KHR')
    total_amount = models.PositiveIntegerField(default=0, help_text='Final total billed in KHR')
    balance_paid = models.PositiveIntegerField(default=0, help_text='Exit balance paid in KHR')

    # Deadlines and actual gate execution timestamps
    payment_deadline = models.DateTimeField(null=True, blank=True, help_text='Checkout timeout for deposit payment')
    arrival_deadline = models.DateTimeField(null=True, blank=True, help_text='Arrival deadline for unpaid same-day holds (3 hours)')
    checked_in_at = models.DateTimeField(null=True, blank=True, help_text='Actual gate entry timestamp')
    checked_out_at = models.DateTimeField(null=True, blank=True, help_text='Actual gate exit timestamp')
    exit_authorized_until = models.DateTimeField(null=True, blank=True, help_text='5-minute gate departure authorization window')

    # Cryptographic access token for scannable QR (opaque, unguessable)
    access_token = models.CharField(max_length=64, unique=True, null=True, blank=True, help_text='Opaque token for scannable access QR')

    # Legacy & reconciliation support
    checked_out = models.BooleanField(default=False)
    is_legacy = models.BooleanField(default=False, help_text='Flagged for staff reconciliation from pre-workflow system')
    staff_notes = models.TextField(blank=True)

    created_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_on', '-id']
        verbose_name = 'Reservation'
        verbose_name_plural = 'Reservations'

    def __str__(self):
        return f"Ticket {self.ticket_code} - {self.customer.username} ({self.parking_zone.name}) [{self.status}]"

    def save(self, *args, **kwargs):
        # Synchronize checked_out boolean with lifecycle status bidirectionally
        if self.checked_out and self.status != 'CHECKED_OUT':
            self.status = 'CHECKED_OUT'
        elif not self.checked_out and self.status == 'CHECKED_OUT':
            self.status = 'CONFIRMED'
        elif self.status == 'CHECKED_OUT':
            self.checked_out = True
        elif self.status in ('CONFIRMED', 'CHECKED_IN', 'PAYMENT_PENDING'):
            self.checked_out = False

        # Ensure daily rate is snapshotted from parking zone if not set
        if not self.daily_rate and self.parking_zone_id:
            self.daily_rate = self.parking_zone.price

        # Populate start_time and finish_time from dates if unset
        if not self.start_time and self.start_date:
            tz = timezone.get_current_timezone()
            self.start_time = timezone.make_aware(datetime.combine(self.start_date, time(6, 0)), tz)
        if not self.finish_time and self.finish_date:
            tz = timezone.get_current_timezone()
            self.finish_time = timezone.make_aware(datetime.combine(self.finish_date, time(22, 0)), tz)

        # Generate access token if not present
        if not self.access_token:
            self.access_token = generate_access_token()

        super().save(*args, **kwargs)

    @property
    def effective_start_time(self):
        if self.start_time:
            return self.start_time
        tz = timezone.get_current_timezone()
        return timezone.make_aware(datetime.combine(self.start_date, time(6, 0)), tz)

    @property
    def effective_finish_time(self):
        if self.finish_time:
            return self.finish_time
        tz = timezone.get_current_timezone()
        return timezone.make_aware(datetime.combine(self.finish_date, time(22, 0)), tz)

    @property
    def is_overstay(self):
        if self.status == 'CHECKED_IN' and self.effective_finish_time:
            return timezone.now() > self.effective_finish_time
        return False

    @property
    def is_active_session(self):
        return self.status in ('CONFIRMED', 'CHECKED_IN') and not self.checked_out

    @property
    def daily_rate_formatted(self):
        return f"{self.daily_rate:,} ៛"

    @property
    def deposit_formatted(self):
        return f"{self.deposit_amount:,} ៛"

    @property
    def total_formatted(self):
        return f"{self.total_amount:,} ៛"


class PaymentTransaction(models.Model):
    PURPOSE_CHOICES = [
        ('DEPOSIT', 'First Day Deposit'),
        ('EXIT_BALANCE', 'Exit Balance Payment'),
        ('REFUND', 'Refund'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]

    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name='transactions')
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    amount = models.PositiveIntegerField(help_text='Amount in KHR')
    currency = models.CharField(max_length=5, default='KHR')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    provider = models.CharField(max_length=30, default='DEMO')
    provider_ref = models.CharField(max_length=100, unique=True, blank=True)
    is_demo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Payment Transaction'
        verbose_name_plural = 'Payment Transactions'

    def __str__(self):
        return f"{self.provider_ref} - {self.purpose} ({self.amount:,} KHR) [{self.status}]"

    def save(self, *args, **kwargs):
        if not self.provider_ref:
            self.provider_ref = generate_payment_ref()
        super().save(*args, **kwargs)
