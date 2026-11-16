"""Customer Portal — identity and tenant-isolation tests.

Cross-tenant isolation is the highest-risk area of the portal
(docs/CUSTOMER_PORTAL.md §4), so these tests exist before any feature
that returns customer data. They cover:

  1. Pool separation      customer tokens never work on staff endpoints,
                          staff tokens never work on portal endpoints.
  2. Token validation     wrong key, wrong audience, access token, expiry.
  3. Account state        disabled / invited / soft-deleted user or
                          customer / unknown identity → no access.
  4. Tenant scope         a customer only ever sees their own organization.
  5. Route guards         every /api/portal/ data route carries the portal
                          authentication + permission classes.
  6. Host split           staff surface is absent on the portal hostname.
  7. Invite rules         email required, staff domains refused, one
                          customer per email, admins only.
  8. Sign-in relay        challenges are passed through; tokens are only
                          released for a usable PortalAccount.

Cognito is never contacted: token signatures are checked against two
in-test RSA keys (one per pool), and portal.cognito is replaced by fakes.
"""

import time
import uuid

import jwt
import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.asymmetric import rsa
from django.urls import get_resolver
from django.utils import timezone
from rest_framework.test import APIClient

from ams_dashboard import auth_cognito
from customers.models import Environment, Organization, OrgUser, Server
from portal import cognito, services
from portal.models import PortalAccount, PortalAccountStatus
from portal.scoping import PORTAL_AUTHENTICATION, PORTAL_PERMISSIONS

pytestmark = pytest.mark.django_db

STAFF_ISS = auth_cognito.issuer_for("us-test-1", "us-test-1_STAFFPOOL")
PORTAL_ISS = auth_cognito.issuer_for("us-test-1", "us-test-1_PORTALPOOL")
STAFF_AUD = "staff-client-id"
PORTAL_AUD = "portal-client-id"

# One signing key per pool, as in Cognito, plus one that belongs to nobody.
_KEYS = {
    STAFF_ISS: rsa.generate_private_key(public_exponent=65537, key_size=2048),
    PORTAL_ISS: rsa.generate_private_key(public_exponent=65537, key_size=2048),
}
_ROGUE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def mint(iss, *, sub, aud, token_use="id", key=None, ttl=3600, **extra):
    now = int(time.time())
    claims = {
        "iss": iss,
        "sub": sub,
        "token_use": token_use,
        "iat": now,
        "exp": now + ttl,
        **extra,
    }
    if aud is not None:
        claims["aud"] = aud
    return jwt.encode(claims, key or _KEYS[iss], algorithm="RS256")


def staff_token(*, admin=True, **kw):
    groups = {"cognito:groups": ["admin"]} if admin else {}
    return mint(
        STAFF_ISS,
        sub=kw.pop("sub", "staff-sub-1"),
        aud=STAFF_AUD,
        email="tech@imt.ca",
        **groups,
        **kw,
    )


def portal_token(account, **kw):
    return mint(
        PORTAL_ISS, sub=kw.pop("sub", account.cognito_sub), aud=kw.pop("aud", PORTAL_AUD), **kw
    )


def client(token=None, **extra):
    c = APIClient(**extra)
    if token:
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return c


@pytest.fixture(autouse=True)
def fake_jwks(monkeypatch):
    """Each issuer's JWKS holds exactly its own pool's public key."""
    monkeypatch.setattr(
        auth_cognito, "_signing_key", lambda token, issuer: _KEYS[issuer].public_key()
    )


def make_org(n, name):
    return Organization.objects.create(jira_org_id=f"synthetic-t{n}", jira_name=name)


def make_user(org, n, email, **kw):
    return OrgUser.objects.create(
        organization=org,
        jira_account_id=f"{org.jira_org_id}:u{n}",
        display_name=f"User {n}",
        email=email,
        **kw,
    )


