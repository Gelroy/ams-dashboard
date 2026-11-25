"""Monthly reports — isolation, workflow and template tests.

Isolation comes first (docs/CUSTOMER_PORTAL.md §4):

  1. Portal documents   a customer sees only their own APPROVED reports;
                        never a draft, a deleted report or another
                        customer's, by list or by guessed id.
  2. Report content     the data gathered for one customer's report never
                        contains another customer's servers, software,
                        patches or metrics.
  3. Notifications      only that customer's active portal users who are
                        flagged for the AMS report are told.
  4. Roles              customers cannot reach the staff report API;
                        viewers cannot generate, edit or approve.
  5. Delivery keys      the monitoring tool's key can deliver metrics
                        and do nothing else (section 11 below).

Then the workflow (draft → approved, frozen afterwards) and the tag
language. Cognito, S3 and SES are never contacted.
"""

from datetime import date, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from baskets.models import ServerInstalledSoftware
from customers.models import Environment, Server
from patching.models import PatchExecution, PatchHistory
from portal.models import PortalAccountStatus
from portal.tests import (  # noqa: F401 — fake_jwks and tenants are fixtures
    client,
    fake_jwks,
    make_account,
    make_user,
    portal_token,
    staff_token,
    tenants,
)
from reports import ingest, notifications, services, storage, templating
from reports.context import build_context
from reports.defaults import DEFAULT_SECTIONS, TICKET_SUMMARY_PLACEHOLDER
from reports.markup import parse_blocks, todo_marks
from reports.models import (
    MetricsDelivery,
    MetricsKey,
    NotificationStatus,
    Report,
    ReportNotification,
    ReportStatus,
    ReportTemplate,
)
from reports.pdf import render_pdf
from software.models import Software, SoftwareRelease

pytestmark = pytest.mark.django_db

OCT = date(2026, 10, 1)
SEP = date(2026, 9, 1)


@pytest.fixture(autouse=True)
def local_storage(settings, tmp_path):
    settings.REPORTS_BUCKET = ""
    settings.REPORTS_LOCAL_DIR = tmp_path / "reports"
    settings.PORTAL_EMAIL_MODE = "log"


def metrics_payload(marker: str) -> dict:
    return {
        "availability": {"percent": 99.9731, "downtimeMinutes": 12},
        "alerts": {"total": 9, "disaster": 0, "high": 1, "average": 3, "warning": 5},
        "hosts": [
            {
                "name": f"{marker}-prod-01",
                "environment": "PROD",
                "availabilityPercent": 99.99,
                "cpuAvgPercent": 21.5,
                "cpuMaxPercent": 88.0,
                "memoryAvgPercent": 60.25,
                "diskUsedPercent": 71.0,
            }
        ],
        "topProblems": [{"name": f"High CPU on {marker}-prod-01", "count": 4, "totalMinutes": 31}],
    }


def furnish(org, marker: str):
    """Give an organization a server, installed software, patch history,
    planned patching, a certificate and October metrics — every value
    carries ``marker`` so leaks between customers are detectable."""
    env, _ = Environment.objects.get_or_create(organization=org, name="PROD")
    server = Server.objects.create(
        environment=env,
        name=f"{marker}-prod-01",
        cert_expires_on=timezone.localdate() + timedelta(days=20),
    )
    software = Software.objects.create(name=f"{marker} AppServer", version="9.5")
    old = SoftwareRelease.objects.create(software=software, release_name=f"{marker}-9.5.1")
    SoftwareRelease.objects.create(
        software=software, release_name=f"{marker}-9.5.2", status="Latest", position=1
    )
    ServerInstalledSoftware.objects.create(server=server, software=software, software_release=old)
    PatchHistory.objects.create(
        organization=org,
        environment=env,
        patched_on=date(2026, 10, 14),
        software=software,
        software_name=software.name,
        from_release=f"{marker}-9.5.0",
        to_release=f"{marker}-9.5.1",
    )
    execution = PatchExecution.objects.create(
        organization=org, environment=env, planned_date=date(2026, 11, 20)
    )
    execution.softwares.add(software)
    MetricsDelivery.objects.create(organization=org, period=OCT, payload=metrics_payload(marker))
    return server


@pytest.fixture
def world(tenants):  # noqa: F811 — the imported fixture
    """The two tenants, each fully furnished and flagged for the report."""
    furnish(tenants["org_a"], "alpha")
    furnish(tenants["org_b"], "bravo")
    for key in ("user_a", "user_b"):
        tenants[key].ams_report = True
        tenants[key].save(update_fields=["ams_report"])
    return tenants


def ready(report: Report) -> Report:
    """Replace the ticket-summary marker so the draft can be approved."""
    sections = [
        {**s, "body": s["body"].replace(TICKET_SUMMARY_PLACEHOLDER, "Quiet month.")}
        for s in report.sections
    ]
    return services.update_draft(report, sections=sections)


def approved(org, period=OCT) -> Report:
    return services.approve(
        ready(services.generate(org, period, actor_email="tech@imt.ca")),
        actor_email="lead@imt.ca",
    )


def staff(admin=True):
    return client(staff_token(admin=admin))


def customer(account):
    return client(portal_token(account))


