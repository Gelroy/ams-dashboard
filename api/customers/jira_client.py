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

    def fetch_open_ticket_count(self, jira_org_id: str) -> int:
        jql = f"organizations = {jira_org_id} AND statusCategory != Done"

        approx_url = f"{self._base}/rest/api/3/search/approximate-count"
        r = self._client.post(approx_url, json={"jql": jql})
        if r.status_code == 200:
            return int(r.json().get("count", 0) or 0)
        if r.status_code not in (404, 410):
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