def make_account(org_user, status=PortalAccountStatus.ACTIVE):
    return PortalAccount.objects.create(
        org_user=org_user,
        email_lower=(org_user.local_email or org_user.email).lower(),
        cognito_sub=str(uuid.uuid4()),
        status=status,
    )


@pytest.fixture
def tenants():
    """Two customers, each with one active portal user."""
    org_a = make_org(1, "Alpha Health")
    org_b = make_org(2, "Bravo Clinics")
    user_a = make_user(org_a, 1, "ann@alpha.example.com")
    user_b = make_user(org_b, 1, "bob@bravo.example.com")
    return {
        "org_a": org_a,
        "org_b": org_b,
        "user_a": user_a,
        "user_b": user_b,
        "acct_a": make_account(user_a),
        "acct_b": make_account(user_b),
    }


def _static_api_paths():
    """Every parameter-free GET-able path under /api/ in the URLconf."""
    found = set()

    def walk(patterns, prefix):
        for p in patterns:
            pat = prefix + str(p.pattern)
            if hasattr(p, "url_patterns"):
                walk(p.url_patterns, pat)
            elif "(?P" not in pat and "<" not in pat:
                found.add("/" + pat.replace("^", "").replace("$", ""))

    walk(get_resolver().url_patterns, "")
    return sorted(p for p in found if p.startswith("/api/"))


STAFF_PATHS = [
    p
    for p in _static_api_paths()
    if not p.startswith("/api/portal/") and not p.startswith("/api/auth/")
]


# ── 1. Pool separation ─────────────────────────────────────────────────


def test_the_route_walker_found_the_staff_api():
    assert "/api/organizations/" in STAFF_PATHS
    assert "/api/me/" in STAFF_PATHS
    assert len(STAFF_PATHS) >= 8


@pytest.mark.parametrize("path", STAFF_PATHS)
def test_customer_token_is_rejected_on_every_staff_endpoint(tenants, path):
    r = client(portal_token(tenants["acct_a"])).get(path)
    assert r.status_code == 401, f"{path} answered {r.status_code} to a customer token"


@pytest.mark.parametrize("path", STAFF_PATHS)
def test_staff_endpoints_require_a_token(path):
    assert client().get(path).status_code in (401, 403)


def test_customer_token_cannot_reach_another_orgs_users_via_staff_api(tenants):
    c = client(portal_token(tenants["acct_a"]))
    for org in (tenants["org_a"], tenants["org_b"]):
        assert c.get(f"/api/organizations/{org.id}/").status_code == 401
        assert c.get(f"/api/organizations/{org.id}/users/").status_code == 401


def test_customer_token_cannot_invite(tenants):
    u = make_user(tenants["org_a"], 2, "new@alpha.example.com")
    r = client(portal_token(tenants["acct_a"])).post(
        f"/api/organizations/{tenants['org_a'].id}/users/{u.id}/portal-invite/"
    )
    assert r.status_code == 401
    assert not PortalAccount.objects.filter(org_user=u).exists()


@pytest.mark.parametrize("path", ["/api/portal/me", "/api/portal/home"])
def test_staff_token_is_rejected_on_portal_endpoints(tenants, path):
    assert client(staff_token()).get(path).status_code == 401


def test_positive_controls(tenants):
    """The 401s above mean something only if valid tokens do work."""
    assert client(staff_token()).get("/api/organizations/").status_code == 200
    assert client(portal_token(tenants["acct_a"])).get("/api/portal/me").status_code == 200


# ── 2. Token validation ────────────────────────────────────────────────


def test_portal_rejects_token_signed_by_unknown_key(tenants):
    t = portal_token(tenants["acct_a"], key=_ROGUE_KEY)
    assert client(t).get("/api/portal/me").status_code == 401


def test_portal_rejects_wrong_audience(tenants):
    t = portal_token(tenants["acct_a"], aud="some-other-client")
    assert client(t).get("/api/portal/me").status_code == 401


def test_portal_rejects_staff_audience_even_with_portal_issuer(tenants):
    t = portal_token(tenants["acct_a"], aud=STAFF_AUD)
    assert client(t).get("/api/portal/me").status_code == 401


