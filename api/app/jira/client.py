from base64 import b64encode
from types import TracebackType

import httpx

from app.config import get_settings


class JiraClient:
    """Async client for JIRA Service Management endpoints used by the sync worker.

    Use as an async context manager. Reads JIRA_URL/EMAIL/TOKEN from settings.
    """

    def __init__(self) -> None:
        s = get_settings()
        if not (s.jira_url and s.jira_email and s.jira_token):
            raise RuntimeError("JIRA_URL, JIRA_EMAIL, and JIRA_TOKEN must all be set")
        self._base = s.jira_url.rstrip("/")
        token = b64encode(f"{s.jira_email}:{s.jira_token}".encode()).decode()
        self._headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "JiraClient":
        self._client = httpx.AsyncClient(headers=self._headers, timeout=30.0)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("JiraClient must be used as an async context manager")
        return self._client

    async def fetch_all_organizations(self) -> list[dict]:
        """Paginated list of {id, name} dicts from JSM organizations endpoint."""
        out: list[dict] = []
        start = 0
        limit = 50
        url = f"{self._base}/rest/servicedeskapi/organization"
        experimental = {"X-ExperimentalApi": "opt-in"}
        while True:
            r = await self.http.get(url, params={"start": start, "limit": limit}, headers=experimental)
            r.raise_for_status()
            data = r.json()
            values = data.get("values") or []
            for v in values:
                out.append({"id": str(v["id"]), "name": v["name"]})
            if data.get("isLastPage") or len(values) < limit:
                break
            start += limit
        return out

    async def fetch_open_ticket_count(self, jira_org_id: str) -> int:
        """Open (statusCategory != Done) issue count for an org.

        Tries /search/approximate-count first; falls back to paginating
        /search/jql when that endpoint isn't available on the instance.
        """
        jql = f"organizations = {jira_org_id} AND statusCategory != Done"

        approx_url = f"{self._base}/rest/api/3/search/approximate-count"
        r = await self.http.post(approx_url, json={"jql": jql})
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
            r = await self.http.post(f"{self._base}/rest/api/3/search/jql", json=body)
            r.raise_for_status()
            data = r.json()
            issues = data.get("issues") or []
            count += len(issues)
            next_page_token = data.get("nextPageToken")
            if not next_page_token or not issues:
                break
        return count
