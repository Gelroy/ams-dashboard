"""CDK assertions for AmsDashboardStack.

Synth is run with asset staging disabled so the Docker image asset doesn't
copy the repo into a temp cdk.out on every test; the image hash is still
computed from the build context.
"""
import aws_cdk as cdk
import aws_cdk.assertions as assertions
import pytest

from infra.infra_stack import AmsDashboardStack

BASE_CONTEXT = {
    "aws:cdk:disable-asset-staging": True,
    "@aws-cdk/core:bootstrapQualifier": "amsdash01",
}
ENV = cdk.Environment(account="123456789012", region="us-east-1")

DOMAIN_CONTEXT = {
    "create_vpc": "true",
    "public_alb": "true",
    "environment": "personal-dev",
    "domain_name": "ams-dev.example.com",
    "hosted_zone_id": "Z0000000000000000000A",
    "hosted_zone_name": "example.com",
    "jira_sync_enabled": "false",
    "aurora_auto_pause_minutes": "15",
    "portal_enabled": "true",
}


def synth(context: dict, stack_name: str = "AmsDashboardStack") -> assertions.Template:
    app = cdk.App(context={**BASE_CONTEXT, **context})
    stack = AmsDashboardStack(app, stack_name, env=ENV)
    return assertions.Template.from_stack(stack)


@pytest.fixture(scope="module")
def prod_template():
    return synth({"create_vpc": "true", "public_alb": "true", "allow_public_http": "true"})


@pytest.fixture(scope="module")
def dev_template():
    return synth(DOMAIN_CONTEXT, stack_name="AmsDashboardPersonalDev")


# ── prod path: unchanged physical names, HTTP, all three sync schedules ──

def test_prod_keeps_bare_resource_names(prod_template):
    prod_template.has_resource_properties(
        "AWS::Cognito::UserPool", {"UserPoolName": "ams-dashboard"}
    )
    prod_template.has_resource_properties(
        "AWS::Logs::LogGroup", {"LogGroupName": "/ams-dashboard/api"}
    )
    prod_template.has_resource_properties(
        "AWS::Logs::LogGroup", {"LogGroupName": "/ams-dashboard/jira-sync"}
    )


def test_prod_without_cert_serves_http_only(prod_template):
    prod_template.resource_count_is("AWS::CertificateManager::Certificate", 0)
    prod_template.resource_count_is("AWS::Route53::RecordSet", 0)
    prod_template.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::Listener", {"Port": 80, "Protocol": "HTTP"}
    )


def test_prod_aurora_keeps_half_acu_floor(prod_template):
    prod_template.has_resource_properties(
        "AWS::RDS::DBCluster",
        {"ServerlessV2ScalingConfiguration": {"MinCapacity": 0.5, "MaxCapacity": 2}},
    )


def test_prod_has_three_jira_sync_schedules(prod_template):
    prod_template.resource_count_is("AWS::Events::Rule", 3)


# ── second environment: suffixed names, issued cert, DNS alias, no sync ──

def test_dev_suffixes_physical_names(dev_template):
    dev_template.has_resource_properties(
        "AWS::Cognito::UserPool", {"UserPoolName": "ams-dashboard-personal-dev"}
    )
    dev_template.has_resource_properties(
        "AWS::Logs::LogGroup", {"LogGroupName": "/ams-dashboard-personal-dev/api"}
    )


def test_dev_issues_wildcard_cert_validated_in_zone(dev_template):
    dev_template.has_resource_properties(
        "AWS::CertificateManager::Certificate",
        {
            "DomainName": "ams-dev.example.com",
            "SubjectAlternativeNames": ["*.ams-dev.example.com"],
            "ValidationMethod": "DNS",
            "DomainValidationOptions": assertions.Match.array_with(
                [{"DomainName": "ams-dev.example.com", "HostedZoneId": "Z0000000000000000000A"}]
            ),
        },
    )


def test_dev_serves_https_and_redirects_http(dev_template):
    dev_template.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::Listener", {"Port": 443, "Protocol": "HTTPS"}
    )
    dev_template.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::Listener",
        {
            "Port": 80,
            "DefaultActions": [
                {"Type": "redirect", "RedirectConfig": assertions.Match.object_like({"Protocol": "HTTPS"})}
            ],
        },
    )


def test_dev_creates_alias_record_at_alb(dev_template):
    dev_template.has_resource_properties(
        "AWS::Route53::RecordSet",
        {
            "Name": "ams-dev.example.com.",
            "Type": "A",
            "HostedZoneId": "Z0000000000000000000A",
            "AliasTarget": assertions.Match.any_value(),
        },
    )


