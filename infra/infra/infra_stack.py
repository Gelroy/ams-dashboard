"""AMS Dashboard — CDK stack.

Provisions everything the AWS admin needs from a single ``cdk deploy``:

  - Aurora Postgres Serverless v2 (private subnets)
  - Secrets Manager: Django SECRET_KEY (auto-generated) + JIRA creds (admin
    fills in JIRA_URL / JIRA_EMAIL / JIRA_TOKEN values)
  - Cognito user pool + app client
  - Internal ALB (HTTPS if acm_cert_arn supplied, else HTTP for first-deploy
    validation)
  - Fargate cluster + API service (the multi-stage Docker image is built by
    CDK from the repo Dockerfile and pushed to ECR)
  - Scheduled Fargate tasks for the three JIRA sync workers
  - A migration TaskDefinition the admin runs once per deploy

Required context (set in cdk.json or via -c flags):
  - vpc_id                  : the existing shared VPC ID, OR
  - create_vpc=true         : have this stack provision a new VPC (2 AZs,
                              public + private subnets, no NAT gateway by
                              default — Fargate tasks run in public subnets
                              with assign_public_ip=True). Mutually exclusive
                              with vpc_id. Intended for deploys into a fresh
                              sub account that has no existing VPC infra.

Optional context:
  - nat_gateways            : with create_vpc=true, number of NAT gateways
                              (default 0 — tasks run in public subnets, ~$0/mo
                              on the VPC itself; set 1 for ~$33/mo NAT or 2
                              for HA NAT ~$66/mo, which moves tasks back to
                              private subnets).
  - acm_cert_arn            : ACM cert in the same region for the ALB. If
                              empty, the ALB serves plain HTTP — fine for
                              initial smoke-testing on the corporate network.
  - private_subnet_ids      : comma-separated list of subnet IDs (e.g.
                              'subnet-aaa,subnet-bbb'). Required when the
                              VPC's subnets don't carry CDK's
                              aws-cdk:subnet-type tag (typical for VPCs
                              managed outside CDK). Must include ≥2 subnets
                              in different AZs for ALB high-availability.
  - availability_zones      : comma-separated AZs matching the subnets,
                              same order (e.g. 'us-west-2a,us-west-2b').
                              Required when private_subnet_ids is set.
  - add_vpc_endpoints       : 'true' (default 'false'). When the VPC has
                              no NAT/IGW egress, set this to create the
                              interface endpoints the Fargate tasks need
                              (Secrets Manager, ECR API, ECR Docker,
                              CloudWatch Logs) plus the S3 gateway
                              endpoint. Costs ~$56/mo across 2 AZs.
  - vpc_cidr                : VPC CIDR (e.g. '172.31.0.0/16'). Required
                              alongside add_vpc_endpoints=true so the
                              endpoint security group can scope its
                              ingress rule to the VPC's address space.
  - private_route_table_ids : comma-separated route table IDs, same order
                              as private_subnet_ids. Required alongside
                              add_vpc_endpoints=true — the S3 gateway
                              endpoint needs to add its route to the
                              subnets' route table(s). If all the chosen
                              subnets use the VPC's main route table,
                              repeat its ID once per subnet.
  - environment             : 'prod', 'staging', etc. Defaults to 'prod'.
                              Applied as a stack-level tag.
  - tags                    : JSON object of additional tags to apply
                              stack-wide, e.g.
                              -c tags='{"CostCenter":"4321","Owner":"AMS-IT"}'

Outputs:
  - ALB DNS name (point your internal DNS CNAME at this)
  - Cognito IDs (UserPoolId, AppClientId) for the runbook
  - Cluster + service names for ``aws ecs run-task`` commands
"""
import json
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    aws_applicationautoscaling as appscaling,
    aws_certificatemanager as acm,
    aws_cognito as cognito,
    aws_ec2 as ec2,
    aws_ecr_assets as ecr_assets,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_elasticloadbalancingv2 as elbv2,
    aws_logs as logs,
    aws_rds as rds,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[2]


class AmsDashboardStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        # Synthesizer reads the bootstrap qualifier from context so this stack
        # uses the matching cdk-amsdash01-...-role-* roles created by
        # `cdk bootstrap --qualifier amsdash01`.
        qualifier = scope.node.try_get_context("@aws-cdk/core:bootstrapQualifier")
        if qualifier and "synthesizer" not in kwargs:
            kwargs["synthesizer"] = cdk.DefaultStackSynthesizer(qualifier=qualifier)
        super().__init__(scope, construct_id, **kwargs)

        # ── Context ─────────────────────────────────────────────────────
        vpc_id = self.node.try_get_context("vpc_id")
        create_vpc = str(self.node.try_get_context("create_vpc") or "").lower() == "true"
        if not vpc_id and not create_vpc:
            raise ValueError(
                "Choose a VPC strategy: pass -c vpc_id=vpc-xxx to consume an "
                "existing VPC, or -c create_vpc=true to have this stack "
                "provision a new VPC (2 AZs, 1 NAT gateway, public + private "
                "subnets — suitable for a fresh sub account)."
            )
        if vpc_id and create_vpc:
            raise ValueError(
                "vpc_id and create_vpc=true are mutually exclusive — pick one."
            )
        cert_arn = self.node.try_get_context("acm_cert_arn") or ""
        environment = self.node.try_get_context("environment") or "prod"
        extra_tags_raw = self.node.try_get_context("tags") or "{}"
        try:
            extra_tags = json.loads(extra_tags_raw) if isinstance(extra_tags_raw, str) else extra_tags_raw
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Invalid JSON in 'tags' context: {e}. Example: "
                "-c tags='{\"CostCenter\":\"4321\",\"Owner\":\"AMS-IT\"}'"
            ) from e
        if not isinstance(extra_tags, dict):
            raise ValueError("'tags' context must be a JSON object of key→value strings.")

        # ── Stack-wide tags (propagate to all taggable resources) ───────
        default_tags = {
            "Application": "ams-dashboard",
            "Environment": environment,
            "ManagedBy": "CDK",
        }
        for key, value in {**default_tags, **{k: str(v) for k, v in extra_tags.items()}}.items():
            cdk.Tags.of(self).add(key, value)

        # ── Networking ──────────────────────────────────────────────────
        # Prefer explicit subnet IDs when supplied; fall back to tag-based
        # discovery via Vpc.from_lookup (which only works if the VPC's
        # subnets are tagged with aws-cdk:subnet-type).
        private_subnet_ids_raw = self.node.try_get_context("private_subnet_ids") or ""
        azs_raw = self.node.try_get_context("availability_zones") or ""
        subnet_ids = [s.strip() for s in str(private_subnet_ids_raw).split(",") if s.strip()]
        azs = [a.strip() for a in str(azs_raw).split(",") if a.strip()]

        # vpc_cidr is needed if we'll be creating VPC interface endpoints
        # (they need to know the VPC's CIDR for their SG rules). Read it
        # up-front so it can also be passed to Vpc.from_vpc_attributes.
        vpc_cidr_context = self.node.try_get_context("vpc_cidr") or ""
        # private_route_table_ids is needed when creating the S3 gateway
        # endpoint — it adds a route via the gateway endpoint to whichever
        # route tables the subnets use. Must be the same length as
        # private_subnet_ids and in the same order.
        rtb_raw = self.node.try_get_context("private_route_table_ids") or ""
        rtbs = [r.strip() for r in str(rtb_raw).split(",") if r.strip()]

        if create_vpc:
            # Fresh-account path: provision a new VPC with 2 AZs.
            #
            # Default (nat_gateways=0): no NAT, ~$0/mo on the VPC itself.
            #   - Fargate tasks run in PUBLIC subnets with assign_public_ip=True
            #     so they can pull images from ECR and reach Atlassian / Cognito
            #     directly via the IGW. Inbound is still locked down by the
            #     task security group (only the ALB SG can reach them).
            #   - Aurora + internal ALB live in PRIVATE_WITH_EGRESS subnets
            #     (no NAT means no actual egress, but that's fine — neither
            #     needs to reach the internet).
            #
            # nat_gateways>=1: tasks move to PRIVATE_WITH_EGRESS subnets and
            #   reach the internet through NAT (~$33/mo per NAT). Pick this if
            #   policy prohibits public IPs on workloads, or if the SecOps team
            #   would rather pay for NAT than audit task SGs.
            nat_gateways_raw = self.node.try_get_context("nat_gateways")
            nat_gateways = int(nat_gateways_raw) if nat_gateways_raw is not None else 0
            vpc = ec2.Vpc(
                self,
                "Vpc",
                max_azs=2,
                nat_gateways=nat_gateways,
                subnet_configuration=[
                    ec2.SubnetConfiguration(
                        name="Public",
                        subnet_type=ec2.SubnetType.PUBLIC,
                        cidr_mask=24,
                    ),
                    ec2.SubnetConfiguration(
                        name="Private",
                        subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                        cidr_mask=24,
                    ),
                ],
            )
            # Aurora + internal ALB always sit in the private subnets.
            private_subnets = ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            )
            # Fargate task placement depends on whether NAT exists.
            if nat_gateways > 0:
                task_subnets = private_subnets
                task_assign_public_ip = False
            else:
                task_subnets = ec2.SubnetSelection(
                    subnet_type=ec2.SubnetType.PUBLIC
                )
                task_assign_public_ip = True
        elif subnet_ids:
            if not azs:
                raise ValueError(
                    "When -c private_subnet_ids=... is set, also pass "
                    "-c availability_zones=us-west-2a,us-west-2b (one AZ per "
                    "subnet, same order)."
                )
            if len(subnet_ids) != len(azs):
                raise ValueError(
                    f"private_subnet_ids has {len(subnet_ids)} entries but "
                    f"availability_zones has {len(azs)}. Lengths must match."
                )
            if len(subnet_ids) < 2:
                raise ValueError(
                    "Provide at least 2 private subnet IDs in different AZs — "
                    "the internal ALB requires multi-AZ for HA."
                )
            vpc_attrs = dict(
                vpc_id=vpc_id,
                availability_zones=azs,
                private_subnet_ids=subnet_ids,
            )
            if vpc_cidr_context:
                vpc_attrs["vpc_cidr_block"] = vpc_cidr_context
            if rtbs:
                if len(rtbs) != len(subnet_ids):
                    raise ValueError(
                        f"private_route_table_ids has {len(rtbs)} entries but "
                        f"private_subnet_ids has {len(subnet_ids)}. Lengths must "
                        f"match (one route table ID per subnet, same order)."
                    )
                vpc_attrs["private_subnet_route_table_ids"] = rtbs
            vpc = ec2.Vpc.from_vpc_attributes(self, "Vpc", **vpc_attrs)
            private_subnets = ec2.SubnetSelection(subnets=vpc.private_subnets)
            task_subnets = private_subnets
            task_assign_public_ip = False
        else:
            vpc = ec2.Vpc.from_lookup(self, "Vpc", vpc_id=vpc_id)
            private_subnets = ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            )
            task_subnets = private_subnets
            task_assign_public_ip = False

        # ── Secrets ─────────────────────────────────────────────────────
        django_secret = secretsmanager.Secret(
            self,
            "DjangoSecretKey",
            description="Django SECRET_KEY for AMS Dashboard.",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                password_length=64, exclude_punctuation=False, exclude_characters='"@/\\'
            ),
        )

        # JIRA creds — admin fills in via the AWS console after first deploy.
        jira_secret = secretsmanager.Secret(
            self,
            "JiraServiceAccount",
            description=(
                "JIRA SM credentials. Fill in JSON: "
                '{"JIRA_URL": "https://yourcompany.atlassian.net", '
                '"JIRA_EMAIL": "...", "JIRA_TOKEN": "..."}'
            ),
            secret_object_value={
                "JIRA_URL": cdk.SecretValue.unsafe_plain_text(""),
                "JIRA_EMAIL": cdk.SecretValue.unsafe_plain_text(""),
                "JIRA_TOKEN": cdk.SecretValue.unsafe_plain_text(""),
            },
        )

        # ── Aurora Postgres Serverless v2 ──────────────────────────────
        db_sg = ec2.SecurityGroup(
            self,
            "DbSg",
            vpc=vpc,
            description="Aurora Postgres for AMS Dashboard",
            allow_all_outbound=False,
        )
        db_cluster = rds.DatabaseCluster(
            self,
            "Db",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_16_4
            ),
            writer=rds.ClusterInstance.serverless_v2("Writer"),
            serverless_v2_min_capacity=0.5,
            serverless_v2_max_capacity=2.0,
            vpc=vpc,
            vpc_subnets=private_subnets,
            security_groups=[db_sg],
            default_database_name="ams_dashboard",
            credentials=rds.Credentials.from_generated_secret("ams"),
            removal_policy=RemovalPolicy.SNAPSHOT,
            backup=rds.BackupProps(retention=Duration.days(7)),
        )

        # ── Cognito ────────────────────────────────────────────────────
        user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name="ams-dashboard",
            sign_in_aliases=cognito.SignInAliases(email=True),
            self_sign_up_enabled=False,
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=RemovalPolicy.RETAIN,
        )
        app_client = user_pool.add_client(
            "AppClient",
            auth_flows=cognito.AuthFlow(
                user_password=True, admin_user_password=True
            ),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
            ),
            generate_secret=False,
        )

        # ── Container image (CDK builds + pushes to ECR) ───────────────
        image_asset = ecr_assets.DockerImageAsset(
            self,
            "ApiImage",
            directory=str(REPO_ROOT),
            file="Dockerfile",
            platform=ecr_assets.Platform.LINUX_AMD64,
        )
        image = ecs.ContainerImage.from_docker_image_asset(image_asset)

        # ── ECS cluster ────────────────────────────────────────────────
        cluster = ecs.Cluster(
            self,
            "Cluster",
            vpc=vpc,
            container_insights_v2=ecs.ContainerInsights.ENABLED,
        )

        log_group = logs.LogGroup(
            self,
            "ApiLogs",
            log_group_name="/ams-dashboard/api",
            retention=logs.RetentionDays.TWO_WEEKS,
            # RETAIN so logs survive stack rollback — without this, a CFN
            # rollback after a failed first deploy nukes the log group along
            # with the rest of the stack, and we lose the container's stdout
            # that explains why it failed.
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Env + secrets are shared by API and sync tasks.
        common_env = {
            "DEBUG": "False",
            "AUTH_BYPASS": "0",
            "ALLOWED_HOSTS": "*",  # internal ALB only
            "DB_NAME": "ams_dashboard",
            "COGNITO_REGION": self.region,
            "COGNITO_USER_POOL_ID": user_pool.user_pool_id,
            "COGNITO_APP_CLIENT_ID": app_client.user_pool_client_id,
        }
        common_secrets = {
            "SECRET_KEY": ecs.Secret.from_secrets_manager(django_secret),
            "DB_HOST": ecs.Secret.from_secrets_manager(db_cluster.secret, "host"),
            "DB_PORT": ecs.Secret.from_secrets_manager(db_cluster.secret, "port"),
            "DB_USER": ecs.Secret.from_secrets_manager(db_cluster.secret, "username"),
            "DB_PASSWORD": ecs.Secret.from_secrets_manager(db_cluster.secret, "password"),
            "JIRA_URL": ecs.Secret.from_secrets_manager(jira_secret, "JIRA_URL"),
            "JIRA_EMAIL": ecs.Secret.from_secrets_manager(jira_secret, "JIRA_EMAIL"),
            "JIRA_TOKEN": ecs.Secret.from_secrets_manager(jira_secret, "JIRA_TOKEN"),
        }

        # ── API service (internal ALB → Fargate) ───────────────────────
        certificate = (
            acm.Certificate.from_certificate_arn(self, "ApiCert", cert_arn)
            if cert_arn
            else None
        )

        api_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "ApiService",
            cluster=cluster,
            cpu=256,
            memory_limit_mib=512,
            desired_count=1,
            public_load_balancer=False,  # internal ALB
            task_subnets=task_subnets,
            assign_public_ip=task_assign_public_ip,
            certificate=certificate,
            redirect_http=bool(certificate),
            protocol=elbv2.ApplicationProtocol.HTTPS if certificate else elbv2.ApplicationProtocol.HTTP,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=image,
                container_port=8000,
                environment=common_env,
                secrets=common_secrets,
                log_driver=ecs.LogDriver.aws_logs(
                    stream_prefix="api", log_group=log_group
                ),
            ),
            health_check_grace_period=Duration.seconds(60),
            # Circuit breaker still fires when tasks repeatedly fail to
            # start, but we set rollback=False so the failing tasks (and
            # their stop reasons) stay visible for debugging instead of
            # being torn down. Re-enable rollback once the first deploy is
            # known-good.
            circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=False),
            min_healthy_percent=50,
            max_healthy_percent=200,
        )
        api_service.target_group.configure_health_check(
            path="/health", healthy_http_codes="200"
        )
        db_cluster.connections.allow_default_port_from(api_service.service)

        # ── VPC endpoints (optional, when the VPC has no NAT/IGW egress) ──
        add_endpoints = str(self.node.try_get_context("add_vpc_endpoints") or "").lower() == "true"
        if add_endpoints:
            if not vpc_cidr_context:
                raise ValueError(
                    "When -c add_vpc_endpoints=true is set, also pass "
                    "-c vpc_cidr=<VPC CIDR, e.g. 172.31.0.0/16>. The "
                    "endpoint security group needs to allow HTTPS from "
                    "anywhere in the VPC."
                )
            if not rtbs:
                raise ValueError(
                    "When -c add_vpc_endpoints=true is set, also pass "
                    "-c private_route_table_ids=<rtb-id>[,<rtb-id>] (one "
                    "per subnet, same order as private_subnet_ids). The S3 "
                    "gateway endpoint needs to add its route to those route "
                    "tables. If all subnets use the VPC's main route table, "
                    "repeat the same RTB ID."
                )
            vpc_cidr = vpc_cidr_context
            endpoint_sg = ec2.SecurityGroup(
                self,
                "VpcEndpointSg",
                vpc=vpc,
                description="HTTPS inbound to AWS service interface endpoints",
                allow_all_outbound=False,
            )
            endpoint_sg.add_ingress_rule(
                ec2.Peer.ipv4(vpc_cidr),
                ec2.Port.tcp(443),
                "HTTPS from anywhere in this VPC",
            )

            interface_services = [
                ("SecretsManager", ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER),
                ("EcrApi", ec2.InterfaceVpcEndpointAwsService.ECR),
                ("EcrDkr", ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER),
                ("Logs", ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS),
            ]
            for name, svc in interface_services:
                ec2.InterfaceVpcEndpoint(
                    self,
                    f"VpcEndpoint{name}",
                    vpc=vpc,
                    service=svc,
                    subnets=private_subnets,
                    security_groups=[endpoint_sg],
                    private_dns_enabled=True,
                )
            # ECR layer storage lives in S3 — gateway endpoint is free and
            # required for image pulls when there's no NAT/IGW.
            ec2.GatewayVpcEndpoint(
                self,
                "VpcEndpointS3",
                vpc=vpc,
                service=ec2.GatewayVpcEndpointAwsService.S3,
                subnets=[private_subnets],
            )

        # ── Migration task definition (manual: aws ecs run-task) ───────
        migration_task = ecs.FargateTaskDefinition(
            self, "MigrationTask", cpu=256, memory_limit_mib=512
        )
        django_secret.grant_read(migration_task.task_role)
        jira_secret.grant_read(migration_task.task_role)
        db_cluster.secret.grant_read(migration_task.task_role)
        migration_task.add_container(
            "migrate",
            image=image,
            command=["python", "manage.py", "migrate", "--noinput"],
            environment=common_env,
            secrets=common_secrets,
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="migrate", log_group=log_group
            ),
        )
        # When the admin runs the migration task they should attach the API
        # service's security group; the DB already permits that SG.

        # ── Scheduled JIRA sync workers ────────────────────────────────
        sync_log_group = logs.LogGroup(
            self,
            "SyncLogs",
            log_group_name="/ams-dashboard/jira-sync",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.RETAIN,
        )

        def _scheduled_sync(name: str, mgmt_command: str, schedule: appscaling.Schedule):
            task_def = ecs.FargateTaskDefinition(
                self, f"{name}Task", cpu=256, memory_limit_mib=512
            )
            django_secret.grant_read(task_def.task_role)
            jira_secret.grant_read(task_def.task_role)
            db_cluster.secret.grant_read(task_def.task_role)
            task_def.add_container(
                name,
                image=image,
                command=["python", "manage.py", mgmt_command],
                environment=common_env,
                secrets=common_secrets,
                logging=ecs.LogDriver.aws_logs(
                    stream_prefix=name, log_group=sync_log_group
                ),
            )
            scheduled = ecs_patterns.ScheduledFargateTask(
                self,
                name,
                cluster=cluster,
                scheduled_fargate_task_definition_options=ecs_patterns.ScheduledFargateTaskDefinitionOptions(
                    task_definition=task_def
                ),
                schedule=schedule,
                subnet_selection=task_subnets,
            )
            # ScheduledFargateTask doesn't expose assign_public_ip directly
            # (open CDK gap). When tasks run in public subnets we need to
            # set it via CfnRule property override so they can reach Atlassian
            # + ECR — SG still blocks all inbound from the SG defaulted by
            # the construct.
            if task_assign_public_ip:
                cfn_rule = scheduled.event_rule.node.default_child
                cfn_rule.add_property_override(
                    "Targets.0.EcsParameters.NetworkConfiguration.AwsVpcConfiguration.AssignPublicIp",
                    "ENABLED",
                )
            # Allow the scheduled task's SG to reach the DB.
            for sg in scheduled.task.security_groups:
                db_cluster.connections.allow_default_port_from(sg)
            return task_def

        _scheduled_sync(
            "JiraSyncOrgs",
            "sync_jira_orgs",
            appscaling.Schedule.rate(Duration.hours(6)),
        )
        _scheduled_sync(
            "JiraSyncUsers",
            "sync_jira_users",
            appscaling.Schedule.rate(Duration.hours(6)),
        )
        _scheduled_sync(
            "JiraSyncTickets",
            "sync_jira_tickets",
            appscaling.Schedule.rate(Duration.minutes(30)),
        )

        # ── Outputs ────────────────────────────────────────────────────
        cdk.CfnOutput(self, "AlbDnsName", value=api_service.load_balancer.load_balancer_dns_name)
        cdk.CfnOutput(self, "ClusterName", value=cluster.cluster_name)
        cdk.CfnOutput(self, "ApiServiceName", value=api_service.service.service_name)
        cdk.CfnOutput(self, "MigrationTaskArn", value=migration_task.task_definition_arn)
        cdk.CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        cdk.CfnOutput(self, "AppClientId", value=app_client.user_pool_client_id)
        cdk.CfnOutput(self, "DbClusterEndpoint", value=db_cluster.cluster_endpoint.hostname)
        cdk.CfnOutput(self, "DjangoSecretArn", value=django_secret.secret_arn)
        cdk.CfnOutput(self, "JiraSecretArn", value=jira_secret.secret_arn)
