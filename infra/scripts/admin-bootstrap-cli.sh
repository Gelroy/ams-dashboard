#!/usr/bin/env bash
# Bootstrap AWS for AMS Dashboard *without* needing the CDK CLI on the
# admin's machine. The admin runs this once with their privileged AWS
# credentials. End state matches what `cdk bootstrap` would create.
#
# What this creates (in the target account+region):
#   - CloudFormation stack `AmsDashboardCdkToolkit`
#   - 5 IAM roles named cdk-<qualifier>-...-role-<account>-<region>
#   - S3 bucket  cdk-<qualifier>-assets-<account>-<region>
#   - ECR repo   cdk-<qualifier>-container-assets-<account>-<region>
#   - SSM param  /cdk-bootstrap/<qualifier>/version
#
# Inputs are positional so the script reads as a linear set of CLI calls.

set -euo pipefail

ACCOUNT="${1:-}"
REGION="${2:-}"
QUALIFIER="${3:-amsdash01}"
STACK_NAME="${4:-AmsDashboardCdkToolkit}"
TEMPLATE_FILE="${5:-$(dirname "$0")/../bootstrap-template.yaml}"

if [[ -z "$ACCOUNT" || -z "$REGION" ]]; then
  cat <<EOF
Usage: $0 <ACCOUNT_ID> <REGION> [QUALIFIER] [STACK_NAME] [TEMPLATE_FILE]

  ACCOUNT_ID     12-digit AWS account ID                (required)
  REGION         e.g. us-west-2                         (required)
  QUALIFIER      bootstrap qualifier (default: amsdash01)
  STACK_NAME     CFN stack name      (default: AmsDashboardCdkToolkit)
  TEMPLATE_FILE  path to bootstrap-template.yaml
                 (default: infra/bootstrap-template.yaml — committed in the repo)

Example:
  $0 048189774358 us-west-2
EOF
  exit 2
fi

if ! [[ "$ACCOUNT" =~ ^[0-9]{12}$ ]]; then
  echo "Error: ACCOUNT_ID must be 12 digits (got '$ACCOUNT')." >&2
  exit 2
fi
if [[ ! -f "$TEMPLATE_FILE" ]]; then
  echo "Error: bootstrap template not found at $TEMPLATE_FILE" >&2
  exit 2
fi

echo "→ Account:    $ACCOUNT"
echo "→ Region:     $REGION"
echo "→ Qualifier:  $QUALIFIER"
echo "→ Stack:      $STACK_NAME"
echo "→ Template:   $TEMPLATE_FILE"
echo

# 1. Create the CloudFormation stack.
echo "→ Creating CloudFormation stack…"
aws cloudformation create-stack \
  --region "$REGION" \
  --stack-name "$STACK_NAME" \
  --template-body "file://$TEMPLATE_FILE" \
  --parameters \
    ParameterKey=Qualifier,ParameterValue="$QUALIFIER" \
    ParameterKey=CloudFormationExecutionPolicies,ParameterValue=arn:aws:iam::aws:policy/AdministratorAccess \
    ParameterKey=PublicAccessBlockConfiguration,ParameterValue=true \
  --capabilities CAPABILITY_NAMED_IAM \
  >/dev/null
echo "  (CloudFormation accepted the request.)"
echo

# 2. Wait for it to finish (typical: 2–4 minutes).
echo "→ Waiting for stack to reach CREATE_COMPLETE (this takes a few minutes)…"
aws cloudformation wait stack-create-complete \
  --region "$REGION" \
  --stack-name "$STACK_NAME"
echo "  Done."
echo

# 3. Verify the SSM parameter exists (the marker CDK checks for).
echo "→ Verifying /cdk-bootstrap/$QUALIFIER/version…"
aws ssm get-parameter \
  --region "$REGION" \
  --name "/cdk-bootstrap/$QUALIFIER/version" \
  --query 'Parameter.Value' \
  --output text
echo

# 4. Print the roles for sanity.
echo "→ IAM roles created:"
aws iam list-roles \
  --query "Roles[?starts_with(RoleName, 'cdk-$QUALIFIER-')].RoleName" \
  --output table

cat <<EOF

✓ Bootstrap complete.

Next steps:
  1. Attach the routine-deploy policy to the IAM principal that will
     run 'cdk deploy' (typically Ron's user). See
     infra/scripts/grant-cdk-deploy-perms.sh — it's the companion to
     this one and works the same way.
  2. Ron can then run 'cdk deploy AmsDashboardStack -c vpc_id=… …'
     against this account/region.
EOF
