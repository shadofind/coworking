from django.contrib import admin

from .models import (
    Booking,
    BookingService,
    DayPass,
    ExtraService,
    MonthlySubscription,
    OccupiedSlot,
    Payment,
    Place,
    Profile,
    Tariff,
)


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "zone", "capacity", "is_active")
    list_filter = ("kind", "zone", "is_active")
    search_fields = ("name",)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("id", "resident", "place", "start_at", "end_at", "status", "total")
    list_filter = ("status", "place__kind", "place")
    search_fields = ("resident__username", "resident__first_name", "place__name")
    date_hierarchy = "start_at"


admin.site.register(
    (Profile, Tariff, ExtraService, BookingService, OccupiedSlot, Payment, DayPass, MonthlySubscription)
)