# ── 1. Portal documents: tenant isolation ──────────────────────────────


def test_customer_lists_only_their_own_approved_reports(world):
    mine = approved(world["org_a"])
    approved(world["org_b"])
    services.generate(world["org_a"], SEP)  # still a draft

    r = customer(world["acct_a"]).get("/api/portal/documents")
    assert r.status_code == 200
    assert [d["id"] for d in r.json()] == [str(mine.id)]
    assert r.json()[0]["period"] == "2026-10"
    # Nothing internal leaks into the customer view.
    assert set(r.json()[0]) == {
        "id",
        "title",
        "period",
        "period_label",
        "published_at",
        "size",
        "filename",
    }


def test_customer_downloads_their_own_report(world):
    report = approved(world["org_a"])
    r = customer(world["acct_a"]).get(f"/api/portal/documents/{report.id}/download")
    assert r.status_code == 200
    assert r["Content-Type"] == "application/pdf"
    assert r["Cache-Control"] == "no-store"
    assert r.content.startswith(b"%PDF")
    assert r.content == storage.get(report.pdf_key)


@pytest.mark.parametrize("suffix", ["", "/download"])
def test_customer_cannot_reach_another_customers_report_by_id(world, suffix):
    theirs = approved(world["org_b"])
    r = customer(world["acct_a"]).get(f"/api/portal/documents/{theirs.id}{suffix}")
    assert r.status_code == 404
    # Positive control: the owner can.
    assert (
        customer(world["acct_b"]).get(f"/api/portal/documents/{theirs.id}{suffix}").status_code
        == 200
    )


@pytest.mark.parametrize("suffix", ["", "/download"])
def test_drafts_are_invisible_to_the_customer(world, suffix):
    draft = services.generate(world["org_a"], OCT)
    c = customer(world["acct_a"])
    assert c.get("/api/portal/documents").json() == []
    assert c.get(f"/api/portal/documents/{draft.id}{suffix}").status_code == 404


def test_deleted_report_disappears_from_the_portal(world):
    report = approved(world["org_a"])
    assert staff().delete(f"/api/reports/{report.id}/").status_code == 204
    c = customer(world["acct_a"])
    assert c.get("/api/portal/documents").json() == []
    assert c.get(f"/api/portal/documents/{report.id}/download").status_code == 404


def test_client_supplied_organization_does_not_widen_documents(world):
    approved(world["org_a"])
    approved(world["org_b"])
    c = customer(world["acct_a"])
    for query in (f"?organization={world['org_b'].id}", f"?organization_id={world['org_b'].id}"):
        assert len(c.get(f"/api/portal/documents{query}").json()) == 1


def test_portal_documents_need_a_usable_customer_token(world):
    report = approved(world["org_a"])
    paths = ["/api/portal/documents", f"/api/portal/documents/{report.id}/download"]
    for path in paths:
        assert client().get(path).status_code == 401
        assert staff().get(path).status_code == 401
    world["acct_a"].status = PortalAccountStatus.DISABLED
    world["acct_a"].save()
    for path in paths:
        assert customer(world["acct_a"]).get(path).status_code == 401


def test_portal_documents_are_read_only(world):
    report = approved(world["org_a"])
    c = customer(world["acct_a"])
    assert c.post("/api/portal/documents", {}, format="json").status_code == 405
    assert c.delete(f"/api/portal/documents/{report.id}").status_code == 405
    assert c.patch(f"/api/portal/documents/{report.id}", {}, format="json").status_code == 405


# ── 2. Report content: no cross-customer data ──────────────────────────


def test_context_holds_only_the_customers_own_data(world):
    text = str(build_context(world["org_a"], OCT))
    assert "alpha-prod-01" in text and "alpha AppServer" in text
    assert "bravo" not in text.lower()


def test_generated_report_and_pdf_source_hold_only_own_data(world):
    report = services.generate(world["org_a"], OCT)
    body = "\n".join(s["body"] for s in report.sections)
    assert "Alpha Health" in body
    assert "alpha-prod-01" in body and "alpha-9.5.2" in body
    assert "bravo" not in (body + str(report.context)).lower()


def test_metrics_come_from_the_right_month_and_customer(world):
    assert build_context(world["org_a"], OCT)["metrics"]["available"] is True
    september = build_context(world["org_a"], SEP)
    assert september["metrics"] == {"available": False}
    assert september["patching"]["applied"] == []


# ── 3. Notifications ───────────────────────────────────────────────────


def test_only_flagged_active_users_of_that_customer_are_notified(world):
    org_a = world["org_a"]
    unflagged = make_user(org_a, 2, "carl@alpha.example.com")
    make_account(unflagged)
    invited = make_user(org_a, 3, "dana@alpha.example.com", ams_report=True)
    make_account(invited, status=PortalAccountStatus.INVITED)
    disabled = make_user(org_a, 4, "erin@alpha.example.com", ams_report=True)
    make_account(disabled, status=PortalAccountStatus.DISABLED)
    make_user(org_a, 5, "fred@alpha.example.com", ams_report=True)  # no portal account

    report = approved(org_a)
    sent = list(ReportNotification.objects.filter(report=report))
    assert [n.email for n in sent] == ["ann@alpha.example.com"]
    assert sent[0].status == NotificationStatus.LOGGED


