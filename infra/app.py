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

# Only synthesize the application stack when vpc_id is provided. `cdk bootstrap`
# loads this file but doesn't need our stack — bootstrap manages the separate
# CDKToolkit stack. Synthesizing AmsDashboardStack without a real VPC would
# either error out (no vpc_id) or trigger a Vpc.from_lookup against bogus
# input. Skipping it here lets `cdk bootstrap` run cleanly.
vpc_id = app.node.try_get_context("vpc_id")
if vpc_id:
    AmsDashboardStack(
        app,
        "AmsDashboardStack",
        env=cdk.Environment(account=account, region=region),
    )
else:
    print(
        "Note: vpc_id context not set — skipping AmsDashboardStack synthesis. "
        "This is fine for 'cdk bootstrap'. For 'cdk deploy' / 'cdk synth' / "
        "'cdk diff', pass -c vpc_id=vpc-xxxxxxxx.",
        file=sys.stderr,
    )

app.synth()
