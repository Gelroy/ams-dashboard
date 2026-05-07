from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    jira_org_id: str
    jira_name: str
    local_name: str | None = None
    ams_level: str | None = None
    zabbix_status: str | None = None
    help_desk_phone: str | None = None
    connection_guide_url: str | None = None
    notes: str | None = None
    open_ticket_count: int | None = None
    ticket_count_synced_at: datetime | None = None
    last_ticket_sync_error: str | None = None
    jira_synced_at: datetime | None = None


class OrganizationList(BaseModel):
    items: list[OrganizationOut]
    total: int
