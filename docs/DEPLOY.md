# AMS Dashboard — AWS Deploy Runbook

Audience: the AWS administrator deploying the CDK bundle into our existing
VPC. The application itself is a single Docker image (API + SPA + Django
admin + JIRA sync workers, all in one container) running on Fargate behind
an internal ALB, with Aurora Postgres Serverless v2 for storage and Cognito
for SSO.

## Prerequisites

On the machine you'll run `cdk deploy` from:

- **AWS CLI** v2 configured with credentials that can deploy CloudFormation,
  ECR, ECS, RDS, Cognito, ALB, Secrets Manager, IAM, EC2 (read), Logs in the
  target account/region.
- **Docker** running — CDK builds and pushes the container image during deploy.
- **Node.js 22 or 24 LTS** (CDK CLI runtime).
- **Python 3.13** + `pip`.
- **AWS CDK CLI**: `npm install -g aws-cdk`.

Information needed from your platform / security teams before first deploy:

| Item | Where it goes |
|---|---|
| VPC ID (the shared internal VPC) | `cdk deploy -c vpc_id=vpc-…` |
| AWS account number | `cdk deploy -c account=…` (or `CDK_DEFAULT_ACCOUNT`) |
| AWS region | `cdk deploy -c region=…` (or `CDK_DEFAULT_REGION`) |
| ACM certificate ARN (optional for first deploy) | `cdk deploy -c acm_cert_arn=arn:aws:acm:…` |
| Internal DNS name to CNAME at the ALB | DNS is provisioned outside CDK; deploy outputs the ALB DNS name to point at |
| Environment label (`prod`, `staging`, …) | `cdk deploy -c environment=prod` (default: `prod`) |
| Company-specific tags (CostCenter, Owner, etc.) | `cdk deploy -c tags='{"CostCenter":"4321","Owner":"AMS-IT"}'` |
| Private subnet IDs (when VPC subnets aren't CDK-tagged) | `cdk deploy -c private_subnet_ids=subnet-a,subnet-b -c availability_zones=us-west-2a,us-west-2b` |

### When you hit "There are no private subnet groups in this VPC"

CDK's default `Vpc.from_lookup` identifies subnets by the
`aws-cdk:subnet-type` tag. VPCs your platform team owns and provisioned
outside of CDK usually don't carry that tag, and the deploy errors out.

Fix: pass the private subnet IDs (and matching AZs) explicitly:

```bash
# Find candidates — private subnets typically don't route 0.0.0.0/0 to
# an IGW. Quick listing:
aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=vpc-XXXXXXXX" \
  --query 'Subnets[].{ID:SubnetId,AZ:AvailabilityZone,CIDR:CidrBlock,Public:MapPublicIpOnLaunch}' \
  --output table

# Then deploy with explicit IDs (at least 2 subnets in different AZs):
cdk deploy AmsDashboardStack \
  -c vpc_id=vpc-XXXXXXXX \
  -c private_subnet_ids=subnet-aaaaaaaa,subnet-bbbbbbbb \
  -c availability_zones=us-west-2a,us-west-2b
```

The subnets you supply must have **outbound internet egress** (NAT
gateway or equivalent) so the API can reach Cognito, the Fargate
tasks can pull the container image, and the JIRA sync workers can
reach Atlassian.

### Tagging

The stack applies these tags to every taggable resource by default:

| Tag | Value |
|---|---|
| `Application` | `ams-dashboard` |
| `Environment` | from `-c environment=…` (default `prod`) |
| `ManagedBy` | `CDK` |

To layer in your company's tagging requirements, pass a JSON object via
the `tags` context — values are applied stack-wide and override defaults
on key collision:

```bash
cdk deploy \
  -c vpc_id=vpc-XXXXXXXX \
  -c tags='{"CostCenter":"4321","Owner":"AMS-IT","DataClass":"Internal","Compliance":"None"}'
```

If `acm_cert_arn` is omitted, the ALB serves plain HTTP for the initial
smoke-test. Add the cert and re-deploy for HTTPS.

## One-time setup

```bash
# 1. Pull the bundle and set up the CDK virtual env
cd ams-dashboard/infra
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Bootstrap CDK in the target account/region (only needs to be done once
#    per account+region per AWS organization). The principal running this
#    needs broad permissions — typically AdministratorAccess for the
#    duration of the bootstrap.
cdk bootstrap aws://<ACCOUNT>/<REGION>
```

### Grant the routine-deploy IAM principal its permissions

After bootstrap, day-to-day `cdk deploy` only needs the ability to assume
the bootstrapped roles plus a few read-only context lookups. The repo
ships a helper script that creates a least-privilege managed policy and
attaches it to a chosen IAM user or role:

```bash
# Attach to an IAM user:
infra/scripts/grant-cdk-deploy-perms.sh \
  --account <ACCOUNT_ID> --user <USERNAME>

# …or to a role (e.g. for CI/CD):
infra/scripts/grant-cdk-deploy-perms.sh \
  --account <ACCOUNT_ID> --role <ROLENAME>

# Preview the policy JSON without making any changes:
infra/scripts/grant-cdk-deploy-perms.sh \
  --account <ACCOUNT_ID> --user <USERNAME> --dry-run
```

The script must be run by a principal that can manage IAM in the target
account (`iam:CreatePolicy`, `iam:CreatePolicyVersion`, `iam:Attach*Policy`).
It's safe to re-run — it updates the existing policy in place and prunes
the oldest non-default version when IAM's 5-version limit is hit.

## First deploy

```bash
cd ams-dashboard/infra
source .venv/bin/activate

cdk deploy \
  -c account=<ACCOUNT> \
  -c region=<REGION> \
  -c vpc_id=vpc-XXXXXXXX \
  -c acm_cert_arn=arn:aws:acm:<region>:<account>:certificate/<id>  # optional
```

The deploy will:
- Build the multi-stage Docker image and push it to an ECR repository
  managed by CDK's asset system.
- Create the Aurora cluster, Cognito user pool, secrets, ECS cluster,
  ALB, Fargate service, scheduled JIRA sync tasks, and the standalone
  migration task definition.
- Output the values you'll need (see below).

Note the **outputs** printed at the end:

```
AmsDashboardStack.AlbDnsName          = internal-...elb.amazonaws.com
AmsDashboardStack.ClusterName         = AmsDashboardStack-Cluster...
AmsDashboardStack.ApiServiceName      = AmsDashboardStack-ApiServiceService...
AmsDashboardStack.MigrationTaskArn    = arn:aws:ecs:...:task-definition/...:1
AmsDashboardStack.UserPoolId          = us-east-1_xxxxx
AmsDashboardStack.AppClientId         = xxxxxxxxxxxxxx
AmsDashboardStack.DbClusterEndpoint   = ...rds.amazonaws.com
AmsDashboardStack.DjangoSecretArn     = arn:aws:secretsmanager:...
AmsDashboardStack.JiraSecretArn       = arn:aws:secretsmanager:...
```

## Post-deploy (in order)

### 1. Fill the JIRA secret

```bash
aws secretsmanager put-secret-value \
  --secret-id "<JiraSecretArn>" \
  --secret-string '{
    "JIRA_URL":   "https://yourcompany.atlassian.net",
    "JIRA_EMAIL": "ams-service@yourcompany.com",
    "JIRA_TOKEN": "<the API token>"
  }'
```

### 2. Run the initial migration

The Django schema must be applied before the API can talk to the DB.

```bash
# Get a subnet ID (private subnet) and the API service's security group ID:
SUBNET=$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=vpc-XXXXXXXX" "Name=tag:aws-cdk:subnet-type,Values=Private" \
  --query 'Subnets[0].SubnetId' --output text)
SG=$(aws ecs describe-services --cluster <ClusterName> \
  --services <ApiServiceName> \
  --query 'services[0].networkConfiguration.awsvpcConfiguration.securityGroups[0]' \
  --output text)

aws ecs run-task \
  --cluster <ClusterName> \
  --task-definition <MigrationTaskArn> \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$SG],assignPublicIp=DISABLED}"
```

Watch progress in CloudWatch Logs at `/ams-dashboard/api` (stream prefix
`migrate`).

### 3. Restart the API service so it picks up the JIRA secret

```bash
aws ecs update-service --cluster <ClusterName> --service <ApiServiceName> --force-new-deployment
```

### 4. Create the first Cognito users

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <UserPoolId> \
  --username someone@yourcompany.com \
  --user-attributes Name=email,Value=someone@yourcompany.com Name=email_verified,Value=true \
  --temporary-password 'ChangeMe123!'
```

(Repeat for each team member. They'll set a real password on first login.)

### 5. Wire DNS

Create a CNAME for your internal hostname (e.g. `ams.internal.company.com`)
pointing at `<AlbDnsName>`.

### 6. Verify

```bash
curl -fsS https://ams.internal.company.com/health     # → {"status":"ok"}
```

Open the URL in a browser. The Cognito login flow should redirect you,
and after login you should see the Customers panel.

## Subsequent deploys

For code changes, the admin just re-runs:

```bash
cd ams-dashboard/infra
source .venv/bin/activate
cdk deploy -c account=<ACCOUNT> -c region=<REGION> -c vpc_id=vpc-XXXXXXXX
```

CDK rebuilds the image, pushes a new tag to ECR, and updates the Fargate
service with a rolling deploy. The circuit breaker rolls back automatically
if the new tasks fail their health checks.

**Run migrations again** after each deploy that includes new Django
migrations (any `*_initial.py` or numbered migration file under
`api/<app>/migrations/`). Same `aws ecs run-task` command as step 2 above.

## Operations

| Need | Where |
|---|---|
| API logs | CloudWatch Logs → `/ams-dashboard/api` |
| JIRA sync logs | CloudWatch Logs → `/ams-dashboard/jira-sync` |
| Database metrics | RDS console → cluster `Db` |
| Active Fargate tasks | ECS console → cluster `<ClusterName>` |
| Trigger a manual JIRA sync | `aws ecs run-task` against `JiraSyncOrgs/Users/Tickets` task definitions (see ECS console for ARNs) |

## Tearing it down

```bash
cdk destroy -c account=<ACCOUNT> -c region=<REGION> -c vpc_id=vpc-XXXXXXXX
```

The Aurora cluster has `removalPolicy: SNAPSHOT` so a final snapshot will
be taken; the Cognito user pool has `RETAIN` and must be manually deleted
if no longer needed.
