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
  - vpc_id                 : the existing shared VPC ID
  - acm_cert_arn (optional): ACM cert in the same region for the ALB. If
                             empty, the ALB serves plain HTTP — fine for
                             initial smoke-testing on the corporate network.

Outputs:
  - ALB DNS name (point your internal DNS CNAME at this)
  - Cognito IDs (UserPoolId, AppClientId) for the runbook
  - Cluster + service names for ``aws ecs run-task`` commands
"""
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
        super().__init__(scope, construct_id, **kwargs)

        # ── Context ─────────────────────────────────────────────────────
        vpc_id = self.node.try_get_context("vpc_id")
        if not vpc_id:
            raise ValueError(
                "Set vpc_id context (cdk deploy -c vpc_id=vpc-xxx) — the existing "
                "shared VPC the app should live in."
            )
        cert_arn = self.node.try_get_context("acm_cert_arn") or ""

        # ── Networking ──────────────────────────────────────────────────
        vpc = ec2.Vpc.from_lookup(self, "Vpc", vpc_id=vpc_id)
        private_subnets = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)

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
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
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
            cpu=512,
            memory_limit_mib=1024,
            desired_count=2,
            public_load_balancer=False,  # internal ALB
            task_subnets=private_subnets,
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
            circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=True),
            min_healthy_percent=50,
            max_healthy_percent=200,
        )
        api_service.target_group.configure_health_check(
            path="/health", healthy_http_codes="200"
        )
        db_cluster.connections.allow_default_port_from(api_service.service)

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
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
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
                subnet_selection=private_subnets,
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
