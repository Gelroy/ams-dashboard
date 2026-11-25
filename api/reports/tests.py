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
  6. Tickets            a customer's ticket activity and ticket titles
                        never appear in another customer's report
                        (section 12 below).
  7. AI summary         the request to the AI service holds one
                        customer's tickets and nothing else, and the reply
                        only ever lands in a draft (section 13 below).

Then the workflow (draft → approved, frozen afterwards) and the tag
language. Cognito, S3 and SES are never contacted.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
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
from reports import ai, ingest, notifications, services, storage, templating, tickets
from reports.context import build_context
from reports.defaults import (
    DEFAULT_SECTIONS,
    TICKET_SUMMARY_PLACEHOLDER,
    TICKETS_BODY,
    TICKETS_BODY_V1,
)
from reports.markup import parse_blocks, todo_marks
from reports.models import (
    MetricsDelivery,
    MetricsKey,
    NotificationStatus,
    Report,
    ReportNotification,
    ReportStatus,
    ReportTemplate,
    TicketOrigin,
    TicketRecord,
    TicketSync,
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


# ── 12. Ticket activity ────────────────────────────────────────────────


def at(day: int, month: int = 10, hour: int = 9) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=UTC)


def ticket(key, opened, resolved=None, priority="Medium", origin=TicketOrigin.MANUAL, **kw):
    return {
        "key": key,
        "summary": kw.pop("summary", f"Summary of {key}"),
        "issue_type": "Incident",
        "priority": priority,
        "status": "Resolved" if resolved else "In progress",
        "origin": origin,
        "opened_at": opened,
        "resolved_at": resolved,
        **kw,
    }


@pytest.fixture
def ticketed(world):
    """October tickets for both tenants; every key and title carries the
    tenant's marker."""
    tickets.store_tickets(
        world["org_a"],
        OCT,
        [
            ticket("ALPHA-1", at(20, 9), at(3), priority="High"),  # carried in, resolved
            ticket("ALPHA-2", at(5), at(7, hour=21), origin=TicketOrigin.AUTOMATED),
            ticket("ALPHA-3", at(12), None, priority="Low"),  # still open
            ticket("ALPHA-4", at(28), at(4, 11), priority="High"),  # resolved next month
            ticket("ALPHA-5", at(2, 9), at(25, 9)),  # closed before October: not active
            ticket("ALPHA-6", at(2, 11), None),  # opened after October: not active
        ],
    )
    tickets.store_tickets(world["org_b"], OCT, [ticket("BRAVO-1", at(9), at(10))])
    return world


def test_month_activity_counts_only_tickets_active_in_the_month(ticketed):
    m = tickets.month_activity(ticketed["org_a"], OCT)
    assert m["available"] is True
    assert (m["opened"], m["resolved"], m["openAtEnd"], m["carriedOver"]) == (3, 2, 2, 1)
    assert (m["openedManual"], m["openedAutomated"]) == (2, 1)
    assert [r["key"] for r in m["resolvedList"]] == ["ALPHA-1", "ALPHA-2"]
    assert m["resolvedList"][1]["daysToResolve"] == 2.5
    assert m["avgDaysToResolve"] == round((13.0 + 2.5) / 2, 1)
    # Open list: most urgent first; a ticket resolved after the month counts as open.
    assert [r["key"] for r in m["openList"]] == ["ALPHA-4", "ALPHA-3"]
    assert m["openList"][1]["ageDays"] == 19
    assert m["byPriority"] == [
        {"priority": "High", "opened": 1, "resolved": 1, "openAtEnd": 1},
        {"priority": "Medium", "opened": 1, "resolved": 1, "openAtEnd": 0},
        {"priority": "Low", "opened": 1, "resolved": 0, "openAtEnd": 1},
    ]
    # The same rows answer for the next month without another sync of October.
    nov = tickets.month_activity(ticketed["org_a"], date(2026, 11, 1))
    assert nov["available"] is False
    assert (nov["opened"], nov["resolved"], nov["carriedOver"]) == (1, 1, 2)


