from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Booking, DayPass, ExtraService, OccupiedSlot, Payment, Place, Profile, Tariff
from .services import create_booking, pay_booking, quote_booking

User = get_user_model()


class BookingServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="resident", password="Strong-pass-123", email="resident@example.test"
        )
        self.place = Place.objects.create(name="Место 3", kind=Place.Kind.WORKSPACE)
        self.meeting = Place.objects.create(
            name="Переговорная А", kind=Place.Kind.MEETING, zone=Place.Zone.MEETING, capacity=6
        )
        Tariff.objects.create(
            name="Почасовой", place_kind=Place.Kind.WORKSPACE,
            plan=Tariff.Plan.HOURLY, price=Decimal("250"),
        )
        Tariff.objects.create(
            name="Дневной", place_kind=Place.Kind.WORKSPACE,
            plan=Tariff.Plan.DAILY, price=Decimal("1400"),
        )
        Tariff.objects.create(
            name="Переговорная", place_kind=Place.Kind.MEETING,
            plan=Tariff.Plan.HOURLY, price=Decimal("600"),
        )

    def future_date(self):
        return timezone.localdate() + timedelta(days=2)

    def test_daily_tariff_applies_at_eight_hours_and_meeting_is_hourly(self):
        day = self.future_date()
        start = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time().replace(hour=8)))
        self.assertEqual(quote_booking(self.place, start, start + timedelta(hours=7)), Decimal("1750"))
        self.assertEqual(quote_booking(self.place, start, start + timedelta(hours=8)), Decimal("1400"))
        self.assertEqual(quote_booking(self.meeting, start, start + timedelta(hours=8)), Decimal("4800"))

    def test_overlapping_reservation_is_rejected_by_unique_hour_slots(self):
        day = self.future_date()
        create_booking(
            resident=self.user, place=self.place, day=day, start_hour=10, end_hour=12
        )
        with self.assertRaises(ValidationError):
            create_booking(
                resident=self.user, place=self.place, day=day, start_hour=11, end_hour=13
            )
        self.assertEqual(Booking.objects.count(), 1)

    def test_touching_reservation_ranges_are_allowed(self):
        day = self.future_date()
        create_booking(
            resident=self.user, place=self.place, day=day, start_hour=10, end_hour=12
        )
        next_booking = create_booking(
            resident=self.user, place=self.place, day=day, start_hour=12, end_hour=13
        )
        self.assertEqual(OccupiedSlot.objects.filter(place=self.place, day=day).count(), 3)
        self.assertEqual(next_booking.duration_hours, 1)

    def test_payment_creates_payment_and_one_day_pass_together(self):
        booking = create_booking(
            resident=self.user, place=self.place, day=self.future_date(), start_hour=10, end_hour=12
        )
        payment, day_pass = pay_booking(booking)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.PAID)
        self.assertEqual(payment.amount, booking.total)
        self.assertEqual(day_pass.booking, booking)
        self.assertEqual(DayPass.objects.count(), 1)

    def test_service_price_is_included_in_booking_total(self):
        coffee = ExtraService.objects.create(name="Кофе", price=Decimal("120"))
        booking = create_booking(
            resident=self.user, place=self.place, day=self.future_date(),
            start_hour=10, end_hour=11, services=[coffee],
        )
        self.assertEqual(booking.total, Decimal("370"))


class BookingViewsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner", password="Strong-pass-123", email="owner@example.test"
        )
        self.other = User.objects.create_user(
            username="other", password="Strong-pass-123", email="other@example.test"
        )
        Profile.objects.create(user=self.owner)
        Profile.objects.create(user=self.other)
        self.place = Place.objects.create(name="Место 1", kind=Place.Kind.WORKSPACE)

    def test_resident_cannot_open_another_residents_booking(self):
        booking = Booking.objects.create(
            resident=self.owner, place=self.place,
            start_at=timezone.now() + timedelta(days=1),
            end_at=timezone.now() + timedelta(days=1, hours=2),
            total=Decimal("500"),
        )
        self.client.force_login(self.other)
        response = self.client.get(reverse("booking_detail", args=[booking.pk]))
        self.assertEqual(response.status_code, 404)

    def test_availability_endpoint_returns_hourly_json(self):
        day = timezone.localdate() + timedelta(days=2)
        OccupiedSlot.objects.create(
            booking=Booking.objects.create(
                resident=self.owner, place=self.place,
                start_at=timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time().replace(hour=10))),
                end_at=timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time().replace(hour=11))),
                total=Decimal("250"),
            ),
            place=self.place, day=day, hour=10,
        )
        response = self.client.get(
            reverse("availability"), {"place": self.place.pk, "date": day.isoformat()}
        )
        self.assertEqual(response.status_code, 200)
        slots = {slot["hour"]: slot["status"] for slot in response.json()["slots"]}
        self.assertEqual(slots[10], "busy")
        self.assertEqual(slots[11], "free")

    def test_payment_view_sends_confirmation_and_issues_pass(self):
        booking = Booking.objects.create(
            resident=self.owner, place=self.place,
            start_at=timezone.now() + timedelta(days=1),
            end_at=timezone.now() + timedelta(days=1, hours=2),
            total=Decimal("500"),
        )
        self.client.force_login(self.owner)
        response = self.client.post(reverse("booking_pay", args=[booking.pk]))
        self.assertRedirects(response, reverse("booking_detail", args=[booking.pk]))
        self.assertEqual(Payment.objects.filter(booking=booking).count(), 1)
        self.assertEqual(DayPass.objects.filter(booking=booking).count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_invalid_availability_parameters_return_json_error(self):
        response = self.client.get(reverse("availability"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_public_and_resident_pages_render(self):
        for name in ("home", "tariffs", "places", "login", "register"):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.client.force_login(self.owner)
        for name in ("dashboard", "booking_create", "profile"):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_resident_can_submit_a_booking_from_the_form(self):
        self.client.force_login(self.owner)
        day = timezone.localdate() + timedelta(days=2)
        response = self.client.post(
            reverse("booking_create"),
            {
                "place": self.place.pk, "day": day.isoformat(),
                "start_hour": "10", "end_hour": "12",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Booking.objects.filter(resident=self.owner).count(), 1)

    def test_staff_pages_render(self):
        staff = User.objects.create_superuser(
            username="manager", password="Strong-pass-123", email="manager@example.test"
        )
        self.client.force_login(staff)
        for name in ("admin_bookings", "admin_reports", "payments"):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_booking_end_reminder_is_sent_once(self):
        end_at = timezone.now() + timedelta(minutes=30)
        booking = Booking.objects.create(
            resident=self.owner, place=self.place,
            start_at=end_at - timedelta(hours=2), end_at=end_at,
            status=Booking.Status.PAID, total=Decimal("500"),
        )
        call_command("send_booking_reminders", stdout=None)
        booking.refresh_from_db()
        self.assertIsNotNone(booking.reminder_sent_at)
        self.assertEqual(len(mail.outbox), 1)
        call_command("send_booking_reminders", stdout=None)
        self.assertEqual(len(mail.outbox), 1)

    def test_booking_detail_shows_exact_service_and_base_amounts(self):
        booking = Booking.objects.create(
            resident=self.owner, place=self.place,
            start_at=timezone.now() + timedelta(days=1),
            end_at=timezone.now() + timedelta(days=1, hours=2),
            total=Decimal("620"),
        )
        service = ExtraService.objects.create(name="Кофе", price=Decimal("120"))
        booking.bookingservice_set.create(service=service, price=Decimal("120"))
        self.client.force_login(self.owner)
        response = self.client.get(reverse("booking_detail", args=[booking.pk]))
        self.assertContains(response, "500 ₽")
        self.assertContains(response, "120 ₽")
