from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.utils import timezone

from bookings.models import (
    Booking,
    DayPass,
    ExtraService,
    OccupiedSlot,
    Payment,
    Place,
    Profile,
    Tariff,
)

User = get_user_model()


class Command(BaseCommand):
    help = "Create sample residents, places, tariffs, services, and at least 30 bookings."

    @transaction.atomic
    def handle(self, *args, **options):
        zones = [Place.Zone.OPEN, Place.Zone.QUIET]
        places = []
        for index in range(1, 11):
            kind = Place.Kind.MEETING if index > 6 else Place.Kind.WORKSPACE
            zone = Place.Zone.MEETING if kind == Place.Kind.MEETING else zones[index % 2]
            capacity = [4, 6, 10, 8][(index - 7) % 4] if kind == Place.Kind.MEETING else 1
            place, _ = Place.objects.get_or_create(
                name=f"{'Переговорная' if kind == Place.Kind.MEETING else 'Место'} {index if kind == Place.Kind.WORKSPACE else chr(64 + index - 6)}",
                defaults={
                    "kind": kind, "zone": zone, "capacity": capacity,
                    "description": "Светлое место с розеткой и быстрым Wi-Fi.",
                },
            )
            places.append(place)

        tariff_data = [
            ("Почасовой тариф", Place.Kind.WORKSPACE, Tariff.Plan.HOURLY, "250"),
            ("Дневной тариф", Place.Kind.WORKSPACE, Tariff.Plan.DAILY, "1400"),
            ("Месячный абонемент", Place.Kind.WORKSPACE, Tariff.Plan.MONTHLY, "12000"),
            ("Почасовой тариф переговорной", Place.Kind.MEETING, Tariff.Plan.HOURLY, "600"),
            ("Дневной тариф переговорной", Place.Kind.MEETING, Tariff.Plan.DAILY, "4800"),
            ("Месячный тариф переговорной", Place.Kind.MEETING, Tariff.Plan.MONTHLY, "45000"),
        ]
        tariff_data.extend(
            [
                (f"Тариф резидента {index}", Place.Kind.WORKSPACE, Tariff.Plan.HOURLY, str(220 + index))
                for index in range(1, 5)
            ]
        )
        for name, kind, plan, price in tariff_data:
            Tariff.objects.get_or_create(
                name=name, defaults={"place_kind": kind, "plan": plan, "price": Decimal(price)}
            )

        for name, price in [
            ("Кофе и чай", "120"), ("Печать документов", "20"),
            ("Доступ к принтеру", "100"), ("Флипчарт и маркеры", "150"),
            ("Парковка на день", "300"), ("Дополнительный монитор", "200"),
            ("Минеральная вода", "80"), ("Аренда гарнитуры", "100"),
            ("Кабель HDMI", "50"), ("Переговорная доска", "100"),
        ]:
            ExtraService.objects.get_or_create(name=name, defaults={"price": Decimal(price)})

        residents = []
        for index in range(1, 11):
            user, created = User.objects.get_or_create(
                username=f"resident{index:02d}",
                defaults={
                    "first_name": f"Резидент {index:02d}",
                    "email": f"resident{index:02d}@example.test",
                },
            )
            if created:
                user.set_unusable_password()
                user.save(update_fields=["password"])
            Profile.objects.get_or_create(user=user)
            residents.append(user)

        if Booking.objects.count() >= 30:
            self.stdout.write(self.style.WARNING("В базе уже есть не менее 30 броней; существующие записи сохранены."))
        else:
            created_count = 0
            day_offset = 0
            while created_count < 30:
                day = timezone.localdate() + timedelta(days=day_offset)
                for place_index, place in enumerate(places):
                    if created_count >= 30:
                        break
                    hour = 8 + (place_index % 10)
                    if OccupiedSlot.objects.filter(place=place, day=day, hour=hour).exists():
                        continue
                    start_at = timezone.make_aware(datetime.combine(day, time(hour)))
                    end_at = start_at + timedelta(hours=2)
                    resident = residents[created_count % len(residents)]
                    status = Booking.Status.PAID if created_count % 3 else Booking.Status.UNPAID
                    booking = Booking.objects.create(
                        resident=resident, place=place, start_at=start_at, end_at=end_at,
                        status=status, total=Decimal("600" if place.kind == Place.Kind.MEETING else "500"),
                    )
                    try:
                        OccupiedSlot.objects.bulk_create(
                            [
                                OccupiedSlot(booking=booking, place=place, day=day, hour=hour + offset)
                                for offset in range(2)
                            ]
                        )
                    except IntegrityError:
                        booking.delete()
                        continue
                    if status == Booking.Status.PAID:
                        Payment.objects.create(booking=booking, amount=booking.total)
                        DayPass.objects.create(booking=booking, valid_on=day)
                    created_count += 1
                day_offset += 1
            self.stdout.write(self.style.SUCCESS(f"Создано демонстрационных броней: {created_count}."))
        self.stdout.write(self.style.SUCCESS("Демонстрационные места, тарифы, услуги и резиденты готовы."))
