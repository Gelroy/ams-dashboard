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
- **Phase 2 — Documents (MVP demo target).** Re-scoped 2026-11-16 from
  "upload a PDF" to generated monthly reports: editable templates with
  tags, draft → approved workflow, PDF in S3, portal Documents screen,
  email on approval (the `ams_report` flag picks recipients). See §11.
- **Phase 3 — Tickets & alerts.** Ticket / comment / attachment models,
  status workflow, staff queue view inside the dashboard, portal create
  + thread view, optional JIRA mirror; dashboard-pushed alerts.
- **Phase 4 — Move home.** Deploy the same stack to the company account
  (real orgs/users already there; portal tables start empty), invite
  real users, cut over from JSM.

## 7. Open questions (not yet answered)

- ~~**Documents:** where do the monthly AMS reports come from today?
  Format? Email notification on publish?~~ Answered 2026-11-16 — see §11.
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

## 10. Phase 1 — Identity (2026-11-13)

Built 2026-11-13; deployed to `personal-dev` and verified live 2026-11-16.
Portal: https://portal.ams-dev.getshaking.live

| | |
|---|---|
| Customer pool | `us-east-1_pcX353APB` (`ams-portal-personal-dev`) |
| App client | `70pdihlv8o9rsqrg5od53j08tn` |
| Migration | `portal.0001_initial` applied 2026-11-16 |
| Live smoke | 35/35 checks passed 2026-11-16 |

### What exists now

| Piece | Where | Notes |
|---|---|---|
| Customer user pool | `infra_stack.py` (`portal_enabled`) | `ams-portal-<env>`. No self-signup. **TOTP MFA required.** 12-char passwords. Refresh tokens last 1 day (staff pool keeps 30). Invitation email names the portal URL. |
| `PortalAccount` | `api/portal/models.py` | As §5: OneToOne → `OrgUser`, globally unique `email_lower`, `cognito_sub`, `status` invited/active/disabled, `invited_by` (+ `invited_by_email`), `last_login_at`. No copied customer data. |
| Two authentication classes | `api/ams_dashboard/auth_cognito.py`, `api/portal/auth.py` | Staff class validates **only** the staff pool and stays the DRF default. Portal class validates **only** the customer pool and is mounted only on `/api/portal/*`. Different signing keys ⇒ a token from the wrong pool fails signature validation (401). |
| Tenant scope | `api/portal/scoping.py`, `views.py` | Organization comes from token → PortalAccount → OrgUser. No portal endpoint accepts an organization id. `PortalScopedMixin` is the base for every future data viewset. |
| Sign-in relay | `api/portal/views.py` | `/api/portal/auth/{login,new-password,mfa/setup,mfa/verify,refresh,logout}`. Tokens leave the server only via `_finish_login`, which requires a usable PortalAccount. Account state is re-checked on **every** request, so disabling is immediate. |
| Invite / resend / disable / enable | `api/portal/services.py`, `OrgUserViewSet` | `POST /api/organizations/<org>/users/<id>/portal-<action>/`, admin only. Rules: email required (local override wins), staff domains refused, one customer per email (409 naming the other customer), no double invite. |
| Dashboard UI | Customer Detail → Users → **Portal** column | Status badge + Invite / Resend / Disable / Enable. Invite and Disable confirm first. |
| Host split | `api/ams_dashboard/middleware.py`, `spa.py` | On `PORTAL_HOST`: only `/api/portal/*`, `/health`, `/static/*`, portal SPA. `/admin` and staff APIs are 404 there; `/api/portal/*` is 404 on the dashboard host. |
| Portal SPA | `portal/` | Sign in → (first time) choose password → enrol authenticator via QR → home. Returning: password → 6-digit code. Home shows the customer's AMS level, help desk number, environments and server counts. Tokens in `sessionStorage`. |

### Tests (isolation first, as §4 asked)

`api/portal/tests.py` — 91 tests, no Cognito or network needed
(`cd api && .venv/bin/python -m pytest`; in-memory SQLite, real auth
classes via `ams_dashboard/settings_test.py`):

- a customer token is sent to **every** parameter-free staff route found
  by walking the URLconf → all 401; staff token → portal → 401;
- wrong key, wrong audience, access token, expired, forged issuer → 401;
- disabled / invited / unknown identity / soft-deleted user / soft-deleted
  customer → 401, including on an already-issued token;
- customer A never sees customer B (supplied organization ids ignored);
- every `/api/portal/` data route is asserted to carry the portal
  authentication + permission classes (guards future endpoints);
