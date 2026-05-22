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
| VPC ID (the shared internal VPC) | `cdk deploy -c vpc_id=vpc-…` (or `-c create_vpc=true` to have the stack provision a new VPC — see below) |
| AWS account number | `cdk deploy -c account=…` (or `CDK_DEFAULT_ACCOUNT`) |
| AWS region | `cdk deploy -c region=…` (or `CDK_DEFAULT_REGION`) |
| ACM certificate ARN (optional for first deploy) | `cdk deploy -c acm_cert_arn=arn:aws:acm:…` |
| Internal DNS name to CNAME at the ALB | DNS is provisioned outside CDK; deploy outputs the ALB DNS name to point at |
| Environment label (`prod`, `staging`, …) | `cdk deploy -c environment=prod` (default: `prod`) |
| Company-specific tags (CostCenter, Owner, etc.) | `cdk deploy -c tags='{"CostCenter":"4321","Owner":"AMS-IT"}'` |
| Private subnet IDs (when VPC subnets aren't CDK-tagged) | `cdk deploy -c private_subnet_ids=subnet-a,subnet-b -c availability_zones=us-west-2a,us-west-2b` |

### Deploying into a fresh sub account (no existing VPC)

When the target account is empty — e.g. a new sub account your AWS admin
spun up for this project — there's no shared VPC to consume. Pass
`-c create_vpc=true` and the stack will provision a new VPC alongside
everything else:

```bash
cdk deploy \
  -c account=<ACCOUNT> \
  -c region=<REGION> \
  -c create_vpc=true
```

The created VPC has:
- 2 AZs (`max_azs=2`)
- Public subnets in each AZ
- Private-with-egress subnets in each AZ (where Aurora + the internal ALB live)
- **No NAT gateway by default** — Fargate tasks run in the public subnets
  with `assign_public_ip=True`. They can reach ECR / Atlassian / Cognito via
  the IGW, but the task security group still blocks all inbound except from
  the ALB SG. Saves ~$33/mo vs a NAT-based topology.

To add NAT instead (e.g. policy forbids public IPs on workloads), pass
`-c nat_gateways=1` (~$33/mo) or `-c nat_gateways=2` for HA across both
AZs (~$66/mo). Tasks then move to the private subnets and don't get
public IPs.

Do not combine `-c create_vpc=true` with `-c vpc_id=…` — they're mutually
exclusive.

`cdk destroy` will tear the VPC down along with the rest of the stack
(the Aurora cluster's final snapshot and the Cognito user pool are
retained per their removal policies).

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

### Alternative #1: bootstrap via AWS CLI + a CloudFormation template

When the admin can't or won't install Node + the CDK CLI, the repo
includes a script that does the same job using only AWS CLI calls
against a pre-generated CloudFormation template at
`infra/bootstrap-template.yaml`:

```bash
cd ams-dashboard
./infra/scripts/admin-bootstrap-cli.sh <ACCOUNT_ID> <REGION>

# Example:
./infra/scripts/admin-bootstrap-cli.sh 048189774358 us-west-2
```

### Alternative #2: bootstrap with raw AWS CLI calls (no CloudFormation at all)

When CloudFormation itself is off the table — for example, the admin's
permissions or org policy don't allow CFN stack creation — every
resource can be created with direct `aws iam` / `aws s3api` / `aws ecr`
/ `aws kms` / `aws ssm` calls instead. The repo ships a script that
runs each call in order:

```bash
./infra/scripts/admin-bootstrap-raw-cli.sh <ACCOUNT_ID> <REGION>

# Example:
./infra/scripts/admin-bootstrap-raw-cli.sh 048189774358 us-west-2
```

It creates (and prints, as it goes):

1. The 5 IAM roles (`file-publishing`, `image-publishing`, `lookup`,
   `cfn-exec`, `deploy`) with trust + permission policies.
2. A KMS key + alias for assets-bucket encryption.
3. The S3 staging bucket (versioning + SSE-KMS + public access block +
   lifecycle + deny-non-SSL bucket policy).
4. The ECR container-assets repository (immutable tags + lifecycle +
   Lambda / EMR-Serverless pull policies).
5. The `/cdk-bootstrap/<qualifier>/version` SSM parameter.

The end state is identical to `cdk bootstrap` / the CFN-based script.
The admin's principal needs `iam:CreateRole`, `iam:PutRolePolicy`,
`iam:AttachRolePolicy`, `iam:TagRole`, `s3:CreateBucket` + bucket
config actions, `ecr:CreateRepository` + policy actions, `kms:*` for
key creation, `ssm:PutParameter`, plus a brief read on the created
roles to fetch ARNs.

Not idempotent — if the script fails partway through, delete the
partially-created resources before retrying.

### Permissions that can be revoked after initial setup

Bootstrap and the first deploy require broad permissions; after that
the same operations don't need them again. The admin can prune the
following from whatever managed policy / SSO permission set / inline
policy was used to run the bootstrap script:

**Safe to revoke immediately after bootstrap completes**

These are only used by `admin-bootstrap-raw-cli.sh` (or `cdk bootstrap`):

| Permission | What used it |
|---|---|
| `iam:CreateRole`, `iam:DeleteRole` | Creating the 5 cdk-*-role-* IAM roles |
| `iam:PutRolePolicy`, `iam:DeleteRolePolicy`, `iam:GetRolePolicy` | Attaching inline policies to those roles |
| `iam:AttachRolePolicy`, `iam:DetachRolePolicy` | Attaching the AWS-managed `ReadOnlyAccess` and `AdministratorAccess` policies |
| `iam:TagRole`, `iam:UntagRole`, `iam:GetRole` | Bootstrap-role tagging and ARN lookup |
| `s3:CreateBucket`, `s3:PutBucketVersioning`, `s3:PutBucketPolicy`, `s3:PutBucketPublicAccessBlock`, `s3:PutEncryptionConfiguration`, `s3:PutLifecycleConfiguration` | Creating the cdk-amsdash01-assets-* staging bucket |
| `ecr:CreateRepository`, `ecr:PutLifecyclePolicy`, `ecr:SetRepositoryPolicy` | Creating the cdk-amsdash01-container-assets-* repo |
| `kms:CreateKey`, `kms:CreateAlias`, `kms:DescribeKey` | Creating the assets-bucket encryption key |
| `ssm:PutParameter` | Writing the `/cdk-bootstrap/amsdash01/version` marker |

Once bootstrap is done, those resources exist and don't need to be
created again. The cdk-*-role-* roles are used at every subsequent
deploy (`sts:AssumeRole` does that), but no further IAM-create perms
are needed.

**Needed for the first `cdk deploy` (running CloudFormation)**

Initial stack creation runs entirely through `cdk-amsdash01-cfn-exec-role`,
which has `AdministratorAccess`. So no extra admin perms are needed at
deploy time — CloudFormation does the creating, not the admin or Ron.

**Must remain (routine deploys + ongoing operation)**

These are what Ron's user keeps via `grant-cdk-deploy-perms.sh`:

- `sts:AssumeRole` on the four `cdk-amsdash01-*-role-*` roles
- `ec2:Describe*` (VPCs, subnets, AZs, route tables, SGs, VPN GWs) — used by CDK at synth time for context lookups
- `ssm:GetParameter*` on `/cdk-bootstrap/*` — every deploy reads the bootstrap version
- `cloudformation:Describe*`/`GetTemplate`/`ListStackResources` scoped to the AmsDashboardStack and AmsDashboardCdkToolkit stacks

**Ad-hoc operational permissions (grant on demand, then revoke)**

| When | What | Why |
|---|---|---|
| Populating the JIRA secret first time, or rotating creds | `secretsmanager:PutSecretValue` on the JIRA secret ARN | One-off; revoke after each rotation |
| Creating Cognito users for new team members | `cognito-idp:AdminCreateUser`, `AdminSetUserPassword` on the user pool | Periodic; can be granted to whoever onboards staff |
| Running the migration task after a deploy | `ecs:RunTask` + `iam:PassRole` on the task roles, scoped to the migration task definition | Per deploy; Ron's principal would normally have this |
| Re-bootstrap (e.g., new region) | Everything in the first table above | Reattach the bootstrap perms, run the script, revoke again |

**TL;DR for the admin**

After bootstrap succeeds and `cdk deploy` finishes once, drop all
`iam:Create*`, `iam:Put*`, `iam:Attach*`, `s3:Create*`, `s3:Put*`,
`ecr:Create*`, `kms:Create*`, and `ssm:PutParameter` perms from their
own user. They never need them again unless you re-bootstrap a new
account/region or rotate a secret. Ron's routine-deploy policy
remains in place untouched.

### About the remaining `"Resource": "*"` entries

Every IAM policy in the bootstrap and grant-perms scripts is scoped to
specific resource ARNs where AWS supports it. A few `"Resource": "*"`
entries remain — each is either required by AWS or an intentional
broad safeguard. The complete list:

| Where | Statement | Why `*` is correct |
|---|---|---|
| `admin-bootstrap-raw-cli.sh` — KMS key policy | All statements | A KMS *key policy* is attached to one key; `*` always means "this key." It's the only valid form for key policies. |
| `admin-bootstrap-raw-cli.sh` — image-publishing-role | `AuthToken` (`ecr:GetAuthorizationToken`) | AWS docs: "calls to this action ignore the resource argument." `*` is the only legal value. Push permissions on the actual repository are scoped to the repo ARN in the same policy. |
| `admin-bootstrap-raw-cli.sh` — lookup-role | `DontReadSecrets` (Deny `kms:Decrypt`) | Intentional broad **Deny**. The role gets `ReadOnlyAccess` which includes `kms:Decrypt`; this deny strips that across all keys. Scoping a deny narrows the safeguard. |
| `admin-bootstrap-raw-cli.sh` — deploy-role | `CliCallerIdentity` (`sts:GetCallerIdentity`) | The action has no resource form. `*` is required. |
| `grant-cdk-deploy-perms.sh` | `EC2ReadOnlyForContextLookups` | `ec2:Describe*` actions don't support resource-level permissions; AWS requires `*`. |

Everything else — S3, ECR push, KMS data-key operations, CloudFormation
stack ops, SSM parameter reads, IAM `PassRole`, `sts:AssumeRole` — is
constrained to the specific bucket / repo / stack / parameter / role
ARNs we created.

The script:

1. Creates CloudFormation stack `AmsDashboardCdkToolkit` from the
   committed template.
2. Waits for `CREATE_COMPLETE` (typically 2–4 minutes).
3. Verifies the `/cdk-bootstrap/amsdash01/version` SSM marker exists.
4. Lists the 5 IAM roles it created.

The admin's credentials still need to be able to create IAM roles
+ S3 buckets + ECR repos + SSM parameters + CloudFormation stacks —
CloudFormation itself does the heavy lifting; the admin's principal
just needs to issue the `cloudformation:CreateStack` call with
`CAPABILITY_NAMED_IAM` and pass the right service permissions
through. `AdministratorAccess` is sufficient and is what CDK would
have requested anyway.

To regenerate `bootstrap-template.yaml` when the CDK version changes:

```bash
cd infra && source .venv/bin/activate
cdk bootstrap --show-template > bootstrap-template.yaml
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

Match the subnet type and `assignPublicIp` to the deployed topology:
- **Default (`create_vpc=true`, no NAT):** Public subnets, `assignPublicIp=ENABLED`
- **NAT path (`-c nat_gateways>=1`, or existing-VPC with NAT):** Private subnets, `assignPublicIp=DISABLED`

```bash
# Default no-NAT topology (substitute Private/DISABLED if you set nat_gateways>0):
SUBNET=$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=vpc-XXXXXXXX" "Name=tag:aws-cdk:subnet-type,Values=Public" \
  --query 'Subnets[0].SubnetId' --output text)
SG=$(aws ecs describe-services --cluster <ClusterName> \
  --services <ApiServiceName> \
  --query 'services[0].networkConfiguration.awsvpcConfiguration.securityGroups[0]' \
  --output text)

aws ecs run-task \
  --cluster <ClusterName> \
  --task-definition <MigrationTaskArn> \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$SG],assignPublicIp=ENABLED}"
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
