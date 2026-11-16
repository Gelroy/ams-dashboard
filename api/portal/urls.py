from django.urls import path

from . import views

urlpatterns = [
    path("auth/login", views.login, name="portal-login"),
    path("auth/new-password", views.new_password, name="portal-new-password"),
    path("auth/mfa/setup", views.mfa_setup, name="portal-mfa-setup"),
    path("auth/mfa/verify", views.mfa_verify, name="portal-mfa-verify"),
    path("auth/refresh", views.refresh, name="portal-refresh"),
    path("auth/logout", views.logout, name="portal-logout"),
    path("me", views.me, name="portal-me"),
    path("home", views.home, name="portal-home"),
]
