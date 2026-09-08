from django.contrib import admin
from .models import ParkingZone, Reservation


@admin.register(ParkingZone)
class ParkingZoneAdmin(admin.ModelAdmin):
    list_display = ('name', 'khmer_name', 'district', 'num_of_slots', 'occupied_slots', 'vacant_slots', 'price_display')
    search_fields = ('name', 'khmer_name', 'address', 'district')
    prepopulated_fields = {'slug': ('name',)}
    list_filter = ('district',)

    @admin.display(description='Price (KHR)')
    def price_display(self, obj):
        return obj.price_khr_formatted


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('ticket_code', 'customer', 'parking_zone', 'start_date', 'finish_date', 'plate_number', 'checked_out', 'created_on')
    list_filter = ('checked_out', 'parking_zone', 'start_date')
    search_fields = ('ticket_code', 'customer__username', 'plate_number', 'phone_number')
    readonly_fields = ('ticket_code', 'created_on')