def test_dev_passes_csrf_origin_to_containers(dev_template):
    dev_template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": assertions.Match.array_with(
                [
                    assertions.Match.object_like(
                        {
                            "Environment": assertions.Match.array_with(
                                [
                                    {
                                        "Name": "CSRF_TRUSTED_ORIGINS",
                                        "Value": "https://ams-dev.example.com,https://*.ams-dev.example.com",
                                    }
                                ]
                            )
                        }
                    )
                ]
            )
        },
    )


def test_dev_aurora_auto_pauses_after_15_minutes(dev_template):
    dev_template.has_resource_properties(
        "AWS::RDS::DBCluster",
        {
            "ServerlessV2ScalingConfiguration": {
                "MinCapacity": 0,
                "MaxCapacity": 2,
                "SecondsUntilAutoPause": 900,
            }
        },
    )


def test_api_desired_count_is_configurable():
    template = synth({**DOMAIN_CONTEXT, "api_desired_count": "0"}, stack_name="Parked")
    template.has_resource_properties("AWS::ECS::Service", {"DesiredCount": 0})


def test_auto_pause_minutes_validated():
    with pytest.raises(ValueError, match="aurora_auto_pause_minutes"):
        synth({"create_vpc": "true", "aurora_auto_pause_minutes": "2"})


def test_dev_has_no_jira_sync_schedules(dev_template):
    dev_template.resource_count_is("AWS::Events::Rule", 0)


def test_dev_outputs_app_url(dev_template):
    dev_template.has_output("AppUrl", {"Value": "https://ams-dev.example.com"})


# ── validation ──

def test_domain_requires_zone():
    with pytest.raises(ValueError, match="hosted_zone_id"):
        synth({"create_vpc": "true", "public_alb": "true", "domain_name": "x.example.com"})


def test_domain_must_be_inside_zone():
    with pytest.raises(ValueError, match="not inside hosted zone"):
        synth(
            {
                "create_vpc": "true",
                "public_alb": "true",
                "domain_name": "x.other.com",
                "hosted_zone_id": "Z1",
                "hosted_zone_name": "example.com",
            }
        )


def test_environment_must_be_a_slug():
    with pytest.raises(ValueError, match="environment"):
        synth({"create_vpc": "true", "environment": "Personal Dev"})


def test_public_alb_with_domain_needs_no_http_override():
    # A domain counts as TLS, so the plain-HTTP guard must not fire.
    synth(DOMAIN_CONTEXT)


# ── customer portal identity layer ──

def test_prod_has_only_the_staff_pool(prod_template):
    prod_template.resource_count_is("AWS::Cognito::UserPool", 1)
    prod_template.resource_count_is("AWS::Cognito::UserPoolClient", 1)
    assert "PORTAL_" not in str(prod_template.to_json())


def test_dev_has_a_separate_customer_pool_with_mandatory_totp(dev_template):
    dev_template.resource_count_is("AWS::Cognito::UserPool", 2)
    dev_template.has_resource_properties(
        "AWS::Cognito::UserPool",
        {
            "UserPoolName": "ams-portal-personal-dev",
            "MfaConfiguration": "ON",
            "EnabledMfas": ["SOFTWARE_TOKEN_MFA"],
            "AdminCreateUserConfig": assertions.Match.object_like(
                {"AllowAdminCreateUserOnly": True}
            ),
            "Policies": {
                "PasswordPolicy": assertions.Match.object_like({"MinimumLength": 12})
            },
        },
    )


def test_portal_invitation_email_points_at_the_portal(dev_template):
    pools = dev_template.find_resources(
        "AWS::Cognito::UserPool", {"Properties": {"UserPoolName": "ams-portal-personal-dev"}}
    )
    (pool,) = pools.values()
    body = pool["Properties"]["AdminCreateUserConfig"]["InviteMessageTemplate"]["EmailMessage"]
    assert "https://portal.ams-dev.example.com" in body
    assert "{username}" in body and "{####}" in body


def test_portal_client_is_public_password_flow_with_short_refresh(dev_template):
    dev_template.has_resource_properties(
        "AWS::Cognito::UserPoolClient",
        {
            "ExplicitAuthFlows": ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
            "GenerateSecret": False,
            "PreventUserExistenceErrors": "ENABLED",
            "EnableTokenRevocation": True,
            "RefreshTokenValidity": 1440,
        },
    )


