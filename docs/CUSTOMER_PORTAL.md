# Customer Portal — Skunkworks Handoff

_Written 2026-10-20 at the end of the design conversation on the company
machine, so the work can continue on Tony's personal machine / personal
AWS account with full context. Read this first in the new session._

## 1. What we're building

A customer-facing web portal, tied to the AMS Dashboard's existing
customer data, with two goals:

1. **Secure document publishing** — post customer-specific information
   (notably the monthly AMS reports) behind a login, scoped so each
   customer sees only their own material.
2. **Ticketing + alerts** — eventually replace JIRA Service Management as
   the customer-facing ticket and alert system.

It is a personal skunkworks project: built and tested in Tony's
**personal AWS account**, not the company account, with the intent of
moving it home once proven.

## 2. Decisions locked (2026-10-20)

| Topic | Decision |
|---|---|
| Where it runs during development | **Option 3:** deploy a clone of the AMS Dashboard CDK stack into the personal account, populated with **synthetic customers only**. No real customer data leaves the company account (data-privacy decision). |
| Relationship to the dashboard data | The portal uses the **same tables and unique keys** (`Organization.id`, `OrgUser.id`). Portal-specific tables FK to them. **Do not duplicate** customer/user data into portal-owned copies. |
| Codebase | Same monorepo as the dashboard (shared Django models, one deployable stack). |
| Customer identity | **Separate Cognito user pool** for customers — never mixed with the staff pool. |
| Provisioning | Customer users are **invited from the AMS Dashboard** (staff action on the Customer Detail Users table). No self-signup. |
| Uniqueness | Users are **unique by email** and **cannot belong to more than one customer**. |

Still open — see §7.

## 3. Prod data audit (read-only, 2026-10-20)

Run against the company database to test the uniqueness rule against
reality (no individual emails recorded here, domains only):

- 333 active `OrgUser` rows; 327 distinct emails; **3 users with no
  email at all** (cannot be invited until one is added).
- **2 emails appear under more than one customer** — one address is
  listed under two unrelated customers, and one under two organizations
  that belong to the same customer (names withheld: this repository is
  public). The one-customer rule means staff will
  have to pick ONE org at invite time for these; the portal-account
  uniqueness constraint (§5) blocks inviting the second.
- **17 `@imt.ca` addresses** exist as customer OrgUsers (staff listed in
  customer JIRA orgs). These must never be invited as *customers* —
  exclude staff domains at invite time (configurable list, default
  `imt.ca`).

Relevant existing `OrgUser` fields (api/customers/models.py): `email`
(nullable, JIRA-synced, **no uniqueness constraint**), `local_email`
(local override), `jira_account_id` (null ⇒ local user), and local-only
flags `ams_report` ("receives the periodic AMS report email" — a natural
hook for document notifications), `alerts_enabled`, `is_primary`,
`is_access_contact`, `is_hidden`. `sync_jira_users` only writes
`display_name` + `email`; anything portal-related must likewise be
untouched by sync.

## 4. Proposed architecture

```
personal AWS account (dev)                    company account (later: home)
┌─────────────────────────────────────┐       same stack, real data
│ Cloned AMS Dashboard CDK stack      │
│  Aurora (synthetic orgs/users)      │
│  Django/DRF (one image)             │
│   ├─ staff API  ← staff Cognito pool│
│   └─ portal API ← CUSTOMER pool     │  ← new
│  SPA: dashboard (web/)              │
│  SPA: portal (portal/)              │  ← new, separate Vite project
│  S3: portal documents (private)     │  ← new
│  ALB + ACM cert + Route53 (HTTPS)   │  ← required day one for customers
└─────────────────────────────────────┘
```

Key points:

- **One Django backend, two audiences.** JWT validation accepts two
  issuers (staff pool, customer pool) and tags the request with its
  principal type. Portal endpoints require a customer principal and
  scope *every* query to `account.org_user.organization_id`; staff
  endpoints reject customer tokens outright. Cross-tenant isolation is
  the single highest-risk area — write isolation tests before features.
- **Portal SPA** is a separate Vite project (different auth, branding,
  and audience) built into the same Docker image and served on its own
  hostname (e.g. `portal.<dev-domain>`). The dashboard SPA is unchanged.
- **Documents** live in a private S3 bucket (SSE, no public access);
  downloads via short-lived presigned URLs; metadata rows FK to
  `Organization`.
- **Tickets** are native models from day one (not a JSM wrapper), with
  an optional JIRA-mirror toggle for the transition period. "Alerts"
  can leverage data the dashboard already has (planned patch windows,
  cert expirations) — a differentiator JSM cannot offer.

## 5. Identity model (proposed)

New Django app `api/portal/`:

