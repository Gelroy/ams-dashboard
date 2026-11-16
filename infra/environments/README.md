# Deploy environments

One file per deployable environment. `infra/scripts/deploy.sh --env <name>`
and `infra/scripts/run-task.sh --env <name> …` source `<name>.env` and
**refuse to run unless the active AWS profile resolves to `AWS_ACCOUNT_ID`**.
That guard is what keeps a personal-account experiment from ever landing in
the company account (or vice versa).

| Variable | Meaning |
|---|---|
| `AWS_PROFILE` | Named profile in `~/.aws/config` to deploy with |
| `AWS_REGION` | Target region (must be CDK-bootstrapped with qualifier `amsdash01`) |
| `AWS_ACCOUNT_ID` | The account the profile *must* resolve to |
| `STACK` | CloudFormation stack name (`-c stack_name`) |
| `ENVIRONMENT` | `-c environment` — tag value and resource-name suffix (prod = no suffix) |
| `PUBLIC_ALB` | `true` for an internet-facing ALB |
| `ALLOW_PUBLIC_HTTP` | `true` only while there is no certificate at all |
| `ACM_CERT_ARN` | Pre-issued certificate (optional; overrides issuing one) |
| `DOMAIN_NAME` / `HOSTED_ZONE_ID` / `HOSTED_ZONE_NAME` | Issue a cert + create the DNS alias (see stack docstring) |
| `JIRA_SYNC_ENABLED` | `false` disables the scheduled JIRA sync tasks |
| `AURORA_AUTO_PAUSE_MINUTES` | `0` keeps the 0.5 ACU floor; 5–1440 lets Aurora pause to 0 ACU after that many idle minutes |
| `API_DESIRED_COUNT` | API tasks to run; `0` parks the environment |
| `PORTAL_ENABLED` | `true` creates the customer Cognito pool and `portal.<DOMAIN_NAME>` |
| `PORTAL_STAFF_EMAIL_DOMAINS` | Comma-separated domains never invited as customers (default `imt.ca`) |
| `PORTAL_EMAIL_FROM` | Sender for customer emails ("your report is ready"). Must be a verified SES identity. Unset = nothing is sent; recipients are only recorded |

Files are plain `KEY=value` lines (sourced by bash) — no quotes needed, no
secrets allowed.