def test_ses_mode_sends_a_link_and_never_the_report(world, settings, monkeypatch):
    settings.PORTAL_EMAIL_MODE = "ses"
    settings.PORTAL_EMAIL_FROM = "reports@ams.example.com"
    settings.PORTAL_HOST = "portal.test"
    calls = []

    class FakeSes:
        def send_email(self, **kw):
            calls.append(kw)

    monkeypatch.setattr(notifications.boto3, "client", lambda name, **kw: FakeSes())
    report = approved(world["org_a"])

    assert len(calls) == 1
    assert calls[0]["Destination"] == {"ToAddresses": ["ann@alpha.example.com"]}
    assert calls[0]["FromEmailAddress"] == "reports@ams.example.com"
    text = calls[0]["Content"]["Simple"]["Body"]["Text"]["Data"]
    assert "https://portal.test/documents" in text
    assert "alpha-prod-01" not in text and "Attachments" not in calls[0]["Content"]["Simple"]
    assert report.notifications.get().status == NotificationStatus.SENT


def test_a_mail_failure_does_not_undo_the_approval(world, settings, monkeypatch):
    settings.PORTAL_EMAIL_MODE = "ses"
    settings.PORTAL_EMAIL_FROM = "reports@ams.example.com"

    class Broken:
        def send_email(self, **kw):
            raise RuntimeError("SES is in the sandbox")

    monkeypatch.setattr(notifications.boto3, "client", lambda name, **kw: Broken())
    report = approved(world["org_a"])
    assert report.status == ReportStatus.APPROVED
    note = report.notifications.get()
    assert note.status == NotificationStatus.FAILED and "sandbox" in note.detail


def test_email_mode_is_log_unless_a_sender_is_configured():
    from ams_dashboard import settings as real

    assert real.PORTAL_EMAIL_MODE == "log"


# ── 4. Roles ───────────────────────────────────────────────────────────


def test_customer_token_cannot_use_the_staff_report_api(world):
    report = approved(world["org_a"])
    c = customer(world["acct_a"])
    assert c.get("/api/reports/").status_code == 401
    assert c.get(f"/api/reports/{report.id}/pdf/").status_code == 401
    assert c.post(f"/api/reports/{report.id}/approve/").status_code == 401
    assert c.get("/api/report-templates/").status_code == 401
    assert c.post("/api/report-metrics/", {}, format="json").status_code == 401


def test_viewers_can_read_but_not_change_reports(world):
    draft = services.generate(world["org_a"], OCT)
    viewer = staff(admin=False)
    assert viewer.get("/api/reports/").status_code == 200
    assert viewer.get(f"/api/reports/{draft.id}/pdf/").status_code == 200
    body = {"organization": str(world["org_b"].id), "period": "2026-10"}
    assert viewer.post("/api/reports/", body, format="json").status_code == 403
    assert (
        viewer.patch(f"/api/reports/{draft.id}/", {"title": "x"}, format="json").status_code == 403
    )
    assert viewer.post(f"/api/reports/{draft.id}/approve/").status_code == 403
    assert viewer.delete(f"/api/reports/{draft.id}/").status_code == 403
    assert (
        viewer.post("/api/reports/generate-all/", {"period": "2026-10"}, format="json").status_code
        == 403
    )
    template = ReportTemplate.objects.get()
    assert (
        viewer.patch(
            f"/api/report-templates/{template.id}/", {"name": "x"}, format="json"
        ).status_code
        == 403
    )
    draft.refresh_from_db()
    assert draft.status == ReportStatus.DRAFT


# ── 5. Workflow ────────────────────────────────────────────────────────


def test_generate_creates_a_draft_filled_from_the_default_template(world):
    r = staff().post(
        "/api/reports/",
        {"organization": str(world["org_a"].id), "period": "2026-10"},
        format="json",
    )
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "draft" and data["period_label"] == "October 2026"
    assert data["template_name"] == "Standard monthly report"
    assert data["created_by_email"] == "tech@imt.ca"
    assert [s["key"] for s in data["sections"]] == [s["key"] for s in DEFAULT_SECTIONS]
    overview = data["sections"][0]["body"]
    assert "This report was generated for **Alpha Health** on" in overview
    assert "{" not in overview
    monitoring = data["sections"][1]["body"]
    assert "**99.97%**" in monitoring and "| alpha-prod-01 | PROD | 99.99 | 21.5 |" in monitoring
    software = data["sections"][3]["body"]
    assert (
        "| PROD | alpha-prod-01 | alpha AppServer | alpha-9.5.1 | alpha-9.5.2 | Patch available |"
        in software
    )
    assert "14 Oct 2026: alpha AppServer in PROD, alpha-9.5.0 to alpha-9.5.1" in software
    assert "20 Nov 2026: alpha AppServer in PROD" in software
    assert "alpha-prod-01 (PROD): expires" in software
    # The ticket summary still has to be written, and that blocks approval.
    assert [i["level"] for i in data["issues"]] == ["blocker"]
    assert data["recipients"] == ["ann@alpha.example.com"]