def test_ticket_activity_never_crosses_customers(ticketed):
    a = build_context(ticketed["org_a"], OCT)["tickets"]["month"]
    b = build_context(ticketed["org_b"], OCT)["tickets"]["month"]
    assert "BRAVO" not in str(a) and "ALPHA" not in str(b)
    assert (b["opened"], b["resolved"], b["openAtEnd"]) == (1, 1, 0)

    report = services.generate(ticketed["org_a"], OCT)
    text = "\n".join(sec["body"] for sec in report.sections)
    assert "ALPHA-2" in text and "Summary of ALPHA-3" in text
    assert "BRAVO" not in text and "BRAVO" not in str(report.context)
    assert "BRAVO" not in services.pdf_bytes(report).decode("latin-1")


def test_a_month_without_a_sync_falls_back_to_the_open_counts(world):
    m = tickets.month_activity(world["org_a"], OCT)
    assert m["available"] is False and m["opened"] == 0 and m["byPriority"] == []
    section = next(
        sec for sec in services.generate(world["org_a"], OCT).sections if sec["key"] == "tickets"
    )
    assert "At the time this report was prepared" in section["body"]
    assert "Resolved in October 2026" not in section["body"]
    assert TICKET_SUMMARY_PLACEHOLDER in section["body"]


def test_a_synced_month_with_no_tickets_says_so(world):
    tickets.store_tickets(world["org_a"], OCT, [])
    # One customer's sync says nothing about another's.
    assert tickets.month_activity(world["org_b"], OCT)["available"] is False
    assert TicketSync.objects.get(organization=world["org_a"]).ticket_count == 0
    section = next(
        sec for sec in services.generate(world["org_a"], OCT).sections if sec["key"] == "tickets"
    )
    assert "**0** tickets were opened" in section["body"]
    assert "No tickets were resolved this month." in section["body"]
    assert "No tickets were open at the end of the month." in section["body"]
    assert "| Priority |" not in section["body"]


def test_ticket_section_lists_the_month_and_still_needs_the_written_summary(ticketed):
    report = services.generate(ticketed["org_a"], OCT)
    body = next(sec["body"] for sec in report.sections if sec["key"] == "tickets")
    assert "**3** tickets were opened (2 raised by your team, 1 raised automatically" in body
    assert "| ALPHA-2 | Summary of ALPHA-2 | Medium | 5 Oct 2026 | 7 Oct 2026 |" in body
    assert "| ALPHA-3 | Summary of ALPHA-3 | Low | In progress | 12 Oct 2026 | 19 |" in body
    assert "| ALPHA-4 | Summary of ALPHA-4 | High | Since resolved | 28 Oct 2026 | 3 |" in body
    assert "ALPHA-5" not in body and "ALPHA-6" not in body
    assert not templating.leftover_tags(body)
    assert [i for i in services.issues(report) if i["level"] == "blocker"]
    done = services.approve(ready(report), actor_email="lead@imt.ca")
    assert done.status == ReportStatus.APPROVED


def test_ticket_titles_cannot_break_the_report_or_block_approval(world):
    hostile = "Export fails | error {customer.name} [[fix me]]\nsecond line"
    tickets.store_tickets(world["org_a"], OCT, [ticket("ALPHA-9", at(5), None, summary=hostile)])
    report = services.generate(world["org_a"], OCT)
    body = next(sec["body"] for sec in report.sections if sec["key"] == "tickets")
    row = next(line for line in body.splitlines() if line.startswith("| ALPHA-9"))
    assert "(customer.name)" in row and "[fix me]" in row and "second line" in row
    assert row.count(" | ") == 5  # still six cells: the pipe in the title is escaped
    assert not templating.leftover_tags(body)
    assert todo_marks(body) == [TICKET_SUMMARY_PLACEHOLDER.strip("[]")]
    assert services.pdf_bytes(report).startswith(b"%PDF")


def test_long_ticket_lists_are_capped_but_counted(world, monkeypatch):
    monkeypatch.setattr(tickets, "LIST_LIMIT", 3)
    tickets.store_tickets(
        world["org_a"], OCT, [ticket(f"ALPHA-{n}", at(n + 1), at(n + 2)) for n in range(8)]
    )
    m = tickets.month_activity(world["org_a"], OCT)
    assert m["resolved"] == 8 and len(m["resolvedList"]) == 3 and m["resolvedNotListed"] == 5
    body = next(
        sec["body"]
        for sec in services.generate(world["org_a"], OCT).sections
        if sec["key"] == "tickets"
    )
    assert "5 more resolved tickets are not listed here." in body


