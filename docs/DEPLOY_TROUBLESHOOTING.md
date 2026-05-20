# AMS Dashboard — Deploy Troubleshooting Log

Captured during the first deployment to AWS account `048189774358` in
`us-west-2` against the company shared VPC `vpc-efd8178b`. Each section
records the symptom, what was actually happening, and what we changed
to fix it. If you hit the same issue again, jump to that section.

## Quick index

| Symptom (verbatim or near it) | Section |
|---|---|
| `NAME_CONFLICT_VALIDATION_VALIDATION_ERROR` during `cdk bootstrap` | [Bootstrap name collision](#bootstrap-name-collision) |
| `Expected environment name in format 'aws://<account>/<region>', got: true` | [Bootstrap arg parsing](#bootstrap-arg-parsing) |
| `ModuleNotFoundError: No module named 'aws_cdk'` | [CDK Python module missing](#cdk-python-module-missing) |
| `ValueError: Set vpc_id context …` during `cdk bootstrap` | [vpc_id required at bootstrap](#vpc_id-required-at-bootstrap) |
| `This app contains no stacks` followed by no further output | [Same as above](#vpc_id-required-at-bootstrap) |
| `SSM parameter /cdk-bootstrap/amsdash01/version not found` | [Bootstrap qualifier mismatch](#bootstrap-qualifier-mismatch) |
| Admin won't grant `iam:CreateRole` | [Bootstrap without role-create perms](#bootstrap-without-role-create-perms) |
| Admin objects to `Resource: "*"` in policies | [Scoping IAM policies](#scoping-iam-policies) |
| `There are no private subnet groups in this VPC` | [VPC subnets not tagged](#vpc-subnets-not-tagged) |
| `current credentials could not be used to assume …role …Proceeding anyway` | [Missing assume-role policy](#missing-assume-role-policy) |
| `docker login … exited with error code 1` | [Docker daemon not running](#docker-daemon-not-running) |
| `ECS Deployment Circuit Breaker was triggered` | [Fargate tasks failing to start](#fargate-tasks-failing-to-start) |
| `Stack with id AmsDashboardStack does not exist` after a failed deploy | [Rollback ate the resources](#rollback-ate-the-resources) |
| Stack stuck in `ROLLBACK_COMPLETE` | [ROLLBACK_COMPLETE blocks redeploy](#rollback_complete-blocks-redeploy) |
| `ResourceInitializationError: unable to retrieve secret from asm` | [No network path to AWS APIs](#no-network-path-to-aws-apis) |

---

## Bootstrap name collision

**Symptom:** `cdk bootstrap` exits with
`NAME_CONFLICT_VALIDATION_VALIDATION_ERROR`.

**Cause:** The default CDK bootstrap qualifier (`hnb659fds`) was
already in use in this account/region by another team. Their resources
collided with the ones our bootstrap was trying to create
(`cdk-hnb659fds-assets-…`, `cdk-hnb659fds-*-role-…`, etc.).

**Fix:** Use a custom qualifier per application and a custom toolkit
stack name so multiple bootstraps can coexist in one account/region.

```bash
cdk bootstrap aws://<ACCOUNT>/<REGION> \
  --qualifier amsdash01 \
  --toolkit-stack-name AmsDashboardCdkToolkit
```

The qualifier (`amsdash01`) must also be threaded into the application
stack so it looks up the matching role names. This is wired in
`infra/cdk.json` (`@aws-cdk/core:bootstrapQualifier`) and applied via
`DefaultStackSynthesizer(qualifier=…)` in `infra_stack.py`.

---

## Bootstrap arg parsing

**Symptom:** `Expected environment name in format 'aws://<account>/<region>', got: true`.

**Cause:** Either the placeholder `<ACCOUNT>` / `<REGION>` was passed
literally (zsh / bash interpret `<` and `>` as redirection), or
another flag earlier in the command line consumed the URL as its
argument.

**Fix:** Use real values, quoted, with no other CLI flags between
`bootstrap` and the URL.

```bash
ACCT=$(aws sts get-caller-identity --query Account --output text)
REGION=$(aws configure get region)
cdk bootstrap "aws://${ACCT}/${REGION}"
```

---

## CDK Python module missing

**Symptom:** `ModuleNotFoundError: No module named 'aws_cdk'` when CDK
runs `python3 app.py`.

**Cause:** The Python virtualenv isn't activated in the shell running
`cdk`, so the requirements installed into the venv aren't on
`sys.path`.

**Fix:**

```bash
cd ~/<repo>/infra
source .venv/bin/activate
which python                       # should be inside .venv
python -c "import aws_cdk"         # should not error
pip install -r requirements.txt    # if it still errors
```

Any new shell that's going to run `cdk` needs the activate step first.

---

## vpc_id required at bootstrap

**Symptom:** `cdk bootstrap` errors with
`ValueError: Set vpc_id context (cdk deploy -c vpc_id=vpc-xxx)` or
exits early with `This app contains no stacks` and no further output.

**Cause:** CDK CLI loads `app.py` on every command, including
`bootstrap`. Our app used to raise on missing `vpc_id` before bootstrap
could proceed. Even the friendly "no stacks" message didn't tell the
whole story — the bootstrap operation itself never ran.

**Fix:** `infra/app.py` now skips instantiating `AmsDashboardStack`
when `vpc_id` context isn't set. Bootstrap proceeds independently;
deploy/synth/diff still require the context.

To verify bootstrap actually completed (not just exited cleanly):

```bash
aws cloudformation describe-stacks --region <REGION> \
  --stack-name AmsDashboardCdkToolkit --query 'Stacks[0].StackStatus'
# Want: CREATE_COMPLETE
aws ssm get-parameter --region <REGION> \
  --name /cdk-bootstrap/amsdash01/version
# Want: a Value (e.g. "31")
```

---

## Bootstrap qualifier mismatch

**Symptom:** `cdk deploy` errors with
`SSM parameter /cdk-bootstrap/amsdash01/version not found. Has the environment been bootstrapped?`

**Cause:** Either bootstrap never actually completed under the
`amsdash01` qualifier (see [previous section](#vpc_id-required-at-bootstrap)),
or bootstrap was done under a different qualifier than what the stack
expects.

**Fix:** Confirm with the SSM check above, then either re-bootstrap
with the right qualifier or adjust `infra/cdk.json` to match what
exists.

---

## Bootstrap without role-create perms

**Context:** Our AWS admin couldn't grant `iam:CreateRole` to the
deployer, and didn't want to install Node + CDK CLI to run
`cdk bootstrap` themselves.

**Three paths the repo supports**, in order of admin preference:

1. **CDK CLI** (default). Admin runs `cdk bootstrap` once with their
   privileged credentials. After that the deployer assumes the
   bootstrapped roles for routine `cdk deploy`.

2. **CloudFormation template + AWS CLI.** Admin runs
   `infra/scripts/admin-bootstrap-cli.sh` which submits the
   pre-generated CFN template at `infra/bootstrap-template.yaml`. One
   `aws cloudformation create-stack` call; CFN does all the resource
   creation. Admin needs `cloudformation:CreateStack` +
   `CAPABILITY_NAMED_IAM`.

3. **Pure AWS CLI, no CloudFormation.** Admin runs
   `infra/scripts/admin-bootstrap-raw-cli.sh` which issues direct
   `aws iam` / `aws s3api` / `aws ecr` / `aws kms` / `aws ssm` calls
   in order. Useful when CFN itself is off the table or the admin
   wants to review every resource as it's created. **This is what we
   ended up using for this deploy.**

All three create the same end state: the toolkit stack, 5 IAM roles
(file-publishing, image-publishing, lookup, deploy, cfn-exec), assets
S3 bucket with KMS encryption, container-assets ECR repo, and the
`/cdk-bootstrap/amsdash01/version` SSM marker.

---

## Scoping IAM policies

**Context:** Admin objected to `Resource: "*"` entries in the
bootstrap and grant-deploy policies.

**What we did:** Audited each instance and scoped to specific ARNs
where AWS supports it. The remaining `*` entries are either required
by AWS (the action has no resource form) or intentionally broad
denies. See the "About the remaining `Resource: *` entries" table in
`docs/DEPLOY.md` for the full audit.

**Permissions that can be revoked after initial setup:** Documented
in the "Permissions that can be revoked" section of `docs/DEPLOY.md`.
Short version: all bootstrap-time IAM/S3/ECR/KMS/SSM **create**
permissions can be revoked from the admin's user once the bootstrap
finishes. The deployer's routine-deploy policy stays in place.

---

## VPC subnets not tagged

**Symptom:** `cdk deploy` errors with `There are no private subnet groups in this VPC`.

**Cause:** `Vpc.from_lookup` identifies subnets by the
`aws-cdk:subnet-type` tag. The company's shared VPC, provisioned
outside of CDK, doesn't carry that tag.

**Fix:** Pass the subnet IDs (and matching AZs) explicitly via
context. The stack switches to `Vpc.from_vpc_attributes` when
`private_subnet_ids` is set.

```bash
aws ec2 describe-subnets --filters "Name=vpc-id,Values=<VPC_ID>" \
  --query 'Subnets[].{ID:SubnetId,AZ:AvailabilityZone,CIDR:CidrBlock}' \
  --output table

cdk deploy AmsDashboardStack \
  -c vpc_id=<VPC_ID> \
  -c private_subnet_ids=subnet-aaa,subnet-bbb \
  -c availability_zones=us-west-2c,us-west-2b
```

At least two subnets across two AZs are required (ALB minimum;
enforced in our stack with a validation check).

---

## Missing assume-role policy

**Symptom:** During `cdk deploy`, output contains:

```
current credentials could not be used to assume
'arn:aws:iam::<acct>:role/cdk-amsdash01-image-publishing-role-…',
but are for the right account. Proceeding anyway.
```

**Cause:** The deployer's IAM user doesn't have `sts:AssumeRole` on
the bootstrapped CDK roles. CDK falls back to using the user's direct
credentials, which usually lack ECR/S3/CFN perms needed.

**Fix:** Admin runs `infra/scripts/grant-cdk-deploy-perms.sh` to
attach the `AmsDashboardCdkDeploy` managed policy to the deployer.
That policy grants `sts:AssumeRole` on the four `cdk-amsdash01-*-role-…`
ARN patterns plus the read-only context lookups the deployer needs.

```bash
USER=$(aws sts get-caller-identity --query Arn --output text | awk -F'/' '{print $NF}')
infra/scripts/grant-cdk-deploy-perms.sh --account <ACCT> --user $USER
sleep 30   # IAM propagation
```

---

## Docker daemon not running

**Symptom:** `docker login --username AWS --password-stdin <…> exited with error code 1`
during `cdk deploy`. CDK doesn't surface the actual docker error.

**Cause:** Docker daemon not running on the deployer's machine (CDK
builds the container image as a Docker asset).

**Diagnosis:**

```bash
docker info | head -5            # errors if daemon isn't running
aws ecr get-login-password --region <REGION> | \
  docker login --username AWS --password-stdin <ACCT>.dkr.ecr.<REGION>.amazonaws.com
# This shows the real docker error
```

**Fix:**

```bash
sudo systemctl status docker
sudo systemctl start docker
sudo systemctl enable docker

# If permission-denied on /var/run/docker.sock:
sudo usermod -aG docker $USER     # then log out and back in
```

---

## Fargate tasks failing to start

**Symptom:** Deploy fails at `AWS::ECS::Service` with
`ECS Deployment Circuit Breaker was triggered`.

**Cause:** Tasks repeatedly failed to start, the circuit breaker
gave up. The actual reason is in the stopped tasks' `stoppedReason`
or the container's CloudWatch logs.

**Debug-friendly stack settings** (already committed):
- `infra/infra/infra_stack.py` sets `circuit_breaker(rollback=False)`
  so failed services aren't torn down (the stopped tasks stay visible).
- Log groups use `RemovalPolicy.RETAIN` so container stdout survives
  stack rollback.

**Use `--no-rollback`** on the next `cdk deploy` so CloudFormation
leaves failed resources in place:

```bash
cdk deploy AmsDashboardStack --no-rollback -c …
```

**Diagnostic recipe** for a failed service:

```bash
REGION=us-west-2
CLUSTER=$(aws cloudformation describe-stack-resources --region $REGION \
  --stack-name AmsDashboardStack \
  --query "StackResources[?ResourceType=='AWS::ECS::Cluster'].PhysicalResourceId | [0]" --output text)
SERVICE=$(aws cloudformation describe-stack-resources --region $REGION \
  --stack-name AmsDashboardStack \
  --query "StackResources[?ResourceType=='AWS::ECS::Service'].PhysicalResourceId | [0]" --output text)

# Stop reasons for the most recent failed tasks:
aws ecs list-tasks --region $REGION --cluster $CLUSTER \
  --service-name $SERVICE --desired-status STOPPED \
  --query 'taskArns[0:3]' --output text | tr '\t' '\n' | while read T; do
    aws ecs describe-tasks --region $REGION --cluster $CLUSTER --tasks "$T" \
      --query 'tasks[0].{StoppedReason:stoppedReason,Containers:containers[*].{Reason:reason,ExitCode:exitCode}}'
  done

# Container stdout (if the task got far enough to write any):
aws logs tail /ams-dashboard/api --region $REGION --since 30m --format short
```

---

## Rollback ate the resources

**Symptom:** After a failed first deploy, follow-up queries return
`Stack with id AmsDashboardStack does not exist` even though CDK said
the stack failed.

**Cause:** CloudFormation rolled the failed CREATE back; with no
prior successful state to roll back to, all stack resources were
deleted. This is the default CFN behavior for a failed CREATE.

**Fix going forward:** Use `cdk deploy --no-rollback` for first
deploys. CFN leaves failed resources in place so you can describe
them. Combined with our `RemovalPolicy.RETAIN` log group, container
logs are also preserved.

---

## ROLLBACK_COMPLETE blocks redeploy

**Symptom:** Subsequent `cdk deploy` attempts fail because the stack
sits in `ROLLBACK_COMPLETE`.

**Cause:** CloudFormation policy — a stack in `ROLLBACK_COMPLETE`
(failed first create that couldn't be rolled forward) is a terminal
state. CFN will not accept any update to it. The stack must be
deleted before a new create.

**Fix:**

```bash
aws cloudformation delete-stack --region <REGION> --stack-name AmsDashboardStack
aws cloudformation wait stack-delete-complete --region <REGION> --stack-name AmsDashboardStack

# Then re-run cdk deploy
```

(`cdk destroy` does the same thing under the hood.)

---

## No network path to AWS APIs

**Symptom:** ECS task `stoppedReason` =
`ResourceInitializationError: unable to retrieve secret from asm:
There is a connection issue between the task and AWS Secrets Manager.
… https response error StatusCode: 0 … context deadline exceeded`.

CloudWatch log stream is empty — the container never even started.

**Cause:** The Fargate task fired up, tried to fetch its secrets via
the Secrets Manager API endpoint, and got no network response. The
chosen subnets have no path to AWS service APIs from a private IP.

**Diagnosis path we walked:**

1. Check route tables on the chosen subnets:
   ```bash
   for SUBNET in subnet-b3cdc9ea subnet-dc46aeaa; do
     aws ec2 describe-route-tables --region us-west-2 \
       --filters "Name=association.subnet-id,Values=$SUBNET" \
       --query 'RouteTables[0].Routes[?DestinationCidrBlock==`0.0.0.0/0`]' \
       --output table
   done
   ```
   Got back empty results.

2. Check the VPC's main route table (subnets without explicit
   association use this):
   ```bash
   aws ec2 describe-route-tables --region us-west-2 \
     --filters "Name=vpc-id,Values=vpc-efd8178b" \
     --query 'RouteTables[].{RT:RouteTableId,Main:Associations[?Main==`true`]|[0].Main,Routes:Routes[*].[DestinationCidrBlock,GatewayId,NatGatewayId,TransitGatewayId]}' \
     --output yaml
   ```
   Found the main RT had `0.0.0.0/0 → igw-95e1c1f0`. So the VPC has
   an IGW route — but our tasks have `assignPublicIp=DISABLED` (correct
   for an internal app), so they can't actually use the IGW.

3. Confirmed no NAT gateway and no Transit Gateway:
   ```bash
   aws ec2 describe-nat-gateways --region us-west-2 \
     --filter "Name=vpc-id,Values=vpc-efd8178b" \
     --query 'NatGateways[?State==`available`]'
   aws ec2 describe-transit-gateway-vpc-attachments --region us-west-2 \
     --filters "Name=vpc-id,Values=vpc-efd8178b" \
     --query 'TransitGatewayVpcAttachments[?State==`available`]'
   ```
   Both empty.

**Conclusion:** The VPC behaves like a default VPC (IGW for public-IP
egress) with no NAT for private-IP egress. Our tasks can't reach AWS
service APIs.

**Fix:** Use VPC interface endpoints. The stack supports this behind
an opt-in context flag:

```bash
cdk deploy AmsDashboardStack --no-rollback \
  -c vpc_id=vpc-efd8178b \
  -c private_subnet_ids=subnet-b3cdc9ea,subnet-dc46aeaa \
  -c availability_zones=us-west-2c,us-west-2b \
  -c add_vpc_endpoints=true \
  -c vpc_cidr=172.31.0.0/16
```

When `add_vpc_endpoints=true`, the stack creates:

- **Secrets Manager** interface endpoint (for `GetSecretValue`)
- **ECR API** interface endpoint (for auth + repo metadata)
- **ECR Docker** interface endpoint (for image pulls)
- **CloudWatch Logs** interface endpoint (for stdout streaming)
- **S3 gateway endpoint** (free; ECR layers live in S3)
- **Endpoint security group** allowing 443 inbound from the VPC CIDR

Cost: ~$45/month at 2 AZs.

**Alternative:** ask the platform team to add a NAT gateway in this
VPC. That removes the need for our endpoint set; the deploy then
uses the standard NAT egress path. NAT runs ~$32/month plus data.

---

## Settings to revert once first deploy is stable

These debug-friendly settings were committed for the first deploy and
should be flipped back once everything works:

| File | Setting | Current (debug) | Production |
|---|---|---|---|
| `infra/infra/infra_stack.py` | `ApiLogs.removal_policy` | `RETAIN` | `DESTROY` |
| `infra/infra/infra_stack.py` | `SyncLogs.removal_policy` | `RETAIN` | `DESTROY` |
| `infra/infra/infra_stack.py` | `DeploymentCircuitBreaker(rollback=…)` | `False` | `True` |
| `cdk deploy` flag | `--no-rollback` | included | omit |

Reverting these gives you the production-clean behavior: log groups
get cleaned up on stack delete, the circuit breaker rolls back to the
previous task definition, and failed deploys self-clean.