def test_one_report_per_customer_per_month(world):
    services.generate(world["org_a"], OCT)
    r = staff().post(
        "/api/reports/",
        {"organization": str(world["org_a"].id), "period": "2026-10"},
        format="json",
    )
    assert r.status_code == 409
    assert (
        staff()
        .post(
            "/api/reports/",
            {"organization": str(world["org_a"].id), "period": "Oct"},
            format="json",
        )
        .status_code
        == 400
    )


def test_approval_is_blocked_until_markers_and_tags_are_resolved(world):
    draft = services.generate(world["org_a"], OCT)
    r = staff().post(f"/api/reports/{draft.id}/approve/")
    assert r.status_code == 409 and "Ticket summary" in r.json()["detail"]

    sections = ready(draft).sections
    sections[0]["body"] += "\nSee {metrics.nope} for detail."
    services.update_draft(draft, sections=sections)
    r = staff().post(f"/api/reports/{draft.id}/approve/")
    assert r.status_code == 409 and "{metrics.nope}" in r.json()["detail"]
    draft.refresh_from_db()
    assert draft.status == ReportStatus.DRAFT and draft.pdf_key == ""
    assert not ReportNotification.objects.exists()


def test_approve_stores_the_pdf_and_freezes_the_report(world):
    draft = ready(services.generate(world["org_a"], OCT))
    api = staff()
    r = api.post(f"/api/reports/{draft.id}/approve/")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "approved" and data["approved_by_email"] == "tech@imt.ca"
    report = Report.objects.get(pk=draft.id)
    stored = storage.get(report.pdf_key)
    assert stored.startswith(b"%PDF") and len(stored) == report.pdf_size
    assert str(world["org_a"].id) in report.pdf_key

    # Frozen: no edit, no regenerate, no second approval; the PDF is the stored one.
    assert (
        api.patch(f"/api/reports/{draft.id}/", {"title": "Changed"}, format="json").status_code
        == 409
    )
    assert api.post(f"/api/reports/{draft.id}/regenerate/").status_code == 409
    assert api.post(f"/api/reports/{draft.id}/approve/").status_code == 409
    assert api.get(f"/api/reports/{draft.id}/pdf/").content == stored
    assert ReportNotification.objects.filter(report=report).count() == 1


def test_a_failed_upload_leaves_the_report_a_draft(world, monkeypatch):
    draft = ready(services.generate(world["org_a"], OCT))

    def boom(*a, **kw):
        raise RuntimeError("bucket unavailable")

    monkeypatch.setattr(storage, "put", boom)
    with pytest.raises(RuntimeError):
        services.approve(draft, actor_email="lead@imt.ca")
    draft.refresh_from_db()
    assert draft.status == ReportStatus.DRAFT
    assert not ReportNotification.objects.exists()


def test_draft_edits_are_kept_and_regenerate_discards_them(world):
    draft = services.generate(world["org_a"], OCT)
    api = staff()
    sections = draft.sections
    sections[0]["body"] = "Hand-written overview."
    r = api.patch(
        f"/api/reports/{draft.id}/",
        {"title": "October review", "sections": sections},
        format="json",
    )
    assert r.status_code == 200
    assert r.json()["title"] == "October review"
    assert r.json()["sections"][0]["body"] == "Hand-written overview."

    r = api.post(f"/api/reports/{draft.id}/regenerate/")
    assert r.status_code == 200
    assert "Alpha Health" in r.json()["sections"][0]["body"]


def test_draft_pdf_is_rendered_on_demand_and_not_stored(world):
    draft = services.generate(world["org_a"], OCT)
    r = staff().get(f"/api/reports/{draft.id}/pdf/")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    draft.refresh_from_db()
    assert draft.pdf_key == ""


def test_notify_again_only_for_approved_reports(world):
    draft = services.generate(world["org_a"], OCT)
    api = staff()
    assert api.post(f"/api/reports/{draft.id}/notify/").status_code == 409
    services.approve(ready(draft), actor_email="lead@imt.ca")
    assert api.post(f"/api/reports/{draft.id}/notify/").status_code == 200
    assert ReportNotification.objects.filter(report=draft).count() == 2


def test_overview_and_generate_all(world):
    for org in (world["org_a"], world["org_b"]):
        org.ams_level = "Essential"
        org.save()
    approved(world["org_a"])
    api = staff()

    r = api.post("/api/reports/generate-all/", {"period": "2026-10"}, format="json")
    assert r.json() == {"created": 1, "skipped": 1}
    assert api.post("/api/reports/generate-all/", {"period": "2026-10"}, format="json").json() == {
        "created": 0,
        "skipped": 2,
    }

    rows = {
        row["organization_name"]: row
        for row in api.get("/api/reports/overview/?period=2026-10").json()["rows"]
    }
    assert rows["Alpha Health"]["report"]["status"] == "approved"
    assert rows["Bravo Clinics"]["report"]["status"] == "draft"
    assert rows["Alpha Health"]["metrics_received"] is True
    assert rows["Alpha Health"]["portal_users"] == 1
    assert rows["Alpha Health"]["report_recipients"] == 1
    empty = api.get("/api/reports/overview/?period=2026-09").json()["rows"]
    assert all(row["report"] is None and not row["metrics_received"] for row in empty)