def test_portal_rejects_access_tokens(tenants):
    t = portal_token(tenants["acct_a"], token_use="access")
    assert client(t).get("/api/portal/me").status_code == 401


def test_portal_rejects_expired_tokens(tenants):
    t = portal_token(tenants["acct_a"], ttl=-60)
    assert client(t).get("/api/portal/me").status_code == 401


def test_portal_rejects_forged_issuer(tenants):
    # Signed with the portal key but claiming to be the staff pool, and
    # the reverse: a staff-signed token claiming the portal issuer.
    a = tenants["acct_a"]
    t1 = mint(STAFF_ISS, sub=a.cognito_sub, aud=PORTAL_AUD, key=_KEYS[PORTAL_ISS])
    t2 = mint(PORTAL_ISS, sub=a.cognito_sub, aud=PORTAL_AUD, key=_KEYS[STAFF_ISS])
    assert client(t1).get("/api/portal/me").status_code == 401
    assert client(t2).get("/api/portal/me").status_code == 401


def test_portal_requires_a_token():
    assert client().get("/api/portal/me").status_code in (401, 403)


def test_portal_audience_is_mandatory(tenants, settings):
    settings.PORTAL_COGNITO_APP_CLIENT_ID = ""
    with pytest.raises(RuntimeError):
        client(portal_token(tenants["acct_a"])).get("/api/portal/me")


# ── 3. Account state ───────────────────────────────────────────────────


def test_unknown_identity_has_no_access(tenants):
    t = mint(PORTAL_ISS, sub=str(uuid.uuid4()), aud=PORTAL_AUD)
    assert client(t).get("/api/portal/me").status_code == 401


@pytest.mark.parametrize("status", [PortalAccountStatus.DISABLED, PortalAccountStatus.INVITED])
def test_non_active_account_has_no_access(tenants, status):
    a = tenants["acct_a"]
    a.status = status
    a.save()
    assert client(portal_token(a)).get("/api/portal/me").status_code == 401


def test_disable_takes_effect_on_an_already_issued_token(tenants, fake_cognito):
    a = tenants["acct_a"]
    t = portal_token(a)
    assert client(t).get("/api/portal/home").status_code == 200
    services.disable(a)
    assert client(t).get("/api/portal/home").status_code == 401
    assert ("disable", a.cognito_sub) in fake_cognito.calls


def test_soft_deleted_user_loses_access(tenants):
    u = tenants["user_a"]
    u.deleted_at = timezone.now()
    u.save()
    assert client(portal_token(tenants["acct_a"])).get("/api/portal/me").status_code == 401


def test_soft_deleted_customer_loses_access(tenants):
    o = tenants["org_a"]
    o.deleted_at = timezone.now()
    o.save()
    assert client(portal_token(tenants["acct_a"])).get("/api/portal/me").status_code == 401
    # …and the other customer is unaffected.
    assert client(portal_token(tenants["acct_b"])).get("/api/portal/me").status_code == 200


# ── 4. Tenant scope ────────────────────────────────────────────────────


def test_me_returns_the_callers_own_customer(tenants):
    for key, org_key, email in (
        ("acct_a", "org_a", "ann@alpha.example.com"),
        ("acct_b", "org_b", "bob@bravo.example.com"),
    ):
        body = client(portal_token(tenants[key])).get("/api/portal/me").json()
        assert body["email"] == email
        assert body["organization"] == {
            "id": str(tenants[org_key].id),
            "name": tenants[org_key].jira_name,
        }


