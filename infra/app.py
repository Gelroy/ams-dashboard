#!/usr/bin/env python3
import aws_cdk as cdk

from infra.infra_stack import AmsDashboardStack


app = cdk.App()
AmsDashboardStack(app, "AmsDashboardStack")
app.synth()
