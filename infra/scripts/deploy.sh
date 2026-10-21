#!/usr/bin/env bash
# Deploy wrapper for the AMS Dashboard stack.
#
# Every deploy targets a named environment from infra/environments/*.env,
# which fixes the profile, account, region, stack name and the cdk context
# flags that must be identical from one deploy to the next (forgetting any
# of them silently changes infrastructure). Before anything runs, the
# active profile's account is checked against the file — see env-lib.sh.
#
# Usage:
#   ./infra/scripts/deploy.sh --env prod                 # company (default)
#   ./infra/scripts/deploy.sh --env personal-dev         # skunkworks clone
#   ./infra/scripts/deploy.sh --env personal-dev --diff  # cdk diff only
#   ./infra/scripts/deploy.sh --env prod --yes           # auto-approve
#   ./infra/scripts/deploy.sh --env prod -- --hotswap    # extra cdk flags
#
# Overrides (command line only, never by editing the env file in place):
#   ACM_CERT_ARN=arn:…   swap HTTP-public for HTTPS with a pre-issued cert.
#   DEPLOY_ENV=<name>    same as --env.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "$REPO_ROOT/infra/scripts/env-lib.sh"

ENV_NAME="${DEPLOY_ENV:-prod}"
ACTION=deploy
AUTO_APPROVE=()
EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)   ENV_NAME="$2"; shift 2 ;;
    --env=*) ENV_NAME="${1#--env=}"; shift ;;
    --diff)  ACTION=diff; shift ;;
    --synth) ACTION=synth; shift ;;
    --yes|-y) AUTO_APPROVE=(--require-approval never); shift ;;
    --) shift; EXTRA=("$@"); break ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

# Command-line ACM_CERT_ARN wins over the env file's value.
CLI_ACM_CERT_ARN="${ACM_CERT_ARN:-}"
load_env "$ENV_NAME"
[[ -n "$CLI_ACM_CERT_ARN" ]] && ACM_CERT_ARN="$CLI_ACM_CERT_ARN"
build_context_flags

cd "$REPO_ROOT/infra"

# Activate the CDK venv if we find one and the user hasn't already.
if [[ -z "${VIRTUAL_ENV:-}" && -f "$REPO_ROOT/infra/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$REPO_ROOT/infra/.venv/bin/activate"
fi

# Silence the noisy untested-node-version banner newer Node prints under jsii.
export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1

echo "→ cdk $ACTION $STACK in $AWS_REGION (profile $AWS_PROFILE, env $ENV_NAME)"
echo "  Context: ${CONTEXT_FLAGS[*]}"
if [[ -n "${ACM_CERT_ARN:-}" ]]; then
  echo "  Scheme:  HTTPS via pre-issued cert $ACM_CERT_ARN"
elif [[ -n "${DOMAIN_NAME:-}" ]]; then
  echo "  Scheme:  HTTPS at https://$DOMAIN_NAME (cert issued + DNS record by the stack)"
else
  echo "  Scheme:  plain HTTP (no cert; set DOMAIN_NAME or ACM_CERT_ARN for HTTPS)"
fi

if [[ "$ACTION" != "deploy" ]]; then
  exec cdk "$ACTION" "$STACK" "${CONTEXT_FLAGS[@]}" ${EXTRA[@]+"${EXTRA[@]}"}
fi

# `set -o pipefail` so a Docker build failure (which CDK pipes through
# `tee`) actually fails the script.
LOG="/tmp/cdk-deploy-$ENV_NAME-$(date +%Y%m%d-%H%M%S).log"
echo "  Log:     $LOG"
# macOS ships bash 3.2 which treats empty arrays as unset under `set -u`;
# the ${name[@]+"${name[@]}"} dance expands to nothing when empty.
cdk deploy "$STACK" \
  "${CONTEXT_FLAGS[@]}" \
  ${AUTO_APPROVE[@]+"${AUTO_APPROVE[@]}"} \
  ${EXTRA[@]+"${EXTRA[@]}"} \
  2>&1 | tee "$LOG"
