#!/usr/bin/env python3
import os
import sys

import aws_cdk as cdk

from infra.infra_stack import AmsDashboardStack

app = cdk.App()

# Account/region come from the deploy environment (CDK_DEFAULT_*) or can be
# overridden via context (-c account=… -c region=…). Vpc.from_lookup needs
# explicit env, so always require these.
account = app.node.try_get_context("account") or os.environ.get("CDK_DEFAULT_ACCOUNT")
region = app.node.try_get_context("region") or os.environ.get("CDK_DEFAULT_REGION")
if not account or not region:
    raise SystemExit(
        "Account and region must be set. Either configure AWS credentials so "
        "CDK_DEFAULT_ACCOUNT/REGION resolve, or pass -c account=… -c region=…"
    )

# Only synthesize the application stack when the caller has chosen a VPC
# strategy — either consume an existing VPC (`-c vpc_id=…`) or have the stack
# create a new one (`-c create_vpc=true`). `cdk bootstrap` loads this file but
# doesn't need our stack; skipping synthesis when neither flag is set lets
# bootstrap run cleanly without spurious lookups or errors.
vpc_id = app.node.try_get_context("vpc_id")
create_vpc = str(app.node.try_get_context("create_vpc") or "").lower() == "true"
if vpc_id or create_vpc:
    AmsDashboardStack(
        app,
        "AmsDashboardStack",
        env=cdk.Environment(account=account, region=region),
    )
else:
    print(
        "Note: neither vpc_id nor create_vpc context is set — skipping "
        "AmsDashboardStack synthesis. This is fine for 'cdk bootstrap'. For "
        "'cdk deploy' / 'cdk synth' / 'cdk diff', either pass "
        "-c vpc_id=vpc-xxxxxxxx (existing VPC) or -c create_vpc=true "
        "(have the stack provision one).",
        file=sys.stderr,
    )

app.synth()