def test_generate_reports_command_only_creates_what_is_missing(world, capsys):
    world["org_a"].ams_level = "Expert"
    world["org_a"].save()
    call_command("generate_reports", "--period", "2026-10")
    call_command("generate_reports", "--period", "2026-10")
    assert Report.objects.count() == 1
    assert Report.objects.get().status == ReportStatus.DRAFT
    assert "created 0 draft(s), 1 already existed" in capsys.readouterr().out


# ── 6. Metrics deliveries ──────────────────────────────────────────────


def test_metrics_delivery_is_an_upsert_per_customer_and_month(world):
    api = staff()
    body = {
        "organization": str(world["org_a"].id),
        "period": "2026-09",
        "payload": {"availability": {"percent": 98.5}},
    }
    first = api.post("/api/report-metrics/", body, format="json")
    assert first.status_code == 201, first.json()
    body["payload"] = {"availability": {"percent": 99.5}}
    assert api.post("/api/report-metrics/", body, format="json").status_code == 200
    delivery = MetricsDelivery.objects.get(organization=world["org_a"], period=SEP)
    assert delivery.payload["availability"]["percent"] == 99.5
    assert delivery.delivered_by == "tech@imt.ca"

    body["payload"] = [1, 2, 3]
    assert api.post("/api/report-metrics/", body, format="json").status_code == 400
    listed = api.get(f"/api/report-metrics/?organization={world['org_a'].id}&period=2026-09")
    assert len(listed.json()) == 1


# ── 7. Templates ───────────────────────────────────────────────────────


def test_default_template_is_installed_by_migration():
    template = ReportTemplate.objects.get()
    assert template.is_default and template.sections == DEFAULT_SECTIONS
    for section in DEFAULT_SECTIONS:
        assert templating.validate(section["body"]) is None


def test_template_api_validates_and_keeps_exactly_one_default(world):
    api = staff()
    original = ReportTemplate.objects.get()
    bad = {"name": "Broken", "sections": [{"title": "A", "body": "{#each hosts}never closed"}]}
    r = api.post("/api/report-templates/", bad, format="json")
    assert r.status_code == 400 and "never closed" in str(r.json())

    good = {
        "name": "Short form",
        "report_title": "AMS Summary",
        "is_default": True,
        "sections": [{"title": "Header", "body": "Prepared for {customerName} on {dateTime}."}],
    }
    r = api.post("/api/report-templates/", good, format="json")
    assert r.status_code == 201, r.json()
    assert r.json()["sections"][0]["key"] == "header"
    assert list(ReportTemplate.objects.filter(is_default=True).values_list("name", flat=True)) == [
        "Short form"
    ]
    assert api.post("/api/report-templates/", good, format="json").status_code == 400  # same name

    # The default cannot be deleted while another template exists…
    assert api.delete(f"/api/report-templates/{r.json()['id']}/").status_code == 409
    # …but a non-default one can.
    assert api.delete(f"/api/report-templates/{original.id}/").status_code == 204

    report = services.generate(world["org_a"], OCT)
    assert report.title == "AMS Summary"
    assert report.sections[0]["body"].startswith("Prepared for Alpha Health on ")


def test_template_preview_renders_unsaved_text_for_a_real_customer(world):
    r = staff().post(
        "/api/report-templates/preview/",
        {
            "organization": str(world["org_a"].id),
            "period": "2026-10",
            "sections": [{"title": "Header", "body": "For {customerName}."}],
        },
        format="json",
    )
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert Report.objects.count() == 0


def test_tag_reference_lists_paths_from_delivered_metrics(world):
    data = staff().get("/api/report-templates/tags/").json()
    assert {"tag": "customerName", "description": "Customer's display name"} in data["tags"]
    assert "metrics.availability.percent" in data["metrics_paths"]
    assert any(p.startswith("metrics.hosts  (list: ") for p in data["metrics_paths"])


# ── 8. The tag language ────────────────────────────────────────────────

CTX = {
    "customerName": "Acme | Sons",
    "n": 3.14159,
    "zero": 0,
    "nothing": None,
    "when": "2026-10-05",
    "hosts": [{"name": "a\nb", "cpu": 1.5}, {"name": "c", "cpu": None}],
    "tags": ["x", "y"],
    "empty": [],
    "nested": {"deep": {"value": 7}},
}


def r(source):
    return templating.render(source, CTX)


def test_tags_are_replaced_from_the_context():
    assert r("Report for {customerName} at {nested.deep.value}").text == (
        "Report for Acme \\| Sons at 7"
    )
    assert r("{n} {n|round:2} {n|round:0} {zero}").text == "3.14 3.14 3 0"
    assert r("{when|date} {customerName|upper} {tags}").text == "5 Oct 2026 ACME \\| SONS x, y"


def test_unknown_tags_stay_visible_and_are_reported():
    out = r("Hello {custmerName} and {nested.missing}")
    assert out.text == "Hello {custmerName} and {nested.missing}"
    assert out.missing == ["custmerName", "nested.missing"]
    assert templating.leftover_tags(out.text) == ["{custmerName}", "{nested.missing}"]


