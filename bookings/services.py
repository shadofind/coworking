from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    Booking,
    BookingService,
    DayPass,
    MonthlySubscription,
    OccupiedSlot,
    Payment,
    Tariff,
)


def quote_booking(place, start_at, end_at, services=()):
    hours = int((end_at - start_at).total_seconds() // 3600)
    plan = Tariff.Plan.DAILY if place.kind == "workspace" and hours >= 8 else Tariff.Plan.HOURLY
    tariff = Tariff.objects.filter(
        place_kind=place.kind, plan=plan, is_active=True
    ).first()
    if tariff is None and plan == Tariff.Plan.DAILY:
        tariff = Tariff.objects.filter(
            place_kind=place.kind, plan=Tariff.Plan.HOURLY, is_active=True
        ).first()
        amount = (tariff.price if tariff else Decimal("250")) * hours
    elif tariff is None:
        amount = Decimal("600" if place.kind == "meeting" else "250") * hours
    else:
        amount = tariff.price if plan == Tariff.Plan.DAILY else tariff.price * hours
    amount += sum((service.price for service in services), Decimal("0"))
    return amount


def create_booking(*, resident, place, day, start_hour, end_hour, services=()):
    if end_hour <= start_hour:
        raise ValidationError("Время окончания должно быть позже начала.")
    if start_hour < 8 or end_hour > 22:
        raise ValidationError("Коворкинг открыт с 08:00 до 22:00.")
    start_at = timezone.make_aware(datetime.combine(day, time(start_hour)))
    end_at = timezone.make_aware(datetime.combine(day, time(end_hour)))
    if start_at <= timezone.now():
        raise ValidationError("Нельзя забронировать прошедшее время.")
    slots = [
        OccupiedSlot(place=place, day=day, hour=hour)
        for hour in range(start_hour, end_hour)
    ]
    total = quote_booking(place, start_at, end_at, services)
    try:
        with transaction.atomic():
            booking = Booking.objects.create(
                resident=resident, place=place, start_at=start_at, end_at=end_at, total=total
            )
            for service in services:
                BookingService.objects.create(booking=booking, service=service, price=service.price)
            for slot in slots:
                slot.booking = booking
            OccupiedSlot.objects.bulk_create(slots)
    except IntegrityError as error:
        raise ValidationError("Один или несколько выбранных часов уже заняты. Обновите сетку.") from error
    return booking


def pay_booking(booking):
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.status != Booking.Status.UNPAID:
            raise ValidationError("Эта бронь уже оплачена или отменена.")
        payment = Payment.objects.create(booking=booking, amount=booking.total)
        booking.status = Booking.Status.PAID
        booking.save(update_fields=["status"])
        day_pass, _ = DayPass.objects.get_or_create(
            booking=booking, defaults={"valid_on": timezone.localtime(booking.start_at).date()}
        )
    return payment, day_pass


def extend_booking(booking):
    next_hour = timezone.localtime(booking.end_at).hour
    if next_hour >= 22:
        raise ValidationError("Нельзя продлить бронь за пределы времени работы коворкинга.")
    day = timezone.localtime(booking.end_at).date()
    try:
        with transaction.atomic():
            OccupiedSlot.objects.create(
                booking=booking, place=booking.place, day=day, hour=next_hour
            )
            end_at = booking.end_at + timedelta(hours=1)
            new_total = quote_booking(booking.place, booking.start_at, end_at, booking.services.all())
            increment = max(Decimal("0"), new_total - booking.total)
            booking.end_at = end_at
            booking.total = new_total
            booking.save(update_fields=["end_at", "total"])
            Payment.objects.create(booking=booking, amount=increment)
    except IntegrityError as error:
        raise ValidationError("Следующий час уже занят.") from error
    return booking


def create_monthly_subscription(*, resident, place, starts_on):
    if place.kind != "workspace":
        raise ValidationError("Месячный абонемент доступен только для рабочего места.")
    tariff = Tariff.objects.filter(
        place_kind=place.kind, plan=Tariff.Plan.MONTHLY, is_active=True
    ).first()
    price = tariff.price if tariff else Decimal("12000")
    next_month = (starts_on.replace(day=28) + timedelta(days=4)).replace(day=1)
    ends_on = next_month - timedelta(days=1)
    with transaction.atomic():
        subscription = MonthlySubscription.objects.create(
            resident=resident, place=place, starts_on=starts_on, ends_on=ends_on, price=price
        )
        Payment.objects.create(
            booking=Booking.objects.create(
                resident=resident,
                place=place,
                start_at=timezone.make_aware(datetime.combine(starts_on, time(8))),
                end_at=timezone.make_aware(datetime.combine(ends_on, time(22))),
                status=Booking.Status.PAID,
                total=price,
            ),
            amount=price,
        )
    return subscription
