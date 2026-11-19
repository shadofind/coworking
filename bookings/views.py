import csv
import json
from datetime import date, datetime, time
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db.models import Avg, Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.core.paginator import Paginator

from .forms import BookingForm, PlaceForm, ProfileForm, RegistrationForm
from .models import Booking, DayPass, ExtraService, OccupiedSlot, Payment, Place, Tariff
from .services import create_booking, extend_booking, pay_booking

User = get_user_model()


def home(request):
    places = Place.objects.filter(is_active=True)
    return render(request, "bookings/home.html", {"places": places[:8]})


def tariffs(request):
    return render(request, "bookings/tariffs.html", {"tariffs": Tariff.objects.filter(is_active=True)})


def place_list(request):
    places = Place.objects.filter(is_active=True)
    kind = request.GET.get("kind", "")
    zone = request.GET.get("zone", "")
    search = request.GET.get("q", "").strip()
    if kind in Place.Kind.values:
        places = places.filter(kind=kind)
    if zone in Place.Zone.values:
        places = places.filter(zone=zone)
    if search:
        places = places.filter(name__icontains=search)
    return render(
        request, "bookings/places.html",
        {"places": places, "kind": kind, "zone": zone, "search": search},
    )


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        from .models import Profile

        Profile.objects.create(user=user)
        login(request, user)
        messages.success(request, "Аккаунт создан. Добро пожаловать!")
        return redirect("dashboard")
    return render(request, "registration/register.html", {"form": form})


@login_required
def dashboard(request):
    bookings = Booking.objects.filter(resident=request.user).select_related("place").prefetch_related("services")
    passes = DayPass.objects.filter(booking__resident=request.user, booking__status=Booking.Status.PAID)
    return render(request, "bookings/dashboard.html", {"bookings": bookings, "passes": passes})


