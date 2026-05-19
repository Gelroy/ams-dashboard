#!/usr/bin/env bash
# Raw AWS-CLI bootstrap for AMS Dashboard — creates the same end-state as
# `cdk bootstrap` (or the CloudFormation-based bootstrap script) but without
# touching CloudFormation. Every resource is created via a direct AWS CLI
# call so the admin can review each step.
#
# What gets created (in the target account/region, with qualifier amsdash01):
#   - KMS key + alias    alias/cdk-amsdash01-assets-key
#   - S3 bucket          cdk-amsdash01-assets-<account>-<region>
#                        (versioned, SSE-KMS, public access blocked,
#                         lifecycle, deny-non-SSL bucket policy)
#   - ECR repository     cdk-amsdash01-container-assets-<account>-<region>
#                        (immutable tags, untagged-images expire, lambda &
#                         emr-serverless pull policies)
#   - IAM roles:
#       cdk-amsdash01-file-publishing-role-<account>-<region>
#       cdk-amsdash01-image-publishing-role-<account>-<region>
#       cdk-amsdash01-lookup-role-<account>-<region>
#       cdk-amsdash01-cfn-exec-role-<account>-<region>
#       cdk-amsdash01-deploy-role-<account>-<region>
#   - SSM parameter      /cdk-bootstrap/amsdash01/version  =  "31"
#
# This script is NOT idempotent. If something fails partway through, delete
# the partially-created resources before retrying.

set -euo pipefail

ACCOUNT="${1:-}"
REGION="${2:-}"
QUALIFIER="${3:-amsdash01}"
BOOTSTRAP_VERSION="${4:-31}"

if [[ -z "$ACCOUNT" || -z "$REGION" ]]; then
  cat <<EOF
Usage: $0 <ACCOUNT_ID> <REGION> [QUALIFIER] [BOOTSTRAP_VERSION]

  ACCOUNT_ID         12-digit AWS account ID            (required)
  REGION             e.g. us-west-2                     (required)
  QUALIFIER          bootstrap qualifier                (default: amsdash01)
  BOOTSTRAP_VERSION  CDK bootstrap stack version        (default: 31)

Example:
  $0 048189774358 us-west-2
EOF
  exit 2
fi

if ! [[ "$ACCOUNT" =~ ^[0-9]{12}$ ]]; then
  echo "Error: ACCOUNT_ID must be 12 digits (got '$ACCOUNT')." >&2
  exit 2
fi

BUCKET="cdk-${QUALIFIER}-assets-${ACCOUNT}-${REGION}"
REPO="cdk-${QUALIFIER}-container-assets-${ACCOUNT}-${REGION}"
KEY_ALIAS="alias/cdk-${QUALIFIER}-assets-key"

FILE_PUB_ROLE="cdk-${QUALIFIER}-file-publishing-role-${ACCOUNT}-${REGION}"
IMG_PUB_ROLE="cdk-${QUALIFIER}-image-publishing-role-${ACCOUNT}-${REGION}"
LOOKUP_ROLE="cdk-${QUALIFIER}-lookup-role-${ACCOUNT}-${REGION}"
CFN_EXEC_ROLE="cdk-${QUALIFIER}-cfn-exec-role-${ACCOUNT}-${REGION}"
DEPLOY_ROLE="cdk-${QUALIFIER}-deploy-role-${ACCOUNT}-${REGION}"

TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

echo "→ Account:    $ACCOUNT"
echo "→ Region:     $REGION"
echo "→ Qualifier:  $QUALIFIER"
echo

# ────────────────────────────────────────────────────────────────────────────
# 1. IAM roles (trust policies only — permission policies are attached below
#    once we have all the resource ARNs).
# ────────────────────────────────────────────────────────────────────────────

cat > "$TMPDIR/trust-account.json" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect":"Allow","Principal":{"AWS":"arn:aws:iam::${ACCOUNT}:root"},"Action":"sts:AssumeRole"},
    {"Effect":"Allow","Principal":{"AWS":"arn:aws:iam::${ACCOUNT}:root"},"Action":"sts:TagSession"}
  ]
}
EOF

