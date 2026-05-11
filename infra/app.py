#!/usr/bin/env python3
import os

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

AmsDashboardStack(
    app,
    "AmsDashboardStack",
    env=cdk.Environment(account=account, region=region),
)

app.synth()