```
PortalAccount
  org_user      OneToOne → OrgUser (CASCADE)   # the key tie — no duplicated name/email
  email_lower   unique                         # enforces one-customer-per-email globally
  cognito_sub   unique, nullable until first login
  status        invited | active | disabled
  invited_by    FK Staff (SET_NULL), invited_at
  last_login_at
```

Invite flow: Customer Detail → Users table → **Invite to Portal** →
backend validates (has email; email not in a staff domain; no existing
PortalAccount for that email anywhere) → `admin_create_user` in the
customer pool (Cognito emails the temp password; Cognito's default
sender is fine for dev at ≤50 emails/day) → `PortalAccount(status=
invited)`. Mandatory MFA is recommended for the customer pool.

## 6. Phase plan

- **Phase 0 — Environment.** Personal AWS profile + `cdk bootstrap`;
  parameterize the stack for a second environment (account/region, stack
  name, domain + ACM cert, pool names); add a **deploy guard** so
  `deploy.sh` refuses to run unless the active profile matches the
  target environment (prevents an accidental company deploy); deploy the
  clone; `seed_synthetic` management command (idempotent: ~6 fake orgs
  with environments/servers/users on `example.com` emails).
- **Phase 1 — Identity.** Customer Cognito pool (MFA), `PortalAccount`,
  Invite-to-Portal on Customer Detail, dual-issuer JWT auth, portal SPA
  shell (login, forced password change, MFA setup, "my customer" home),
  isolation test suite.
- **Phase 2 — Documents (MVP demo target).** S3 bucket + upload from
  Customer Detail (category e.g. "AMS Monthly Report" + period), portal
  document list + presigned download, optional "new report" email
  (reuse the `ams_report` flag as the recipient filter).
- **Phase 3 — Tickets & alerts.** Ticket / comment / attachment models,
  status workflow, staff queue view inside the dashboard, portal create
  + thread view, optional JIRA mirror; dashboard-pushed alerts.
- **Phase 4 — Move home.** Deploy the same stack to the company account
  (real orgs/users already there; portal tables start empty), invite
  real users, cut over from JSM.

## 7. Open questions (not yet answered)

- **Documents:** where do the monthly AMS reports come from today (manual
  PDFs, a tool export, something the dashboard could generate)? Format
  and size? Email notification on publish?
- **JSM scope:** which features are actually used — create/comment/
  attach/status only, or also SLAs, approvals, email-to-ticket, canned
  responses, reporting? Migrate historical tickets or start clean?
- **"Alert" meaning:** customer-raised urgent issues, dashboard-pushed
  notices to customers, or both?
- **Roles within a customer** (customer admin vs. viewer)? Any customer
  needing SSO federation to their own IdP, or is email+password+MFA
  enough for v1?
- **Personal account practicals:** region; a **domain you own** for the
  dev portal (HTTPS + SES/Cognito email need it — `imt.ca` cannot be
  used in a personal account); monthly budget (the current stack shape
  runs roughly $60–120/month).
- **First demo:** who sees it first, and which single screen wins them?

## 8. Getting started on the personal machine

1. **Push from the company machine first** — both remotes were behind
   local on 2026-10-20 (43 commits behind on BitBucket `origin`, 75 on
   GitHub `github`). Then clone and check out `cost-optimize-tier1`.
2. Confirm the personal profile: `aws configure list-profiles`. The
   company profile is `ams-admin` — never use it for this project.
3. `cdk bootstrap` the personal account/region once.
4. Start with Phase 0; `docs/ARCHITECTURE.md` explains the existing
   stack, deploy script, and the ECS migration-task pattern.

### Suggested opening prompt for the new session

> Read docs/CUSTOMER_PORTAL.md and docs/ARCHITECTURE.md. We're starting
> Phase 0 of the Customer Portal in my personal AWS account (profile
> `<name>`, region `<region>`, dev domain `<domain>`). Parameterize the
> CDK stack for a second environment with a deploy guard, deploy the
> clone, and add the synthetic seed command.

## 9. Phase 0 log (personal machine)

_2026-10-21._ Decisions taken for the personal environment:

| Item | Value |
|---|---|
| AWS profile | `default` (IAM user in account `465362304148`; `ams-admin` does not exist on this machine) |
| Region | `us-east-1` |
| Dev domain | `ams-dev.getshaking.live` (zone `Z077931918WPQT6KQ24A9`; getshaking.live is an idle personal domain, so a dev portal and its emails disturb nothing) |
| Stack | `AmsDashboardPersonalDev`, environment tag `personal-dev` |
| Bootstrap | qualifier `amsdash01`, toolkit stack `AmsDashboardCdkToolkit` (the account's default-qualifier `CDKToolkit` is untouched) |
| Portal hostname (Phase 1) | `portal.ams-dev.getshaking.live` — already covered by the wildcard SAN on the issued cert |

What Phase 0 added to the repo:

- `infra/environments/*.env` + `infra/scripts/env-lib.sh` — named
  environments and the **deploy guard** (caller account must equal the
  file's `AWS_ACCOUNT_ID`). `deploy.sh --env <name>` and
  `run-task.sh --env <name> <manage.py command>` both use it.
- Stack context `domain_name` / `hosted_zone_id` / `hosted_zone_name`
  (issues the ACM cert + Route53 alias), `jira_sync_enabled=false`
  (no scheduled syncs, so nothing in the personal account talks to the
  company JIRA), `stack_name`, and `environment`-suffixed physical names
  so the clone could even coexist with prod in one account.
- `api/customers/management/commands/seed_synthetic.py` — six fictional
  organizations (example.com users, 10.x servers, cert expiries spread
  past/imminent/future). Refuses to run where non-synthetic orgs exist;
  create-only on re-run, `--reset` restores canonical values. Includes the
  §3 edge cases on purpose: a user with no email, one email under two
  customers (`shared.contact@example.org`), hidden users.
- `infra/tests/unit/test_infra_stack.py` — real assertions for both the
  prod path (bare names, HTTP, 3 sync rules) and the dev path (suffixed
  names, wildcard cert, alias record, HTTPS redirect, no sync rules).

### First deploy — done 2026-10-21

| Output | Value |
|---|---|
| App URL | https://ams-dev.getshaking.live (HTTPS, HTTP→HTTPS redirect, cert SANs `ams-dev.getshaking.live` + `*.ams-dev.getshaking.live`) |
| Stack | `AmsDashboardPersonalDev` (us-east-1), deployed in ~7 min |
| User pool (staff) | `us-east-1_cxYACb709`, app client `2kco2c3r7dcunkrl8n42bsqc1j` |
| Cluster / service | `AmsDashboardPersonalDev-ClusterEB0386A7-oxsNub32gQFa` / `AmsDashboardPersonalDev-ApiService199661B5-HFcYS5u79KUy` |
| Aurora | `amsdashboardpersonaldev-db5d02a0a9-fnaffzmawj3p…`, Postgres **16.11** |
| Bootstrap | `AmsDashboardCdkToolkit` stack, qualifier `amsdash01` |

- Migrations applied and `seed_synthetic` run via `run-task.sh`
  (6 orgs, 21 servers, 17 users, 5 documents).
- `/health` 200 over HTTPS; real API routes return 401 JSON without a
  token; unknown paths fall through to the SPA (200 HTML) by design.
- Login page renders with no console errors.
- Gotcha hit on the first attempt: Aurora Postgres **16.4 can no longer
  be created** in us-east-1 (RDS withdrew it); the stack now pins 16.11,
  which the company cluster already runs after auto minor upgrades. The
  failed stack left RETAIN'd log groups + an empty user pool behind;
  those had to be deleted by hand before the recreate.
- JIRA secret deliberately left empty; sync schedules are not created
  in this environment.

**First staff login** (not yet done — Cognito emails the temporary
password; the SPA then forces a password change):

```bash
aws cognito-idp admin-create-user --profile default --region us-east-1 \
  --user-pool-id us-east-1_cxYACb709 --username <you@example.com> \
  --user-attributes Name=email,Value=<you@example.com> Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL
aws cognito-idp admin-add-user-to-group --profile default --region us-east-1 \
  --user-pool-id us-east-1_cxYACb709 --username <you@example.com> --group-name admin
```

### Cost (2026-10-21)

Running 24/7 the clone is ~$85/mo at list price: Aurora 0.5 ACU floor
~$44, ALB ~$17, three public IPv4 addresses ~$11, Fargate task ~$9,
logs/secrets/ECR ~$4. Applied: **Aurora auto-pause** after 15 idle
minutes (`AURORA_AUTO_PAUSE_MINUTES=15` in `personal-dev.env`, min
capacity 0 ACU, ~15 s resume on the first query) → roughly $40–45/mo
when lightly used. Available but not applied: `API_DESIRED_COUNT=0`
parks the API task (saves ~$13; ALB still bills ~$25 as the floor).
The ALB stays because it terminates TLS with the wildcard cert, gives
a stable DNS target, and will host-route the portal hostname in Phase 1
— replacing it with API Gateway would save ~$20 but diverge from prod.

**Next:** Phase 1 (customer Cognito pool with MFA, `PortalAccount`,
Invite-to-Portal, dual-issuer JWT auth, portal SPA shell at
`portal.ams-dev.getshaking.live`, isolation tests).