def test_resync_updates_tickets_in_place(ticketed):
    tickets.store_tickets(ticketed["org_a"], OCT, [ticket("ALPHA-3", at(12), at(30))])
    assert TicketRecord.objects.filter(organization=ticketed["org_a"]).count() == 6
    assert tickets.month_activity(ticketed["org_a"], OCT)["resolved"] == 3
    # The same key under another customer is a different ticket.
    tickets.store_tickets(ticketed["org_b"], OCT, [ticket("ALPHA-3", at(1), None)])
    assert TicketRecord.objects.get(organization=ticketed["org_a"], key="ALPHA-3").resolved_at


def test_shipped_ticket_section_is_upgraded_only_where_unedited():
    from importlib import import_module

    from django.apps import apps

    migration = import_module("reports.migrations.0005_ticket_section")
    shipped = ReportTemplate.objects.get()
    assert next(x for x in shipped.sections if x["key"] == "tickets")["body"] == TICKETS_BODY
    old = [
        {**x, "body": TICKETS_BODY_V1} if x["key"] == "tickets" else x for x in shipped.sections
    ]
    shipped.sections = old
    shipped.save()
    edited = ReportTemplate.objects.create(
        name="Edited",
        sections=[{"key": "tickets", "title": "Tickets", "body": "Ours: {tickets.open}\n"}],
    )
    migration.upgrade(apps, None)
    shipped.refresh_from_db()
    edited.refresh_from_db()
    assert next(x for x in shipped.sections if x["key"] == "tickets")["body"] == TICKETS_BODY
    assert edited.sections[0]["body"] == "Ours: {tickets.open}\n"
    assert templating.validate(TICKETS_BODY) is None


class FakeJira:
    """Stands in for customers.jira_client.JiraClient."""

    def __init__(self, by_org, alert_ids=("alert-bot",), fail_for=()):
        self.by_org, self.alert_ids, self.fail_for = by_org, list(alert_ids), set(fail_for)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch_alert_account_ids(self):
        return self.alert_ids

    def fetch_month_tickets(self, jira_org_id, start, end):
        self.calls.append((jira_org_id, start, end))
        if jira_org_id in self.fail_for:
            raise RuntimeError("JIRA said no")
        return [dict(t) for t in self.by_org.get(jira_org_id, [])]


def jira_ticket(key, assignee=""):
    t = ticket(key, at(5), at(6))
    t.pop("origin")
    return {**t, "assignee_id": assignee}


def test_sync_command_stores_each_customers_tickets_and_survives_one_failure(
    world, monkeypatch, capsys
):
    from reports.management.commands import sync_report_tickets

    for org in (world["org_a"], world["org_b"]):
        org.ams_level = "Essential"
        org.save(update_fields=["ams_level"])
    fake = FakeJira(
        {"synthetic-t1": [jira_ticket("ALPHA-1", "alert-bot"), jira_ticket("ALPHA-2", "a-person")]},
        fail_for={"synthetic-t2"},
    )
    monkeypatch.setattr(sync_report_tickets, "JiraClient", lambda: fake)
    with pytest.raises(CommandError, match="1 failed"):
        call_command("sync_report_tickets", "--period", "2026-10")
    assert fake.calls[0] == ("synthetic-t1", date(2026, 10, 1), date(2026, 11, 1))
    origins = dict(TicketRecord.objects.values_list("key", "origin"))
    assert origins == {"ALPHA-1": "automated", "ALPHA-2": "manual"}
    assert TicketSync.objects.filter(organization=world["org_a"], period=OCT).exists()
    assert not TicketSync.objects.filter(organization=world["org_b"]).exists()


