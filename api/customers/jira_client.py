from base64 import b64encode

import httpx
from django.conf import settings


class JiraClient:
    """Sync httpx client for JIRA Service Management endpoints."""

    def __init__(self):
        if not (settings.JIRA_URL and settings.JIRA_EMAIL and settings.JIRA_TOKEN):
            raise RuntimeError("JIRA_URL, JIRA_EMAIL, and JIRA_TOKEN must all be set")
        self._base = settings.JIRA_URL.rstrip("/")
        token = b64encode(f"{settings.JIRA_EMAIL}:{settings.JIRA_TOKEN}".encode()).decode()
        self._client = httpx.Client(
            headers={
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._client.close()

    def fetch_all_organizations(self) -> list[dict]:
        out: list[dict] = []
        start = 0
        limit = 50
        url = f"{self._base}/rest/servicedeskapi/organization"
        experimental = {"X-ExperimentalApi": "opt-in"}
        while True:
            r = self._client.get(url, params={"start": start, "limit": limit}, headers=experimental)
            r.raise_for_status()
            data = r.json()
            values = data.get("values") or []
            for v in values:
                out.append({"id": str(v["id"]), "name": v["name"]})
            if data.get("isLastPage") or len(values) < limit:
                break
            start += limit
        return out

    def fetch_organization_users(self, jira_org_id: str) -> list[dict]:
        """Paginated users for one org from the JSM organization users endpoint."""
        out: list[dict] = []
        start = 0
        limit = 50
        url = f"{self._base}/rest/servicedeskapi/organization/{jira_org_id}/user"
        experimental = {"X-ExperimentalApi": "opt-in"}
        while True:
            r = self._client.get(url, params={"start": start, "limit": limit}, headers=experimental)
            r.raise_for_status()
            data = r.json()
            values = data.get("values") or []
            for v in values:
                out.append(
                    {
                        "accountId": v.get("accountId", ""),
                        "displayName": v.get("displayName", ""),
                        "emailAddress": v.get("emailAddress", ""),
                    }
                )
            if data.get("isLastPage") or len(values) < limit:
                break
            start += limit
        return out

    def fetch_alert_account_ids(self) -> list[str]:
        """Return account IDs of every JIRA user whose display name contains
        "Alert". Used to split ticket counts into Automated (assigned to one
        of these) vs Manual. The team treats "*Alert*" accounts as the
        signal that a ticket originated from monitoring rather than from a
        human reaching out.

        Lookup is one /user/search call per JIRA sync run; we don't cache
        across runs because new alert accounts get added when new customers
        onboard and we want them to start counting automatically.
        """
        r = self._client.get(
            f"{self._base}/rest/api/3/user/search",
            params={"query": "Alert", "maxResults": 200},
        )
        r.raise_for_status()
        return [u["accountId"] for u in r.json() if u.get("accountId")]

    def _count_open_with_jql(self, jql: str) -> int:
        """Internal — same approximate-count + paginated fallback as
        fetch_open_ticket_count, but parametric over an arbitrary JQL."""
        approx_url = f"{self._base}/rest/api/3/search/approximate-count"
        r = self._client.post(approx_url, json={"jql": jql})
        if r.status_code == 200:
            count = r.json().get("count")
            if count is not None:
                return int(count)
            # JIRA occasionally returns {"count": null} on tenants where the
            # approximate index hasn't caught up; fall through to paginate.
        elif r.status_code not in (404, 410):
            r.raise_for_status()

        count = 0
        next_page_token: str | None = None
        for _ in range(20):  # safety cap: 20 * 100 = 2000 issues
            body: dict = {"jql": jql, "fields": ["summary"], "maxResults": 100}
            if next_page_token:
                body["nextPageToken"] = next_page_token
            r = self._client.post(f"{self._base}/rest/api/3/search/jql", json=body)
            r.raise_for_status()
            data = r.json()
            issues = data.get("issues") or []
            count += len(issues)
            next_page_token = data.get("nextPageToken")
            if not next_page_token or not issues:
                break
        return count

    def fetch_split_ticket_counts(
        self, jira_org_id: str, alert_account_ids: list[str]
    ) -> tuple[int, int]:
        """Return (automated_count, manual_count) for one org's open tickets.

        Automated = assigned to any of the supplied "*Alert*" accountIds.
        Manual = everyone else (including unassigned).

        Implementation note: we run two separate counts rather than one
        get-all-and-bucket call so we use JIRA's cheap approximate-count
        endpoint where possible. Costs ~2 API calls per org per sync.
        """
        if not alert_account_ids:
            # No alert accounts found — degenerate case; everything is manual.
            total = self._count_open_with_jql(
                f"organizations = {jira_org_id} AND statusCategory != Done"
            )
            return 0, total

        ids = ", ".join(f'"{aid}"' for aid in alert_account_ids)
        jql_auto = (
            f"organizations = {jira_org_id} AND statusCategory != Done "
            f"AND assignee in ({ids})"
        )
        jql_manual = (
            f"organizations = {jira_org_id} AND statusCategory != Done "
            f"AND (assignee not in ({ids}) OR assignee IS EMPTY)"
        )
        return self._count_open_with_jql(jql_auto), self._count_open_with_jql(jql_manual)

    def fetch_open_ticket_count(self, jira_org_id: str) -> int:
        """Total open ticket count for one org. Kept for backwards compatibility
        and as a sanity sum; sync_jira_tickets now uses
        fetch_split_ticket_counts and writes the parts plus open_ticket_count
        = automated + manual."""
        return self._count_open_with_jql(
            f"organizations = {jira_org_id} AND statusCategory != Done"
        )