@login_required
def booking_create(request):
    form = BookingForm(
        request.POST or None,
        initial={"place": request.GET.get("place"), "day": timezone.localdate().isoformat()},
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            booking = create_booking(
                resident=request.user,
                place=data["place"],
                day=data["day"],
                start_hour=data["start_hour"],
                end_hour=data["end_hour"],
                services=data["services"],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Бронь создана. Для подтверждения перейдите к оплате.")
            return redirect("booking_detail", pk=booking.pk)
    return render(request, "bookings/booking_form.html", {"form": form})


@require_GET
def availability(request):
    try:
        day = date.fromisoformat(request.GET.get("date", ""))
        place_id = int(request.GET.get("place", ""))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Укажите корректные место и дату."}, status=400)
    place = get_object_or_404(Place, pk=place_id, is_active=True)
    occupied = set(
        OccupiedSlot.objects.filter(place=place, day=day).values_list("hour", flat=True)
    )
    now = timezone.localtime()
    slots = [
        {
            "hour": hour,
            "status": (
                "past" if day < now.date() or (day == now.date() and hour <= now.hour)
                else "busy" if hour in occupied
                else "free"
            ),
        }
        for hour in range(8, 22)
    ]
    return JsonResponse({"place": place.name, "date": day.isoformat(), "slots": slots})


@login_required
def booking_detail(request, pk):
    booking = get_object_or_404(
        Booking.objects.select_related("place").prefetch_related("services"),
        pk=pk, resident=request.user,
    )
    service_lines = list(
        booking.bookingservice_set.select_related("service").values("service__name", "price")
    )
    service_total = sum((line["price"] for line in service_lines), Decimal("0"))
    return render(
        request, "bookings/booking_detail.html",
        {
            "booking": booking, "now": timezone.now(),
            "base_total": booking.total - service_total, "service_lines": service_lines,
            "tariff_label": "Почасовой тариф" if booking.place.kind == Place.Kind.MEETING or booking.duration_hours < 8 else "Дневной тариф",
        },
    )


@login_required
@require_POST
def booking_pay(request, pk):
    booking = get_object_or_404(Booking, pk=pk, resident=request.user)
    try:
        payment, day_pass = pay_booking(booking)
    except ValidationError as error:
        messages.error(request, error.message)
    else:
        send_mail(
            subject=f"Оплата брони №{booking.pk} подтверждена",
            message=f"Оплата {payment.amount} ₽ прошла. Ваш пропуск: {day_pass.code}",
            from_email=None,
            recipient_list=[request.user.email],
            fail_silently=False,
        )
        messages.success(request, "Оплата подтверждена, пропуск сформирован и отправлен на email.")
    return redirect("booking_detail", pk=pk)


@login_required
@require_POST
def booking_cancel(request, pk):
    booking = get_object_or_404(Booking, pk=pk, resident=request.user)
    if booking.start_at <= timezone.now():
        messages.error(request, "Начавшуюся бронь отменить нельзя.")
    elif booking.status == Booking.Status.CANCELLED:
        messages.info(request, "Бронь уже отменена.")
    else:
        from django.db import transaction

        with transaction.atomic():
            booking.status = Booking.Status.CANCELLED
            booking.save(update_fields=["status"])
            OccupiedSlot.objects.filter(booking=booking).delete()
        messages.success(request, "Бронь отменена.")
    return redirect("booking_detail", pk=pk)


@login_required
@require_POST
def booking_extend(request, pk):
    booking = get_object_or_404(Booking, pk=pk, resident=request.user)
    if booking.status != Booking.Status.PAID:
        messages.error(request, "Продлить можно только оплаченную бронь.")
    elif booking.end_at <= timezone.now():
        messages.error(request, "Продлить можно до окончания брони.")
    else:
        try:
            extend_booking(booking)
        except ValidationError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, "Бронь продлена на один час.")
    return redirect("booking_detail", pk=pk)


@login_required
def profile(request):
    from .models import Profile

    profile, _ = Profile.objects.get_or_create(user=request.user)
    form = ProfileForm(request.POST or None, request.FILES or None, user=request.user, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Профиль сохранён.")
        return redirect("profile")
    return render(request, "bookings/profile.html", {"form": form, "profile": profile})


@login_required
def pass_detail(request, pk):
    day_pass = get_object_or_404(
        DayPass.objects.select_related("booking__place", "booking__resident"),
        pk=pk, booking__resident=request.user,
    )
    return render(request, "bookings/pass.html", {"day_pass": day_pass})


def is_coworking_admin(user):
    return user.is_staff


def is_accountant(user):
    return user.is_staff or (
        user.is_authenticated and getattr(getattr(user, "profile", None), "role", "") == "accountant"
    )


@user_passes_test(is_coworking_admin)
def admin_bookings(request):
    bookings = Booking.objects.select_related("resident", "place")
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    kind = request.GET.get("kind", "")
    resident = request.GET.get("resident", "")
    sort = request.GET.get("sort", "-start_at")
    valid_sorts = {"start_at", "-start_at", "total", "-total", "created_at", "-created_at"}
    if search:
        bookings = bookings.filter(
            Q(resident__first_name__icontains=search)
            | Q(resident__username__icontains=search)
            | Q(place__name__icontains=search)
        )
    if status in Booking.Status.values:
        bookings = bookings.filter(status=status)
    if kind in Place.Kind.values:
        bookings = bookings.filter(place__kind=kind)
    if resident.isdigit():
        bookings = bookings.filter(resident_id=resident)
    if sort not in valid_sorts:
        sort = "-start_at"
    page_obj = Paginator(bookings.order_by(sort), 20).get_page(request.GET.get("page"))
    return render(
        request, "bookings/admin_bookings.html",
        {
            "page_obj": page_obj, "search": search, "status": status,
            "kind": kind, "resident": resident, "sort": sort,
            "statuses": Booking.Status.choices,
            "residents": User.objects.filter(bookings__isnull=False).distinct().order_by(
                "first_name", "username"
            ),
        },
    )


@user_passes_test(is_coworking_admin)
def admin_place_create(request):
    form = PlaceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Место добавлено.")
        return redirect("places")
    return render(request, "bookings/place_form.html", {"form": form, "title": "Добавить место"})


@user_passes_test(is_coworking_admin)
def admin_place_edit(request, pk):
    place = get_object_or_404(Place, pk=pk)
    form = PlaceForm(request.POST or None, instance=place)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Изменения сохранены.")
        return redirect("places")
    return render(request, "bookings/place_form.html", {"form": form, "title": "Редактировать место"})


@user_passes_test(is_coworking_admin)
@require_POST
def admin_place_delete(request, pk):
    place = get_object_or_404(Place, pk=pk)
    if place.bookings.exists():
        place.is_active = False
        place.save(update_fields=["is_active"])
    else:
        place.delete()
    messages.success(request, "Место удалено или скрыто (если у него есть история бронирований).")
    return redirect("places")


@user_passes_test(is_coworking_admin)
def admin_reports(request):
    bookings = Booking.objects.exclude(status=Booking.Status.CANCELLED)
    payments = Payment.objects.filter(status=Payment.Status.SUCCEEDED)
    total_revenue = payments.aggregate(value=Sum("amount"))["value"] or Decimal("0")
    total_count = bookings.count()
    average_ticket = payments.aggregate(value=Avg("amount"))["value"] or Decimal("0")
    meeting_share = (
        bookings.filter(place__kind=Place.Kind.MEETING).count() * 100 / total_count if total_count else 0
    )
    day_start = timezone.localdate() - timezone.timedelta(days=6)
    daily = []
    for offset in range(7):
        day = day_start + timezone.timedelta(days=offset)
        count = bookings.filter(start_at__date=day).count()
        daily.append({"label": day.strftime("%a"), "count": count})
    max_count = max((item["count"] for item in daily), default=0) or 1
    for item in daily:
        item["height"] = max(8, round(item["count"] / max_count * 100))
    slot_capacity = Place.objects.filter(is_active=True).count() * 14 * 30
    occupied = OccupiedSlot.objects.filter(day__gte=day_start, day__lt=day_start + timezone.timedelta(days=30)).count()
    utilization = round(occupied * 100 / slot_capacity) if slot_capacity else 0
    return render(
        request, "bookings/reports.html",
        {
            "total_revenue": total_revenue, "total_count": total_count,
            "average_ticket": average_ticket, "meeting_share": round(meeting_share),
            "utilization": utilization, "daily": daily,
        },
    )


@user_passes_test(is_accountant)
def payments(request):
    records = Payment.objects.select_related("booking__resident", "booking__place")
    start = request.GET.get("from", "")
    end = request.GET.get("to", "")
    status = request.GET.get("status", "")
    if start:
        records = records.filter(created_at__date__gte=start)
    if end:
        records = records.filter(created_at__date__lte=end)
    if status in Payment.Status.values:
        records = records.filter(status=status)
    return render(
        request, "bookings/payments.html",
        {"payments": records, "start": start, "end": end, "status": status, "statuses": Payment.Status.choices},
    )


@user_passes_test(is_accountant)
def payments_csv(request):
    records = Payment.objects.select_related("booking__resident", "booking__place")
    start = request.GET.get("from", "")
    end = request.GET.get("to", "")
    status = request.GET.get("status", "")
    if start:
        records = records.filter(created_at__date__gte=start)
    if end:
        records = records.filter(created_at__date__lte=end)
    if status in Payment.Status.values:
        records = records.filter(status=status)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="payments.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Оплата", "Бронь", "Дата", "Резидент", "Место", "Способ", "Сумма", "Статус"])
    for payment in records:
        writer.writerow([
            payment.pk, payment.booking_id, timezone.localtime(payment.created_at).strftime("%d.%m.%Y %H:%M"),
            payment.booking.resident.get_full_name() or payment.booking.resident.username,
            payment.booking.place.name, payment.method, payment.amount, payment.get_status_display(),
        ])
    return response