def test_home_shows_only_the_callers_organization(tenants):
    env_a = Environment.objects.get(organization=tenants["org_a"], name="PROD")
    env_b = Environment.objects.get(organization=tenants["org_b"], name="PROD")
    Server.objects.create(environment=env_a, name="alpha-prod-01")
    Server.objects.create(environment=env_a, name="alpha-prod-old", deleted_at=timezone.now())
    for i in range(3):
        Server.objects.create(environment=env_b, name=f"bravo-prod-0{i}")

    body = client(portal_token(tenants["acct_a"])).get("/api/portal/home").json()
    assert body["organization"]["name"] == "Alpha Health"
    counts = {e["name"]: e["server_count"] for e in body["environments"]}
    assert counts["PROD"] == 1  # own live server only: not B's three, not the deleted one
    assert "bravo" not in str(body).lower()


@pytest.mark.parametrize("path", ["/api/portal/me", "/api/portal/home"])
def test_client_supplied_organization_is_ignored(tenants, path):
    b = tenants["org_b"]
    c = client(portal_token(tenants["acct_a"]))
    r = c.get(
        path,
        {"organization": str(b.id), "organization_id": str(b.id), "org": str(b.id)},
        HTTP_X_ORGANIZATION=str(b.id),
    )
    assert r.status_code == 200
    assert r.json()["organization"]["name"] == "Alpha Health"


def test_portal_data_endpoints_are_read_only(tenants):
    c = client(portal_token(tenants["acct_a"]))
    for path in ("/api/portal/me", "/api/portal/home"):
        for method in ("post", "put", "patch", "delete"):
            assert getattr(c, method)(path).status_code == 405


# ── 5. Route guards ────────────────────────────────────────────────────


def _portal_routes():
    out = []

    def walk(patterns, prefix):
        for p in patterns:
            pat = prefix + str(p.pattern)
            if hasattr(p, "url_patterns"):
                walk(p.url_patterns, pat)
            elif pat.startswith("api/portal/"):
                out.append((pat, p.callback))

    walk(get_resolver().url_patterns, "")
    return out


def test_every_portal_data_route_uses_portal_auth():
    routes = _portal_routes()
    assert len(routes) >= 8
    for pattern, callback in routes:
        cls = callback.cls
        if pattern.startswith("api/portal/auth/"):
            # Sign-in endpoints take credentials, not tokens.
            assert cls.authentication_classes == [], pattern
        else:
            assert cls.authentication_classes == PORTAL_AUTHENTICATION, pattern
            assert cls.permission_classes == PORTAL_PERMISSIONS, pattern


def test_portal_auth_is_not_a_drf_default():
    from rest_framework.settings import api_settings

    names = [c.__name__ for c in api_settings.DEFAULT_AUTHENTICATION_CLASSES]
    assert names == ["CognitoJWTAuthentication"]


# ── 6. Host split ──────────────────────────────────────────────────────


@pytest.fixture
def split_hosts(settings):
    settings.PORTAL_HOST = "portal.test"
    settings.ALLOWED_HOSTS = ["*"]


def test_staff_surface_is_absent_on_the_portal_host(tenants, split_hosts):
    c = client(staff_token(), HTTP_HOST="portal.test")
    for path in ("/api/organizations/", "/api/me/", "/api/auth/login", "/admin/", "/admin/login/"):
        assert c.get(path).status_code == 404, path
    assert c.post("/api/auth/login", {"username": "a", "password": "b"}).status_code == 404


def test_portal_api_is_absent_on_the_dashboard_host(tenants, split_hosts):
    c = client(portal_token(tenants["acct_a"]), HTTP_HOST="dash.test")
    assert c.get("/api/portal/me").status_code == 404
    assert c.post("/api/portal/auth/login", {}).status_code == 404


def test_each_host_serves_its_own_api(tenants, split_hosts):
    assert (
        client(portal_token(tenants["acct_a"]), HTTP_HOST="portal.test")
        .get("/api/portal/me")
        .status_code
        == 200
    )
    assert (
        client(staff_token(), HTTP_HOST="dash.test").get("/api/organizations/").status_code == 200
    )
    for host in ("portal.test", "dash.test", "10.0.0.7"):  # ALB health checks use the task IP
        assert client(HTTP_HOST=host).get("/health").status_code == 200


