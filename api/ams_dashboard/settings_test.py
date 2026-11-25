"""Settings used by the test suite (see [tool.pytest.ini_options]).

The environment is fixed here, before the real settings module is
imported, because DRF binds its default authentication classes at import
time — they cannot be switched per test — and pytest-django loads
settings before any conftest.py runs.

  AUTH_BYPASS=0   tests run with the real authentication and permission
                  classes, like a deployed environment.
  DATABASE_URL    in-memory SQLite unless TEST_DATABASE_URL is exported,
                  so the suite needs no running Postgres.
  COGNITO_* / PORTAL_*  fake pool ids; JWKS lookups are replaced in tests.
"""

import os

os.environ["AUTH_BYPASS"] = "0"
os.environ["DEBUG"] = "False"
os.environ.setdefault("SECRET_KEY", "test-only-not-a-secret")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite://:memory:")
os.environ["COGNITO_REGION"] = "us-test-1"
os.environ["COGNITO_USER_POOL_ID"] = "us-test-1_STAFFPOOL"
os.environ["COGNITO_APP_CLIENT_ID"] = "staff-client-id"
os.environ["PORTAL_COGNITO_USER_POOL_ID"] = "us-test-1_PORTALPOOL"
os.environ["PORTAL_COGNITO_APP_CLIENT_ID"] = "portal-client-id"
os.environ["PORTAL_HOST"] = ""
os.environ["PORTAL_STAFF_EMAIL_DOMAINS"] = "imt.ca"
os.environ["REPORTS_BUCKET"] = ""
os.environ["PORTAL_EMAIL_MODE"] = "log"
os.environ["ANTHROPIC_API_KEY"] = ""  # tests never call the AI service

from .settings import *  # noqa: E402, F401, F403