def test_empty_values_and_defaults():
    assert r("{nothing}|{nothing|default:TBC}|{missing|default:n/a}").text == "—|TBC|n/a"
    assert r("{nothing|date|default:Date to be confirmed}").text == "Date to be confirmed"
    assert r("{missing|default:n/a}").missing == []


def test_each_repeats_rows_and_cannot_break_a_table():
    out = r("| Host | CPU |\n{#each hosts}\n| {name} | {cpu} | {index} |\n{/each}\nafter")
    assert out.text == "| Host | CPU |\n| a b | 1.5 | 1 |\n| c | — | 2 |\nafter"
    table = parse_blocks(r("{#each hosts}\n| {customerName} | {name} |\n{/each}").text)[0]
    assert table["rows"] == [["Acme | Sons", "a b"], ["Acme | Sons", "c"]]


def test_each_else_and_if_else():
    assert r("{#each empty}\nx\n{#else}\nnone\n{/each}").text == "none\n"
    assert r("{#each missing}x{#else}none{/each}").missing == ["missing"]
    assert r("{#if n}yes{#else}no{/if} {#if zero}yes{#else}no{/if} {#if nope}y{/if}").text == (
        "yes no "
    )
    assert r("{#each tags}{this}{index} {/each}").text == "x1 y2 "


def test_text_that_only_looks_like_a_tag_is_left_alone():
    source = 'JSON {"a": 1}, a set {1, 2}, empty {} and {not a tag}'
    assert r(source).text == source and r(source).missing == []


def test_the_language_can_only_read_dictionary_keys():
    class Secret:
        token = "s3cr3t"

    ctx = {"obj": Secret(), "text": "abc", "items": [1, 2]}
    for tag in ("{obj.token}", "{obj.__class__}", "{text.upper}", "{items.__len__}", "{items.5}"):
        out = templating.render(tag, ctx)
        assert out.text == tag, tag
    assert templating.render("{items.1}", ctx).text == "2"


@pytest.mark.parametrize(
    "source, problem",
    [
        ("{#each hosts}x", "never closed"),
        ("x{/if}", "Unexpected {/if}"),
        ("{#each a}{/if}", "expected {/each}"),
        ("{#else}", "must sit inside"),
        ("{#if a}{#else}{#else}{/if}", "must sit inside"),
        ("{n|shout}", "Unknown filter"),
        ("{n|round:x}", "round needs"),
    ],
)
def test_malformed_templates_are_rejected_with_a_reason(source, problem):
    assert problem in templating.validate(source)
    with pytest.raises(templating.TemplateError):
        templating.render(source, CTX)


# ── 9. Markup and PDF ──────────────────────────────────────────────────


def test_markup_blocks():
    text = (
        "Intro line\nsecond line\n\n## Heading\n- one\n- two\n"
        "| A | B |\n|---|---|\n| 1 | 2\\|3 |\n\n[[check this]]"
    )
    assert parse_blocks(text) == [
        {"type": "paragraph", "lines": ["Intro line", "second line"]},
        {"type": "heading", "level": 2, "text": "Heading"},
        {"type": "bullets", "items": ["one", "two"]},
        {"type": "table", "rows": [["A", "B"], ["1", "2|3"]]},
        {"type": "paragraph", "lines": ["[[check this]]"]},
    ]
    assert todo_marks(text) == ["check this"]


def test_pdf_renders_hostile_text_and_long_tables():
    rows = "\n".join(f"| srv-{i} | <b>&amp;</b> | {i} |" for i in range(150))
    data = render_pdf(
        title="AMS <Monthly> Report",
        customer="R&D </para> Ltd",
        period_label="October 2026",
        sections=[
            {
                "title": "A & B",
                "body": "Unbalanced <i>markup & **bold** text\n\n| H1 | H2 | H3 |\n" + rows,
            },
            {"title": "Empty", "body": ""},
        ],
        draft=True,
    )
    assert data.startswith(b"%PDF") and data.rstrip().endswith(b"%%EOF")


def test_storage_keys_cannot_escape_the_reports_directory():
    with pytest.raises(ValueError):
        storage.put("../outside.pdf", b"x")


# ── 10. Synthetic seed ─────────────────────────────────────────────────


def test_synthetic_report_seed_fills_every_section_and_is_idempotent(capsys):
    call_command("seed_synthetic")
    call_command("seed_synthetic_reports")
    first = capsys.readouterr().out
    call_command("seed_synthetic_reports")
    assert "created 0 software, 0 installed, 0 patches, 0 planned, 0 metrics" in (
        capsys.readouterr().out
    )
    assert "created 4 software" in first

    from customers.models import Organization

    period = services.previous_period()
    org = Organization.objects.get(jira_org_id="synthetic-001")
    report = services.generate(org, period)
    body = "\n".join(s["body"] for s in report.sections)
    assert templating.leftover_tags(body) == []
    assert "Harbor App Server v9.5" in body and "Patch available" in body
    assert "Overall availability for the month was" in body
    assert [i["level"] for i in services.issues(report) if i["level"] == "blocker"] == ["blocker"]

    late = Organization.objects.get(jira_org_id="synthetic-006")
    assert "has not been received yet" in services.generate(late, period).sections[1]["body"]


