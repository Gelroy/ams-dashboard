from datetime import datetime
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import Enum, Integer, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AmsLevel(str, PyEnum):
    Essential = "Essential"
    Enhanced = "Enhanced"
    Expert = "Expert"


class ZabbixStatus(str, PyEnum):
    Good = "Good"
    Issue = "Issue"


# Postgres enum types are created by the bootstrap migration, so create_type=False.
_ams_level = Enum(AmsLevel, name="ams_level", create_type=False, native_enum=True)
_zabbix_status = Enum(ZabbixStatus, name="zabbix_status", create_type=False, native_enum=True)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    jira_org_id: Mapped[str] = mapped_column(Text, nullable=False)
    jira_name: Mapped[str] = mapped_column(Text, nullable=False)
    local_name: Mapped[str | None] = mapped_column(Text)
    ams_level: Mapped[AmsLevel | None] = mapped_column(_ams_level)
    zabbix_status: Mapped[ZabbixStatus | None] = mapped_column(_zabbix_status)
    help_desk_phone: Mapped[str | None] = mapped_column(Text)
    connection_guide_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    open_ticket_count: Mapped[int | None] = mapped_column(Integer)
    ticket_count_synced_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_ticket_sync_error: Mapped[str | None] = mapped_column(Text)
    jira_synced_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
