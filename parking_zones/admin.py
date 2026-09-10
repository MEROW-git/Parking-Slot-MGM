from django.contrib import admin
from django.db.models import Q
from .models import ParkingZone, Reservation, PaymentTransaction
from .crypto import compute_plate_hmac


class PaymentTransactionInline(admin.TabularInline):
    model = PaymentTransaction
    extra = 0
    readonly_fields = ('purpose', 'amount', 'currency', 'status', 'provider', 'provider_ref', 'is_demo', 'created_at', 'completed_at')
    can_delete = False


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
    list_display = (
        'ticket_code', 'customer', 'parking_zone', 'plate_number',
        'status', 'payment_method', 'payment_status',
        'start_time', 'finish_time', 'overstay_status', 'created_on'
    )
    list_filter = ('status', 'payment_method', 'payment_status', 'is_legacy', 'parking_zone')
    search_fields = ('ticket_code', 'customer__username', 'plate_number', 'phone_number', 'access_token')
    readonly_fields = ('ticket_code', 'access_token', 'created_on', 'checked_in_at', 'checked_out_at', 'exit_authorized_until')
    inlines = [PaymentTransactionInline]

    @admin.display(description='Overstay?', boolean=True)
    def overstay_status(self, obj):
        return obj.is_overstay

    def get_search_results(self, request, queryset, search_term):
        """Enhances admin search to match encrypted vehicle plates via keyed HMAC lookup."""
        queryset, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        term = (search_term or '').strip()
        if term:
            candidate_hmacs = []
            candidate_terms = [term]
            lower_term = term.lower()
            if not any(lower_term.startswith(p) for p in ('phnom penh', 'kandal', 'siem reap', 'battambang', 'cambodia')):
                candidate_terms.append(f"Phnom Penh {term}")

            for t in candidate_terms:
                try:
                    h = compute_plate_hmac(t)
                    if h and h not in candidate_hmacs:
                        candidate_hmacs.append(h)
                except Exception:
                    pass

            if candidate_hmacs:
                hmac_matches = self.model.objects.filter(plate_lookup_hmac__in=candidate_hmacs)
                queryset = (queryset | hmac_matches).distinct()
        return queryset, may_have_duplicates


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ('provider_ref', 'reservation', 'purpose', 'amount_display', 'status', 'provider', 'is_demo', 'created_at')
    list_filter = ('purpose', 'status', 'provider', 'is_demo')
    search_fields = ('provider_ref', 'reservation__ticket_code', 'reservation__plate_number')
    readonly_fields = ('reservation', 'purpose', 'amount', 'currency', 'status', 'provider', 'provider_ref', 'is_demo', 'created_at', 'updated_at', 'completed_at', 'raw_response')

    @admin.display(description='Amount (KHR)')
    def amount_display(self, obj):
        return f"{obj.amount:,} {obj.currency}"

    def get_search_results(self, request, queryset, search_term):
        """Enhances transaction search to match encrypted vehicle plates via reservation HMAC."""
        queryset, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        term = (search_term or '').strip()
        if term:
            candidate_hmacs = []
            candidate_terms = [term]
            lower_term = term.lower()
            if not any(lower_term.startswith(p) for p in ('phnom penh', 'kandal', 'siem reap', 'battambang', 'cambodia')):
                candidate_terms.append(f"Phnom Penh {term}")

            for t in candidate_terms:
                try:
                    h = compute_plate_hmac(t)
                    if h and h not in candidate_hmacs:
                        candidate_hmacs.append(h)
                except Exception:
                    pass

            if candidate_hmacs:
                hmac_matches = self.model.objects.filter(reservation__plate_lookup_hmac__in=candidate_hmacs)
                queryset = (queryset | hmac_matches).distinct()
        return queryset, may_have_duplicates