def test_each_host_serves_its_own_spa(split_hosts, settings, tmp_path):
    web, portal = tmp_path / "web", tmp_path / "portal"
    web.mkdir()
    portal.mkdir()
    (web / "index.html").write_text("DASHBOARD SPA")
    (portal / "index.html").write_text("PORTAL SPA")
    settings.WEB_BUILD_DIR, settings.PORTAL_BUILD_DIR = web, portal
    assert client(HTTP_HOST="portal.test").get("/login").content == b"PORTAL SPA"
    assert client(HTTP_HOST="dash.test").get("/login").content == b"DASHBOARD SPA"


# ── 7. Invite rules ────────────────────────────────────────────────────


class FakeCognito:
    """Stands in for portal.cognito's admin calls."""

    class exceptions:  # noqa: N801 — mirrors boto3's client.exceptions
        class UsernameExistsException(Exception): ...

        class UnsupportedUserStateException(Exception): ...

        class InvalidParameterException(Exception): ...

    def __init__(self):
        self.calls = []
        self.users = {}  # email → sub
        self.fail_create = None  # exception instance to raise from create

    def admin_create_user(self, email, *, resend=False):
        self.calls.append(("resend" if resend else "create", email))
        if self.fail_create:
            raise self.fail_create
        if resend:
            return self.users[email]
        if email in self.users:
            raise self.exceptions.UsernameExistsException()
        self.users[email] = str(uuid.uuid4())
        return self.users[email]

    def admin_get_user_sub(self, email):
        return self.users.get(email)

    def admin_disable_user(self, username):
        self.calls.append(("disable", username))

    def admin_enable_user(self, username):
        self.calls.append(("enable", username))


@pytest.fixture
def fake_cognito(monkeypatch):
    fake = FakeCognito()
    for name in (
        "admin_create_user",
        "admin_get_user_sub",
        "admin_disable_user",
        "admin_enable_user",
    ):
        monkeypatch.setattr(cognito, name, getattr(fake, name))
    monkeypatch.setattr(cognito, "client_exceptions", lambda: fake.exceptions)
    return fake


def invite_url(user, action="invite"):
    return f"/api/organizations/{user.organization_id}/users/{user.id}/portal-{action}/"


def test_admin_can_invite(tenants, fake_cognito):
    u = make_user(tenants["org_a"], 2, "New.Person@Alpha.Example.com")
    r = client(staff_token()).post(invite_url(u))
    assert r.status_code == 200, r.content
    acct = PortalAccount.objects.get(org_user=u)
    assert acct.status == PortalAccountStatus.INVITED
    assert acct.email_lower == "new.person@alpha.example.com"
    assert acct.cognito_sub == fake_cognito.users["new.person@alpha.example.com"]
    assert acct.invited_by_email == "tech@imt.ca"
    assert r.json()["portal_account"]["status"] == "invited"


def test_invite_uses_local_email_override(tenants, fake_cognito):
    u = make_user(
        tenants["org_a"], 2, "jira@alpha.example.com", local_email="real@alpha.example.com"
    )
    assert client(staff_token()).post(invite_url(u)).status_code == 200
    assert PortalAccount.objects.get(org_user=u).email_lower == "real@alpha.example.com"


def test_viewer_cannot_invite(tenants, fake_cognito):
    u = make_user(tenants["org_a"], 2, "new@alpha.example.com")
    assert client(staff_token(admin=False)).post(invite_url(u)).status_code == 403
    assert fake_cognito.calls == []


def test_invite_requires_an_email(tenants, fake_cognito):
    u = make_user(tenants["org_a"], 2, None)
    r = client(staff_token()).post(invite_url(u))
    assert r.status_code == 400 and "no email" in r.json()["detail"]
    assert fake_cognito.calls == []


@pytest.mark.parametrize("email", ["tech@imt.ca", "Tech@IMT.CA", "x@mail.imt.ca"])
def test_staff_domains_are_never_invited(tenants, fake_cognito, email):
    u = make_user(tenants["org_a"], 2, email)
    r = client(staff_token()).post(invite_url(u))
    assert r.status_code == 400 and "staff address" in r.json()["detail"]
    assert fake_cognito.calls == []


