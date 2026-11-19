from datetime import date

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import ExtraService, Place, Profile

User = get_user_model()


class RegistrationForm(UserCreationForm):
    first_name = forms.CharField(label="Имя и фамилия", max_length=150)
    email = forms.EmailField(label="Email")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "email")
        labels = {"username": "Логин"}

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Этот email уже зарегистрирован.")
        return email


class BookingForm(forms.Form):
    place = forms.ModelChoiceField(queryset=Place.objects.none(), label="Место")
    day = forms.DateField(
        label="Дата",
        widget=forms.DateInput(attrs={"type": "date"}),
        input_formats=["%Y-%m-%d"],
    )
    start_hour = forms.TypedChoiceField(
        label="Начало", choices=[(hour, f"{hour:02d}:00") for hour in range(8, 22)], coerce=int
    )
    end_hour = forms.TypedChoiceField(
        label="Окончание", choices=[(hour, f"{hour:02d}:00") for hour in range(9, 23)], coerce=int
    )
    services = forms.ModelMultipleChoiceField(
        queryset=ExtraService.objects.none(), label="Дополнительные услуги", required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["place"].queryset = Place.objects.filter(is_active=True)
        self.fields["services"].queryset = ExtraService.objects.filter(is_active=True)

    def clean_day(self):
        day = self.cleaned_data["day"]
        if day < date.today():
            raise forms.ValidationError("Нельзя забронировать место задним числом.")
        return day

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_hour")
        end = cleaned.get("end_hour")
        day = cleaned.get("day")
        if start is not None and end is not None and end <= start:
            self.add_error("end_hour", "Время окончания должно быть позже начала.")
        if day == date.today() and start is not None:
            from django.utils import timezone

            if start <= timezone.localtime().hour:
                self.add_error("start_hour", "Выберите ещё не прошедший час.")
        return cleaned


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(label="Имя и фамилия", max_length=150)
    email = forms.EmailField(label="Email")

    class Meta:
        model = Profile
        fields = ("phone", "photo")
        labels = {"phone": "Телефон", "photo": "Фото для пропуска"}
        widgets = {"photo": forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png"})}

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["first_name"].initial = user.first_name
        self.fields["email"].initial = user.email

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("Этот email уже используется.")
        return email

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and photo.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Размер фотографии не должен превышать 5 МБ.")
        if photo and photo.content_type not in {"image/jpeg", "image/png"}:
            raise forms.ValidationError("Загрузите изображение в формате JPG или PNG.")
        return photo

    def save(self, commit=True):
        profile = super().save(commit=False)
        self.user.first_name = self.cleaned_data["first_name"]
        self.user.email = self.cleaned_data["email"]
        if commit:
            self.user.save()
            profile.save()
        return profile


class PlaceForm(forms.ModelForm):
    class Meta:
        model = Place
        fields = ("name", "kind", "zone", "capacity", "description", "is_active")