- host split; invite rules; sign-in relay incl. token withholding.

Three guards were mutation-checked (soft-delete check, org filter,
id-token check): each removal makes tests fail.

`infra/scripts/portal-smoke.py --env personal-dev` runs the same story
end to end against the deployed stack with real Cognito (throwaway staff
and customer identities, real TOTP codes), then cleans up.
It leaves one disabled `PortalAccount` row; remove it with
`infra/scripts/run-task.sh --env personal-dev portal_prune_smoke`.

Deploy gotcha: a deploy that stalls for hours (laptop asleep) fails at
`docker push` with `403 Forbidden` because the ECR login expired. The
stack is untouched; just rerun `deploy.sh`.

### Decisions taken (were open in §7)

- **MFA:** authenticator app (TOTP), mandatory. Needs no SES/SNS.
- **Roles within a customer:** none in v1 — every portal user of a
  customer sees the same thing. Add a `role` on `PortalAccount` when
  documents/tickets need admin-vs-viewer.
- **SSO federation:** not in v1 (email + password + TOTP).

### Known gaps (deliberate, for later phases)

- **No self-service password reset or MFA reset.** A locked-out customer
  needs staff: today that means the AWS console. Needs a "Reset access"
  action next to Disable, and a forgot-password flow (which needs SES for
  reliable email).
- **Email changes are not propagated.** The Cognito username and
  `email_lower` are fixed at invite time; if the JIRA email later changes,
  the portal login does not follow.
- **Invitation email uses Cognito's default sender** (50/day, generic
  from-address). Fine for dev; production needs SES on a real domain.
- **No audit log** of portal sign-ins/invites beyond the PortalAccount
  timestamps and CloudWatch.
- **Local portal development** needs real customer-pool tokens; there is
  no `AUTH_BYPASS` equivalent for portal endpoints (on purpose). Use
  `PORTAL_API_TARGET=https://portal.ams-dev.getshaking.live npm run dev`.

**Next:** Phase 2 — see §11.

## 11. Phase 2 — Monthly reports (2026-11-16)

Phase 2 was planned as "staff upload a PDF". The answers to the §7
document questions (2026-11-16) changed it into a **report generator**:

1. A report has several sections fed from different places: a mostly
   generic header, monitoring metrics delivered monthly from Zabbix
   (assumed JSON), a JIRA ticket summary (may need an AI step later), and
   System Software & Patch Planning from the dashboard.
2. Header and section text come from **editable templates** that mix
   fixed wording with tags, e.g. `This report was generated for
   {customerName} on {dateTime}.`
3. Reports are delivered as **PDF**.
4. A generated report starts as **DRAFT**; when it is **APPROVED** the
   customer is emailed.

Deployed to `personal-dev` and verified live 2026-11-16: migrations
`reports.0001`–`0002` applied, synthetic report data seeded, live smoke
52/52 (including a real S3 round trip for report PDFs). Reports bucket:
`amsdashboardpersonaldev-reportsbucket4e7c5994-x0ztren47ntp`.

### How it works

```
template ─┐
metrics ──┼─► generate ─► DRAFT ─► staff edit / preview ─► approve ─► APPROVED
dashboard ┘                                                  │
                                           PDF stored in S3 ─┤─► portal Documents
                                           email (link only) ┘
```