def test_generate_reports_can_sync_tickets_first_and_carries_on_without_jira(
    world, monkeypatch, capsys
):
    from reports.management.commands import sync_report_tickets

    world["org_a"].ams_level = "Essential"
    world["org_a"].save(update_fields=["ams_level"])
    fake = FakeJira({"synthetic-t1": [jira_ticket("ALPHA-1")]})
    monkeypatch.setattr(sync_report_tickets, "JiraClient", lambda: fake)
    call_command("generate_reports", "--period", "2026-10", "--sync-tickets")
    body = str(Report.objects.get(organization=world["org_a"], period=OCT).sections)
    assert "ALPHA-1" in body

    # No JIRA settings (a synthetic environment): the drafts are still created.
    def unconfigured():
        raise RuntimeError("JIRA_URL, JIRA_EMAIL, and JIRA_TOKEN must all be set")

    monkeypatch.setattr(sync_report_tickets, "JiraClient", unconfigured)
    call_command("generate_reports", "--period", "2026-09", "--sync-tickets")
    assert Report.objects.filter(organization=world["org_a"], period=SEP).exists()
    assert "Ticket sync skipped" in capsys.readouterr().err
    # Without the flag JIRA is never touched.
    monkeypatch.setattr(sync_report_tickets, "JiraClient", lambda: pytest.fail("called JIRA"))
    call_command("generate_reports", "--period", "2026-08")


def test_jira_fetch_asks_for_the_months_active_tickets_and_follows_pages(settings):
    import httpx

    from customers.jira_client import JiraClient

    settings.JIRA_URL, settings.JIRA_EMAIL, settings.JIRA_TOKEN = "https://jira.test", "e", "t"
    seen = []

    def issue(key, created, resolved=None, assignee=None):
        return {
            "key": key,
            "fields": {
                "summary": f"Summary of {key}",
                "issuetype": {"name": "Incident"},
                "priority": {"name": "High"},
                "status": {"name": "Done"},
                "assignee": {"accountId": assignee} if assignee else None,
                "created": created,
                "resolutiondate": resolved,
            },
        }

    def handler(request):
        import json

        body = json.loads(request.content)
        seen.append(body)
        if "nextPageToken" not in body:
            page = {
                "issues": [issue("AMS-1", "2026-10-05T09:00:00.000+0000", None, "alert-bot")],
                "nextPageToken": "p2",
            }
        else:
            page = {
                "issues": [
                    issue("AMS-2", "2026-09-20T09:00:00.000-0500", "2026-10-03T10:30:00.000-0500"),
                    {"key": "AMS-3", "fields": {"created": None}},
                ]
            }
        return httpx.Response(200, json=page)

    with JiraClient() as jira:
        jira._client = httpx.Client(transport=httpx.MockTransport(handler))
        got = jira.fetch_month_tickets("42", date(2026, 10, 1), date(2026, 11, 1))
    assert len(seen) == 2 and seen[1]["nextPageToken"] == "p2"
    assert 'organizations = 42 AND created < "2026-11-01"' in seen[0]["jql"]
    assert '(resolution IS EMPTY OR resolved >= "2026-10-01")' in seen[0]["jql"]
    assert [t["key"] for t in got] == ["AMS-1", "AMS-2"]  # the undated issue is skipped
    assert got[0]["assignee_id"] == "alert-bot" and got[0]["resolved_at"] is None
    assert got[1]["resolved_at"] == datetime(2026, 10, 3, 15, 30, tzinfo=UTC)
    assert got[1]["priority"] == "High" and got[1]["issue_type"] == "Incident"


def test_synthetic_seed_adds_repeatable_tickets(capsys):
    call_command("seed_synthetic")
    call_command("seed_synthetic_reports")
    first = capsys.readouterr().out
    assert " tickets for 6 synthetic customers" in first
    count = TicketRecord.objects.count()
    assert count >= 6 * 3 * 4 and set(TicketRecord.objects.values_list("source", flat=True)) == {
        "synthetic"
    }
    call_command("seed_synthetic_reports")
    assert "0 tickets" in capsys.readouterr().out and TicketRecord.objects.count() == count
    from customers.models import Organization

    org = Organization.objects.order_by("jira_org_id").first()
    m = tickets.month_activity(org, services.previous_period())
    assert m["available"] and m["opened"] >= 4
    report = services.generate(org, services.previous_period())
    assert "SYN-001-" in str(report.sections)


