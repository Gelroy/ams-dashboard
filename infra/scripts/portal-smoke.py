#!/usr/bin/env python3
"""End-to-end smoke test of the Customer Portal identity layer against a
DEPLOYED non-production environment.

    api/.venv/bin/python infra/scripts/portal-smoke.py --env personal-dev

What it proves, over real HTTPS against real Cognito:
  1. A staff admin can invite a customer user from the dashboard API.
  2. That user's first sign-in walks temporary password → new password →
     authenticator (TOTP) enrolment → tokens, and later sign-ins demand a
     TOTP code.
  3. The customer sees their own organization and nothing else.
  4. A customer token is refused by the staff API, and a staff token by
     the portal API.
  5. The two hostnames expose only their own surface.
  6. Disabling the account cuts off an already-issued token at once.

How: it creates two throwaway identities with random passwords — one
staff admin in the staff pool, and (through the real invite endpoint) one
customer on a synthetic OrgUser — and deletes both Cognito users when it
finishes, pass or fail. The customer's PortalAccount row is left behind
disabled (the product has no delete, by design); the script prints the
one-line run-task command that removes it.

Refuses to run against the prod environment, and uses the same account
guard as deploy.sh (the profile must resolve to the environment's
AWS_ACCOUNT_ID). Passwords are generated in-process, never printed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import secrets
import ssl
import string
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import boto3

try:  # python.org builds of Python ship without a CA bundle for urllib
    import certifi

    TLS = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    TLS = ssl.create_default_context()


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60, context=TLS) as r:
        return r.read()

REPO = Path(__file__).resolve().parents[2]


def load_env(name: str) -> dict[str, str]:
    path = REPO / "infra" / "environments" / f"{name}.env"
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def totp(secret_b32: str, at: float | None = None) -> str:
    """RFC 6238, SHA-1, 30 s step, 6 digits — what authenticator apps compute."""
    key = base64.b32decode(secret_b32.upper() + "=" * (-len(secret_b32) % 8))
    counter = int((at or time.time()) // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def random_password() -> str:
    alphabet = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alphabet) for _ in range(28))
    return f"Aa1-{core}"  # guarantees upper, lower, digit, symbol


class Http:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, *, token: str | None = None, body=None):
        req = urllib.request.Request(self.base + path, method=method)
        req.add_header("Accept", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, data=data, timeout=60, context=TLS) as r:
                raw = r.read()
                status = r.status
                ctype = r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            raw = e.read()
            status = e.code
            ctype = e.headers.get("Content-Type", "")
        parsed = None
        if "json" in ctype and raw:
            parsed = json.loads(raw)
        return status, parsed


class Smoke:
    def __init__(self):
        self.failures = 0
        self.checks = 0

    def check(self, label: str, ok: bool, detail: str = ""):
        self.checks += 1
        mark = "✓" if ok else "✗"
        if not ok:
            self.failures += 1
        print(f"  {mark} {label}" + (f"  [{detail}]" if detail and not ok else ""))
        return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    args = ap.parse_args()

    env = load_env(args.env)
    if env.get("ENVIRONMENT") == "prod":
        sys.exit("✗ refusing to run the smoke test against prod")
    if env.get("PORTAL_ENABLED") != "true" or not env.get("DOMAIN_NAME"):
        sys.exit("✗ this environment has no portal (PORTAL_ENABLED / DOMAIN_NAME)")

    session = boto3.Session(profile_name=env["AWS_PROFILE"], region_name=env["AWS_REGION"])
    account = session.client("sts").get_caller_identity()["Account"]
    if account != env["AWS_ACCOUNT_ID"]:
        sys.exit(f"✗ profile is account {account}, environment expects {env['AWS_ACCOUNT_ID']}")

    outputs = {
        o["OutputKey"]: o["OutputValue"]
        for o in session.client("cloudformation").describe_stacks(StackName=env["STACK"])[
            "Stacks"
        ][0]["Outputs"]
    }
    staff_pool, portal_pool = outputs["UserPoolId"], outputs["PortalUserPoolId"]
    idp = session.client("cognito-idp")
    dash = Http(f"https://{env['DOMAIN_NAME']}")
    portal = Http(f"https://portal.{env['DOMAIN_NAME']}")
    s = Smoke()

    tag = secrets.token_hex(4)
    staff_email = f"smoke-staff-{tag}@example.com"
    customer_email = f"smoke-customer-{tag}@example.com"
    staff_pw, temp_pw, new_pw = random_password(), random_password(), random_password()
    created_staff = False
    invited_user = None  # (org_id, user_id, original local_email)
    customer_sub = None

    try:
        print(f"→ environment {args.env}: {dash.base} / {portal.base}")

        # ── host split, no credentials ────────────────────────────────
        print("Host split")
        s.check("portal host serves the portal SPA",
                b"AMS Customer Portal" in fetch(portal.base + "/login"))
        s.check("dashboard host serves the dashboard SPA",
                b"AMS Customer Portal" not in fetch(dash.base + "/login"))
        s.check("staff API absent on portal host", portal.call("GET", "/api/organizations/")[0] == 404)
        s.check("Django admin absent on portal host", portal.call("GET", "/admin/login/")[0] == 404)
        s.check("portal API absent on dashboard host", dash.call("GET", "/api/portal/me")[0] == 404)
        s.check("portal API requires a token", portal.call("GET", "/api/portal/me")[0] in (401, 403))
        st, body = portal.call("POST", "/api/portal/auth/login",
                               body={"email": f"nobody-{tag}@example.com", "password": "x"})
        s.check("unknown user gets a generic 401",
                st == 401 and body == {"detail": "Incorrect email or password."}, f"{st} {body}")

        # ── throwaway staff admin ─────────────────────────────────────
        print("Staff side")
        idp.admin_create_user(
            UserPoolId=staff_pool, Username=staff_email, MessageAction="SUPPRESS",
            UserAttributes=[{"Name": "email", "Value": staff_email},
                            {"Name": "email_verified", "Value": "true"}],
        )
        created_staff = True
        idp.admin_set_user_password(UserPoolId=staff_pool, Username=staff_email,
                                    Password=staff_pw, Permanent=True)
        idp.admin_add_user_to_group(UserPoolId=staff_pool, Username=staff_email, GroupName="admin")
        st, body = dash.call("POST", "/api/auth/login",
                             body={"username": staff_email, "password": staff_pw})
        if not s.check("staff admin signs in", st == 200 and "id_token" in (body or {}), f"{st}"):
            return 1
        staff_token = body["id_token"]

        st, orgs = dash.call("GET", "/api/organizations/", token=staff_token)
        orgs = [o for o in (orgs or {}).get("results", []) if o["jira_org_id"].startswith("synthetic-")]
        if not s.check("synthetic organizations are present", st == 200 and len(orgs) >= 2):
            return 1
        org, other_org = orgs[0], orgs[1]

        st, users = dash.call("GET", f"/api/organizations/{org['id']}/users/", token=staff_token)
        candidates = [u for u in users["results"] if u["portal_account"] is None]
        if not s.check("an uninvited synthetic user exists", bool(candidates)):
            return 1
        user = candidates[0]
        base = f"/api/organizations/{org['id']}/users/{user['id']}"

        # Point the synthetic user at the throwaway address, then invite.
        dash.call("PATCH", base + "/", token=staff_token, body={"local_email": customer_email})
        invited_user = (org["id"], user["id"], user["local_email"])
        st, body = dash.call("POST", base + "/portal-invite/", token=staff_token)
        s.check("invite succeeds", st == 200 and body["portal_account"]["status"] == "invited",
                f"{st} {body}")
        st, body = dash.call("POST", base + "/portal-invite/", token=staff_token)
        s.check("second invite is refused (409)", st == 409, f"{st}")

        # We cannot read the invitation email, so set a known temporary
        # password; the user is still in FORCE_CHANGE_PASSWORD.
        idp.admin_set_user_password(UserPoolId=portal_pool, Username=customer_email,
                                    Password=temp_pw, Permanent=False)
        customer_sub = next(
            a["Value"] for a in idp.admin_get_user(
                UserPoolId=portal_pool, Username=customer_email)["UserAttributes"]
            if a["Name"] == "sub")

        # ── first sign-in ─────────────────────────────────────────────
        print("Customer first sign-in")
        st, step = portal.call("POST", "/api/portal/auth/login",
                               body={"email": customer_email, "password": temp_pw})
        s.check("temporary password → NEW_PASSWORD_REQUIRED",
                st == 200 and step.get("challenge") == "NEW_PASSWORD_REQUIRED", f"{st} {step}")
        st, step = portal.call("POST", "/api/portal/auth/new-password", body={
            "session": step["session"], "username": step["username"],
            "email": customer_email, "new_password": new_pw})
        s.check("new password → MFA_SETUP with a secret",
                st == 200 and step.get("challenge") == "MFA_SETUP" and step.get("secret_code")
                and step.get("otpauth_uri", "").startswith("otpauth://totp/"), f"{st}")
        secret = step["secret_code"]
        st, bad = portal.call("POST", "/api/portal/auth/mfa/setup", body={
            "session": step["session"], "username": step["username"], "code": "000000"})
        s.check("wrong enrolment code is refused", st == 400 and "id_token" not in (bad or {}), f"{st}")
        # A failed verify consumes the session: begin again as the user would.
        st, step = portal.call("POST", "/api/portal/auth/login",
                               body={"email": customer_email, "password": new_pw})
        s.check("sign-in still demands MFA setup",
                st == 200 and step.get("challenge") == "MFA_SETUP", f"{st} {step}")
        secret = step["secret_code"]
        st, tokens = portal.call("POST", "/api/portal/auth/mfa/setup", body={
            "session": step["session"], "username": step["username"], "code": totp(secret)})
        if not s.check("correct code → tokens", st == 200 and "id_token" in (tokens or {}),
                       f"{st} {tokens}"):
            return 1
        cust_token = tokens["id_token"]

        # ── scope ─────────────────────────────────────────────────────
        print("Tenant scope")
        st, me = portal.call("GET", "/api/portal/me", token=cust_token)
        s.check("me → own organization",
                st == 200 and me["organization"]["id"] == org["id"] and me["email"] == customer_email,
                f"{st} {me}")
        st, home = portal.call("GET", f"/api/portal/home?organization={other_org['id']}",
                               token=cust_token)
        s.check("home ignores a supplied organization id",
                st == 200 and home["organization"]["id"] == org["id"], f"{st}")
        st, users = dash.call("GET", f"/api/organizations/{org['id']}/users/", token=staff_token)
        mine = next(u for u in users["results"] if u["id"] == user["id"])
        s.check("dashboard shows the account as active",
                mine["portal_account"]["status"] == "active")

        print("Pool separation")
        for path in ("/api/organizations/", f"/api/organizations/{org['id']}/users/",
                     f"/api/organizations/{other_org['id']}/", "/api/staff/", "/api/me/"):
            s.check(f"customer token refused: {path.split('/')[2]} …",
                    dash.call("GET", path, token=cust_token)[0] == 401)
        s.check("customer token cannot invite",
                dash.call("POST", base + "/portal-resend/", token=cust_token)[0] == 401)
        s.check("staff token refused by portal API",
                portal.call("GET", "/api/portal/me", token=staff_token)[0] == 401)
        s.check("access token refused by portal API",
                portal.call("GET", "/api/portal/me", token=tokens["access_token"])[0] == 401)

        # ── returning sign-in ─────────────────────────────────────────
        print("Returning sign-in")
        st, step = portal.call("POST", "/api/portal/auth/login",
                               body={"email": customer_email, "password": new_pw})
        s.check("password alone is not enough (SOFTWARE_TOKEN_MFA)",
                st == 200 and step.get("challenge") == "SOFTWARE_TOKEN_MFA"
                and "id_token" not in step, f"{st} {step}")
        # Cognito refuses to accept the same TOTP code twice; wait for the next step.
        wait = 30 - (time.time() % 30) + 1
        print(f"    (waiting {wait:.0f}s for the next TOTP window)")
        time.sleep(wait)
        st, tokens2 = portal.call("POST", "/api/portal/auth/mfa/verify", body={
            "session": step["session"], "username": step["username"], "code": totp(secret)})
        s.check("TOTP code → tokens", st == 200 and "id_token" in (tokens2 or {}), f"{st} {tokens2}")
        st, refreshed = portal.call("POST", "/api/portal/auth/refresh",
                                    body={"refresh_token": tokens["refresh_token"]})
        s.check("refresh token mints a new id token", st == 200 and "id_token" in (refreshed or {}))

        # ── revocation ────────────────────────────────────────────────
        print("Revocation")
        st, body = dash.call("POST", base + "/portal-disable/", token=staff_token)
        s.check("disable succeeds", st == 200 and body["portal_account"]["status"] == "disabled")
        s.check("already-issued token is refused immediately",
                portal.call("GET", "/api/portal/me", token=cust_token)[0] == 401)
        st, _ = portal.call("POST", "/api/portal/auth/refresh",
                            body={"refresh_token": tokens["refresh_token"]})
        s.check("refresh token no longer works", st in (401, 403), f"{st}")
        st, _ = portal.call("POST", "/api/portal/auth/login",
                            body={"email": customer_email, "password": new_pw})
        s.check("disabled user cannot sign in", st == 401, f"{st}")

    finally:
        print("Cleanup")
        if invited_user:
            org_id, user_id, original = invited_user
            try:
                # Restore the synthetic user's email override. The PortalAccount
                # row stays (disabled) — see the note printed below.
                st, body = dash.call("POST", "/api/auth/login",
                                     body={"username": staff_email, "password": staff_pw})
                if st == 200:
                    dash.call("PATCH", f"/api/organizations/{org_id}/users/{user_id}/",
                              token=body["id_token"], body={"local_email": original})
            except Exception as e:  # noqa: BLE001
                print(f"  ! could not restore the synthetic user's email: {e}")
        for pool, username, label in ((portal_pool, customer_email, "customer"),
                                      (staff_pool, staff_email, "staff")):
            if label == "staff" and not created_staff:
                continue
            try:
                idp.admin_delete_user(UserPoolId=pool, Username=username)
                print(f"  ✓ deleted throwaway {label} Cognito user")
            except idp.exceptions.UserNotFoundException:
                pass
            except Exception as e:  # noqa: BLE001
                print(f"  ! could not delete {label} user {username}: {e}")
        if customer_sub:
            print("  · a disabled PortalAccount row for the throwaway customer remains;")
            print("    remove it with:  infra/scripts/run-task.sh --env "
                  f"{args.env} portal_prune_smoke")

    print(f"\n{s.checks - s.failures}/{s.checks} checks passed")
    return 1 if s.failures else 0


if __name__ == "__main__":
    sys.exit(main())
