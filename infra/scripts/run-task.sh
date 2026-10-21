#!/usr/bin/env bash
# Run a one-off `manage.py` command inside the deployed stack, using the
# migration task definition with the ECS network settings copied from the
# live API service (same subnets, same security group, same public-IP
# setting — so the task can reach Aurora exactly like the API does).
#
# Usage:
#   ./infra/scripts/run-task.sh --env personal-dev migrate
#   ./infra/scripts/run-task.sh --env personal-dev seed_synthetic
#   ./infra/scripts/run-task.sh --env prod migrate --noinput
#
# Waits for the task to stop, prints its exit code and the CloudWatch log
# lines it wrote. Exit status mirrors the container's.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "$REPO_ROOT/infra/scripts/env-lib.sh"

ENV_NAME="${DEPLOY_ENV:-}"
CMD=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)   ENV_NAME="$2"; shift 2 ;;
    --env=*) ENV_NAME="${1#--env=}"; shift ;;
    *) CMD+=("$1"); shift ;;
  esac
done
[[ ${#CMD[@]} -gt 0 ]] || die "give a manage.py command, e.g. migrate or seed_synthetic"
load_env "$ENV_NAME"

out() { aws cloudformation describe-stacks --stack-name "$STACK" \
          --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
CLUSTER="$(out ClusterName)"; SERVICE="$(out ApiServiceName)"; TASK_DEF="$(out MigrationTaskArn)"
[[ -n "$CLUSTER" && "$CLUSTER" != "None" ]] || die "stack $STACK has no ClusterName output — is it deployed?"

NETCFG="$(aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
            --query 'services[0].networkConfiguration.awsvpcConfiguration' --output json)"
SUBNETS="$(echo "$NETCFG" | python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)["subnets"]))')"
SGS="$(echo "$NETCFG" | python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)["securityGroups"]))')"
PUBLIC_IP="$(echo "$NETCFG" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("assignPublicIp","DISABLED"))')"

COMMAND_JSON="$(python3 -c 'import json,sys; print(json.dumps(["python","manage.py",*sys.argv[1:]]))' "${CMD[@]}")"
echo "→ running: python manage.py ${CMD[*]}  (cluster $CLUSTER)"
TASK_ARN="$(aws ecs run-task \
  --cluster "$CLUSTER" --task-definition "$TASK_DEF" --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SGS],assignPublicIp=$PUBLIC_IP}" \
  --overrides "{\"containerOverrides\":[{\"name\":\"migrate\",\"command\":$COMMAND_JSON}]}" \
  --query 'tasks[0].taskArn' --output text)"
TASK_ID="${TASK_ARN##*/}"
echo "  task $TASK_ID — waiting for it to stop…"
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK_ARN"

read -r EXIT_CODE STOP_REASON < <(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK_ARN" \
  --query 'tasks[0].[containers[0].exitCode, stoppedReason]' --output text)

echo "── logs ($(api_log_group) migrate/migrate/$TASK_ID) ──"
aws logs get-log-events --log-group-name "$(api_log_group)" \
  --log-stream-name "migrate/migrate/$TASK_ID" --start-from-head \
  --query 'events[].message' --output text 2>/dev/null | sed 's/^/  /' || echo "  (no log stream yet)"
echo "── exit code: $EXIT_CODE ($STOP_REASON)"
[[ "$EXIT_CODE" == "0" ]]