def test_synthetic_report_seed_refuses_a_database_with_real_customers():
    from django.core.management.base import CommandError

    from customers.models import Organization

    Organization.objects.create(jira_org_id="12345", jira_name="A real customer")
    with pytest.raises(CommandError, match="Refusing to seed"):
        call_command("seed_synthetic_reports")


def test_s3_storage_round_trip_uses_the_configured_bucket(settings, monkeypatch):
    settings.REPORTS_BUCKET = "reports-bucket"
    objects = {}

    class FakeS3:
        def put_object(self, *, Bucket, Key, Body, ContentType):
            objects[(Bucket, Key)] = (Body, ContentType)

        def get_object(self, *, Bucket, Key):
            from io import BytesIO

            return {"Body": BytesIO(objects[(Bucket, Key)][0])}

    monkeypatch.setattr(storage.boto3, "client", lambda name, **kw: FakeS3())
    storage.put("reports/a/2026-10/x.pdf", b"%PDF-1.4 test")
    assert objects[("reports-bucket", "reports/a/2026-10/x.pdf")][1] == "application/pdf"
    assert storage.get("reports/a/2026-10/x.pdf") == b"%PDF-1.4 test"


# ── 11. Unattended metrics delivery ────────────────────────────────────

INGEST = "/api/report-metrics/ingest"


def new_key(name="zabbix-prod") -> str:
    made = staff().post("/api/report-metrics-keys/", {"name": name}, format="json")
    assert made.status_code == 201, made.json()
    return made.json()["key"]


def machine(key: str):
    return client(key)


def test_a_key_is_shown_once_and_only_its_hash_is_kept(world):
    made = staff().post("/api/report-metrics-keys/", {"name": " zabbix-prod "}, format="json")
    assert made.status_code == 201
    raw = made.json()["key"]
    assert raw.startswith("amsm_") and len(raw) > 40
    row = MetricsKey.objects.get()
    assert row.name == "zabbix-prod" and row.created_by_email == "tech@imt.ca"
    assert row.key_hash == ingest.hash_key(raw) and row.prefix == raw[: len(row.prefix)]
    assert raw not in "".join(str(v) for v in vars(row).values())

    listed = staff(admin=False).get("/api/report-metrics-keys/")
    assert listed.status_code == 200
    assert raw not in listed.content.decode() and row.key_hash not in listed.content.decode()
    assert "key" not in listed.json()[0]
    assert staff().get(f"/api/report-metrics-keys/{row.id}/").status_code == 405
    blank = staff().post("/api/report-metrics-keys/", {"name": "  "}, format="json")
    assert blank.status_code == 400


def test_only_admins_create_and_revoke_keys(world):
    raw = new_key()
    row = MetricsKey.objects.get()
    viewer = staff(admin=False)
    assert viewer.post("/api/report-metrics-keys/", {"name": "x"}, format="json").status_code == 403
    assert viewer.delete(f"/api/report-metrics-keys/{row.id}/").status_code == 403
    assert customer(world["acct_a"]).get("/api/report-metrics-keys/").status_code == 401
    body = {"customer": "synthetic-t1", "period": "2026-09", "metrics": {"a": 1}}
    assert machine(raw).post(INGEST, body, format="json").status_code == 200

    assert staff().delete(f"/api/report-metrics-keys/{row.id}/").status_code == 204
    row.refresh_from_db()
    assert row.revoked_at is not None and row.revoked_by_email == "tech@imt.ca"
    assert machine(raw).post(INGEST, body, format="json").status_code == 401
    # Revoked keys stay listed, for the record.
    assert staff().get("/api/report-metrics-keys/").json()[0]["revoked_at"]


def test_ingest_stores_a_month_per_customer_and_replaces_on_resend(world):
    api = machine(new_key())
    body = {
        "period": "2026-09",
        "deliveries": [
            {"customer": "synthetic-t1", "metrics": {"availability": {"percent": 98.5}}},
            {"customer": str(world["org_b"].id), "metrics": {"availability": {"percent": 97.0}}},
        ],
    }
    first = api.post(INGEST, body, format="json")
    assert first.status_code == 200, first.json()
    assert first.json()["accepted"] == 2 and first.json()["rejected"] == 0
    assert [r["status"] for r in first.json()["results"]] == ["created", "created"]

    body["deliveries"][0]["metrics"] = {"availability": {"percent": 99.5}}
    again = api.post(INGEST + "/", body, format="json")
    assert [r["status"] for r in again.json()["results"]] == ["replaced", "replaced"]

    a = MetricsDelivery.objects.get(organization=world["org_a"], period=SEP)
    b = MetricsDelivery.objects.get(organization=world["org_b"], period=SEP)
    assert a.payload == {"availability": {"percent": 99.5}}
    assert b.payload == {"availability": {"percent": 97.0}}
    assert a.delivered_by == "key:zabbix-prod" and a.source == "zabbix"
    assert MetricsKey.objects.get().last_used_at is not None
    # October, delivered by the fixture, is untouched; and it reaches the report.
    assert MetricsDelivery.objects.filter(organization=world["org_a"]).count() == 2
    assert build_context(world["org_a"], SEP)["metrics"]["availability"]["percent"] == 99.5
    assert "bravo" not in str(build_context(world["org_a"], OCT)["metrics"])


