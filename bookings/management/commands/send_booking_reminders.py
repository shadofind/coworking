from datetime import timedelta

from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.utils import timezone

from bookings.models import Booking


class Command(BaseCommand):
    help = "Email residents whose paid booking ends within the next hour."

    def handle(self, *args, **options):
        now = timezone.now()
        bookings = Booking.objects.filter(
            status=Booking.Status.PAID,
            end_at__gt=now,
            end_at__lte=now + timedelta(hours=1),
            reminder_sent_at__isnull=True,
        ).select_related("resident", "place")
        sent = 0
        for booking in bookings:
            send_mail(
                subject=f"Бронь №{booking.pk} скоро закончится",
                message=(
                    f"Ваша бронь места «{booking.place.name}» заканчивается "
                    f"в {timezone.localtime(booking.end_at):%H:%M}. "
                    "Если место свободно, вы можете продлить бронирование в личном кабинете."
                ),
                from_email=None,
                recipient_list=[booking.resident.email],
                fail_silently=False,
            )
            booking.reminder_sent_at = now
            booking.save(update_fields=["reminder_sent_at"])
            sent += 1
        self.stdout.write(self.style.SUCCESS(f"Отправлено напоминаний: {sent}"))