def test_lookalike_domain_is_not_treated_as_staff(tenants, fake_cognito):
    u = make_user(tenants["org_a"], 2, "someone@notimt.ca")
    assert client(staff_token()).post(invite_url(u)).status_code == 200


def test_one_email_cannot_hold_access_under_two_customers(tenants, fake_cognito):
    shared = "shared.contact@example.org"
    u1 = make_user(tenants["org_a"], 2, shared)
    u2 = make_user(tenants["org_b"], 2, shared.upper())
    c = client(staff_token())
    assert c.post(invite_url(u1)).status_code == 200
    r = c.post(invite_url(u2))
    assert r.status_code == 409
    assert "Alpha Health" in r.json()["detail"]
    assert not PortalAccount.objects.filter(org_user=u2).exists()
    assert fake_cognito.calls == [("create", shared)]


def test_user_cannot_be_invited_twice(tenants, fake_cognito):
    r = client(staff_token()).post(invite_url(tenants["user_a"]))
    assert r.status_code == 409
    assert fake_cognito.calls == []


def test_cognito_failure_leaves_no_account_behind(tenants, fake_cognito):
    u = make_user(tenants["org_a"], 2, "new@alpha.example.com")
    fake_cognito.fail_create = fake_cognito.exceptions.InvalidParameterException("bad email")
    assert client(staff_token()).post(invite_url(u)).status_code == 400
    assert not PortalAccount.objects.filter(org_user=u).exists()


def test_orphaned_cognito_user_is_adopted(tenants, fake_cognito):
    fake_cognito.users["new@alpha.example.com"] = "orphan-sub"
    u = make_user(tenants["org_a"], 2, "new@alpha.example.com")
    assert client(staff_token()).post(invite_url(u)).status_code == 200
    assert PortalAccount.objects.get(org_user=u).cognito_sub == "orphan-sub"


def test_invite_refused_when_portal_not_configured(tenants, fake_cognito, settings):
    settings.PORTAL_COGNITO_USER_POOL_ID = ""
    u = make_user(tenants["org_a"], 2, "new@alpha.example.com")
    assert client(staff_token()).post(invite_url(u)).status_code == 503


def test_user_must_belong_to_the_org_in_the_url(tenants, fake_cognito):
    u = make_user(tenants["org_a"], 2, "new@alpha.example.com")
    url = f"/api/organizations/{tenants['org_b'].id}/users/{u.id}/portal-invite/"
    assert client(staff_token()).post(url).status_code == 404
    assert fake_cognito.calls == []


def test_disable_enable_and_resend(tenants, fake_cognito):
    c = client(staff_token())
    u = make_user(tenants["org_a"], 2, "new@alpha.example.com")
    assert c.post(invite_url(u)).status_code == 200
    assert c.post(invite_url(u, "resend")).status_code == 200

    assert c.post(invite_url(u, "disable")).json()["portal_account"]["status"] == "disabled"
    assert c.post(invite_url(u, "resend")).status_code == 409
    # Never signed in, so enabling returns to "invited", not "active".
    assert c.post(invite_url(u, "enable")).json()["portal_account"]["status"] == "invited"

    a = tenants["user_a"]  # has signed in before
    PortalAccount.objects.filter(org_user=a).update(last_login_at=timezone.now())
    assert c.post(invite_url(a, "disable")).json()["portal_account"]["status"] == "disabled"
    assert c.post(invite_url(a, "enable")).json()["portal_account"]["status"] == "active"
    assert c.post(invite_url(a, "resend")).status_code == 409  # already active


def test_portal_actions_404_without_an_account(tenants, fake_cognito):
    u = make_user(tenants["org_a"], 2, "new@alpha.example.com")
    for action in ("resend", "disable", "enable"):
        assert client(staff_token()).post(invite_url(u, action)).status_code == 404


