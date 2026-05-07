import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.jira.client import JiraClient
from app.models import Organization

logger = logging.getLogger(__name__)


async def sync_organizations(db: AsyncSession) -> dict:
    now = datetime.now(UTC)
    async with JiraClient() as jira:
        orgs = await jira.fetch_all_organizations()

    if not orgs:
        return {"fetched": 0, "upserted": 0}

    rows = [
        {"jira_org_id": o["id"], "jira_name": o["name"], "jira_synced_at": now}
        for o in orgs
    ]
    stmt = pg_insert(Organization).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Organization.jira_org_id],
        index_where=Organization.deleted_at.is_(None),
        set_={
            "jira_name": stmt.excluded.jira_name,
            "jira_synced_at": stmt.excluded.jira_synced_at,
        },
    )
    await db.execute(stmt)
    await db.commit()
    return {"fetched": len(orgs), "upserted": len(orgs)}


async def sync_ticket_counts(db: AsyncSession) -> dict:
    rows = (
        await db.execute(
            select(Organization.id, Organization.jira_org_id).where(
                Organization.deleted_at.is_(None)
            )
        )
    ).all()
    if not rows:
        return {"orgs": 0, "ok": 0, "errors": 0}

    ok = 0
    errors = 0
    async with JiraClient() as jira:
        for org_id, jira_org_id in rows:
            now = datetime.now(UTC)
            try:
                count = await jira.fetch_open_ticket_count(jira_org_id)
                await db.execute(
                    update(Organization)
                    .where(Organization.id == org_id)
                    .values(
                        open_ticket_count=count,
                        ticket_count_synced_at=now,
                        last_ticket_sync_error=None,
                    )
                )
                ok += 1
            except Exception as e:
                logger.warning("ticket count sync failed for %s: %s", jira_org_id, e)
                await db.execute(
                    update(Organization)
                    .where(Organization.id == org_id)
                    .values(
                        ticket_count_synced_at=now,
                        last_ticket_sync_error=str(e)[:500],
                    )
                )
                errors += 1
    await db.commit()
    return {"orgs": len(rows), "ok": ok, "errors": errors}
