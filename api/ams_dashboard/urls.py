from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path, re_path

from .auth_views import (
    challenge_new_password,
    login as auth_login,
    me as auth_me,
    refresh as auth_refresh,
)
from .spa import spa_index


def health(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health", health),
    # Auth endpoints — public; they exchange creds for Cognito JWTs.
    path("api/auth/login", auth_login, name="auth-login"),
    path("api/auth/challenge", challenge_new_password, name="auth-challenge"),
    path("api/auth/refresh", auth_refresh, name="auth-refresh"),
    path("api/me/", auth_me, name="auth-me"),
    path("api/", include("customers.urls")),
    path("api/", include("software.urls")),
    path("api/", include("baskets.urls")),
    path("api/", include("patching.urls")),
    path("api/", include("analytics.urls")),
    path("api/", include("staff.urls")),
    path("api/", include("activities.urls")),
    # SPA fallback — must be last; matches every path not consumed above.
    re_path(r"^.*$", spa_index, name="spa-index"),
]
