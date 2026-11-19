from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("tariffs/", views.tariffs, name="tariffs"),
    path("places/", views.place_list, name="places"),
    path("register/", views.register, name="register"),
    path(
        "login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("profile/", views.profile, name="profile"),
    path("bookings/new/", views.booking_create, name="booking_create"),
    path("bookings/<int:pk>/", views.booking_detail, name="booking_detail"),
    path("bookings/<int:pk>/pay/", views.booking_pay, name="booking_pay"),
    path("bookings/<int:pk>/cancel/", views.booking_cancel, name="booking_cancel"),
    path("bookings/<int:pk>/extend/", views.booking_extend, name="booking_extend"),
    path("passes/<int:pk>/", views.pass_detail, name="pass_detail"),
    path("api/availability/", views.availability, name="availability"),
    path("staff/bookings/", views.admin_bookings, name="admin_bookings"),
    path("staff/places/new/", views.admin_place_create, name="admin_place_create"),
    path("staff/places/<int:pk>/edit/", views.admin_place_edit, name="admin_place_edit"),
    path("staff/places/<int:pk>/delete/", views.admin_place_delete, name="admin_place_delete"),
    path("staff/reports/", views.admin_reports, name="admin_reports"),
    path("accounting/payments/", views.payments, name="payments"),
    path("accounting/payments.csv", views.payments_csv, name="payments_csv"),
    path(
        "password/change/",
        auth_views.PasswordChangeView.as_view(
            template_name="registration/password_change.html", success_url="/profile/"
        ),
        name="password_change",
    ),
]