def test_one_bad_delivery_does_not_block_the_others_but_fails_the_request(world):
    api = machine(new_key())
    body = {
        "period": "2026-09",
        "deliveries": [
            {"customer": "synthetic-t1", "metrics": {"a": 1}},
            {"customer": "no-such-customer", "metrics": {"a": 1}},
            {"customer": "00000000-0000-0000-0000-000000000000", "metrics": {"a": 1}},
            {"customer": "synthetic-t2", "metrics": []},
            {"customer": "synthetic-t2", "period": "2999-01", "metrics": {"a": 1}},
            {"customer": "synthetic-t2", "period": "September", "metrics": {"a": 1}},
            {"customer": "synthetic-t2", "source": "Not A Source!", "metrics": {"a": 1}},
            "nonsense",
        ],
    }
    r = api.post(INGEST, body, format="json")
    assert r.status_code == 422
    out = r.json()
    assert out["accepted"] == 1 and out["rejected"] == 7
    assert out["results"][0]["status"] == "created"
    # A customer that does not exist answers the same way whatever was sent.
    assert out["results"][1]["detail"] == out["results"][2]["detail"] == "Unknown customer."
    assert all(x["status"] == "rejected" and x["detail"] for x in out["results"][1:])
    assert MetricsDelivery.objects.filter(period=SEP).count() == 1


def test_a_deleted_customer_cannot_receive_metrics(world):
    api = machine(new_key())
    world["org_b"].deleted_at = timezone.now()  # soft delete, as the dashboard does
    world["org_b"].save(update_fields=["deleted_at"])
    body = {"customer": "synthetic-t2", "period": "2026-09", "metrics": {"a": 1}}
    r = api.post(INGEST, body, format="json")
    assert r.status_code == 422 and r.json()["results"][0]["detail"] == "Unknown customer."


@pytest.mark.parametrize(
    "body",
    [[], [{"customer": "synthetic-t1"}], {"deliveries": []}, {"deliveries": "x"}],
)
def test_ingest_rejects_malformed_requests(world, body):
    assert machine(new_key()).post(INGEST, body, format="json").status_code == 400


def test_ingest_limits_request_size(world, monkeypatch):
    api = machine(new_key())
    one = {"customer": "synthetic-t1", "metrics": {"a": 1}}
    monkeypatch.setattr(ingest, "MAX_DELIVERIES", 2)
    body = {"period": "2026-09", "deliveries": [one, one, one]}
    assert api.post(INGEST, body, format="json").status_code == 400
    monkeypatch.setattr(ingest, "MAX_METRICS_BYTES", 20)
    big = {"customer": "synthetic-t1", "period": "2026-09", "metrics": {"a": "x" * 50}}
    assert api.post(INGEST, big, format="json").status_code == 422
    monkeypatch.setattr(ingest, "MAX_BODY_BYTES", 10)
    assert api.post(INGEST, one, format="json").status_code == 413
    assert not MetricsDelivery.objects.filter(period=SEP).exists()


def test_ingest_accepts_nothing_but_a_live_delivery_key(world):
    body = {"customer": "synthetic-t1", "period": "2026-09", "metrics": {"a": 1}}
    callers = [
        client(),
        staff(),
        customer(world["acct_a"]),
        client("amsm_" + "x" * 43),
        client("not-a-key"),
    ]
    for c in callers:
        assert c.post(INGEST, body, format="json").status_code == 401
    basic = client()
    basic.credentials(HTTP_AUTHORIZATION="Basic " + new_key())
    assert basic.post(INGEST, body, format="json").status_code == 401
    assert not MetricsDelivery.objects.filter(period=SEP).exists()


def test_a_delivery_key_opens_nothing_else(world):
    report = approved(world["org_a"])
    api = machine(new_key())
    assert api.get(INGEST).status_code == 405
    for path in [
        "/api/reports/",
        f"/api/reports/{report.id}/pdf/",
        "/api/report-metrics/",
        "/api/report-metrics-keys/",
        "/api/report-templates/",
        "/api/organizations/",
        "/api/portal/documents",
        f"/api/portal/documents/{report.id}/download",
    ]:
        assert api.get(path).status_code == 401, path
    assert api.post("/api/report-metrics-keys/", {"name": "x"}, format="json").status_code == 401
    assert api.post(f"/api/reports/{report.id}/notify/").status_code == 401


def test_smoke_prune_removes_only_revoked_smoke_keys(world, capsys):
    for name, revoked in [("smoke-key-ab12", True), ("smoke-key-cd34", False), ("zabbix", True)]:
        MetricsKey.objects.create(
            name=name,
            prefix="amsm_x",
            key_hash=ingest.hash_key(name),
            revoked_at=timezone.now() if revoked else None,
        )
    call_command("portal_prune_smoke")
    assert sorted(MetricsKey.objects.values_list("name", flat=True)) == ["smoke-key-cd34", "zabbix"]
    assert "1 revoked smoke key" in capsys.readouterr().out