def test_users_list_reports_portal_state(tenants):
    make_user(tenants["org_a"], 2, "never@alpha.example.com")
    rows = (
        client(staff_token())
        .get(f"/api/organizations/{tenants['org_a'].id}/users/")
        .json()["results"]
    )
    by_email = {r["email"]: r["portal_account"] for r in rows}
    assert by_email["never@alpha.example.com"] is None
    assert by_email["ann@alpha.example.com"]["status"] == "active"


# ── 8. Sign-in relay ───────────────────────────────────────────────────


def _auth_result(account_or_sub):
    sub = getattr(account_or_sub, "cognito_sub", account_or_sub)
    return {
        "AuthenticationResult": {
            "IdToken": mint(PORTAL_ISS, sub=sub, aud=PORTAL_AUD),
            "AccessToken": "access",
            "RefreshToken": "refresh",
            "ExpiresIn": 3600,
        }
    }


def _client_error(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "Op")


def test_first_sign_in_walks_password_then_mfa_setup(tenants, monkeypatch):
    acct = tenants["acct_a"]
    acct.status = PortalAccountStatus.INVITED
    acct.save()
    monkeypatch.setattr(
        cognito,
        "initiate_auth",
        lambda e, p: {
            "ChallengeName": "NEW_PASSWORD_REQUIRED",
            "Session": "s1",
            "ChallengeParameters": {"USER_ID_FOR_SRP": "uuid-username"},
        },
    )
    monkeypatch.setattr(
        cognito,
        "respond_new_password",
        lambda s, u, p: {
            "ChallengeName": "MFA_SETUP",
            "Session": "s2",
            "ChallengeParameters": {},
        },
    )
    monkeypatch.setattr(
        cognito,
        "associate_software_token",
        lambda s: {"SecretCode": "JBSWY3DPEHPK3PXP", "Session": "s3"},
    )
    monkeypatch.setattr(
        cognito, "verify_software_token", lambda s, c: {"Status": "SUCCESS", "Session": "s4"}
    )
    monkeypatch.setattr(cognito, "respond_mfa_setup", lambda s, u: _auth_result(acct))

    c = client()
    r = c.post("/api/portal/auth/login", {"email": " Ann@Alpha.Example.com ", "password": "pw"})
    assert r.json() == {
        "challenge": "NEW_PASSWORD_REQUIRED",
        "session": "s1",
        "username": "uuid-username",
    }

    r = c.post(
        "/api/portal/auth/new-password",
        {
            "session": "s1",
            "username": "uuid-username",
            "new_password": "N3w-password!",
            "email": "ann@alpha.example.com",
        },
    )
    body = r.json()
    assert body["challenge"] == "MFA_SETUP" and body["session"] == "s3"
    assert body["secret_code"] == "JBSWY3DPEHPK3PXP"
    assert body["otpauth_uri"].startswith("otpauth://totp/AMS%20Customer%20Portal:ann%40alpha")
    assert "secret=JBSWY3DPEHPK3PXP" in body["otpauth_uri"]

    r = c.post(
        "/api/portal/auth/mfa/setup",
        {"session": "s3", "username": "uuid-username", "code": "123456"},
    )
    assert r.status_code == 200 and r.json()["id_token"]
    acct.refresh_from_db()
    assert acct.status == PortalAccountStatus.ACTIVE and acct.last_login_at is not None
    # The issued token works immediately.
    assert client(r.json()["id_token"]).get("/api/portal/me").status_code == 200


def test_returning_sign_in_requires_totp(tenants, monkeypatch):
    monkeypatch.setattr(
        cognito,
        "initiate_auth",
        lambda e, p: {
            "ChallengeName": "SOFTWARE_TOKEN_MFA",
            "Session": "s1",
            "ChallengeParameters": {},
        },
    )
    monkeypatch.setattr(cognito, "respond_totp", lambda s, u, c: _auth_result(tenants["acct_a"]))
    c = client()
    r = c.post("/api/portal/auth/login", {"email": "ann@alpha.example.com", "password": "pw"})
    assert r.json()["challenge"] == "SOFTWARE_TOKEN_MFA" and "id_token" not in r.json()
    r = c.post(
        "/api/portal/auth/mfa/verify",
        {"session": "s1", "username": "ann@alpha.example.com", "code": "654321"},
    )
    assert r.status_code == 200 and r.json()["refresh_token"] == "refresh"