def test_overview_shows_whether_tickets_were_synced(ticketed):
    ticketed["org_a"].ams_level = "Essential"
    ticketed["org_a"].save(update_fields=["ams_level"])
    rows = staff().get("/api/reports/overview/?period=2026-10").json()["rows"]
    row = next(r for r in rows if r["organization"] == str(ticketed["org_a"].id))
    assert row["tickets_synced"] is True and row["tickets_count"] == 6
    sep = staff().get("/api/reports/overview/?period=2026-09").json()["rows"]
    assert all(r["tickets_synced"] is False for r in sep)


# ── 13. AI-drafted ticket summary ──────────────────────────────────────
# The Anthropic client is always replaced: no test reaches the network.


class FakeBlock:
    def __init__(self, type, text=""):
        self.type, self.text = type, text


class FakeResponse:
    def __init__(self, text="We resolved two tickets.", stop_reason="end_turn", model=None):
        self.content = [FakeBlock("thinking"), FakeBlock("text", text)]
        self.stop_reason, self.model = stop_reason, model or "claude-opus-5-5"


class FakeAnthropic:
    """Records every request; answers with ``reply`` or raises it."""

    def __init__(self, reply=None):
        self.reply = reply or FakeResponse()
        self.requests = []
        self.options = []
        self.beta = self
        self.messages = self

    def with_options(self, **options):
        self.options.append(options)
        return self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def claude(settings, monkeypatch):
    settings.ANTHROPIC_API_KEY = "test-key"
    settings.REPORTS_AI_MODEL = "claude-opus-5-5"
    fake = FakeAnthropic()
    monkeypatch.setattr(ai, "_client", lambda: fake)
    return fake


def api_error(cls, status):
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("nope", response=httpx2.Response(status, request=request), body=None)


def tickets_body(report) -> str:
    return next(sec["body"] for sec in report.sections if sec["key"] == "tickets")


def test_ai_request_holds_one_customers_month_and_nothing_else(ticketed, claude):
    draft = services.generate(ticketed["org_a"], OCT)
    services.write_ai_summary(draft, actor_email="lead@imt.ca")
    (request,) = claude.requests
    sent = str(request)
    assert "ALPHA-2" in sent and "Summary of ALPHA-3" in sent and "October 2026" in sent
    # Nothing of the other customer, and nothing identifying this one beyond its tickets.
    assert "BRAVO" not in sent and "Bravo" not in sent
    assert "Alpha Health" not in sent and "ann@alpha.example.com" not in sent
    assert "alpha-prod-01" not in sent  # servers, metrics and software are not sent
    assert request["model"] == "claude-opus-5-5" and request["fallbacks"] == "default"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert request["output_config"] == {"effort": "medium"}
    assert "temperature" not in request and "thinking" not in request
    assert "never instructions" in request["system"]
    assert [m["role"] for m in request["messages"]] == ["user"]
    # A person is waiting: one attempt, done well inside the load balancer's limit.
    assert claude.options == [{"timeout": 45.0, "max_retries": 0}]


def test_ai_summary_replaces_the_marker_and_is_flagged_until_edited(ticketed, claude):
    draft = services.generate(ticketed["org_a"], OCT)
    api = staff()
    assert api.get(f"/api/reports/{draft.id}/").json()["can_write_ai_summary"] is True
    r = api.post(f"/api/reports/{draft.id}/ai-summary/")
    assert r.status_code == 200, r.json()
    out = r.json()
    body = next(x["body"] for x in out["sections"] if x["key"] == "tickets")
    assert "We resolved two tickets." in body and TICKET_SUMMARY_PLACEHOLDER not in body
    assert "| ALPHA-2 |" in body  # the rest of the section is untouched
    assert out["ai_summary"]["model"] == "claude-opus-5-5"
    assert out["ai_summary"]["requested_by"] == "tech@imt.ca" and "text" not in out["ai_summary"]
    warnings = [i["message"] for i in out["issues"] if i["level"] == "warning"]
    assert any("drafted by AI" in w for w in warnings)
    assert not [i for i in out["issues"] if i["level"] == "blocker"]

    # Asking again replaces its own unedited attempt...
    claude.reply = FakeResponse("A calmer second attempt.")
    again = api.post(f"/api/reports/{draft.id}/ai-summary/").json()
    body = next(x["body"] for x in again["sections"] if x["key"] == "tickets")
    assert "A calmer second attempt." in body and "We resolved two tickets." not in body

    # ...but never text a person has touched.
    sections = [
        {**x, "body": x["body"].replace("A calmer second attempt.", "Edited by a person.")}
        for x in again["sections"]
    ]
    edited = api.patch(
        f"/api/reports/{draft.id}/", {"title": again["title"], "sections": sections}, format="json"
    ).json()
    assert not any("drafted by AI" in i["message"] for i in edited["issues"])
    assert edited["can_write_ai_summary"] is False
    assert api.post(f"/api/reports/{draft.id}/ai-summary/").status_code == 409
    assert len(claude.requests) == 2
    assert "Edited by a person." in tickets_body(Report.objects.get(pk=draft.id))