cat > "$TMPDIR/trust-cfn.json" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect":"Allow","Principal":{"Service":"cloudformation.amazonaws.com"},"Action":"sts:AssumeRole"}
  ]
}
EOF

echo "→ Creating IAM roles…"
aws iam create-role --role-name "$FILE_PUB_ROLE" \
  --assume-role-policy-document "file://$TMPDIR/trust-account.json" \
  --tags Key=aws-cdk:bootstrap-role,Value=file-publishing >/dev/null
echo "    $FILE_PUB_ROLE"

aws iam create-role --role-name "$IMG_PUB_ROLE" \
  --assume-role-policy-document "file://$TMPDIR/trust-account.json" \
  --tags Key=aws-cdk:bootstrap-role,Value=image-publishing >/dev/null
echo "    $IMG_PUB_ROLE"

aws iam create-role --role-name "$LOOKUP_ROLE" \
  --assume-role-policy-document "file://$TMPDIR/trust-account.json" \
  --tags Key=aws-cdk:bootstrap-role,Value=lookup >/dev/null
aws iam attach-role-policy --role-name "$LOOKUP_ROLE" \
  --policy-arn arn:aws:iam::aws:policy/ReadOnlyAccess
echo "    $LOOKUP_ROLE (+ ReadOnlyAccess)"

aws iam create-role --role-name "$CFN_EXEC_ROLE" \
  --assume-role-policy-document "file://$TMPDIR/trust-cfn.json" >/dev/null
aws iam attach-role-policy --role-name "$CFN_EXEC_ROLE" \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
echo "    $CFN_EXEC_ROLE (+ AdministratorAccess)"

aws iam create-role --role-name "$DEPLOY_ROLE" \
  --assume-role-policy-document "file://$TMPDIR/trust-account.json" \
  --tags Key=aws-cdk:bootstrap-role,Value=deploy >/dev/null
echo "    $DEPLOY_ROLE"

# Wait briefly for IAM eventual consistency before referencing role ARNs.
sleep 5
FILE_PUB_ARN=$(aws iam get-role --role-name "$FILE_PUB_ROLE" --query Role.Arn --output text)
CFN_EXEC_ARN=$(aws iam get-role --role-name "$CFN_EXEC_ROLE" --query Role.Arn --output text)

# ────────────────────────────────────────────────────────────────────────────
# 2. KMS key for the assets bucket (policy references FILE_PUB_ARN).
# ────────────────────────────────────────────────────────────────────────────

cat > "$TMPDIR/kms-policy.json" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::${ACCOUNT}:root"},
      "Action": ["kms:Create*","kms:Describe*","kms:Enable*","kms:List*","kms:Put*","kms:Update*","kms:Revoke*","kms:Disable*","kms:Get*","kms:Delete*","kms:ScheduleKeyDeletion","kms:CancelKeyDeletion","kms:GenerateDataKey","kms:TagResource","kms:UntagResource"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Principal": {"AWS": "*"},
      "Action": ["kms:Decrypt","kms:DescribeKey","kms:Encrypt","kms:ReEncrypt*","kms:GenerateDataKey*"],
      "Resource": "*",
      "Condition": {"StringEquals": {"kms:CallerAccount": "${ACCOUNT}", "kms:ViaService": "s3.${REGION}.amazonaws.com"}}
    },
    {
      "Effect": "Allow",
      "Principal": {"AWS": "${FILE_PUB_ARN}"},
      "Action": ["kms:Decrypt","kms:DescribeKey","kms:Encrypt","kms:ReEncrypt*","kms:GenerateDataKey*"],
      "Resource": "*"
    }
  ]
}
EOF

echo "→ Creating KMS key for the assets bucket…"
KEY_ID=$(aws kms create-key --region "$REGION" \
  --description "CDK assets bucket key — qualifier $QUALIFIER" \
  --policy "file://$TMPDIR/kms-policy.json" \
  --query 'KeyMetadata.KeyId' --output text)
KEY_ARN=$(aws kms describe-key --region "$REGION" --key-id "$KEY_ID" \
  --query 'KeyMetadata.Arn' --output text)