| Piece | Where | Notes |
|---|---|---|
| Models | `api/reports/models.py` | `ReportTemplate` (ordered sections of template text; exactly one default), `MetricsDelivery` (one JSON payload per customer per month; re-delivery replaces), `Report` (one live report per customer per month; sections hold the *filled* text), `ReportNotification` |
| Tag language | `api/reports/templating.py` | `{path}`, filters `round:N` `default:text` `date` `upper` `lower`, `{#each list}…{#else}…{/each}`, `{#if value}…{#else}…{/if}`. Reads dictionary keys only — no attribute access or calls. An unknown tag is left visible and reported |
| Layout markup | `api/reports/markup.py` | `## heading`, `- bullet`, `**bold**`, `\| cell \| cell \|` table rows. `[[text]]` marks something staff must still write |
| Data for tags | `api/reports/context.py` | Everything is queried by the one organization passed in. `metrics.*` is the delivered JSON as-is, so templates map any shape |
| Ticket summary | `api/reports/tickets.py` | Seam for the future JIRA + AI summariser. Returns nothing today, so drafts carry a `[[Ticket summary…]]` marker |
| PDF | `api/reports/pdf.py` | ReportLab (pure Python, no system libraries). Drafts are watermarked |
| Workflow | `api/reports/services.py` | `generate`, `update_draft`, `regenerate`, `approve`. Approval is refused while any `{tag}` or `[[marker]]` remains |
| Storage | `api/reports/storage.py` | S3 bucket `REPORTS_BUCKET` (private, encrypted, TLS-only, versioned); local disk when unset |
| Email | `api/reports/notifications.py` | Link to the portal only — never the report. `PORTAL_EMAIL_MODE=log` (default) records recipients and sends nothing; `ses` sends from `PORTAL_EMAIL_FROM` |
| Staff API | `api/reports/views.py` | `/api/reports/`, `/api/report-templates/`, `/api/report-metrics/`. Viewers read and preview; admins generate, edit, approve, delete |
| Unattended delivery | `api/reports/ingest.py` | `POST /api/report-metrics/ingest` with a delivery key. See "Unattended metrics delivery" below |
| Customer API | `api/portal/documents.py` | `/api/portal/documents` and `…/<id>/download`. Own organization, APPROVED only |
| Staff screens | `web/src/pages/Report*.tsx`, `MetricsDeliveryPage.tsx` | **Reports** (month overview, upload metrics, generate drafts), report review (edit, preview, approve), **Report Templates** (editor with tag reference and live preview), **Metrics Delivery** (delivery keys, what to send, customer ids) |
| Customer screen | `portal/src/pages/DocumentsPage.tsx` | List, view, download |
| Infra | `infra/infra/infra_stack.py` | `ReportsBucket`; API role may put and get objects there, nothing else; optional `portal_email_from` adds `ses:SendEmail` limited to that sender; optional `reports_schedule_day` adds the monthly draft task |

### Tags

The reference is built into the template editor (and `defaults.py`):
`customerName`, `dateTime`, `customer.*`, `report.*`, `metrics.*`,
`tickets.*`, `software.*`, `patching.*`, `certificates.*`. The default
template ("Standard monthly report", installed by migration) uses all of
them and is the best worked example.

### Decisions taken

- **Who is emailed:** the customer's *active* portal users who have the
  existing **AMS report** box ticked on Customer Detail. The approve
  dialog lists them first.
- **One report per customer per month.** Deleting a report (admin) hides
  it from the portal at once and frees the month for a new one.
- **Approved means frozen.** No edit, no regenerate. To correct one:
  delete it and generate again.
- **The PDF is streamed through the API**, not handed out as a storage
  link, so the customer's organization is checked on every download.
- **Draft content is a snapshot.** Editing a template never changes
  drafts or reports that already exist.
- **Monitoring JSON shape is not fixed in code.** The seeded shape
  (`availability`, `alerts`, `hosts[]`, `topProblems[]`) is an assumption;
  when the real Zabbix export exists, edit the template's tags to match.

### Tests

`cd api && .venv/bin/pytest` — 177 tests. The 67 in `reports/tests.py`
start with isolation: a customer sees only their own approved reports
(by list and by guessed id), report content holds only that customer's
data, and only that customer's flagged users are notified. Four guards
were mutation-checked (approved-only filter, organization filter on
installed software, organization filter on recipients, month filter on
metrics): removing any one fails tests. The delivery-key tests were
checked the same way (revoked-key filter, future-month check, the key
permission, soft-deleted customers).

`infra/scripts/portal-smoke.py --env personal-dev` now also generates,
approves, downloads and deletes throwaway reports (months 2020-01) for
two customers against the live stack, and creates, uses and revokes a
delivery key.

### Running it in personal-dev

```
infra/scripts/run-task.sh --env personal-dev migrate --noinput
infra/scripts/run-task.sh --env personal-dev seed_synthetic_reports
```

`seed_synthetic_reports` adds a fictional software catalog, installed
software, patch history, planned patching and three months of monitoring
metrics for the six synthetic customers (the last one has no metrics for
the latest month, to show the "not received" case). Then in the
dashboard: **Reports → Generate missing drafts**.

`manage.py generate_reports [--period YYYY-MM]` does the same from the
command line and only creates what is missing.

### Unattended metrics delivery (2026-11-24)

The monitoring server cannot sign in with Cognito, so it gets a
**delivery key**: a long random secret (`amsm_…`) an admin creates on
**Config → Metrics Delivery**. The key is shown once; only its SHA-256 is
stored. One key per server, each revocable on its own.

