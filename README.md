# AMS Dashboard

Internal dashboard for the AMS support team. Replaces the single-file
`tabbed-app.html` prototype with a Django + DRF + React app, deployable to
AWS Fargate behind an internal ALB.

## What's in here

| Directory | What it is |
|---|---|
| `api/` | Django 5 project. Apps: `customers`, `software`, `baskets`, `patching`, `analytics`, `staff`, `activities`. |
| `web/` | React + TypeScript + Vite SPA. |
| `infra/` | AWS CDK Python stack — VPC lookup, Aurora SLv2, Cognito, ALB, Fargate (API + scheduled JIRA syncs). |
| `db/schema.sql` | Machine-generated reference of the live Postgres schema. The Django models + migrations are the source of truth. |
| `docs/DEPLOY.md` | Runbook for the AWS admin: prerequisites, first deploy, post-deploy steps, ops. |
| `Dockerfile` | Multi-stage build (web bundle → Django container). The same image runs the API and the JIRA sync workers. |
| `docker-compose.yml` | Local Postgres for development. Not deployed. |

## For developers

```bash
# Once
docker compose up -d postgres
cd api && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python manage.py migrate
python manage.py createsuperuser     # for /admin

cd ../web && npm install
```

```bash
# Daily
docker compose up -d postgres        # if not already
cd api && source .venv/bin/activate && python manage.py runserver
cd web && npm run dev
# Open http://localhost:5173
```

Auth in dev is bypassed (`AUTH_BYPASS=1` in `api/.env`). Cognito kicks in
when the container runs with `AUTH_BYPASS=0`.

**JIRA sync (optional):** fill in `JIRA_URL`, `JIRA_EMAIL`, `JIRA_TOKEN` in
`api/.env`, then run:

```bash
python manage.py sync_jira_orgs
python manage.py sync_jira_users
python manage.py sync_jira_tickets
```

## For the AWS admin

See [docs/DEPLOY.md](docs/DEPLOY.md). Short version:

```bash
cd infra
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk bootstrap aws://<account>/<region>     # once per account
cdk deploy \
  -c account=<account> -c region=<region> \
  -c vpc_id=vpc-XXXXXXXX \
  -c acm_cert_arn=<ACM cert ARN, optional>
```

Outputs printed at the end include the internal ALB DNS name, Cognito IDs,
and the migration task ARN to run post-deploy.

## Tests

```bash
cd api && pytest -q
cd web && npm run build       # type-checks the SPA
```

## Versioning

This repo uses git tags for release coordination with the AWS admin —
e.g. `v1.0.0`. To deploy a specific version: `git checkout v1.0.0` then
follow the runbook.