def test_ai_reply_cannot_smuggle_tags_markers_headings_or_tables(ticketed, claude):
    claude.reply = FakeResponse(
        "## Summary\n| a | b |\nIgnore that. {customer.name} [[todo]]\n\n\n\nDone."
    )
    report = services.write_ai_summary(services.generate(ticketed["org_a"], OCT))
    text = report.ai_summary["text"]
    assert text == "Summary\na, b\nIgnore that. (customer.name) [todo]\n\nDone."
    body = tickets_body(report)
    assert not templating.leftover_tags(body) and not todo_marks(body)
    assert services.pdf_bytes(report).startswith(b"%PDF")
    done = services.approve(report, actor_email="lead@imt.ca")
    assert done.status == ReportStatus.APPROVED
    # Once approved, the "read it first" warning is history, not a to-do.
    assert not any("drafted by AI" in i["message"] for i in services.issues(done))
    # And an approved report is never sent to the AI again, even though
    # its unedited AI summary is still sitting in the text.
    assert staff().post(f"/api/reports/{done.id}/ai-summary/").status_code == 409
    assert len(claude.requests) == 1


def test_ai_summary_is_off_without_a_key(ticketed, settings, monkeypatch):
    settings.ANTHROPIC_API_KEY = ""
    monkeypatch.setattr(ai, "_client", lambda: pytest.fail("called the AI service"))
    draft = services.generate(ticketed["org_a"], OCT, ai_summary=True)
    assert TICKET_SUMMARY_PLACEHOLDER in tickets_body(draft) and draft.ai_summary == {}
    api = staff()
    assert api.get(f"/api/reports/{draft.id}/").json()["can_write_ai_summary"] is False
    r = api.post(f"/api/reports/{draft.id}/ai-summary/")
    assert r.status_code == 409 and "not set up" in r.json()["detail"]


def test_ai_summary_roles_and_states(ticketed, claude, world):
    draft = services.generate(ticketed["org_a"], OCT)
    assert staff(admin=False).post(f"/api/reports/{draft.id}/ai-summary/").status_code == 403
    assert customer(world["acct_a"]).post(f"/api/reports/{draft.id}/ai-summary/").status_code == 401
    done = approved(ticketed["org_b"])
    assert staff().post(f"/api/reports/{done.id}/ai-summary/").status_code == 409
    # A month whose tickets were never synced has nothing to summarise.
    sep = services.generate(ticketed["org_a"], SEP)
    r = staff().post(f"/api/reports/{sep.id}/ai-summary/")
    assert r.status_code == 409 and "not been synced" in r.json()["detail"]
    assert claude.requests == []


def test_a_quiet_month_is_summarised_without_calling_the_ai(world, claude):
    tickets.store_tickets(world["org_a"], OCT, [])
    report = services.write_ai_summary(services.generate(world["org_a"], OCT))
    assert "No support tickets were opened, resolved or outstanding during October 2026." in (
        tickets_body(report)
    )
    assert claude.requests == [] and report.ai_summary == {}


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (FakeResponse(stop_reason="refusal"), "declined"),
        (FakeResponse(stop_reason="max_tokens"), "cut off"),
        (FakeResponse(text="   "), "returned nothing"),
        (FakeResponse(text="x" * 5000), "far longer"),
    ],
)
def test_unusable_ai_replies_leave_the_draft_alone(ticketed, claude, reply, message):
    claude.reply = reply
    draft = services.generate(ticketed["org_a"], OCT)
    r = staff().post(f"/api/reports/{draft.id}/ai-summary/")
    assert r.status_code == 502 and message in r.json()["detail"]
    draft.refresh_from_db()
    assert TICKET_SUMMARY_PLACEHOLDER in tickets_body(draft) and draft.ai_summary == {}


