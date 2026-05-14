#!/usr/bin/env bash
# Grant an IAM principal the minimum permissions to run 'cdk deploy' for
# AMS Dashboard against an already-bootstrapped AWS account.
#
# CDK's bootstrap process (a one-time operation per account+region) creates
# the cdk-*-deploy-role / file-publishing-role / image-publishing-role /
# lookup-role IAM roles. Routine 'cdk deploy' calls only need to AssumeRole
# on those roles, plus a few read-only permissions for context lookups.
#
# This script:
#   1. Creates (or updates) the IAM managed policy "AmsDashboardCdkDeploy"
#      in the target account.
#   2. Attaches it to the IAM user or role you name.
#
# 'cdk bootstrap' itself needs broader permissions and should be run ONCE
# by a principal with AdministratorAccess (or equivalent). See the runbook
# at docs/DEPLOY.md.

set -euo pipefail

PRINCIPAL_TYPE=""
PRINCIPAL=""
ACCOUNT=""
POLICY_NAME="AmsDashboardCdkDeploy"
DRY_RUN=0

usage() {
  cat <<EOF
Usage:
  $0 --account <ACCOUNT_ID> --user <USERNAME>  [--policy-name <NAME>] [--dry-run]
  $0 --account <ACCOUNT_ID> --role <ROLENAME>  [--policy-name <NAME>] [--dry-run]

Required:
  --account <ID>          Target AWS account ID
  --user <NAME>           IAM user to attach the policy to, OR
  --role <NAME>           IAM role to attach the policy to

Options:
  --policy-name <NAME>    Override managed-policy name (default: ${POLICY_NAME})
  --dry-run               Print the policy JSON and exit (no AWS calls)
  -h, --help              Show this help

The AWS CLI must be configured with credentials that can manage IAM in
the target account.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --account)     ACCOUNT="$2"; shift 2 ;;
    --user)        PRINCIPAL_TYPE=user; PRINCIPAL="$2"; shift 2 ;;
    --role)        PRINCIPAL_TYPE=role; PRINCIPAL="$2"; shift 2 ;;
    --policy-name) POLICY_NAME="$2"; shift 2 ;;
    --dry-run)     DRY_RUN=1; shift ;;
    -h|--help)     usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

[[ -z "$ACCOUNT"        ]] && { echo "Error: --account is required."         >&2; usage; exit 2; }
[[ -z "$PRINCIPAL"      ]] && { echo "Error: --user or --role is required."  >&2; usage; exit 2; }
[[ -z "$PRINCIPAL_TYPE" ]] && { echo "Error: pick --user or --role."         >&2; usage; exit 2; }

# Sanity-check the account is a 12-digit number.
if ! [[ "$ACCOUNT" =~ ^[0-9]{12}$ ]]; then
  echo "Error: --account must be a 12-digit AWS account ID (got: '$ACCOUNT')." >&2
  exit 2
fi

POLICY_JSON=$(cat <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CdkAssumeBootstrapRoles",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": [
        "arn:aws:iam::${ACCOUNT}:role/cdk-*-deploy-role-${ACCOUNT}-*",
        "arn:aws:iam::${ACCOUNT}:role/cdk-*-file-publishing-role-${ACCOUNT}-*",
        "arn:aws:iam::${ACCOUNT}:role/cdk-*-image-publishing-role-${ACCOUNT}-*",
        "arn:aws:iam::${ACCOUNT}:role/cdk-*-lookup-role-${ACCOUNT}-*"
      ]
    },
    {
      "Sid": "CdkContextLookups",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeVpcs",
        "ec2:DescribeSubnets",
        "ec2:DescribeAvailabilityZones",
        "ec2:DescribeRouteTables",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeVpnGateways",
        "ssm:GetParameter",
        "ssm:GetParameters"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudFormationVisibility",
      "Effect": "Allow",
      "Action": [
        "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackEvents",
        "cloudformation:DescribeStackResource",
        "cloudformation:DescribeStackResources",
        "cloudformation:GetTemplate",
        "cloudformation:ListStacks",
        "cloudformation:ListStackResources"
      ],
      "Resource": "*"
    }
  ]
}
JSON
)

if [[ "$DRY_RUN" == "1" ]]; then
  echo "$POLICY_JSON"
  exit 0
fi

POLICY_ARN="arn:aws:iam::${ACCOUNT}:policy/${POLICY_NAME}"

if aws iam get-policy --policy-arn "$POLICY_ARN" >/dev/null 2>&1; then
  echo "Policy ${POLICY_NAME} already exists — creating a new default version."
  # IAM caps a customer-managed policy at 5 versions. Prune the oldest
  # non-default version if we're at the limit.
  NON_DEFAULT=$(aws iam list-policy-versions --policy-arn "$POLICY_ARN" \
    --query 'Versions[?!IsDefaultVersion].VersionId' --output text)
  COUNT=$(echo "$NON_DEFAULT" | wc -w | tr -d ' ')
  if [[ "$COUNT" -ge 4 ]]; then
    OLDEST=$(echo "$NON_DEFAULT" | awk '{print $NF}')
    echo "  Pruning oldest version: ${OLDEST}"
    aws iam delete-policy-version --policy-arn "$POLICY_ARN" --version-id "$OLDEST"
  fi
  aws iam create-policy-version \
    --policy-arn "$POLICY_ARN" \
    --policy-document "$POLICY_JSON" \
    --set-as-default >/dev/null
else
  echo "Creating policy ${POLICY_NAME}…"
  aws iam create-policy \
    --policy-name "$POLICY_NAME" \
    --policy-document "$POLICY_JSON" \
    --description "CDK routine-deploy permissions for AMS Dashboard." >/dev/null
fi

echo "Attaching policy to ${PRINCIPAL_TYPE} ${PRINCIPAL}…"
if [[ "$PRINCIPAL_TYPE" == "user" ]]; then
  aws iam attach-user-policy --user-name "$PRINCIPAL" --policy-arn "$POLICY_ARN"
else
  aws iam attach-role-policy --role-name "$PRINCIPAL" --policy-arn "$POLICY_ARN"
fi

cat <<EOF

✓ Done. Policy ${POLICY_NAME} (${POLICY_ARN}) is attached to ${PRINCIPAL_TYPE} ${PRINCIPAL}.

Next steps:
  1. If 'cdk bootstrap' has not been run in this account+region yet, run
     it ONCE using a principal with AdministratorAccess (or equivalent).
     Bootstrap creates the cdk-*-deploy-role-* roles that this policy
     lets ${PRINCIPAL} AssumeRole on.
  2. After bootstrap, ${PRINCIPAL} can run 'cdk deploy' for AMS Dashboard
     using only this policy.
  3. To remove access later:
       aws iam detach-${PRINCIPAL_TYPE}-policy \\
         --${PRINCIPAL_TYPE}-name ${PRINCIPAL} \\
         --policy-arn ${POLICY_ARN}
EOF