def test_portal_hostname_aliases_the_same_alb(dev_template):
    dev_template.has_resource_properties(
        "AWS::Route53::RecordSet",
        {"Name": "portal.ams-dev.example.com.", "Type": "A"},
    )
    dev_template.resource_count_is("AWS::ElasticLoadBalancingV2::LoadBalancer", 1)


def test_api_containers_get_portal_settings(dev_template):
    dev_template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": assertions.Match.array_with(
                [
                    assertions.Match.object_like(
                        {
                            "Environment": assertions.Match.array_with(
                                [
                                    {"Name": "PORTAL_HOST", "Value": "portal.ams-dev.example.com"},
                                    {"Name": "PORTAL_STAFF_EMAIL_DOMAINS", "Value": "imt.ca"},
                                ]
                            )
                        }
                    )
                ]
            )
        },
    )


def test_api_task_role_may_only_administer_the_portal_pool(dev_template):
    policies = dev_template.find_resources("AWS::IAM::Policy")
    statements = [
        s
        for p in policies.values()
        for s in p["Properties"]["PolicyDocument"]["Statement"]
        if any("cognito-idp" in a for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"]))
    ]
    assert len(statements) == 1
    (stmt,) = statements
    assert sorted(stmt["Action"]) == [
        "cognito-idp:AdminCreateUser",
        "cognito-idp:AdminDisableUser",
        "cognito-idp:AdminEnableUser",
        "cognito-idp:AdminGetUser",
        "cognito-idp:AdminUserGlobalSignOut",
    ]
    # Scoped to one pool's ARN (a GetAtt on the portal pool), never "*".
    assert stmt["Resource"] != "*"
    assert "PortalUserPool" in str(stmt["Resource"])


# ── reports bucket and customer email ──


def test_reports_bucket_is_private_encrypted_and_tls_only(dev_template):
    dev_template.resource_count_is("AWS::S3::Bucket", 1)
    dev_template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
            "BucketEncryption": assertions.Match.any_value(),
            "VersioningConfiguration": {"Status": "Enabled"},
            "OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]},
        },
    )
    policy = next(iter(dev_template.find_resources("AWS::S3::BucketPolicy").values()))
    deny = [s for s in policy["Properties"]["PolicyDocument"]["Statement"] if s["Effect"] == "Deny"]
    assert deny and deny[0]["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}


def _statements(template, needle):
    return [
        s
        for p in template.find_resources("AWS::IAM::Policy").values()
        for s in p["Properties"]["PolicyDocument"]["Statement"]
        if any(needle in a for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"]))
    ]


def test_api_may_write_and_read_reports_but_not_delete_or_list_buckets(dev_template):
    actions = sorted(
        a
        for s in _statements(dev_template, "s3:")
        for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])
    )
    assert "s3:PutObject" in actions and "s3:GetObject*" in actions
    assert not any(a.startswith("s3:Delete") or a in ("s3:*", "s3:ListAllMyBuckets") for a in actions)
    for s in _statements(dev_template, "s3:"):
        assert "ReportsBucket" in str(s["Resource"])


def test_api_containers_get_report_settings_with_email_off_by_default(dev_template):
    dev_template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": assertions.Match.array_with(
                [
                    assertions.Match.object_like(
                        {
                            "Environment": assertions.Match.array_with(
                                [
                                    {"Name": "PORTAL_EMAIL_MODE", "Value": "log"},
                                    {"Name": "PORTAL_EMAIL_FROM", "Value": ""},
                                ]
                            )
                        }
                    )
                ]
            )
        },
    )
    assert "REPORTS_BUCKET" in str(dev_template.find_resources("AWS::ECS::TaskDefinition"))
    assert _statements(dev_template, "ses:") == []


def test_email_sender_turns_on_ses_limited_to_that_address():
    template = synth({**DOMAIN_CONTEXT, "portal_email_from": "reports@ams.example.com"})
    (stmt,) = _statements(template, "ses:")
    assert stmt["Action"] == "ses:SendEmail"
    assert stmt["Condition"] == {"StringEquals": {"ses:FromAddress": "reports@ams.example.com"}}
    assert '"PORTAL_EMAIL_MODE", "Value": "ses"' in __import__("json").dumps(
        template.find_resources("AWS::ECS::TaskDefinition")
    )


def test_no_reports_bucket_without_the_portal(prod_template):
    prod_template.resource_count_is("AWS::S3::Bucket", 0)
    assert "REPORTS_BUCKET" not in str(prod_template.find_resources("AWS::ECS::TaskDefinition"))


def test_email_sender_requires_the_portal():
    with pytest.raises(ValueError, match="portal_email_from"):
        synth({"create_vpc": "true", "portal_email_from": "reports@ams.example.com"})