```
curl --fail-with-body -X POST https://<dashboard host>/api/report-metrics/ingest \
  -H "Authorization: Bearer $AMS_METRICS_KEY" \
  -H "Content-Type: application/json" -d @metrics.json
```

```
{"period": "2026-10",
 "deliveries": [{"customer": "<jira org id>", "metrics": { … }}]}
```

- `customer` is the JIRA organization id (the screen lists them) or the
  dashboard's own organization id. `metrics` is free-form, exactly what
  templates read as `{metrics.…}`. `period` may also be set per delivery.
- A delivery is an upsert per customer + month + source, the same row the
  manual upload writes. Re-sending is always safe.
- Each delivery is judged on its own. All accepted → 200. Any rejected →
  **422**, with the accepted ones still stored, so a cron job notices a
  customer the dashboard does not know. Malformed request → 400; over
  5 MB → 413; future months are rejected.
- **What a key can do: this one POST.** Every other endpoint only accepts
  a staff or customer token, the key returns 401 there, and the ingest
  path does not exist on the portal hostname. It reads nothing back and
  cannot tell which customers exist.
- Drafts already generated keep their figures; regenerate to pick up a
  late delivery.

Still unknown and deliberately not built: the Zabbix-side export script
(it depends on which items and host groups make up a customer), and
whether prod's internal ALB is reachable from the Zabbix server.

### Monthly draft schedule (2026-11-24)

`REPORTS_SCHEDULE_DAY=<1-28>` in an environment file adds one scheduled
Fargate task, `generate_reports`, at 09:00 UTC on that day each month. It
creates last month's missing drafts and nothing else: no approval, no
email, no bucket access. `personal-dev` uses day 2. Set the Zabbix job to
deliver on the 1st so the figures are there first; if they arrive late
the draft shows "no monitoring data" and is regenerated by hand. Logs go
to the API log group under the `ReportsGenerateDrafts` prefix.

Both deployed to `personal-dev` and verified live 2026-11-24: migration
`reports.0003` applied, live smoke 61/61 (nine new checks create a key,
deliver with it, confirm it opens nothing else on either hostname, and
revoke it), rule `cron(0 9 2 * ? *)` enabled, and the scheduled task
definition run once by hand with a read-only command to prove its
network path and database access. First real run: 2026-12-02.

### Looking at the staff screens locally

No Cognito needed — SQLite, synthetic data, authentication bypassed:

```
cd api
export DATABASE_URL=sqlite:///$PWD/local.sqlite3 AUTH_BYPASS=1 DEBUG=True SECRET_KEY=local
.venv/bin/python manage.py migrate && .venv/bin/python manage.py seed_synthetic \
  && .venv/bin/python manage.py seed_synthetic_reports
.venv/bin/python manage.py runserver        # then, in web/:  npm run dev
```

The dashboard's route guard only looks for a token in the tab's session
storage, so in the browser console run
`sessionStorage.setItem('ams-dashboard-id-token', 'local')` and reload.
Approved PDFs land in `api/var/reports/` (git-ignored). The portal has no
such bypass, on purpose.

### Open / not built yet

- ~~How Zabbix delivers the metrics automatically.~~ Receiving side built
  2026-11-24 (delivery keys + ingest endpoint, above). Remaining: the
  export script on the Zabbix side.
- **JIRA ticket summary.** The dashboard only holds open-ticket *counts*.
  A real summary needs ticket detail for the month (a JIRA query) and,
  as discussed, probably an AI step to condense it. `tickets.py` is where
  it plugs in; until then staff write the paragraph in the draft.
- **Real email.** `log` mode everywhere so far. Turning on `ses` needs a
  verified SES identity (and production access, or SES only delivers to
  verified addresses).
- ~~Monthly schedule for `generate_reports`.~~ Built 2026-11-24
  (`REPORTS_SCHEDULE_DAY`, above).
- **Withdrawing an approved report** other than by deleting it; a
  download audit trail; per-customer template choice.
- The non-prod bucket is removed with the stack but must be emptied first.

### Deploy gotcha (2026-11-16)

The first Phase 2 deploy rolled back after 25 minutes ("ECS Deployment
Circuit Breaker was triggered"): `reportlab` had been installed locally
but not added to `api/pyproject.toml`, so every request in the new
container raised `ModuleNotFoundError`. The Dockerfile now runs
`manage.py check` during the image build, which imports every app and the
URL conf — a missing dependency fails the build in a minute instead of
the rollout. To diagnose a rollback like this:
`aws logs tail /ams-dashboard-personal-dev/api --since 1h --filter-pattern Traceback`.
