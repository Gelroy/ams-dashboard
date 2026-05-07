from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user
from app.db import get_db
from app.models import Organization
from app.schemas import OrganizationList

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=OrganizationList)
async def list_organizations(
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[CurrentUser, Depends(get_current_user)],
    ams_level: str | None = Query(None),
    q: str | None = Query(None, description="Case-insensitive substring match on name"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    base = select(Organization).where(Organization.deleted_at.is_(None))
    if ams_level:
        base = base.where(Organization.ams_level == ams_level)
    if q:
        like = f"%{q}%"
        base = base.where(or_(Organization.jira_name.ilike(like), Organization.local_name.ilike(like)))

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

    items_q = (
        base.order_by(func.coalesce(Organization.local_name, Organization.jira_name))
        .offset(offset)
        .limit(limit)
    )
    items = (await db.execute(items_q)).scalars().all()

    return {"items": items, "total": total}