def test_monthly_drafts_are_off_unless_a_day_is_set(dev_template):
    assert "generate_reports" not in str(dev_template.find_resources("AWS::ECS::TaskDefinition"))


def test_monthly_draft_schedule_runs_generate_reports_once_a_month():
    template = synth({**DOMAIN_CONTEXT, "reports_schedule_day": "2"})
    template.resource_count_is("AWS::Events::Rule", 1)
    template.has_resource_properties(
        "AWS::Events::Rule",
        {
            "ScheduleExpression": "cron(0 9 2 * ? *)",
            "State": "ENABLED",
            "Targets": [
                assertions.Match.object_like(
                    {
                        "EcsParameters": assertions.Match.object_like(
                            {
                                "LaunchType": "FARGATE",
                                "NetworkConfiguration": {
                                    "AwsVpcConfiguration": assertions.Match.object_like(
                                        {"AssignPublicIp": "ENABLED"}
                                    )
                                },
                            }
                        )
                    }
                )
            ],
        },
    )
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": [
                assertions.Match.object_like(
                    {"Command": ["python", "manage.py", "generate_reports"]}
                )
            ]
        },
    )
    # The scheduled task writes drafts to the database only: the report
    # bucket stays reachable from the API task role alone.
    scheduled = [
        p["Properties"]
        for p in template.find_resources("AWS::IAM::Policy").values()
        if "ReportsGenerateDraftsTask" in str(p["Properties"]["Roles"])
    ]
    assert scheduled, "expected the scheduled task's own role policies"
    assert "s3:" not in str(scheduled) and "ses:" not in str(scheduled)
    assert "cognito-idp:" not in str(scheduled)


def test_monthly_drafts_fetch_tickets_only_where_jira_is_in_use():
    template = synth(
        {**DOMAIN_CONTEXT, "reports_schedule_day": "2", "jira_sync_enabled": "true"}
    )
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": [
                assertions.Match.object_like(
                    {"Command": ["python", "manage.py", "generate_reports", "--sync-tickets"]}
                )
            ]
        },
    )
    # The synthetic environment (JIRA sync off) must never be told to call JIRA.
    synthetic = synth({**DOMAIN_CONTEXT, "reports_schedule_day": "2"})
    assert "--sync-tickets" not in str(synthetic.find_resources("AWS::ECS::TaskDefinition"))


@pytest.mark.parametrize("day", ["0", "29", "first", "-1"])
def test_monthly_draft_schedule_rejects_days_that_some_months_lack(day):
    with pytest.raises(ValueError, match="reports_schedule_day"):
        synth({**DOMAIN_CONTEXT, "reports_schedule_day": day})


def test_monthly_draft_schedule_requires_the_portal():
    with pytest.raises(ValueError, match="reports_schedule_day"):
        synth({"create_vpc": "true", "reports_schedule_day": "2"})


# ── AI-drafted ticket summaries ──────────────────────────────────────────

def _containers_with_secret(template, name):
    return [
        c["Name"]
        for t in template.find_resources("AWS::ECS::TaskDefinition").values()
        for c in t["Properties"]["ContainerDefinitions"]
        if any(s["Name"] == name for s in c.get("Secrets", []))
    ]


def test_no_anthropic_secret_unless_ai_summaries_are_on(dev_template):
    assert "ANTHROPIC_API_KEY" not in str(dev_template.find_resources("AWS::ECS::TaskDefinition"))
    assert "AnthropicApiKey" not in str(dev_template.find_resources("AWS::SecretsManager::Secret"))


def test_ai_summaries_add_a_placeholder_secret_for_the_api_and_the_monthly_task_only():
    template = synth(
        {**DOMAIN_CONTEXT, "reports_ai_summary": "true", "reports_schedule_day": "2"}
    )
    secrets = template.find_resources("AWS::SecretsManager::Secret")
    (anthropic_secret,) = [v for k, v in secrets.items() if k.startswith("AnthropicApiKey")]
    # A placeholder, never a real key: the key is stored by hand afterwards.
    assert anthropic_secret["Properties"]["SecretString"] == "unset"
    assert sorted(_containers_with_secret(template, "ANTHROPIC_API_KEY")) == [
        "ReportsGenerateDrafts",
        "web",
    ]
    template.has_output("AnthropicSecretArn", {})


def test_ai_summaries_require_the_portal():
    with pytest.raises(ValueError, match="reports_ai_summary"):
        synth({"create_vpc": "true", "reports_ai_summary": "true"})

