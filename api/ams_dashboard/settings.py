from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    AUTH_BYPASS=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
    SECURE_PROXY_SSL_HEADER_NAME=(str, ""),
    JIRA_URL=(str, ""),
    JIRA_EMAIL=(str, ""),
    JIRA_TOKEN=(str, ""),
    # Cognito (used when AUTH_BYPASS=0)
    COGNITO_REGION=(str, ""),
    COGNITO_USER_POOL_ID=(str, ""),
    COGNITO_APP_CLIENT_ID=(str, ""),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")
AUTH_BYPASS = env("AUTH_BYPASS")

JIRA_URL = env("JIRA_URL")
JIRA_EMAIL = env("JIRA_EMAIL")
JIRA_TOKEN = env("JIRA_TOKEN")

COGNITO_REGION = env("COGNITO_REGION")
COGNITO_USER_POOL_ID = env("COGNITO_USER_POOL_ID")
COGNITO_APP_CLIENT_ID = env("COGNITO_APP_CLIENT_ID")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "customers",
    "software",
    "baskets",
    "patching",
    "analytics",
    "staff",
    "activities",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise must come right after SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ams_dashboard.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ams_dashboard.wsgi.application"

# Database — prefer DATABASE_URL (local dev), fall back to individual vars
# (production, mapped from the RDS-managed Secrets Manager secret in ECS).
if env.str("DATABASE_URL", default=""):
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": env("DB_HOST"),
            "PORT": env("DB_PORT", default="5432"),
            "USER": env("DB_USER"),
            "PASSWORD": env("DB_PASSWORD"),
            "NAME": env("DB_NAME"),
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ── Static files ──────────────────────────────────────────────
# In a container the multi-stage Dockerfile copies web/dist/ to BASE_DIR/web_build.
# Vite is configured with base='/static/' for production builds so index.html
# references /static/assets/* — which whitenoise serves out of STATIC_ROOT.
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
WEB_BUILD_DIR = BASE_DIR / "web_build"
if WEB_BUILD_DIR.exists():
    STATICFILES_DIRS = [WEB_BUILD_DIR]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# ── Security (behind an internal ALB doing TLS termination) ────
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"

# ── Logging — JSON-ish lines suitable for CloudWatch ─────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "console": {
            "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "console",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# ── DRF ────────────────────────────────────────────────────────
_auth_classes = (
    [] if AUTH_BYPASS else ["ams_dashboard.auth_cognito.CognitoJWTAuthentication"]
)
_permission_classes = (
    ["rest_framework.permissions.AllowAny"]
    if AUTH_BYPASS
    else ["rest_framework.permissions.IsAuthenticated"]
)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": _auth_classes,
    "DEFAULT_PERMISSION_CLASSES": _permission_classes,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
}
