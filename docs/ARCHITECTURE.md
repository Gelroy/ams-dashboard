# AMS Dashboard — Architecture & Operations Reference

> **Scope:** Comprehensive reference for the AMS Dashboard system as deployed to AWS account `721082559106` in `us-west-2`. Covers AWS infrastructure, application code (Django backend + React frontend), user-facing behavior, and day-to-day operations.
>
> **Accuracy note:** AWS sections describe the live deployment. Code sections describe the code on `main` plus the `cost-optimize-tier1` branch (login flow + cost optimizations + Dockerfile fix). UI walkthroughs are based on code inspection — for the SPA features not yet exercised in production, treat the descriptions as "what the code says happens" rather than "what users have verified."
>
> **Audience:** Engineers and operators picking the project up. Assumes general comfort with AWS, Django, and React but does not require prior project knowledge.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [AWS Architecture](#2-aws-architecture)
3. [Topology & Request Flow](#3-topology--request-flow)
4. [Backend Code Reference (Django)](#4-backend-code-reference-django)
5. [Frontend Code Reference (React)](#5-frontend-code-reference-react)
6. [Infrastructure-as-Code (CDK)](#6-infrastructure-as-code-cdk)
7. [User Interface Walkthroughs](#7-user-interface-walkthroughs)
8. [Operations Runbook](#8-operations-runbook)
9. [Security](#9-security)
10. [Cost](#10-cost)
11. [Known Gaps & Future Work](#11-known-gaps--future-work)
12. [Appendices](#12-appendices)

---

## 1. Executive Summary

The **AMS Dashboard** is an internal web application for the IMT AMS (Application Managed Services) support team. It centralizes per-customer operational data: organization profiles, environments and servers, software inventory and version pinning, patch execution workflows, analytics captures, scheduled activities, and a unified "critical events" calendar. Customer organizations and ticket counts are synced from JIRA Service Management (`infomagnetics.atlassian.net`).

### Architectural choices

- **Single Docker image** runs the Django API, serves the React SPA, runs Django Admin, and is also re-used by the JIRA sync worker tasks. One artifact, four roles.
- **AWS Fargate** for compute — no servers to patch, scales horizontally on demand.
- **Aurora PostgreSQL Serverless v2** for storage — auto-scales between 0.5–2 ACU, minimal idle cost.
- **AWS Cognito User Pool** for identity — JWT-based stateless auth.
- **AWS CDK (Python)** defines everything — one `cdk deploy` provisions or updates the whole stack.
- **Soft delete everywhere** in the data model — `deleted_at` timestamp preserves history rather than dropping rows.

### Current deployment state (snapshot 2026-06-03)

| Property | Value |
|---|---|
| AWS Account | `721082559106` (IMT-Support) |
| Region | `us-west-2` |
| VPC | `vpc-04b75b92656837be8` (CDK-created, 2 AZs, public + private-with-egress subnets, no NAT) |
| ALB | `internet-facing`, HTTP only (HTTPS pending ACM cert + domain) |
| ALB DNS | `AmsDas-ApiSe-Ve9dUATmyXRB-7966907.us-west-2.elb.amazonaws.com` |
| Target domain | `ams-dashboard.infomagnetics.com` (pending DNS) |
| Aurora cluster | `amsdashboardstack-db5d02a0a9-smiqefm0qfai`, Postgres 16.11, SLv2 0.5–2 ACU |
| Aurora protections | `deletion_protection=true`, 7-day automated retention, plus the manual snapshot `ams-manual-2026-06-03-data-entry` |
| Cognito User Pool | `us-west-2_Bao82CnNc` |
| Cognito App Client | `42cotc6iun8ttt8sea4mkfp2h6` |
| Cognito Groups | `admin` (full read/write) + `viewer` (read-only stakeholders, currently empty); see §4.4.3 |
| ECS Cluster | `AmsDashboardStack-ClusterEB0386A7-D1161Vswl3Iu` |
| API Fargate Service | 1× task, 256 CPU / 512 MiB, in public subnet with `AssignPublicIp=ENABLED` |
| Scheduled tasks | JiraSyncOrgs (6h), JiraSyncUsers (6h), JiraSyncTickets (30 min) |
| Bastion EC2 | `i-08bd75fe381f36674` (t4g.nano) — SSM-managed, no inbound SG rules |
| ACM cert (pending) | `arn:aws:acm:us-west-2:721082559106:certificate/317ed450-7572-4d19-936f-2975c1826b35` |
| **Approx monthly cost** | **~$85–90/mo** with current sizing |

The ALB DNS will change whenever its `public_load_balancer` property is toggled or the ACM cert is finally wired up. The previous DNS values (`amsdas-apise-lgncaonjexh2-…`, `internal-AmsDas-ApiSe-FLsYDPfTrT41-…`) are dead — bookmarks should point at the value above until a real domain is in front.

### Repo layout

```
AMS_Dashboard/
├── api/            # Django 5 + DRF backend
├── web/            # React + TypeScript + Vite frontend
├── infra/          # AWS CDK (Python) stack
├── db/             # Reference schema dump (not source of truth — Django migrations are)
├── docs/           # This file + DEPLOY.md + DEPLOY_TROUBLESHOOTING.md
├── Dockerfile      # Multi-stage build (Vite bundle → Django image)
└── docker-compose.yml  # Local Postgres for development only
```

---

## 2. AWS Architecture

### 2.1 Component inventory

Every AWS resource currently provisioned by the stack, grouped by layer.

#### Networking

| Resource | Resource ID / Name | Purpose |
|---|---|---|
| VPC | `vpc-04b75b92656837be8` | Network boundary for all workloads |
| Public subnets (2) | `subnet-0cf412c5862a49750`, `subnet-02f5abcec1a1096fd` | Fargate task placement (no NAT, public IPs for egress); ALB |
| Private-with-egress subnets (2) | (paired, one per AZ) | Aurora cluster, internal ALB (currently unused while ALB is public) |
| IGW | (CDK-generated) | Public subnet internet egress |
| Route tables | (CDK-generated) | Per-subnet routing |
| ALB security group | (CDK-generated) | Inbound 80/443 from 0.0.0.0/0; outbound to task SG |
| API task SG | `sg-031f0db248aab5873` | Inbound from ALB SG only on container port 8000; outbound 0.0.0.0/0 |
| Aurora DB SG | (CDK-generated, named `AmsDashboardStack-DbSg…`) | Inbound on 5432 from API task SG only; outbound disabled |
| Bastion SG | `sg-0b2a8bb3005f31146` | No inbound; outbound 0.0.0.0/0 (for SSM agent + tunnel egress) |

**Why no NAT gateway?** Fargate tasks are placed in public subnets with `assignPublicIp=ENABLED`. They reach the internet (ECR, Secrets Manager, Cognito, Atlassian) via the IGW directly. The task security group restricts *inbound* to the ALB SG, so even though tasks have public IPs they're not reachable from the internet. Saves ~$33/mo vs running a NAT gateway.

#### Compute

| Resource | Resource ID / Name | Purpose |
|---|---|---|
| ECS Cluster | `AmsDashboardStack-ClusterEB0386A7-D1161Vswl3Iu` | Logical Fargate cluster, Container Insights v2 enabled |
| API Service | `AmsDashboardStack-ApiService199661B5-UCTedToL7loE` | Long-running Fargate service behind the ALB |
| API Task Definition | `AmsDashboardStackApiServiceTaskDef3EF0DC00:N` | 256 CPU / 512 MiB, image from ECR |
| Migration Task Def | `AmsDashboardStackMigrationTaskA104F64B:N` | Run-once-per-deploy Django migrate |
| JiraSyncOrgs Task Def | `AmsDashboardStackJiraSyncOrgsTask4ABF20A3:N` | Pulls organizations from JSM |
| JiraSyncUsers Task Def | `AmsDashboardStackJiraSyncUsersTask97473CBE:N` | Pulls per-org users from JSM |
| JiraSyncTickets Task Def | `AmsDashboardStackJiraSyncTicketsTask9E99637D:N` | Counts open tickets per org |
| EventBridge Rules (3) | JiraSyncOrgs/Users (rate 6h), JiraSyncTickets (rate 30min) | Triggers scheduled syncs |
| Bastion EC2 | `i-08bd75fe381f36674` (t4g.nano, Amazon Linux 2023 arm64) | SSM-managed jump host for port-forwarding |

#### Storage

| Resource | Resource ID / Name | Purpose |
|---|---|---|
| Aurora Cluster | `amsdashboardstack-db5d02a0a9-smiqefm0qfai` | Postgres 16.4, Serverless v2 (0.5–2 ACU) |
| Aurora Writer instance | `amsdashboardstack-db5d02a0a9-…-writer` | Single writer, multi-AZ-aware |
| Aurora secret | `AmsDashboardStackDbSecret1F-KEOtKLeuMPbQ-wlaEkM` (Secrets Manager) | Auto-generated master creds (`ams` user) |
| Django SECRET_KEY secret | `DjangoSecretKey0A000B3C-z2Au0NDSvzXo-…` | Auto-generated 64-char random string |
| JIRA credentials secret | `JiraServiceAccount780CFC76-nzmE3kkDgSlw-…` | Holds `JIRA_URL`, `JIRA_EMAIL`, `JIRA_TOKEN` (admin-populated) |
| ECR repository | `cdk-amsdash01-container-assets-721082559106-us-west-2` | Stores the multi-stage Docker image |
| S3 staging bucket | `cdk-amsdash01-assets-721082559106-us-west-2` | CDK uploads CloudFormation templates + Docker context |

#### Identity & Access

| Resource | Resource ID / Name | Purpose |
|---|---|---|
| Cognito User Pool | `us-west-2_Bao82CnNc` (`ams-dashboard`) | Holds team members' identities |
| Cognito App Client | `42cotc6iun8ttt8sea4mkfp2h6` | `USER_PASSWORD_AUTH` + authorization-code-grant configured |
| API task execution role | `AmsDashboardStack-ApiServiceTaskDefExecutionRole…` | ECR pull + secret reads + log writes |
| API task role | `AmsDashboardStack-ApiServiceTaskDefTaskRole…` | App's runtime AWS permissions (currently minimal) |
| Migration task exec role | `AmsDashboardStack-MigrationTaskExecutionRole…` | Same as API exec role, scoped to migration secrets |
| Sync task exec roles | (one per: orgs/users/tickets) | Same shape |
| Bastion IAM role | `ams-bastion-role` | `AmazonSSMManagedInstanceCore` for Session Manager |
| Bastion instance profile | `ams-bastion-profile` | Attaches role to EC2 |
| CDK bootstrap roles (5) | `cdk-amsdash01-{cfn-exec, deploy, file-publishing, image-publishing, lookup}-role-…` | Used by CDK CLI for deploys |

#### Observability

| Resource | Name | Purpose |
|---|---|---|
| CloudWatch Log Group | `/ams-dashboard/api` (`RetentionDays.TWO_WEEKS`, RemovalPolicy.RETAIN) | API + migration container stdout |
| CloudWatch Log Group | `/ams-dashboard/jira-sync` (same retention/policy) | Sync worker stdout |
| CloudWatch Log Group | `/aws/ecs/containerinsights/…/performance` | ECS Container Insights v2 metrics |

#### Edge / Routing

| Resource | Name | Purpose |
|---|---|---|
| Application Load Balancer | (currently) `AmsDas-ApiSe-LgNCAonjExh2-1426856071…` | TLS termination (after cert lands) + HTTP→HTTPS redirect + traffic into Fargate |
| ALB Target Group | `AmsDas-ApiSe-IPZKNX2QJKEW/…` | Container port 8000 health-checked at `/health` |
| ALB Listener (HTTP) | port 80 | Currently serves traffic directly (no cert yet) |
| ALB Listener (HTTPS) | (pending) port 443 | Will be added when cert validates; HTTP→HTTPS redirect added at same time |
| ACM Certificate (pending) | `arn:aws:acm:…:certificate/317ed450-7572-4d19-936f-2975c1826b35` | Issued for `ams-dashboard.infomagnetics.com` |

#### CDK Toolkit (one-time per-account bootstrap)

| Resource | Name | Purpose |
|---|---|---|
| CFN Stack | `CDKToolkit` | Manages the bootstrap resources below |
| KMS Key + Alias | `alias/cdk-amsdash01-assets` | Encrypts staging bucket objects |
| SSM Parameter | `/cdk-bootstrap/amsdash01/version` | Bootstrap version marker |

### 2.2 Resource lifecycle policies

- **Aurora cluster:** `removalPolicy=SNAPSHOT` — `cdk destroy` takes a final snapshot before deletion. Also `deletion_protection=true` as of 2026-06-03: any `aws rds delete-db-cluster` call is refused at the API level until protection is explicitly disabled.
- **Aurora backups:** 7-day automated snapshot retention (configurable via `BackupProps`). Plus on-demand manual snapshots — currently `ams-manual-2026-06-03-data-entry` exists as a long-term restore point.
- **Cognito User Pool:** `removalPolicy=RETAIN` — `cdk destroy` leaves it intact (preserves user accounts and group membership).
- **CloudWatch Log Groups:** `removalPolicy=RETAIN` — survive stack rollbacks/destroys, so container stdout from failed deploys remains debuggable.
- **Everything else:** default (destroyed with the stack).

---

## 3. Topology & Request Flow

### 3.1 High-level topology

```
                                ┌───────────────────────────────────┐
                                │       AWS Account 721082559106     │
                                │              us-west-2             │
   ┌─────────────────┐          │                                    │
   │  Team member's  │          │  ┌─────────────────────────────┐  │
   │     browser     │ ───HTTPS─┼─►│   Application Load Balancer │  │
   │                 │ (port 443)│  │   (internet-facing, HTTPS)  │  │
   └─────────────────┘          │  └──────────────┬──────────────┘  │
                                │                 │                  │
   ┌─────────────────┐          │     ┌───────────▼────────────┐    │
   │ Atlassian       │          │     │   ECS Fargate Task     │    │
   │ JSM             │◄─────────┼─────│   - Django + Gunicorn   │    │
   │ infomagnetics   │ JIRA API │     │   - React SPA (static)  │    │
   │ .atlassian.net  │          │     │   container port 8000   │    │
   └─────────────────┘          │     └────┬─────────────┬──────┘    │
                                │          │             │           │
   ┌─────────────────┐          │          │             ▼           │
   │ AWS Cognito     │◄─────────┼──────────┘  ┌──────────────────┐  │
   │ User Pool       │ JWT/JWKS │             │ Aurora Postgres  │  │
   │ us-west-2_Bao82 │          │             │ Serverless v2    │  │
   └─────────────────┘          │             └──────────────────┘  │
                                │                                    │
                                │  ┌──────────────────────────────┐ │
                                │  │ Scheduled Fargate workers    │ │
                                │  │ (JiraSyncOrgs/Users/Tickets) │ │
                                │  └──────────────────────────────┘ │
                                │                                    │
                                │  ┌──────────────────────────────┐ │
                                │  │ Bastion EC2 (SSM port-fwd)   │ │
                                │  └──────────────────────────────┘ │
                                └────────────────────────────────────┘
```

### 3.2 Technology layers

| Layer | Technology | Purpose |
|---|---|---|
| Client | Browser (Chrome/Safari/Firefox), React 18+ SPA | UI rendering, client-side routing, fetch-based API calls |
| Edge | AWS Application Load Balancer | TLS termination, HTTP→HTTPS redirect, health checks, traffic routing |
| Application | Django 5 + DRF + Gunicorn, running on AWS Fargate | API endpoints, JWT validation, business logic, SPA static serving (via WhiteNoise) |
| Workers | Same Docker image, run as scheduled Fargate tasks via EventBridge | Periodic JIRA syncs (orgs/users every 6h, tickets every 30 min) |
| Data | Aurora PostgreSQL Serverless v2 | Source of truth for all customer + operational data |
| Identity | AWS Cognito User Pool | User accounts, password storage, JWT issuance, lockout policies |
| Secrets | AWS Secrets Manager | Aurora credentials, JIRA token, Django SECRET_KEY |
| Logging | AWS CloudWatch Logs | Container stdout, structured logging from Django |
| Container Storage | AWS ECR | Versioned Docker images, lifecycle-pruned |
| Infrastructure | AWS CDK (Python) | Declarative stack definition, one-shot deploys |

### 3.3 Request lifecycle: a logged-in API call

1. **Browser** sends `GET https://ams-dashboard.infomagnetics.com/api/organizations/` with header `Authorization: Bearer <id_token>` (token previously obtained via `/api/auth/login`).
2. **Route 53** resolves the domain → ALB.
3. **ALB** terminates TLS, looks up the target group, forwards plain HTTP to the Fargate task on port 8000. Sets `X-Forwarded-Proto: https` so Django can know.
4. **Gunicorn** (inside the container) hands the request to Django via WSGI.
5. **Django middleware chain** runs (security headers, sessions skipped, etc.). At the DRF view layer, **`CognitoJWTAuthentication`** runs:
   - Extracts the Bearer token
   - Fetches the user pool's JWKS (cached by `lru_cache`) from `https://cognito-idp.us-west-2.amazonaws.com/us-west-2_Bao82CnNc/.well-known/jwks.json`
   - Verifies signature (RS256), issuer, and audience (`COGNITO_APP_CLIENT_ID`)
   - Wraps claims in a `_CognitoUser` and attaches to `request.user`
6. **`IsAuthenticated`** permission check passes.
7. **`OrganizationViewSet.list()`** runs `Organization.objects.all().order_by(...)`, optionally applying the `OrganizationFilter` if query string includes `ams_level` or `q`.
8. **psycopg** connects to the Aurora writer endpoint using credentials injected from Secrets Manager (`DB_HOST`, `DB_USER`, `DB_PASSWORD`).
9. Result is serialized by `OrganizationSerializer` (including computed `sme_staff` and `needs_patching`), paginated to 50, returned as JSON.

### 3.4 Login flow

1. Browser POSTs `/api/auth/login` with `{username, password}` — **no** Authorization header (this endpoint is `@authentication_classes([])`).
2. Django view calls `boto3.client('cognito-idp').initiate_auth(AuthFlow='USER_PASSWORD_AUTH', ClientId=…, AuthParameters=…)`.
3. Cognito returns one of:
   - `AuthenticationResult` with `IdToken`, `AccessToken`, `RefreshToken` — Django returns these to the browser.
   - `ChallengeName=NEW_PASSWORD_REQUIRED` — Django returns `{challenge, session, username}` so the SPA can prompt for a new password and POST `/api/auth/challenge`.
4. Browser stores `id_token` in `sessionStorage` (see `web/src/auth.ts`).
5. All subsequent API requests attach `Authorization: Bearer <id_token>`.
6. When the access token expires (1 hour default), the next API call returns 401, the SPA clears the token and redirects to `/login`.

### 3.5 JIRA sync flow

1. EventBridge rule fires on schedule (every 30 min for tickets, every 6h for orgs and users).
2. ECS launches a Fargate task using the appropriate task definition (`JiraSyncOrgs`, etc.) — same image as the API, different `CMD` (`python manage.py sync_jira_orgs`, etc.).
3. The task pulls secrets from Secrets Manager (`JIRA_URL`, `JIRA_EMAIL`, `JIRA_TOKEN`, plus DB creds).
4. The management command instantiates `JiraClient` and calls the relevant JSM endpoint.
5. Results are upserted to Postgres in a single transaction. Orgs no longer in JIRA are soft-deleted (not hard-deleted).
6. Task exits 0; stdout flows to CloudWatch under `/ams-dashboard/jira-sync` with stream prefix `JiraSyncOrgs` / `JiraSyncUsers` / `JiraSyncTickets`.

---

## 4. Backend Code Reference (Django)

### 4.1 Project layout

```
api/
├── manage.py                         # Standard Django entrypoint
├── pyproject.toml                    # Dependencies + Ruff + pytest config
├── ams_dashboard/                    # Project config package
│   ├── settings.py                   # All Django settings
│   ├── urls.py                       # Top-level URL conf
│   ├── auth_cognito.py               # Cognito JWT validator (DRF auth class)
│   ├── auth_views.py                 # Custom login + new-password endpoints
│   ├── spa.py                        # SPA index.html fallback view
│   ├── wsgi.py / asgi.py             # Server entrypoints (only wsgi used in prod)
│   └── __init__.py
├── customers/                        # Organizations, users, environments, servers
├── software/                         # Software catalog (Software, Version, Release)
├── baskets/                          # Version pinning + server-basket assignment
├── patching/                         # Patch plans + executions + history
├── analytics/                        # Per-customer metric definitions + captures
├── staff/                            # Internal team + SME assignments
└── activities/                       # Calendar + critical events aggregation
```

### 4.2 Configuration (`api/ams_dashboard/settings.py`)

Key behaviors of the settings module:

- **Env loading:** uses `django-environ` with typed defaults. Reads from `BASE_DIR/.env` if present (dev), otherwise environment variables (prod, set by ECS from Secrets Manager).
- **Database:** preferred path is `DATABASE_URL` (used by local dev compose); production injects `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` separately and falls through to the `else` branch.
- **Static files:** WhiteNoise serves `/static/*` from `STATIC_ROOT`, which is populated at `collectstatic` time during the Docker build. The Vite-built React app lives in `BASE_DIR/web_build/` and is added to `STATICFILES_DIRS` so its hashed assets are served identically.
- **Production hardening (when `DEBUG=False`):**
  ```python
  SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
  SESSION_COOKIE_SECURE = True
  CSRF_COOKIE_SECURE = True
  SECURE_CONTENT_TYPE_NOSNIFF = True
  SECURE_REFERRER_POLICY = "same-origin"
  X_FRAME_OPTIONS = "DENY"
  ```
- **DRF auth strategy:** conditional on `AUTH_BYPASS`. Production (`AUTH_BYPASS=0`) uses `CognitoJWTAuthentication` + `IsAuthenticated`. Dev (`AUTH_BYPASS=1`) uses no auth class and `AllowAny`.

  ```python
  _auth_classes = (
      [] if AUTH_BYPASS else ["ams_dashboard.auth_cognito.CognitoJWTAuthentication"]
  )
  _permission_classes = (
      ["rest_framework.permissions.AllowAny"]
      if AUTH_BYPASS
      else ["rest_framework.permissions.IsAuthenticated"]
  )
  ```

### 4.3 URL routing (`api/ams_dashboard/urls.py`)

```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path("health", health),
    # Auth endpoints — public; they exchange creds for Cognito JWTs.
    path("api/auth/login", auth_login, name="auth-login"),
    path("api/auth/challenge", challenge_new_password, name="auth-challenge"),
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
```

The catch-all at the end is intentional — any URL that didn't match a specific route (e.g. `/customers/abc123` after a hard refresh in the SPA) gets served the SPA `index.html`, and React Router takes over once the page loads. A `health` endpoint at `/health` is exempt for ALB target group checks.

### 4.4 Authentication

#### 4.4.1 `auth_cognito.py` — JWT verifier

```python
@functools.lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    issuer = (
        f"https://cognito-idp.{settings.COGNITO_REGION}.amazonaws.com/"
        f"{settings.COGNITO_USER_POOL_ID}"
    )
    return jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json")


class CognitoJWTAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.lower().startswith("bearer "):
            return None
        token = header.split(" ", 1)[1].strip()
        try:
            signing_key = _jwks_client().get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token, signing_key, algorithms=["RS256"],
                issuer=_issuer(),
                audience=settings.COGNITO_APP_CLIENT_ID or None,
                options={"verify_aud": bool(settings.COGNITO_APP_CLIENT_ID)},
            )
        except jwt.PyJWTError as e:
            raise exceptions.AuthenticationFailed("Invalid or expired token") from e
        return (_CognitoUser(claims), token)
```

**Gotcha worth knowing:** the `aud` claim is only set on Cognito **id_tokens**, not on access_tokens. The SPA must send the id_token. Sending the access_token will fail verification because it has `client_id` instead of `aud`. The login views (next section) return both; the React `LoginPage` stores the id_token.

`_CognitoUser` also parses the `cognito:groups` claim and exposes a `.is_admin` property — driving the role gate (§4.4.3).

#### 4.4.2 `auth_views.py` — login & challenge

Three `@api_view` functions, all `authentication_classes=[]` and `permission_classes=[AllowAny]` so they can be called without an existing token — except `me` which uses `IsAuthenticated` so viewers can call it to discover their own role:

- `login(request)` — POSTs `{username, password}` to Cognito's `InitiateAuth` with `USER_PASSWORD_AUTH`. Returns `{id_token, access_token, refresh_token?, expires_in, token_type}` on success, or `{challenge, session, username}` if Cognito returns `NEW_PASSWORD_REQUIRED`. Maps Cognito error codes to clean HTTP responses (401 for bad creds, 403 for password-reset-required or unconfirmed users, 400 for everything else).
- `challenge_new_password(request)` — POSTs `{session, username, new_password}` to Cognito's `RespondToAuthChallenge`. Returns the same `AuthenticationResult` shape on success.
- `refresh(request)` — POSTs `{refresh_token}` to Cognito's `REFRESH_TOKEN_AUTH` flow. Powers the SPA's silent-refresh; bypasses re-login when a bearer call 401s mid-session.
- `me(request)` — `GET /api/me/`. Returns `{username, email, groups, is_admin}` from the JWT claims. The SPA fetches this on mount to decide whether to render the read-only banner.

All three Cognito-talking views use `boto3.client('cognito-idp', region_name=settings.COGNITO_REGION)`. `InitiateAuth` and `RespondToAuthChallenge` are **unauthenticated** Cognito operations (the user's password proves identity), so the task role does not need any `cognito-idp:*` IAM permissions.

#### 4.4.3 Role gate — `permissions.py` + Cognito groups

In-app roles are stored as Cognito User Pool groups, surfaced on the JWT's `cognito:groups` claim. The pool has two groups (created by CDK):

- `admin` (precedence 1) — full read/write. The AMS team lives here.
- `viewer` (precedence 10) — read-only. Intended for read-only stakeholders. Currently empty; behavior is the same as "no group at all" since the permission class only checks for `admin`.

The DRF permission class `IsAdminOrReadOnly` (in `ams_dashboard/permissions.py`) is wired as `DEFAULT_PERMISSION_CLASSES` when `AUTH_BYPASS=0`:

- `SAFE_METHODS` (GET/HEAD/OPTIONS) → any authenticated user passes.
- Writes (POST/PATCH/PUT/DELETE + custom `@action` writes) → require `admin` in `user.groups`; otherwise 403 with a clear message.

The dev path (`AUTH_BYPASS=1`) still uses `AllowAny` — no role gate in local Docker.

**Operationally:**
- Promote a user: `aws cognito-idp admin-add-user-to-group --user-pool-id us-west-2_Bao82CnNc --username <email> --group-name admin`.
- Group membership is baked into the id_token at issue time — a user must log out + back in for a newly added group to take effect.
- SPA renders an amber "Read-only access" banner at the top of every authenticated page when `me.is_admin === false`. Individual write buttons are NOT hidden in this phase; writes 403 from the backend and surface the error inline.

### 4.5 SPA fallback (`spa.py`)

```python
def spa_index(_request):
    index = Path(settings.WEB_BUILD_DIR) / "index.html"
    if not index.exists():
        raise Http404("SPA build not found at WEB_BUILD_DIR. …")
    response = HttpResponse(index.read_bytes(), content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response
```

Always returns `200 text/html` with `Cache-Control: no-cache, no-store, must-revalidate`. The HTML is tiny (~500 bytes) and references hash-named asset bundles via `<script>` and `<link>`, so the actual bundle URLs change every build — index.html must stay uncached so the browser sees the new hashes immediately after deploy.

### 4.6 Per-app reference

Each Django app is small and follows a consistent shape: `models.py`, `serializers.py`, `views.py`, `urls.py`, plus optional `signals.py`, `services.py`, `management/commands/`. Soft delete is implemented via the `SoftDeleteModel` abstract base in `customers/models.py` and reused (by import) across apps.

#### 4.6.1 `customers/` — Organizations, users, environments, servers

##### `customers/models.py`

Five concrete models, all inheriting from `SoftDeleteModel`:

- **`Organization`** (`db_table="organizations"`) — UUID PK. JIRA-synced (`jira_org_id`, `jira_name`, `jira_synced_at`). Local-only fields: `local_name` (display override), `ams_level` (Essential/Enhanced/Expert), `zabbix_status` (Good/Issue), `help_desk_phone`, `notes`. Ticket count rolled up from JIRA: `open_ticket_count`, `ticket_count_synced_at`, `last_ticket_sync_error`. Has a `display_name` property: `local_name or jira_name`. Unique constraint on `jira_org_id` scoped to `deleted_at IS NULL` so soft-deletes don't block re-sync.
- **`OrgDocument`** — Replaces the legacy single `connection_guide_url` field with a 1-to-many list of `(description, url, position)` rows per organization. Unique-per-org on description.
- **`OrgUser`** — Synced from JIRA (`jira_account_id`, `display_name`, `email`). Writable local fields: `role`, `alerts_enabled` (bool), `is_primary` (bool).
- **`Environment`** — `(organization, name, position)`. Default names: `["DEV", "TEST", "PROD"]` (constant `DEFAULT_ENVIRONMENT_NAMES`).
- **`Server`** — `(environment, name, notes, cert_expires_on)`. Indexed on `cert_expires_on` for the Critical Events calendar query.

Soft-delete pattern:

```python
class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)

class SoftDeleteModel(models.Model):
    deleted_at = models.DateTimeField(null=True, blank=True)
    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()
    class Meta:
        abstract = True
```

Every unique constraint that should be enforced *only on live rows* uses `condition=Q(deleted_at__isnull=True)` — this is critical, otherwise soft-deleting and re-creating an org with the same `jira_org_id` would crash.

##### `customers/signals.py`

`post_save` on `Organization` auto-creates the three `DEFAULT_ENVIRONMENT_NAMES` environments (DEV/TEST/PROD with `position=0,1,2`) the first time an organization is persisted.

##### `customers/views.py`

```python
class OrganizationFilter(filters.FilterSet):
    q = filters.CharFilter(method="filter_q")
    class Meta:
        model = Organization
        fields = ["ams_level"]
    def filter_q(self, queryset, name, value):
        return queryset.filter(Q(jira_name__icontains=value) | Q(local_name__icontains=value))


class OrganizationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                          mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """List, retrieve, and PATCH organizations. No create/delete — orgs come from JIRA."""
    serializer_class = OrganizationSerializer
    filterset_class = OrganizationFilter
    def get_queryset(self):
        return Organization.objects.all().order_by(Coalesce("local_name", "jira_name"))
```

Additional ViewSets in the file: `OrgUserViewSet` (read + PATCH role/alerts/is_primary), `EnvironmentViewSet` (CRUD with soft-delete), `OrgDocumentViewSet`, `ServerViewSet`. Nested routing scopes children to parent IDs.

##### `customers/jira_client.py`

`JiraClient` is a thin httpx wrapper over JSM's Service Desk API:

- HTTP Basic auth: `Authorization: Basic <base64(email:token)>`
- Header `X-ExperimentalApi: opt-in` is required for some JSM endpoints
- `fetch_all_organizations()` → paginates `/rest/servicedeskapi/organization` (50/page)
- `fetch_organization_users(jira_org_id)` → `/rest/servicedeskapi/organization/{id}/user`
- `fetch_open_ticket_count(jira_org_id)` → tries `/rest/api/3/search/approximate-count` (much faster), falls back to paginated `/rest/api/3/search/jql` with a safety cap on 404/410

JIRA URL is read from `settings.JIRA_URL`, populated by ECS from the JIRA secret in Secrets Manager.

##### `customers/management/commands/sync_jira_*.py`

Three commands invoked by the scheduled Fargate tasks:

- `sync_jira_orgs` — fetches all orgs from JIRA, upserts to `Organization` (by `jira_org_id`). Orgs not in the latest fetch are soft-deleted. Atomic transaction.
- `sync_jira_users` — for each org, fetches users from JIRA, upserts to `OrgUser`. Users no longer in the org are soft-deleted.
- `sync_jira_tickets` — for each org, fetches open ticket count, sets `Organization.open_ticket_count` and `ticket_count_synced_at`. On error, writes the message to `last_ticket_sync_error` so it surfaces in the UI.

#### 4.6.2 `software/` — Software catalog

Two-level hierarchy: `Software → SoftwareRelease`. The middle `SoftwareVersion` layer was squashed away in migration `software/0003+0004` (2026-06-03) — each `Software` row now carries its version label and lifecycle status directly. Multi-version Software rows were forked into one row per version at migration time (e.g. "Zabbix" with v4.2/v5.0/v7.4 became "Zabbix 4.2", "Zabbix 5.0", "Zabbix 7.4").

- **`Software`** — `(name, version, status, description)`. Unique on `name`. Lifecycle status ∈ {Latest, Supported, EOL}.
- **`SoftwareRelease`** — `(software FK, release_name, released_on, status, position)`. Unique on `(software, release_name)` and one-Latest-per-software.

The "at most one Latest sibling" rule is still enforced by `_demote_existing_latest()` in `views.py`, atomically demoting any prior Latest release when a new one is promoted.

Routes flattened with the middle layer gone:
- `/api/software/`
- `/api/software/{software_id}/releases/`

The auto-create-PatchExecution-on-new-Latest signal that used to live here was retired in the 2026-06-03 patching redesign — see §4.6.4. `software/services.py` and `software/signals.py` are now placeholder stubs with docstrings explaining the move.

#### 4.6.3 `baskets/` — Logical software groupings & server pinning

After the patching redesign, baskets serve a narrower role: they're a **logical bundle of softwares** that auto-populates a server's installed-software rows when assigned. They are no longer involved in patching automation.

Key models:
- `Basket(name, description)` — named group.
- `BasketSoftware(basket, software)` — which softwares the basket pins. `software_version` FK was dropped in baskets/0003 since `Software` is now a specific version.
- `ServerBasket(server, basket)` — many-to-many: which baskets a server is assigned to.
- `ServerInstalledSoftware(server, software, software_release, functionally_latest, recorded_at)` — what's actually running.
  - `functionally_latest` is a per-server override (added 2026-06-03): when true, this server's installed release is treated as Latest for needs-patching purposes, regardless of the catalog. Used when an interim release doesn't apply (e.g. UNIX-only release on a Windows customer). Sticky across catalog Latest changes; auto-resets when `finalize_execution` moves the server to the actual Latest.

`baskets/services.py`:
- `server_needs_patching(server)` → `"yes"` / `"no"` / `"unknown"`. Short-circuits to "no" when `functionally_latest` is set.
- `organization_needs_patching(org)` / `organization_patching_rollup(org)` — roll-up across servers.
- `copy_installed_software(source, dest)` — used by the Add Server "Include Existing Software?" flow.
- `copy_server_details_to_env_peers(source_server)` — used by the "Copy to Environment" button in expanded Server Details; replaces every peer's notes + basket assignments + installed software (including `functionally_latest`).

`baskets/signals.py` auto-creates `ServerInstalledSoftware` rows when a basket is assigned to a server or a new software is added to an assigned basket — defaulting the installed release to the basket's Software's current Latest.

#### 4.6.4 `patching/` — Software-centric patch plans & executions

The patching domain was substantially redesigned 2026-06-03 (migration `patching/0004`). Patching is now mapped to **Software directly**, not Baskets. Plans own their own steps (groups become one-shot import templates), and execution creation is **manually triggered** from the SPA — the auto-create-on-new-Latest signal is gone.

Templates (reusable):
- **`PatchGroup`** + **`PatchGroupStep`** — reusable runbook fragments. `PatchGroup` has an M2M to `Software`. Steps have a `not_timed` bool for human-judgment checkpoints (no elapsed-time accumulation, Done-at-any-time).

Plans (the document the team executes against):
- **`PatchPlan`** — has an independent M2M to `Software` (the softwares this plan is responsible for) and owns its steps directly. `PatchPlanGroup` was deleted: importing a group into a plan copies the group's steps into `PatchPlanStep` and unions its softwares into the plan's M2M; the plan never refers back to the group.
- **`PatchPlanStep`** — plan-owned step. Same fields as `PatchGroupStep` (description, est_time, per_server, not_timed). No unique constraint on (plan, step_num) — inline renumbering produces transient duplicates which the UX needs to tolerate; display ordering breaks ties on `id`.

Executions:
- **`PatchExecution`** — one execution per `(organization, environment, patch_plan)`. Snapshot M2M `softwares` (frozen at create time). Unique-active constraint enforces at most one active execution per `(org, env, plan)`.
- **`PatchExecutionStep`** — snapshotted from `PatchPlanStep` at create time. Carries `not_timed`. Renumbered sequentially from 1 (so executions never see duplicate step_num even though plans can).
- **`PatchExecutionAbort`** — unchanged.
- **`PatchHistory`** — unchanged.

`patching/services.py`:
- `snapshot_steps_from_plan(execution, plan)` — reads `plan.plan_steps` directly (no group walk).
- `mark_step_done(execution, step)` — special-cases `not_timed` steps (flip done flag, skip timing bookkeeping; for timed steps walks backward over not_timed siblings when seeding `started_at`).
- `finalize_execution(execution)` — walks `execution.softwares` (the snapshot) to update server installed releases. Resets `ServerInstalledSoftware.functionally_latest` on each affected row.
- `check_for_needed_executions()` — **new manual trigger**, called from `POST /api/patch-executions/check/`. Walks AMS-contracted orgs × envs, finds (server, software) pairs where installed_release ≠ Latest AND NOT `functionally_latest`, then creates one `PatchExecution` per `(env, plan)` for every plan covering any stale software. Dedupes; skips when an active execution already exists.
- `resync_pristine_executions(plan)` — when plan steps change, re-snapshots active executions that haven't started running. Softwares are NOT re-snapped (frozen at creation).
- `abort_execution`, `reset_execution`, `format_elapsed` — unchanged.

`patching/signals.py` watches `PatchPlanStep` post_save/post_delete now (not `PatchGroupStep` / `PatchPlanGroup`) — plan-step edits ripple to pristine executions; group-step edits don't.

#### 4.6.5 `analytics/` — Per-customer metric captures

Three models:

- **`AnalyticDefinition`** — `(name, frequency, scope)`. Frequency ∈ {Daily, Weekly, Monthly, Quarterly, Yearly}. Scope ∈ {environment, server}.
- **`CustomerAnalytic`** — instance of a definition for `(organization, environment, optional server, definition)`. Constraint enforces scope (`scope=server` requires `server IS NOT NULL`).
- **`CustomerAnalyticHistory`** — immutable captures `(customer_analytic, captured_at, value: Decimal, description)`. Indexed on `(customer_analytic, -captured_at)`.

Routes:
- `/api/analytic-definitions/` (full CRUD)
- `/api/customer-analytics/` (full CRUD; filterable by `organization`, `environment`)
- `/api/customer-analytics/{id}/history/` (nested; POST appends captures)

#### 4.6.6 `staff/` — Internal team

- **`Staff`** — `(name, email, phone, cognito_sub)`. `cognito_sub` is nullable today but designed to link a staff row to its Cognito identity once SSO matures.
- **`StaffSmeOrganization`** — explicit M2M through-model linking `Staff` ↔ `Organization` for "this person is the SME for that customer." Used by the `OrganizationSerializer.sme_staff` computed field.

Single endpoint: `/api/staff/` with full CRUD plus a `@action set_sme_organizations` for atomically replacing a staff member's SME assignments.

#### 4.6.7 `activities/` — Calendar & critical events

- **`Activity`** — `(name, scheduled_at, organization?, assigned_staff?, type, priority, status, duration, notes, completed_at?)`.
- **`CriticalCalendarView`** — not a ViewSet; a plain APIView at `/api/critical/?weeks=N` that aggregates three streams into a single calendar payload:
  - upcoming `Activity` rows (`status="scheduled"`, `scheduled_at` within window)
  - `Server.cert_expires_on` dates within window
  - recent `PatchHistory` rows
  
  Returns `{start, end, events: [{date, time?, kind, label, organization_id?, organization_name?, ...}]}`.

`weeks` query param defaults to 6 and is capped at 12 server-side.

---

## 5. Frontend Code Reference (React)

### 5.1 Build pipeline

- **Vite** with React + TypeScript template, `base="/static/"` for production
- `npm run build` outputs to `web/dist/` (which the Dockerfile copies to `BASE_DIR/web_build/` so Django + WhiteNoise can serve it)
- `npm run dev` for local development; Vite dev server on `http://localhost:5173`, proxied to Django on `http://localhost:8000`

### 5.2 Source layout

```
web/src/
├── main.tsx                # Vite entry; wraps App in <BrowserRouter>
├── App.tsx                 # Routes + RequireAuth guard + AppLayout
├── App.css, index.css      # Global styles
├── api.ts                  # Centralized fetch wrapper + endpoint helpers
├── auth.ts                 # Token storage + redirect helper
├── types.ts                # All shared TypeScript interfaces / unions
├── components/
│   ├── SidebarNav.tsx
│   ├── CustomerAnalyticsSection.tsx
│   └── CustomerSystemsSection.tsx
└── pages/
    ├── LoginPage.tsx
    ├── NewPasswordPage.tsx
    ├── CustomersPage.tsx
    ├── CustomerDetailPage.tsx
    ├── CriticalPage.tsx
    ├── ActivitiesPage.tsx
    ├── AnalyticsPage.tsx
    ├── BasketsPage.tsx
    ├── PatchExecutionPage.tsx
    ├── StaffPage.tsx
    ├── VersionsPage.tsx
    └── PlaceholderPage.tsx
```

### 5.3 Auth handling

`web/src/auth.ts` is intentionally tiny — three exported functions:

```ts
const TOKEN_KEY = 'ams-dashboard-access-token'
let cachedToken: string | null = sessionStorage.getItem(TOKEN_KEY)

export function getToken(): string | null { return cachedToken }
export function setToken(token: string | null): void {
  cachedToken = token
  if (token) sessionStorage.setItem(TOKEN_KEY, token)
  else sessionStorage.removeItem(TOKEN_KEY)
}
export function clearTokenAndRedirectToLogin(): void {
  setToken(null)
  if (window.location.pathname !== '/login') window.location.replace('/login')
}
```

The token (id_token from Cognito, see §4.4.1) is held in `sessionStorage` — cleared when the browser tab/window closes, persisted across page refreshes within a session. **No refresh token handling**: when the token expires (Cognito default 1h), the next API call returns 401, `api.ts` calls `clearTokenAndRedirectToLogin()`, and the user re-authenticates.

### 5.4 API client (`api.ts`)

A single `request<T>(path, init?)` function wraps `fetch` and handles:
- Attaches `Authorization: Bearer <token>` automatically
- Attaches `Content-Type: application/json` and `Accept: application/json` defaults
- Treats HTTP 401 on **non-auth** paths as "session lost" → clears token and redirects
- Throws on non-OK responses with a string detail extracted from the response body

The rest of the file is endpoint helpers (one or two per resource) — e.g. `listOrganizations`, `getOrganization`, `updateOrganization`, `listSoftware`, `createBasket`, `addBasketSoftware`, `markStepDone`, `getCriticalCalendar`, etc. All return strongly-typed promises against the interfaces in `types.ts`.

The login/challenge endpoints are exempted from the 401-redirect logic:

```ts
const AUTH_PATHS = new Set(['/auth/login', '/auth/challenge'])
if (r.status === 401 && !AUTH_PATHS.has(path)) {
  clearTokenAndRedirectToLogin()
  throw new Error('Unauthorized')
}
```

This is necessary because a bad-password attempt also returns 401; if we bounced the user to `/login`, they'd never see the "wrong password" error on `/login` itself.

### 5.5 Routing & layout

`App.tsx` declares public auth routes (`/login`, `/password-change`) outside the sidebar layout, and wraps everything else in a `RequireAuth` guard:

```tsx
function RequireAuth({ children }: { children: ReactNode }) {
  if (!getToken()) return <Navigate to="/login" replace />
  return <>{children}</>
}

function AppLayout() {
  return (
    <div className="shell">
      <SidebarNav />
      <main className="content"><Outlet /></main>
    </div>
  )
}
```

Authenticated routes (mounted under `AppLayout`):
- `/` → redirect to `/customers`
- `/critical`, `/activities`, `/customers`, `/customers/:id`, `/versions`, `/baskets`, `/patch-execution`, `/analytics`, `/staff`, `/settings`
- `/*` → `PlaceholderPage`

### 5.6 Component overview

- **`SidebarNav`** — fixed left rail. Four collapsible sections (Work, Data, Operations, Config) with `react-router-dom`'s `<NavLink>` highlighting the active route.
- **`CustomerSystemsSection`** — embedded in `CustomerDetailPage`. Renders the per-customer environments / servers / baskets / installed-software tree with inline editing. ~300 lines of cascading-select forms.
- **`CustomerAnalyticsSection`** — also embedded in `CustomerDetailPage`. Lists `CustomerAnalytic` rows and their capture history, with forms to record new captures or define new metrics.

---

## 6. Infrastructure-as-Code (CDK)

### 6.1 Project layout

```
infra/
├── app.py                            # CDK entrypoint
├── cdk.json                          # Context + feature flags
├── bootstrap-template.yaml           # Pre-generated bootstrap CFN (for CLI-only admins)
├── requirements.txt                  # aws-cdk-lib, etc.
├── infra/
│   └── infra_stack.py                # The single AmsDashboardStack class
├── scripts/
│   ├── admin-bootstrap-cli.sh        # Bootstrap via CFN, no Node needed
│   ├── admin-bootstrap-raw-cli.sh    # Bootstrap with raw aws-cli calls (no CFN)
│   └── grant-cdk-deploy-perms.sh     # IAM policy for the routine-deploy principal
└── tests/unit/test_infra_stack.py    # CDK assertions
```

### 6.2 `infra/app.py`

The CDK App entrypoint. Reads `account` and `region` from CDK context or `CDK_DEFAULT_*` env vars (both required), then synthesizes `AmsDashboardStack` *only if* `vpc_id` or `create_vpc=true` context is set. This guard lets `cdk bootstrap` run cleanly (no stack synth needed) without spurious lookups.

### 6.3 `infra/infra/infra_stack.py` — `AmsDashboardStack`

A single class that wires up the entire application. Major sections, in order:

1. **Synthesizer** — sets a custom bootstrap qualifier (`amsdash01`) so resources are named `cdk-amsdash01-*`. Lets the project coexist with other CDK apps in the same account that use the default qualifier.
2. **Context parsing** — reads `vpc_id` / `create_vpc` / `acm_cert_arn` / `public_alb` / `nat_gateways` / `environment` / `tags`. Enforces mutual exclusion (`vpc_id` xor `create_vpc`), and refuses `public_alb=true` without a cert unless `allow_public_http=true` is also set.
3. **Stack-wide tags** — applies `Application=ams-dashboard, Environment=…, ManagedBy=CDK` and any per-deploy overrides from `-c tags='{…}'`.
4. **Networking** — three code paths:
   - `create_vpc=true`: provision a new VPC with 2 AZs, public + private-with-egress subnets, configurable NAT count.
   - `vpc_id` + `private_subnet_ids`: import an existing VPC with explicit subnets (used when the existing VPC isn't CDK-tagged).
   - `vpc_id` alone: `Vpc.from_lookup()` (only works if the VPC's subnets carry CDK tags).
5. **Secrets Manager** — auto-generated Django `SECRET_KEY`, plus an empty JIRA secret the admin populates after first deploy.
6. **Aurora cluster** — Postgres 16.4 Serverless v2 (0.5–2 ACU), single writer, `removalPolicy=SNAPSHOT`, 7-day backups, dedicated security group.
7. **Cognito** — User Pool (`ams-dashboard`, email sign-in, no self-signup, RETAIN), App Client (USER_PASSWORD_AUTH + authorization_code_grant, no client secret).
8. **Container image** — `ecr_assets.DockerImageAsset` builds from `Dockerfile`, pushes to ECR via CDK's asset system.
9. **ECS cluster** — Container Insights v2 enabled.
10. **API service** — `ApplicationLoadBalancedFargateService` with the new image, ALB scheme controlled by `public_alb`, optional HTTPS via `acm_cert_arn`, health-checked at `/health`. Circuit breaker enabled with `rollback=False` so failed first-deploys leave debuggable artifacts. `min_healthy=50%, max_healthy=200%` for rolling deploys.
11. **Migration TaskDefinition** — separate task def with the same image but `CMD=["python","manage.py","migrate","--noinput"]`. Operators run this via `aws ecs run-task` post-deploy.
12. **Scheduled JIRA sync tasks** — three `ScheduledFargateTask`s with separate task definitions, each granted DB + secret read. A CfnRule property override sets `AssignPublicIp=ENABLED` for the NAT-less topology (CDK's ecs-patterns construct doesn't expose this directly).
13. **Outputs** — `AlbDnsName`, `ClusterName`, `ApiServiceName`, `MigrationTaskArn`, `UserPoolId`, `AppClientId`, `DbClusterEndpoint`, `DjangoSecretArn`, `JiraSecretArn`.

### 6.4 Context parameters cheat-sheet

| Context | Type | Default | Purpose |
|---|---|---|---|
| `account` | string | (env var) | AWS account number |
| `region` | string | (env var) | AWS region |
| `vpc_id` | string | – | Use this existing VPC |
| `create_vpc` | bool | `false` | Provision a new VPC instead |
| `nat_gateways` | int | `0` | When create_vpc=true; 0 = NAT-less, tasks in public subnets |
| `public_alb` | bool | `false` | Make the ALB internet-facing |
| `acm_cert_arn` | string | – | ACM cert for HTTPS listener |
| `allow_public_http` | bool | `false` | Required to deploy public_alb=true without a cert |
| `private_subnet_ids` | csv | – | Used with vpc_id when subnets aren't CDK-tagged |
| `availability_zones` | csv | – | Pairs with private_subnet_ids |
| `add_vpc_endpoints` | bool | `false` | Provision Secrets Manager / ECR / Logs interface endpoints + S3 gateway (for isolated VPCs) |
| `vpc_cidr` | string | – | Required for add_vpc_endpoints to scope endpoint SG |
| `private_route_table_ids` | csv | – | Required for add_vpc_endpoints; S3 gateway route attachment |
| `environment` | string | `prod` | Stack-level tag |
| `tags` | JSON | `{}` | Extra tags merged into stack-wide tagging |

---

## 7. User Interface Walkthroughs

> The descriptions below are based on inspection of each page's React source. UI text and behavior reflect what the code says happens. Features that are wired up server-side but not yet exercised in a deployed app are noted.

### 7.1 Login flow

**`/login` — `LoginPage`**

A centered card with the title "AMS Dashboard", an email field, a password field, an error banner (only when populated), and a Sign-in button. The button toggles to "Signing in…" while the request is in flight. On success:
- Normal: `setToken(id_token)` then `navigate('/', { replace: true })` → redirects to `/customers`.
- First login (Cognito `NEW_PASSWORD_REQUIRED`): `navigate('/password-change', { state: { session, username } })`.

On error (bad password, server error), the response's `detail` message is rendered in a red banner above the button.

**`/password-change` — `NewPasswordPage`**

Reached only via redirect from `/login`. Reads `{session, username}` from React Router location state — if missing (bookmarked URL, refresh), the page renders `<Navigate to="/login" />` immediately.

Two password fields (new + confirm), with client-side check that they match. Submits to `/api/auth/challenge` with `{session, username, new_password}`. On success, stores the new id_token and navigates to `/`. On error, surfaces the server's error message (typical: "Password does not meet policy requirements" if the password is too weak per Cognito's policy: 8+ chars, mixed case, number, symbol).

### 7.2 Customers list (`/customers`)

A simple data table. Top of the page:

- "Customers" header with the total count
- Filter bar: free-text search (matches `jira_name` OR `local_name` icontains) + a "Hide customers without AMS level" checkbox (default checked — only AMS-contracted customers show)

Columns: Name (links to detail), AMS Level badge, Automated tickets, Manual tickets, Zabbix status dot (green/yellow/red, or "N/A" for `not_using_zabbix`), Patching status dot (green/yellow/red rollup), Cert status dot (red if any expired, yellow if any within 30 days, green otherwise), Country (US/CA). Sort order: Expert → Enhanced → Essential → unassigned, then alphabetical by display name within each tier.

Table columns: Name (link to detail page), AMS Level (Badge), Zabbix (Badge), Open Tickets, Patching (yes/no/unknown), Last JIRA Sync.

Empty / loading / error states are handled explicitly with single-row "Loading…" / "No customers found." / red error banner.

### 7.3 Customer detail (`/customers/:id`)

The most feature-rich page. Five collapsible sections; **Users** starts collapsed by default, the rest open.

**Details section.** Form-grid layout. Top to bottom:
- Company-name override (`local_name`) + AMS level dropdown (one row).
- Documents (wide) — list with Open/Edit/Delete per row + Add form.
- SMEs (wide, read-only — set on the Staff page) — chips with mailto/tel links.
- **Primary Basket (wide, new 2026-06-03)** — dropdown of all defined baskets. Auto-PATCHes on change (no Save click needed). The basket's pinned softwares render as chips directly below as `name (version)` — at-a-glance reference stack for the customer.
- Roadmap (wide, collapsible) — long-form strategic notes.
- Notes (wide, collapsible) — operational day-to-day notes.
- Open Tickets meta + Last JIRA Sync meta (one row).
- **Bottom row (low-edit fields):** Help Desk # + Country (one row); Not Using Zabbix checkbox alone on the last row; Save Changes button.

Most fields use batched on-Save edits via the "Save Changes" button. Primary Basket is an exception — it PATCHes immediately so the chip list refreshes without a save click.

**Customer Systems section** (via `CustomerSystemsSection` component).

- Environment chips at the top. Each chip has an X to remove (disabled if any server is in that env). Add-environment inline form.
- Server table columns: expand chevron, name, IP address (masked input), env badge, basket names, cert-expires-on, patching badge, delete.
- Expanding a server reveals:
  - Top-right **"Copy to Environment"** button — confirms and bulk-applies this server's notes, basket assignments, and installed software (including the `functionally_latest` flag) to every other server in the same environment.
  - **Assigned baskets**: toggleable chips. The selected state uses a light-green tint with dark-green text (not inverted to white).
  - **Installed software**: per-row showing software name + version label + release dropdown + **Functionally Latest checkbox** (per-server override that treats the installed release as Latest for needs-patching) + delete.

All edits are optimistic with on-blur saves; a brief error banner surfaces if a save fails.

**Users section** (collapsed by default). Table of `OrgUser` rows. JIRA-synced display name and email are read-only by default but can be overridden via `local_display_name` / `local_email` — the JIRA value remains visible as a tooltip. Editable: role, alerts checkbox, primary checkbox, AMS Report checkbox, hide checkbox. Saves on blur.

**Analytics section** (via `CustomerAnalyticsSection` component). One row per `CustomerAnalytic` showing the metric definition, target environment/server, frequency, and capture count. Expanding a row reveals the capture history (when / value / description / delete). Value rendering strips trailing zeros and adds thousands separators ("100.0000" → "100", "1234567" → "1,234,567"). A "Record" form at the bottom of each metric adds a new capture. An "Add Metric" form adds a new `CustomerAnalytic`, with cascading scope-aware selects.

**Patch History section.** Per-software, per-environment timeline of `PatchHistory` rows for this customer.

### 7.4 Critical Events Calendar (`/critical`)

Aggregated calendar covering the past 6 weeks + next 6 weeks (server-capped at 12 forward). Single GET to `/api/critical/?weeks=6` on mount.

Header: "Critical — past 6 weeks + next 6 weeks · N events". Single checkbox: "Hide weekends".

**Split layout:** events are now split into two sections divided by panel headers:
- **Upcoming Tasks** (today + future, chronological) — today's row still highlighted.
- **Overdue Tasks** (past, reverse-chronological — most recently missed first).

Each event row shows: Time (or "—"), Kind badge (Cert / Patch / Patch_planned / activity type), Label (with `EXPIRED:` or `OVERDUE:` prefix when applicable), organization-name link.

Date headers include the year ("Sun Jun 02, 2026") since the 12-week window can cross a year boundary. Cert events use `Server.cert_expires_on`; patch events come from `PatchHistory`; planned-patch events come from active `PatchExecution` rows with a `planned_date`; activity events come from scheduled `Activity` rows.

### 7.5 Activities (`/activities`)

Header: "Activities · N total" with a "Status" filter (Open / Completed / All) and a "+ Add Activity" button.

Cards (not a table). Each card shows the activity name, scheduled date+time, type badge, priority badge, organization name (if set), assigned staff (if set), and (when not yet completed) a Complete button and a delete X.

Clicking a card expands an edit form for the same fields plus a notes textarea. Completed activities are dimmed.

Add-activity inline form (revealed by the button) collects name, date+time, type, priority, customer, assigned staff, then closes after a successful create.

### 7.6 Software Catalog (`/versions` — nav label "Software")

Two-level cards (post-squash): **Software → Release**. The route path stays `/versions` so existing bookmarks resolve.

- Software cards: name + version (both inline editable) + status dropdown (Latest / Supported / EOL) + release count + delete X. Add Software form at bottom requires both name and version up front.
- Expand a software card to see its releases — each release shows the version prefix as a label, a freeform suffix input, a release date, a status dropdown, and a Latest badge if applicable.

The atomic-demote logic (§4.6.2) means selecting a status of "Latest" on any sibling release silently demotes the previous Latest to "Supported".

### 7.7 Baskets (`/baskets`)

After the patching redesign, baskets are purely logical software groupings — the basket auto-populates a server's installed-software when the server is assigned to it.

Cards per basket: editable name, description, software count, delete X. Expand to see:
- Software list rows: software name + version label (badge: `name (version) — status`) + computed Latest-release display + remove.
- Bottom add form: pick a Software from the dropdown — the version is intrinsic to the Software row now, no separate version select.

To change a basket's pinned version: remove the current Software entry and add the new Software (e.g. swap "Apache 2.4" for "Apache 2.6").

### 7.8 Patch Execution (`/patch-execution`)

Three-tab page with **Executions** first (the daily-work surface), then **Groups** and **Plans**.

- **Executions tab.** Top action row: **"Check for Needed Patch Executions"** button + "+ Add Execution". The Check button calls `POST /api/patch-executions/check/` which walks AMS-contracted customers, finds stale (server, software) pairs (`installed_release != Latest AND NOT functionally_latest`), and creates one execution per `(env, plan)` for every plan whose softwares M2M covers any stale software. Results render in a dismissable banner summarising created/skipped per row.

  Each active execution card shows: org-env header, plan name, software-list snapshot, planned-date (click to edit), step table. Per-step Done buttons. `not_timed` steps render `(not timed)` next to the description, hide their Elapsed input, and Done is always enabled (no prior-step gating). Timed-step gating walks backward over `not_timed` siblings when deciding when the next timed step unlocks. Last step's Done triggers `finalize_execution` server-side (writes `PatchHistory`, advances `ServerInstalledSoftware` per `execution.softwares` snapshot, resets each affected row's `functionally_latest`, marks completed).

  Abort flow: notes field required, "Confirm Abort" records the attempt and resets steps. Reset is a clean restart (no abort logged).

- **Groups tab.** Cards of `PatchGroup` rows. Expand for the Software chip-picker (M2M to Software) and the steps table (#/description/est/per-server/NOT Timed/delete). Step # is digits-only-masked; renumbering produces transient duplicates which the UI tolerates (display sort breaks ties on `id`).

- **Plans tab.** Cards of `PatchPlan` rows. Expand for: Software chip-picker (independent of any group); steps table (plan-owned, same columns as Groups); "+ Add Step" form + "+ Import from Group…" dropdown. Importing a group is a one-shot copy — the group's steps get appended to the plan's step list, the group's softwares get unioned into the plan's softwares, and the plan never refers back to the group afterward.

### 7.9 Analytics definitions (`/analytics`)

Lightweight CRUD for `AnalyticDefinition` — just rows of (name, frequency dropdown, scope dropdown, delete). Used to define what kinds of metrics the team tracks per customer; the actual captures happen inside the Customer Detail page's Analytics section.

### 7.10 Staff (`/staff`)

Cards per staff member. Editable: name, email, phone. Expand for the SME assignment grid — toggleable chips, one per organization, showing ✓ when this staff member is the SME for that org.

### 7.11 Other / placeholders

- `/settings` → `PlaceholderPage title="Settings"` — empty placeholder, intentional future home for things like preferred notification channels, JIRA admin overrides, etc.
- `/*` (404 fallback) → `PlaceholderPage title="Not found"`.

---

## 8. Operations Runbook

### 8.1 Deploy a code change

The day-to-day path is the wrapper script:

```bash
./infra/scripts/deploy.sh --yes
```

It activates the CDK venv, silences the jsii Node-version banner, bakes in the three context flags the running stack needs (`create_vpc=true`, `public_alb=true`, `allow_public_http=true`), turns on `pipefail` so a Docker build failure actually fails the deploy, and tees output to `/tmp/cdk-deploy-<timestamp>.log`. When HTTPS lands, set `ACM_CERT_ARN=arn:…` in the environment — the wrapper swaps `allow_public_http=true` for `acm_cert_arn=…` automatically.

The equivalent raw `cdk deploy` if you ever need to bypass the wrapper:

```bash
cd infra
source .venv/bin/activate
export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1
AWS_PROFILE=ams-admin AWS_REGION=us-west-2 cdk deploy AmsDashboardStack \
  -c create_vpc=true \
  -c public_alb=true \
  -c allow_public_http=true \
  --require-approval never
```

Context flags must match the *current* desired state on every deploy — CDK is declarative, so dropping a flag will revert it. Forgetting `public_alb=true` flips the ALB back to internal scheme and changes its DNS, locking everyone out until reversed. (This is exactly what the `deploy.sh` wrapper exists to prevent.)

Typical timing: 4 min for a code-only change with Docker layers cached; 7–8 min if the API image rebuilds from scratch. ALB scheme changes add another 3 minutes for the LB replacement.

### 8.2 Run a migration after a deploy

```bash
CLUSTER=AmsDashboardStack-ClusterEB0386A7-D1161Vswl3Iu
SUBNET=subnet-0cf412c5862a49750
SG=sg-031f0db248aab5873
# Latest migration task def ARN — bump revision after each deploy
MIGRATION=arn:aws:ecs:us-west-2:721082559106:task-definition/AmsDashboardStackMigrationTaskA104F64B:N

aws --profile ams-admin --region us-west-2 ecs run-task \
  --cluster $CLUSTER --task-definition $MIGRATION --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$SG],assignPublicIp=ENABLED}"
```

Watch `aws logs tail /ams-dashboard/api --log-stream-name-prefix migrate` for output.

### 8.3 Manually trigger a sync

```bash
aws --profile ams-admin --region us-west-2 ecs run-task \
  --cluster $CLUSTER \
  --task-definition AmsDashboardStackJiraSyncOrgsTask4ABF20A3 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$SG],assignPublicIp=ENABLED}"
```

Substitute `JiraSyncUsersTask…` or `JiraSyncTicketsTask…` as needed. Watch `/ams-dashboard/jira-sync` logs.

### 8.4 Restart the API to pick up a Secrets Manager change

```bash
aws --profile ams-admin --region us-west-2 ecs update-service \
  --cluster $CLUSTER --service AmsDashboardStack-ApiService199661B5-UCTedToL7loE \
  --force-new-deployment
```

ECS rolls a new task; the new task fetches secrets fresh on startup.

### 8.5 Create a Cognito user

```bash
aws --profile ams-admin --region us-west-2 cognito-idp admin-create-user \
  --user-pool-id us-west-2_Bao82CnNc \
  --username someone@imt.ca \
  --user-attributes Name=email,Value=someone@imt.ca Name=email_verified,Value=true \
  --temporary-password 'ChangeMe123!'
```

User logs in once with the temp password, sees the NEW_PASSWORD_REQUIRED challenge, sets a real one.

### 8.6 Tunneling via the bastion (admin/SSH-style access)

```bash
aws --profile ams-admin --region us-west-2 ssm start-session \
  --target i-08bd75fe381f36674 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["<remote-host>"],"portNumber":["<port>"],"localPortNumber":["<local>"]}'
```

E.g. to reach the Aurora cluster directly: `host=…cluster-…rds.amazonaws.com, portNumber=5432, localPortNumber=15432`, then `psql -h localhost -p 15432 -U ams …` with the master password from Secrets Manager. The bastion's SG has no inbound — SSM tunnels work via Systems Manager, not direct TCP.

### 8.7 Tear it down

```bash
cdk destroy --profile ams-admin -c account=721082559106 -c region=us-west-2 -c create_vpc=true
```

What survives `destroy`:
- Aurora final snapshot
- Cognito User Pool (RETAIN)
- CloudWatch log groups
- ECR repository (CDK toolkit-owned)
- The bastion EC2 + its IAM role (created outside the stack — needs manual cleanup)

### 8.8 Common troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Login loop (token cleared on every API call) | SPA is storing the access_token, but Django verifies `aud` (id_token only) | Already fixed — `LoginPage` and `NewPasswordPage` now store `resp.id_token` |
| Migration fails with "Connection refused to 127.0.0.1:5432" | Dockerfile leaked `DATABASE_URL=postgres://x:x@localhost/x` into the runtime image | Already fixed — `Dockerfile` uses inline-on-RUN env vars now |
| JIRA sync 404 on `/rest/servicedeskapi/organization` | Wrong JIRA URL OR no JSM subscription on tenant OR API user lacks JSM permission | Verify `JIRA_URL` in Secrets Manager (must match Atlassian tenant, e.g. `https://infomagnetics.atlassian.net`); check user has agent access in JSM |
| ALB returns 503 immediately after deploy | New task is unhealthy (failing /health) before old drained | Check `aws ecs describe-services` events + `aws logs tail /ams-dashboard/api --log-stream-name-prefix api` |
| `cdk bootstrap` errors with "This app contains no stacks" | App.py guard skipped synth because neither `vpc_id` nor `create_vpc` was passed | Pass `-c create_vpc=true -c account=… -c region=…` to bootstrap |
| Cognito tells user "Password does not meet policy" | Default policy: 8+ chars, mixed case, number, symbol | Try a stronger password, or relax policy via Cognito console |

---

## 9. Security

### 9.1 Identity & authorization

- All API calls except `/health`, `/api/auth/login`, `/api/auth/challenge`, and the SPA fallback require a valid Cognito JWT.
- JWTs are validated against the user pool's JWKS on every request — no DB lookup, no shared secret.
- Token type matters: the SPA sends the **id_token** (audience-verified). Access tokens would be rejected.
- Cognito's built-in lockout fires after repeated failed login attempts (default ~5 attempts → temporary lockout, escalating).

### 9.2 Network

- Aurora cluster's security group accepts inbound on 5432 **only** from the API task SG. No public access. No bastion SG access — Aurora is reachable only via SSM port-forwarding through the bastion + the API task SG (a separate intentional path).
- The API task SG accepts inbound on container port 8000 **only** from the ALB SG. Even though tasks have public IPs (NAT-less topology), they're not reachable from the internet.
- ALB SG accepts inbound on 80 from `0.0.0.0/0` (until HTTPS lands, then 80 + 443).
- Bastion SG has **no** inbound rules. SSM agent connects out to Systems Manager; users connect via SSM API, not direct TCP.

### 9.3 Secrets

- No plaintext secrets in code, env files, or Docker images. All secrets live in Secrets Manager.
- ECS task **execution** roles have `secretsmanager:GetSecretValue` scoped to the specific secret ARNs.
- ECS task **runtime** roles have no Cognito IAM permissions (the calls we make to Cognito are unauthenticated).
- The Aurora master credential rotates manually today; rotation Lambda is not configured (see §11 Known Gaps).
- Django `SECRET_KEY` is auto-generated by CDK on first deploy and never logged.

### 9.4 Transport

- (After cert validation lands) HTTPS-only at the ALB, with `redirect_http=True` on port 80.
- Django sets `SECURE_PROXY_SSL_HEADER` so it understands the `X-Forwarded-Proto: https` header from the ALB.
- Secure cookies (`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`) when `DEBUG=False`.

### 9.5 Frontend

- No `dangerouslySetInnerHTML` anywhere in the SPA (verify with `grep`); React's default escaping handles XSS for user input.
- API base URL is same-origin relative (`/api`), so no CORS surface.
- `sessionStorage` for the JWT (cleared on tab close); a smarter design would keep it in memory only, but `sessionStorage` is the chosen trade-off for survive-page-refresh UX.

### 9.6 Known security gaps (see §11 for more)

- No WAF in front of the public ALB. Cognito's lockout protects login; everything else is just rate-unlimited.
- Django admin (`/admin`) is publicly reachable. There are currently no Django superusers in the deployed DB, so login can't succeed — but it's still a probe target. Consider IP-restricting the admin path or blocking it at the ALB.
- The `tony@imt.ca` IAM user has full `AdministratorAccess` in the sub-account. Consider trimming to a least-privilege policy once stable.
- The Aurora master credential was inadvertently exposed in chat during development; it has not yet been rotated.

---

## 10. Cost

Approximate steady-state monthly cost for the current configuration (low-traffic internal app, 20 users):

| Component | Cost/mo | Notes |
|---|---|---|
| Aurora Serverless v2 | ~$44 | 0.5 ACU minimum × $0.12/ACU-h × 730 h |
| Fargate API task | ~$15 | 256 CPU + 512 MiB × 730 h |
| Application Load Balancer | ~$22 | $0.0225/h + LCU |
| Bastion EC2 | ~$3 | t4g.nano on-demand |
| CloudWatch Logs | ~$1–2 | 14-day retention, low volume |
| Secrets Manager | ~$1.20 | 3 secrets × $0.40/mo |
| ECR storage | ~$0.50 | A few image revisions |
| Cognito | $0 | Under 50k MAU |
| Scheduled task runtimes | ~$1 | 1 sync × 30 min × 0.5 vCPU is pennies |
| Data transfer | ~$1–3 | At 20-user scale |
| **Total** | **~$90/mo** | |

### Cost-reduction levers explored

| Idea | Saving | Trade-off |
|---|---|---|
| Aurora SLv2 min capacity 0.5 → 0 (auto-pause) | up to $40 when idle | ~15s cold-start latency on first request |
| RDS Postgres `db.t4g.micro` single-AZ instead of Aurora | ~$30 | No auto-failover, manual scaling |
| Schedule API task to desired=0 outside work hours | ~$10 | Cold-start delay on first hit |
| WAF rate-limiting | -$5+ | Adds cost |
| HTTPS via CloudFront instead of ALB cert | similar | More complex routing |

---

## 11. Known Gaps & Future Work

### 11.1 Infrastructure

- **HTTPS not yet active** — ALB is internet-facing on HTTP. ACM cert was issued (`317ed450-…`) but the DNS validation CNAME hasn't been wired up at the parent domain, and no Route 53 record points at the ALB. Until that lands, the SPA login posts passwords over plain HTTP. The team explicitly accepted the risk for the internal-app phase; not for production-team customer use.
- **No WAF** — public ALB has no rate-limiting beyond Cognito's per-user lockout.
- **No CloudWatch alarms** — nothing alerts on task crashes, health-check failures, sync failures, NAT throughput, etc.
- **Aurora storage not encrypted at rest** — storage-level confidentiality, not a data-loss risk. Enabling requires a cluster recreate; deferred.
- **Aurora master credential rotation Lambda not deployed** — rotation today is manual.
- **No monitoring of the JIRA sync jobs' success/failure** — a silent sync failure today only surfaces when the dashboard data goes stale.
- **Django application logs aren't reaching CloudWatch** — only gunicorn access logs do. `logger.info(...)` calls from Django apps (e.g. signal handlers, sync jobs) don't appear in the `/ams-dashboard/api` log group, which made debugging the no-PatchExecution-on-new-Latest issue harder than it needed to be.
- **Bastion EC2 lives outside the CDK stack** — created by manual `aws ec2 run-instances` during deploy. Move it into the stack (or remove it once HTTPS is live and SSM tunneling is no longer needed).
- **Closed since v1:** Aurora deletion protection enabled, manual recovery snapshot taken, `RemovalPolicy.SNAPSHOT` confirmed.

### 11.2 Application

- **No Django superuser exists in the deployed DB** — `/admin` login fails for everyone, which is a feature for security but a bug if anyone needs admin access. Run `python manage.py createsuperuser` via a one-off ECS task to create one when needed.
- **No password reset flow** — Cognito supports `ForgotPassword` natively but the SPA has no UI for it.
- **No MFA** — Cognito supports it but the user pool wasn't configured with `mfa=ON|OPTIONAL`.
- **No SSO** — Cognito user pool, not Identity Center. Each user has a separate password. For a 20-person team this is fine; for growth, federate to Microsoft Entra ID / Google Workspace via Cognito's identity providers.
- **Role-gate Phase 2 not done** — the SPA shows a "Read-only access" banner for viewers but doesn't yet hide individual write buttons. Viewer writes 403 from the backend and the error surfaces inline. Full UI gating is deferred.
- **JIRA sync is one-way** — changes in the dashboard don't propagate back to JIRA. Intentional today but worth flagging.
- **No automated tests run on deploy** — `pytest` exists but isn't enforced in CI. Adding GitHub Actions to run `pytest` and `npm run build` on every push to main would catch regressions before deploy.
- **Closed since v1:** silent-refresh on 401 (id-token issuance via refresh token), the SPA's React ErrorBoundary, role gate Phase 1, plus most of the daily-use UI ergonomics (Critical page split, Software Catalog squash, Patching redesign, Functionally Latest override, Primary Basket field, etc).

### 11.3 Process

- **No CI/CD** — deploys are run manually from a developer's machine via `./infra/scripts/deploy.sh --yes`. A GitHub Actions workflow assuming the `cdk-amsdash01-deploy-role-…` via OIDC would let `git push` to main trigger a deploy.
- **No staging environment** — only `prod`. Adding a `staging` stack (same code, smaller sizing, separate Cognito user pool) would let changes bake before they hit the team. With `create_vpc=true` and Tier 1 sizing this would cost ~$50/mo.
- **No structured release tags** — the runbook references `git checkout v1.0.0` but no version tags exist yet.
- **Inadvertent credential exposure in chat during initial deploy work** — the Aurora master credential and an IAM access key were both visible at one point. The IAM access key was rotated; the Aurora credential rotation is still pending. Deletion protection now blocks the worst-case scenario, but the credential itself should still be rotated before broader use.

### 11.4 Documentation

- `db/schema.sql` is described as "machine-generated reference of the live Postgres schema" — there's no automation today to keep it in sync. Add a `make schema-dump` target or a post-migrate signal.
- `DEPLOY.md` was lightly refreshed (deploy wrapper noted) but its "first deploy" sections still reflect the original bootstrap path. Anyone running a *fresh* deploy from scratch should expect to consult both `DEPLOY.md` and the `infra/scripts/admin-bootstrap-*.sh` scripts.

---

## 12. Appendices

### 12.1 Environment variables (container)

Set via ECS task definition; sourced from CDK / Secrets Manager.

| Variable | Source | Purpose |
|---|---|---|
| `DEBUG` | env literal `False` | Disables Django's debug mode + insecure defaults |
| `AUTH_BYPASS` | env literal `0` | Required for `CognitoJWTAuthentication` to be wired in |
| `ALLOWED_HOSTS` | env literal `*` | OK while behind ALB; consider tightening once domain is final |
| `DB_NAME` | env literal `ams_dashboard` | Database name |
| `COGNITO_REGION` | env literal `us-west-2` | Region for the user pool (matches deploy) |
| `COGNITO_USER_POOL_ID` | env from CDK | `us-west-2_Bao82CnNc` |
| `COGNITO_APP_CLIENT_ID` | env from CDK | `42cotc6iun8ttt8sea4mkfp2h6` |
| `SECRET_KEY` | Secrets Manager (DjangoSecretKey) | Django SECRET_KEY |
| `DB_HOST` | Secrets Manager (Aurora `host`) | Aurora writer endpoint |
| `DB_PORT` | Secrets Manager (Aurora `port`) | 5432 |
| `DB_USER` | Secrets Manager (Aurora `username`) | `ams` |
| `DB_PASSWORD` | Secrets Manager (Aurora `password`) | (rotates) |
| `JIRA_URL` | Secrets Manager (JIRA) | `https://infomagnetics.atlassian.net` |
| `JIRA_EMAIL` | Secrets Manager (JIRA) | JSM agent email |
| `JIRA_TOKEN` | Secrets Manager (JIRA) | Atlassian API token |

### 12.2 Useful one-liners

```bash
# Watch container logs in real time
aws --profile ams-admin --region us-west-2 logs tail /ams-dashboard/api --follow

# Last 50 sync events (any sync)
aws --profile ams-admin --region us-west-2 logs tail /ams-dashboard/jira-sync --since 1d | tail -50

# Cognito user pool — list users
aws --profile ams-admin --region us-west-2 cognito-idp list-users --user-pool-id us-west-2_Bao82CnNc

# ECS — current API service state
aws --profile ams-admin --region us-west-2 ecs describe-services \
  --cluster AmsDashboardStack-ClusterEB0386A7-D1161Vswl3Iu \
  --services AmsDashboardStack-ApiService199661B5-UCTedToL7loE \
  --query 'services[0].{Status:status,Desired:desiredCount,Running:runningCount,Pending:pendingCount}'

# Aurora — describe cluster
aws --profile ams-admin --region us-west-2 rds describe-db-clusters \
  --db-cluster-identifier amsdashboardstack-db5d02a0a9-smiqefm0qfai

# ACM cert status (DNS validation)
aws --profile ams-admin --region us-west-2 acm describe-certificate \
  --certificate-arn arn:aws:acm:us-west-2:721082559106:certificate/317ed450-7572-4d19-936f-2975c1826b35 \
  --query 'Certificate.Status'
```

### 12.3 Glossary

- **ACU** — Aurora Capacity Unit. SLv2 billing increment; ~2 GiB memory + corresponding CPU per ACU.
- **AMS** — Application Managed Services (the IMT team this app is built for).
- **JSM** — JIRA Service Management (formerly Service Desk).
- **SME** — Subject Matter Expert. In our model, a Staff member assigned as the primary contact for one or more customer organizations.
- **Basket** — a named bundle of (software → pinned version) pairs used to drive patching status and patch executions.
- **Latest** — the special status assigned to exactly one Version per Software (and one Release per Version). Drives "needs patching" computation.
- **Soft delete** — setting `deleted_at` instead of removing the row. The default model manager filters these out, but `Model.all_objects` includes them.

### 12.4 Resource IDs (snapshot)

For quick reference, all the live identifiers in one place. **These will change** on a fresh deploy — treat as illustrative for the current account.

```
AWS Account:        721082559106
Region:             us-west-2
VPC:                vpc-04b75b92656837be8
Public subnets:     subnet-0cf412c5862a49750, subnet-02f5abcec1a1096fd
API task SG:        sg-031f0db248aab5873
Bastion SG:         sg-0b2a8bb3005f31146
Bastion EC2:        i-08bd75fe381f36674
ECS cluster:        AmsDashboardStack-ClusterEB0386A7-D1161Vswl3Iu
API service:        AmsDashboardStack-ApiService199661B5-UCTedToL7loE
ALB DNS (current):  AmsDas-ApiSe-LgNCAonjExh2-1426856071.us-west-2.elb.amazonaws.com
Aurora cluster:     amsdashboardstack-db5d02a0a9-smiqefm0qfai
Aurora endpoint:    amsdashboardstack-db5d02a0a9-smiqefm0qfai.cluster-c7akgms4sdyg.us-west-2.rds.amazonaws.com
Cognito User Pool:  us-west-2_Bao82CnNc
Cognito App Client: 42cotc6iun8ttt8sea4mkfp2h6
Django secret:      arn:aws:secretsmanager:us-west-2:721082559106:secret:DjangoSecretKey0A000B3C-z2Au0NDSvzXo-oSZMly
Aurora secret:      arn:aws:secretsmanager:us-west-2:721082559106:secret:AmsDashboardStackDbSecret1F-KEOtKLeuMPbQ-wlaEkM
JIRA secret:        arn:aws:secretsmanager:us-west-2:721082559106:secret:JiraServiceAccount780CFC76-nzmE3kkDgSlw-kr6NFk
ACM cert (pending): arn:aws:acm:us-west-2:721082559106:certificate/317ed450-7572-4d19-936f-2975c1826b35
Bootstrap qualifier: amsdash01
```

---

*Last updated during the deploy session — reflects state as of `cost-optimize-tier1` branch with login flow + public-HTTP ALB. When HTTPS is live and DNS is configured, the `Current deployment state` table in §1 and the ALB DNS in §12.4 should be refreshed.*
