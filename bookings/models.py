import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


def generate_pass_code():
    return uuid.uuid4().hex[:12].upper()


class Profile(models.Model):
    class Role(models.TextChoices):
        RESIDENT = "resident", "Резидент"
        ACCOUNTANT = "accountant", "Бухгалтер"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.RESIDENT)
    phone = models.CharField(max_length=30, blank=True)
    photo = models.ImageField(upload_to="residents/", blank=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class Place(models.Model):
    class Kind(models.TextChoices):
        WORKSPACE = "workspace", "Рабочее место"
        MEETING = "meeting", "Переговорная"

    class Zone(models.TextChoices):
        OPEN = "open", "Открытая зона"
        QUIET = "quiet", "Тихая комната"
        MEETING = "meeting", "Переговорные"

    name = models.CharField("Название", max_length=80, unique=True)
    kind = models.CharField("Тип", max_length=16, choices=Kind.choices, default=Kind.WORKSPACE)
    zone = models.CharField("Зона", max_length=16, choices=Zone.choices, default=Zone.OPEN)
    capacity = models.PositiveSmallIntegerField("Вместимость", default=1, validators=[MinValueValidator(1)])
    description = models.CharField("Описание", max_length=240, blank=True)
    is_active = models.BooleanField("Доступно для брони", default=True)

    class Meta:
        ordering = ["kind", "name"]
        verbose_name = "Место"
        verbose_name_plural = "Места"

    def __str__(self):
        return self.name


class Tariff(models.Model):
    class Plan(models.TextChoices):
        HOURLY = "hourly", "Почасовой"
        DAILY = "daily", "Дневной"
        MONTHLY = "monthly", "Месячный"

    name = models.CharField("Название", max_length=80)
    place_kind = models.CharField("Тип места", max_length=16, choices=Place.Kind.choices)
    plan = models.CharField("План", max_length=12, choices=Plan.choices)
    price = models.DecimalField("Цена, ₽", max_digits=9, decimal_places=2, validators=[MinValueValidator(0)])
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        ordering = ["place_kind", "plan"]
        verbose_name = "Тариф"
        verbose_name_plural = "Тарифы"

    def __str__(self):
        return f"{self.name} — {self.price} ₽"


class ExtraService(models.Model):
    name = models.CharField("Услуга", max_length=80, unique=True)
    price = models.DecimalField("Цена, ₽", max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    is_active = models.BooleanField("Доступна", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Дополнительная услуга"
        verbose_name_plural = "Дополнительные услуги"

    def __str__(self):
        return self.name


class Booking(models.Model):
    class Status(models.TextChoices):
        UNPAID = "unpaid", "Не оплачена"
        PAID = "paid", "Активна"
        COMPLETED = "completed", "Завершена"
        CANCELLED = "cancelled", "Отменена"

    resident = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings", verbose_name="Резидент"
    )
    place = models.ForeignKey(Place, on_delete=models.PROTECT, related_name="bookings", verbose_name="Место")
    start_at = models.DateTimeField("Начало")
    end_at = models.DateTimeField("Окончание")
    status = models.CharField("Статус", max_length=12, choices=Status.choices, default=Status.UNPAID)
    total = models.DecimalField("Сумма, ₽", max_digits=9, decimal_places=2)
    reminder_sent_at = models.DateTimeField("Напоминание отправлено", null=True, blank=True)
    services = models.ManyToManyField(ExtraService, through="BookingService", blank=True, related_name="bookings")
    created_at = models.DateTimeField("Создана", auto_now_add=True)

    class Meta:
        ordering = ["-start_at"]
        verbose_name = "Бронирование"
        verbose_name_plural = "Бронирования"

    def __str__(self):
        return f"Бронь №{self.pk} — {self.place}"

    @property
    def duration_hours(self):
        return int((self.end_at - self.start_at).total_seconds() // 3600)


class BookingService(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE)
    service = models.ForeignKey(ExtraService, on_delete=models.PROTECT)
    price = models.DecimalField("Цена на момент бронирования", max_digits=8, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["booking", "service"], name="unique_service_per_booking")
        ]
        verbose_name = "Услуга в бронировании"
        verbose_name_plural = "Услуги в бронировании"


class OccupiedSlot(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="slots")
    place = models.ForeignKey(Place, on_delete=models.PROTECT, related_name="occupied_slots")
    day = models.DateField()
    hour = models.PositiveSmallIntegerField(validators=[MinValueValidator(8), MaxValueValidator(21)])

    class Meta:
        ordering = ["day", "hour"]
        constraints = [
            models.UniqueConstraint(fields=["place", "day", "hour"], name="unique_place_hour")
        ]
        indexes = [models.Index(fields=["day", "place", "hour"])]
        verbose_name = "Занятый час"
        verbose_name_plural = "Занятые часы"


class Payment(models.Model):
    class Status(models.TextChoices):
        SUCCEEDED = "succeeded", "Оплачена"
        REFUNDED = "refunded", "Возвращена"

    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="payments", verbose_name="Бронь")
    amount = models.DecimalField("Сумма, ₽", max_digits=9, decimal_places=2)
    status = models.CharField("Статус", max_length=12, choices=Status.choices, default=Status.SUCCEEDED)
    method = models.CharField("Способ", max_length=40, default="Банковская карта")
    created_at = models.DateTimeField("Дата оплаты", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Оплата"
        verbose_name_plural = "Оплаты"


class DayPass(models.Model):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name="day_pass", verbose_name="Бронь")
    code = models.CharField("Код пропуска", max_length=24, unique=True, default=generate_pass_code)
    valid_on = models.DateField("Действителен")
    issued_at = models.DateTimeField("Выдан", default=timezone.now)

    class Meta:
        ordering = ["-valid_on"]
        verbose_name = "Пропуск"
        verbose_name_plural = "Пропуска"

    def __str__(self):
        return self.code


class MonthlySubscription(models.Model):
    resident = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions", verbose_name="Резидент"
    )
    place = models.ForeignKey(Place, on_delete=models.PROTECT, related_name="subscriptions", verbose_name="Место")
    starts_on = models.DateField("Начало")
    ends_on = models.DateField("Окончание")
    price = models.DecimalField("Цена за месяц, ₽", max_digits=9, decimal_places=2)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        ordering = ["-starts_on"]
        verbose_name = "Месячный абонемент"
        verbose_name_plural = "Месячные абонементы"
