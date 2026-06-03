#!/usr/bin/env bash
# One-line deploy wrapper for the AMS Dashboard stack.
#
# Why this exists: cdk deploy needs three pieces of context to match the
# currently-running prod stack, and forgetting any of them silently
# changes infrastructure on the next deploy:
#   - create_vpc=true        the stack provisions its own VPC; without
#                            this flag synth refuses to produce a stack.
#   - public_alb=true        keep the ALB internet-facing so teammates
#                            can reach it without VPN. Without this it
#                            falls back to internal scheme and the DNS
#                            stops resolving from outside the VPC, which
#                            already locked us out once (June 2026).
#   - allow_public_http=true required while we're on plain HTTP (no ACM
#                            cert wired up yet); the stack refuses
#                            public_alb without it as a guardrail.
#
# Usage:
#   ./infra/scripts/deploy.sh                  # interactive — confirms before apply
#   ./infra/scripts/deploy.sh --yes            # auto-approve (CI / hands-off)
#   ./infra/scripts/deploy.sh -- --hotswap     # forward extra flags to cdk
#
# Environment knobs (override on the command line, not by editing this file):
#   AWS_PROFILE   default: ams-admin
#   AWS_REGION    default: us-west-2
#   STACK         default: AmsDashboardStack
#   ACM_CERT_ARN  optional. If set, swaps HTTP-public for HTTPS-public and
#                 drops the allow_public_http=true guardrail override.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT/infra"

: "${AWS_PROFILE:=ams-admin}"
: "${AWS_REGION:=us-west-2}"
: "${STACK:=AmsDashboardStack}"
: "${ACM_CERT_ARN:=}"
export AWS_PROFILE AWS_REGION

CONTEXT_FLAGS=(-c create_vpc=true -c public_alb=true)
if [[ -n "$ACM_CERT_ARN" ]]; then
  # HTTPS path: provide the cert ARN; the stack drops the HTTP listener
  # in favor of TLS so we don't need allow_public_http=true.
  CONTEXT_FLAGS+=(-c "acm_cert_arn=$ACM_CERT_ARN")
else
  CONTEXT_FLAGS+=(-c allow_public_http=true)
fi

AUTO_APPROVE=()
EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y)
      AUTO_APPROVE=(--require-approval never)
      shift
      ;;
    --)
      shift
      EXTRA=("$@")
      break
      ;;
    *)
      EXTRA+=("$1")
      shift
      ;;
  esac
done

# Activate the CDK venv if we find one and the user hasn't already.
if [[ -z "${VIRTUAL_ENV:-}" && -f "$REPO_ROOT/infra/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$REPO_ROOT/infra/.venv/bin/activate"
fi

# Silence the noisy untested-node-version banner that newer Node spits out
# under jsii. We pin a CDK-supported Node in CI; locally users may run newer.
export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1

echo "→ Deploying $STACK to $AWS_REGION (profile $AWS_PROFILE)"
echo "  Context: ${CONTEXT_FLAGS[*]}"
if [[ -n "$ACM_CERT_ARN" ]]; then
  echo "  Scheme:  internet-facing, HTTPS via ACM cert $ACM_CERT_ARN"
else
  echo "  Scheme:  internet-facing, plain HTTP (set ACM_CERT_ARN=... for HTTPS)"
fi

# `set -o pipefail` so a Docker build failure (which CDK pipes through
# `tee`) actually fails the script. Without it, the original deploy can
# silently exit 0 even when the build broke.
set -o pipefail
LOG="/tmp/cdk-deploy-$(date +%Y%m%d-%H%M%S).log"
echo "  Log:     $LOG"
# macOS ships bash 3.2 which treats empty arrays as unset under `set -u`.
# The `${name[@]+"${name[@]}"}` dance expands to nothing when the array is
# empty and to the array's contents (preserving quoting) otherwise.
cdk deploy "$STACK" \
  "${CONTEXT_FLAGS[@]}" \
  ${AUTO_APPROVE[@]+"${AUTO_APPROVE[@]}"} \
  ${EXTRA[@]+"${EXTRA[@]}"} \
  2>&1 | tee "$LOG"
