#!/usr/bin/env bash
# Shared by deploy.sh and run-task.sh: load an environment file and refuse
# to continue unless the active AWS profile resolves to the account that
# file names. Source this; it defines load_env and build_context_flags.
#
#   load_env <name>        → exports AWS_PROFILE/AWS_REGION/STACK/… from
#                            infra/environments/<name>.env and verifies the
#                            caller identity's account matches AWS_ACCOUNT_ID.
#   build_context_flags    → fills the CONTEXT_FLAGS array with the -c flags
#                            that reproduce the environment for cdk.

ENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../environments" && pwd)"

die() { echo "✗ $*" >&2; exit 1; }

load_env() {
  local name="${1:-}"
  [[ -n "$name" ]] || die "no environment given (use --env <name>; see infra/environments/)"
  local file="$ENV_DIR/$name.env"
  [[ -f "$file" ]] || die "no such environment file: $file"

  # shellcheck disable=SC1090
  set -a; source "$file"; set +a
  DEPLOY_ENV="$name"

  for required in AWS_PROFILE AWS_REGION AWS_ACCOUNT_ID STACK ENVIRONMENT; do
    [[ -n "${!required:-}" ]] || die "$file does not set $required"
  done
  export AWS_PROFILE AWS_REGION

  # ── Deploy guard ───────────────────────────────────────────────
  # The one check that matters: whoever we are about to act as must be in
  # the account this environment file names. A typo'd --env, a stale
  # AWS_PROFILE in the shell, or an SSO session for the wrong account all
  # stop here instead of creating resources somewhere they don't belong.
  local actual
  actual="$(aws sts get-caller-identity --profile "$AWS_PROFILE" \
              --query Account --output text 2>/dev/null)" \
    || die "cannot resolve credentials for profile '$AWS_PROFILE' (aws sts get-caller-identity failed)"
  if [[ "$actual" != "$AWS_ACCOUNT_ID" ]]; then
    die "profile '$AWS_PROFILE' is account $actual but environment '$name' expects $AWS_ACCOUNT_ID — refusing"
  fi
  echo "✓ environment '$name': profile $AWS_PROFILE → account $actual, region $AWS_REGION, stack $STACK"
}

build_context_flags() {
  CONTEXT_FLAGS=(-c create_vpc=true -c "stack_name=$STACK" -c "environment=$ENVIRONMENT")
  [[ "${PUBLIC_ALB:-}" == "true" ]] && CONTEXT_FLAGS+=(-c public_alb=true)
  if [[ -n "${ACM_CERT_ARN:-}" ]]; then
    CONTEXT_FLAGS+=(-c "acm_cert_arn=$ACM_CERT_ARN")
  fi
  if [[ -n "${DOMAIN_NAME:-}" ]]; then
    CONTEXT_FLAGS+=(
      -c "domain_name=$DOMAIN_NAME"
      -c "hosted_zone_id=${HOSTED_ZONE_ID:-}"
      -c "hosted_zone_name=${HOSTED_ZONE_NAME:-}"
    )
  fi
  if [[ -z "${ACM_CERT_ARN:-}" && -z "${DOMAIN_NAME:-}" && "${ALLOW_PUBLIC_HTTP:-}" == "true" ]]; then
    CONTEXT_FLAGS+=(-c allow_public_http=true)
  fi
  if [[ "${JIRA_SYNC_ENABLED:-true}" == "false" ]]; then
    CONTEXT_FLAGS+=(-c jira_sync_enabled=false)
  fi
  if [[ -n "${AURORA_AUTO_PAUSE_MINUTES:-}" && "${AURORA_AUTO_PAUSE_MINUTES}" != "0" ]]; then
    CONTEXT_FLAGS+=(-c "aurora_auto_pause_minutes=$AURORA_AUTO_PAUSE_MINUTES")
  fi
  if [[ -n "${API_DESIRED_COUNT:-}" ]]; then
    CONTEXT_FLAGS+=(-c "api_desired_count=$API_DESIRED_COUNT")
  fi
  if [[ "${PORTAL_ENABLED:-false}" == "true" ]]; then
    CONTEXT_FLAGS+=(-c portal_enabled=true)
    if [[ -n "${PORTAL_STAFF_EMAIL_DOMAINS:-}" ]]; then
      CONTEXT_FLAGS+=(-c "portal_staff_email_domains=$PORTAL_STAFF_EMAIL_DOMAINS")
    fi
    if [[ -n "${PORTAL_EMAIL_FROM:-}" ]]; then
      CONTEXT_FLAGS+=(-c "portal_email_from=$PORTAL_EMAIL_FROM")
    fi
    if [[ "${REPORTS_AI_SUMMARY:-false}" == "true" ]]; then
      CONTEXT_FLAGS+=(-c reports_ai_summary=true)
    fi
    if [[ -n "${REPORTS_SCHEDULE_DAY:-}" ]]; then
      CONTEXT_FLAGS+=(-c "reports_schedule_day=$REPORTS_SCHEDULE_DAY")
    fi
  fi
}

# Log group name must mirror infra_stack.py's name_suffix rule.
api_log_group() {
  if [[ "$ENVIRONMENT" == "prod" ]]; then echo "/ams-dashboard/api"; else echo "/ams-dashboard-$ENVIRONMENT/api"; fi
}