def test_ai_service_errors_become_messages_staff_can_act_on(ticketed, claude):
    import anthropic

    draft = services.generate(ticketed["org_a"], OCT)
    for error, message in [
        (api_error(anthropic.AuthenticationError, 401), "rejected the API key"),
        (api_error(anthropic.RateLimitError, 429), "busy"),
        (api_error(anthropic.InternalServerError, 500), "had a problem"),
        (api_error(anthropic.BadRequestError, 400), "did not accept"),
        (anthropic.APIConnectionError(request=None), "could not be reached"),
        (anthropic.APITimeoutError(request=None), "took too long"),
    ]:
        claude.reply = error
        r = staff().post(f"/api/reports/{draft.id}/ai-summary/")
        assert r.status_code == 502 and message in r.json()["detail"], (error, r.json())
    assert "test-key" not in str(r.json())


def test_scheduled_generation_drafts_summaries_and_survives_ai_failure(world, claude, capsys):
    for org, marker in ((world["org_a"], "ALPHA"), (world["org_b"], "BRAVO")):
        org.ams_level = "Essential"
        org.save(update_fields=["ams_level"])
        tickets.store_tickets(org, OCT, [ticket(f"{marker}-1", at(5), at(6))])
    call_command("generate_reports", "--period", "2026-10")
    assert len(claude.requests) == 2
    pairs = (("ALPHA", "BRAVO"), ("BRAVO", "ALPHA"))
    for request, (mine, theirs) in zip(claude.requests, pairs, strict=True):
        assert mine in str(request) and theirs not in str(request)
    a = Report.objects.get(organization=world["org_a"], period=OCT)
    assert "We resolved two tickets." in tickets_body(a)
    assert a.ai_summary["requested_by"] == "generate_reports"
    assert claude.options[0] == {"timeout": 180.0, "max_retries": 2}  # nobody is waiting
    assert a.status == ReportStatus.DRAFT  # never approved or sent by the schedule

    # The AI being down costs the summary, not the drafts.
    import anthropic

    claude.reply = api_error(anthropic.InternalServerError, 500)
    for org in (world["org_a"], world["org_b"]):
        tickets.store_tickets(org, SEP, [ticket("OLD-1", at(5, 9), at(6, 9))])
    call_command("generate_reports", "--period", "2026-09")
    sep = Report.objects.get(organization=world["org_a"], period=SEP)
    assert TICKET_SUMMARY_PLACEHOLDER in tickets_body(sep) and sep.ai_summary == {}

    # --no-ai leaves the summaries to staff.
    claude.reply = FakeResponse()
    before = len(claude.requests)
    for org in (world["org_a"], world["org_b"]):
        tickets.store_tickets(org, date(2026, 8, 1), [ticket("AUG-1", at(5, 8), at(6, 8))])
    call_command("generate_reports", "--period", "2026-08", "--no-ai")
    assert len(claude.requests) == before


def test_regenerate_and_manual_generation_never_call_the_ai(ticketed, claude):
    draft = services.generate(ticketed["org_a"], OCT)
    services.write_ai_summary(draft)
    api = staff()
    fresh = api.post(f"/api/reports/{draft.id}/regenerate/").json()
    assert fresh["ai_summary"] is None
    assert TICKET_SUMMARY_PLACEHOLDER in next(
        x["body"] for x in fresh["sections"] if x["key"] == "tickets"
    )
    body = {"organization": str(ticketed["org_b"].id), "period": "2026-10"}
    assert api.post("/api/reports/", body, format="json").status_code == 201
    assert len(claude.requests) == 1


def test_placeholder_key_from_a_new_secret_means_off(monkeypatch):
    import importlib

    from ams_dashboard import settings as real

    monkeypatch.setenv("ANTHROPIC_API_KEY", " unset ")
    try:
        assert importlib.reload(real).ANTHROPIC_API_KEY == ""
    finally:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        importlib.reload(real)