@pytest.mark.parametrize("make_unusable", ["no_account", "disabled", "user_deleted"])
def test_tokens_are_withheld_without_a_usable_account(tenants, monkeypatch, make_unusable):
    acct = tenants["acct_a"]
    sub = acct.cognito_sub
    if make_unusable == "no_account":
        sub = str(uuid.uuid4())
    elif make_unusable == "disabled":
        acct.status = PortalAccountStatus.DISABLED
        acct.save()
    else:
        acct.org_user.deleted_at = timezone.now()
        acct.org_user.save()
    monkeypatch.setattr(cognito, "initiate_auth", lambda e, p: _auth_result(sub))
    r = client().post("/api/portal/auth/login", {"email": "x@y.example.com", "password": "pw"})
    assert r.status_code == 403
    assert "id_token" not in r.json()


def test_refresh_does_not_reactivate_or_serve_unusable_accounts(tenants, monkeypatch):
    acct = tenants["acct_a"]
    monkeypatch.setattr(cognito, "refresh", lambda t: _auth_result(acct))
    assert client().post("/api/portal/auth/refresh", {"refresh_token": "r"}).status_code == 200
    acct.status = PortalAccountStatus.DISABLED
    acct.save()
    assert client().post("/api/portal/auth/refresh", {"refresh_token": "r"}).status_code == 403
    acct.refresh_from_db()
    assert acct.status == PortalAccountStatus.DISABLED


@pytest.mark.parametrize(
    "code,expected",
    [
        ("NotAuthorizedException", 401),
        ("UserNotFoundException", 401),
        ("TooManyRequestsException", 429),
        ("InternalErrorException", 503),
    ],
)
def test_login_errors_do_not_reveal_whether_the_user_exists(monkeypatch, code, expected):
    def boom(e, p):
        raise _client_error(code)

    monkeypatch.setattr(cognito, "initiate_auth", boom)
    r = client().post("/api/portal/auth/login", {"email": "who@example.com", "password": "pw"})
    assert r.status_code == expected
    if expected == 401:
        assert r.json()["detail"] == "Incorrect email or password."


def test_wrong_mfa_code_is_a_400_not_a_logout(monkeypatch):
    def boom(s, u, c):
        raise _client_error("CodeMismatchException")

    monkeypatch.setattr(cognito, "respond_totp", boom)
    r = client().post(
        "/api/portal/auth/mfa/verify", {"session": "s", "username": "u", "code": "000000"}
    )
    assert r.status_code == 400 and "not correct" in r.json()["detail"]


def test_sign_in_endpoints_validate_input_and_configuration(settings):
    c = client()
    assert c.post("/api/portal/auth/login", {"email": "a@b.example.com"}).status_code == 400
    assert c.post("/api/portal/auth/mfa/verify", {"session": "s"}).status_code == 400
    assert c.post("/api/portal/auth/refresh", {}).status_code == 400
    assert c.get("/api/portal/auth/login").status_code == 405
    settings.PORTAL_COGNITO_USER_POOL_ID = ""
    assert (
        c.post("/api/portal/auth/login", {"email": "a@b.example.com", "password": "x"}).status_code
        == 503
    )


def test_logout_always_succeeds(monkeypatch):
    revoked = []
    monkeypatch.setattr(cognito, "revoke", revoked.append)
    assert client().post("/api/portal/auth/logout", {"refresh_token": "r"}).status_code == 204
    assert client().post("/api/portal/auth/logout", {}).status_code == 204
    assert revoked == ["r"]
