import secrets
import string
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils.text import slugify


def generate_ticket_code():
    chars = string.ascii_uppercase + string.digits
    suffix = ''.join(secrets.choice(chars) for _ in range(7))
    return f"SPK-{suffix}"


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
    ticket_code = models.CharField(max_length=20, default=generate_ticket_code, unique=True)
    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reservations')
    start_date = models.DateField()
    finish_date = models.DateField()
    parking_zone = models.ForeignKey(ParkingZone, on_delete=models.CASCADE, related_name='reservations')
    plate_number = models.CharField(max_length=40, help_text='Cambodian vehicle plate e.g. 2AZ-1234')
    phone_number = models.CharField(max_length=30, help_text='Contact phone e.g. +855 12 345 678')
    checked_out = models.BooleanField(default=False)
    created_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_on', '-id']
        verbose_name = 'Reservation'
        verbose_name_plural = 'Reservations'

    def __str__(self):
        return f"Ticket {self.ticket_code} - {self.customer.username} ({self.parking_zone.name})"
