#!/usr/bin/env bash
# Store the Anthropic API key for AI-drafted ticket summaries, then restart
# the API service so it picks the key up.
#
# Usage:
#   ./infra/scripts/set-anthropic-key.sh --env personal-dev
#   ./infra/scripts/set-anthropic-key.sh --env personal-dev --clear   # turn the feature off
#
# The key is read from the terminal without echo and handed to AWS on
# standard input: it is never an argument, so it does not land in shell
# history or the process list. Needs REPORTS_AI_SUMMARY=true in the
# environment file and a deploy, which creates the secret.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "$REPO_ROOT/infra/scripts/env-lib.sh"

ENV_NAME="${DEPLOY_ENV:-}"
CLEAR=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)   ENV_NAME="$2"; shift 2 ;;
    --env=*) ENV_NAME="${1#--env=}"; shift ;;
    --clear) CLEAR=true; shift ;;
    *) die "unknown argument: $1" ;;
  esac
done
load_env "$ENV_NAME"

out() { aws cloudformation describe-stacks --stack-name "$STACK" \
          --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
SECRET_ARN="$(out AnthropicSecretArn)"
[[ -n "$SECRET_ARN" && "$SECRET_ARN" != "None" ]] \
  || die "stack $STACK has no AnthropicSecretArn output — set REPORTS_AI_SUMMARY=true in the environment file and deploy first"

if [[ "$CLEAR" == "true" ]]; then
  KEY="unset"
else
  [[ -t 0 ]] || die "run this in a terminal: the key is typed, not piped"
  read -r -s -p "Anthropic API key (input hidden): " KEY
  echo
  [[ "$KEY" == sk-ant-* ]] || die "that does not look like an Anthropic API key (expected it to start with sk-ant-)"
  [[ "$KEY" != sk-ant-admin* ]] || die "that is an Admin API key; use a regular API key"
fi

printf '%s' "$KEY" | aws secretsmanager put-secret-value \
  --secret-id "$SECRET_ARN" --secret-string file:///dev/stdin \
  --query 'VersionId' --output text >/dev/null
unset KEY
echo "✓ secret updated"

CLUSTER="$(out ClusterName)"; SERVICE="$(out ApiServiceName)"
aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" --force-new-deployment \
  --query 'service.serviceName' --output text >/dev/null
echo "✓ API service restarting; the new setting is live in two or three minutes"