aws kms create-alias --region "$REGION" \
  --alias-name "$KEY_ALIAS" --target-key-id "$KEY_ID"
echo "    $KEY_ARN ($KEY_ALIAS)"

# ────────────────────────────────────────────────────────────────────────────
# 3. S3 staging bucket.
# ────────────────────────────────────────────────────────────────────────────

echo "→ Creating S3 staging bucket…"
if [[ "$REGION" == "us-east-1" ]]; then
  aws s3api create-bucket --region "$REGION" --bucket "$BUCKET" >/dev/null
else
  aws s3api create-bucket --region "$REGION" --bucket "$BUCKET" \
    --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
fi
echo "    $BUCKET (created)"

aws s3api put-bucket-versioning --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration "BlockPublicAcls=true,BlockPublicPolicy=true,IgnorePublicAcls=true,RestrictPublicBuckets=true"

cat > "$TMPDIR/bucket-enc.json" <<EOF
{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms","KMSMasterKeyID":"${KEY_ARN}"}}]}
EOF
aws s3api put-bucket-encryption --bucket "$BUCKET" \
  --server-side-encryption-configuration "file://$TMPDIR/bucket-enc.json"

cat > "$TMPDIR/bucket-lifecycle.json" <<EOF
{
  "Rules":[
    {"ID":"CleanupOldVersions","Status":"Enabled","Filter":{},"NoncurrentVersionExpiration":{"NoncurrentDays":30}},
    {"ID":"AbortIncompleteMultipartUploads","Status":"Enabled","Filter":{},"AbortIncompleteMultipartUpload":{"DaysAfterInitiation":1}}
  ]
}
EOF
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" \
  --lifecycle-configuration "file://$TMPDIR/bucket-lifecycle.json"

cat > "$TMPDIR/bucket-policy.json" <<EOF
{
  "Version":"2012-10-17",
  "Id":"AccessControl",
  "Statement":[
    {
      "Sid":"AllowSSLRequestsOnly",
      "Effect":"Deny",
      "Principal":"*",
      "Action":"s3:*",
      "Resource":["arn:aws:s3:::${BUCKET}","arn:aws:s3:::${BUCKET}/*"],
      "Condition":{"Bool":{"aws:SecureTransport":"false"}}
    }
  ]
}
EOF
aws s3api put-bucket-policy --bucket "$BUCKET" --policy "file://$TMPDIR/bucket-policy.json"
echo "    versioning + KMS encryption + public-access block + lifecycle + deny-non-SSL policy applied"

# ────────────────────────────────────────────────────────────────────────────
# 4. ECR container-assets repository.
# ────────────────────────────────────────────────────────────────────────────

echo "→ Creating ECR repository…"
aws ecr create-repository --region "$REGION" --repository-name "$REPO" \
  --image-tag-mutability IMMUTABLE >/dev/null
echo "    $REPO"

cat > "$TMPDIR/ecr-lifecycle.json" <<EOF
{"rules":[{"rulePriority":1,"description":"Untagged images should not exist, but expire any older than one year","selection":{"tagStatus":"untagged","countType":"sinceImagePushed","countUnit":"days","countNumber":365},"action":{"type":"expire"}}]}
EOF
aws ecr put-lifecycle-policy --region "$REGION" --repository-name "$REPO" \
  --lifecycle-policy-text "file://$TMPDIR/ecr-lifecycle.json" >/dev/null

cat > "$TMPDIR/ecr-policy.json" <<EOF
{
  "Version":"2012-10-17",
  "Statement":[
    {
      "Sid":"LambdaECRImageRetrievalPolicy",
      "Effect":"Allow",
      "Principal":{"Service":"lambda.amazonaws.com"},
      "Action":["ecr:BatchGetImage","ecr:GetDownloadUrlForLayer"],
      "Condition":{"StringLike":{"aws:sourceArn":"arn:aws:lambda:${REGION}:${ACCOUNT}:function:*"}}
    },
    {
      "Sid":"EmrServerlessImageRetrievalPolicy",
      "Effect":"Allow",
      "Principal":{"Service":"emr-serverless.amazonaws.com"},
      "Action":["ecr:BatchGetImage","ecr:GetDownloadUrlForLayer","ecr:DescribeImages"],
      "Condition":{"StringLike":{"aws:sourceArn":"arn:aws:emr-serverless:${REGION}:${ACCOUNT}:/applications/*"}}
    }
  ]
}
EOF
aws ecr set-repository-policy --region "$REGION" --repository-name "$REPO" \
  --policy-text "file://$TMPDIR/ecr-policy.json" >/dev/null
echo "    + lifecycle + repository policy"

# ────────────────────────────────────────────────────────────────────────────
# 5. Inline permission policies on the four "deployer" roles.
# ────────────────────────────────────────────────────────────────────────────

echo "→ Attaching inline permission policies…"

cat > "$TMPDIR/file-publish-perms.json" <<EOF
{
  "Version":"2012-10-17",
  "Statement":[
    {
      "Effect":"Allow",
      "Action":["s3:GetObject*","s3:GetBucket*","s3:GetEncryptionConfiguration","s3:List*","s3:DeleteObject*","s3:PutObject*","s3:Abort*"],
      "Resource":["arn:aws:s3:::${BUCKET}","arn:aws:s3:::${BUCKET}/*"],
      "Condition":{"StringEquals":{"aws:ResourceAccount":"${ACCOUNT}"}}
    },
    {
      "Effect":"Allow",
      "Action":["kms:Decrypt","kms:DescribeKey","kms:Encrypt","kms:ReEncrypt*","kms:GenerateDataKey*"],
      "Resource":"${KEY_ARN}"
    }
  ]
}
EOF
aws iam put-role-policy --role-name "$FILE_PUB_ROLE" \
  --policy-name "cdk-${QUALIFIER}-file-publishing-role-default-policy-${ACCOUNT}-${REGION}" \
  --policy-document "file://$TMPDIR/file-publish-perms.json"
echo "    $FILE_PUB_ROLE  ← S3 + KMS"

# ecr:GetAuthorizationToken does NOT support resource-level permissions
# (AWS API: "calls to this action ignore the resource argument") — Resource:*
# is the only valid form. Everything else is scoped to this exact repo.
cat > "$TMPDIR/image-publish-perms.json" <<EOF
{
  "Version":"2012-10-17",
  "Statement":[
    {
      "Sid":"PushToRepo","Effect":"Allow",
      "Action":["ecr:PutImage","ecr:InitiateLayerUpload","ecr:UploadLayerPart","ecr:CompleteLayerUpload","ecr:BatchCheckLayerAvailability","ecr:DescribeRepositories","ecr:DescribeImages","ecr:BatchGetImage","ecr:GetDownloadUrlForLayer"],
      "Resource":"arn:aws:ecr:${REGION}:${ACCOUNT}:repository/${REPO}"
    },
    {"Sid":"AuthToken","Effect":"Allow","Action":"ecr:GetAuthorizationToken","Resource":"*"}
  ]
}
EOF
aws iam put-role-policy --role-name "$IMG_PUB_ROLE" \
  --policy-name "cdk-${QUALIFIER}-image-publishing-role-default-policy-${ACCOUNT}-${REGION}" \
  --policy-document "file://$TMPDIR/image-publish-perms.json"
echo "    $IMG_PUB_ROLE  ← ECR push"

# Intentional broad Deny — the lookup role is granted ReadOnlyAccess
# (a managed policy that includes kms:Decrypt). This deny narrows that
# so the role can read most resources but never decrypt anything. A Deny
# should be broad by design; scoping it would defeat the safeguard.
cat > "$TMPDIR/lookup-deny-secrets.json" <<EOF
{"Version":"2012-10-17","Statement":[{"Sid":"DontReadSecrets","Effect":"Deny","Action":"kms:Decrypt","Resource":"*"}]}
EOF
aws iam put-role-policy --role-name "$LOOKUP_ROLE" \
  --policy-name "LookupRolePolicy" \
  --policy-document "file://$TMPDIR/lookup-deny-secrets.json"
echo "    $LOOKUP_ROLE   ← Deny kms:Decrypt (DontReadSecrets)"

SSM_PARAM_ARN="arn:aws:ssm:${REGION}:${ACCOUNT}:parameter/cdk-bootstrap/${QUALIFIER}/version"
# CloudFormation actions get scoped to our two stacks (the toolkit stack
# bootstrap creates, and the application stack 'cdk deploy' creates/updates).
# sts:GetCallerIdentity is unscopeable by AWS (no resource form), so it
# stays Resource:*.
cat > "$TMPDIR/deploy-perms.json" <<EOF
{
  "Version":"2012-10-17",
  "Statement":[
    {
      "Sid":"CloudFormationStackOps","Effect":"Allow",
      "Action":[
        "cloudformation:CreateChangeSet","cloudformation:DeleteChangeSet","cloudformation:DescribeChangeSet",
        "cloudformation:DescribeStacks","cloudformation:DescribeStackEvents","cloudformation:ExecuteChangeSet",
        "cloudformation:CreateStack","cloudformation:UpdateStack","cloudformation:RollbackStack",
        "cloudformation:ContinueUpdateRollback","cloudformation:DeleteStack",
        "cloudformation:GetTemplate","cloudformation:GetTemplateSummary","cloudformation:GetHookResult",
        "cloudformation:UpdateTerminationProtection"
      ],
      "Resource":[
        "arn:aws:cloudformation:${REGION}:${ACCOUNT}:stack/AmsDashboardStack/*",
        "arn:aws:cloudformation:${REGION}:${ACCOUNT}:stack/AmsDashboardCdkToolkit/*"
      ]
    },
    {"Sid":"PassRoleToCfn","Effect":"Allow","Action":"iam:PassRole","Resource":"${CFN_EXEC_ARN}"},
    {
      "Sid":"CliCallerIdentity","Effect":"Allow",
      "Action":"sts:GetCallerIdentity",
      "Resource":"*"
    },
    {
      "Sid":"CliStagingBucket","Effect":"Allow",
      "Action":["s3:GetObject*","s3:GetBucket*","s3:List*"],
      "Resource":["arn:aws:s3:::${BUCKET}","arn:aws:s3:::${BUCKET}/*"]
    },
    {
      "Sid":"ReadBootstrapVersion","Effect":"Allow",
      "Action":["ssm:GetParameter","ssm:GetParameters"],
      "Resource":"${SSM_PARAM_ARN}"
    }
  ]
}
EOF
aws iam put-role-policy --role-name "$DEPLOY_ROLE" \
  --policy-name "default" \
  --policy-document "file://$TMPDIR/deploy-perms.json"
echo "    $DEPLOY_ROLE     ← CFN deploy + PassRole + SSM read + assets read"

# ────────────────────────────────────────────────────────────────────────────
# 6. Bootstrap version marker.
# ────────────────────────────────────────────────────────────────────────────

echo "→ Creating SSM parameter /cdk-bootstrap/${QUALIFIER}/version…"
aws ssm put-parameter --region "$REGION" \
  --name "/cdk-bootstrap/${QUALIFIER}/version" \
  --value "$BOOTSTRAP_VERSION" --type String --overwrite >/dev/null
echo "    = ${BOOTSTRAP_VERSION}"

cat <<EOF

✓ Bootstrap complete. CDK will recognize this account/region as
  bootstrapped with qualifier '${QUALIFIER}'.

Next steps:
  1. Attach the routine-deploy policy to the IAM principal that will
     run 'cdk deploy':
       infra/scripts/grant-cdk-deploy-perms.sh --account ${ACCOUNT} --user <username>
  2. The deployer can then run:
       cdk deploy AmsDashboardStack -c vpc_id=… …

To undo everything created above (in reverse order), the admin would:
  - Delete the SSM parameter
  - Delete role policies, detach managed policies, delete roles
  - Empty + delete the S3 bucket (NOTE: contents are versioned)
  - Delete the ECR repository
  - Schedule deletion of the KMS key
EOF
