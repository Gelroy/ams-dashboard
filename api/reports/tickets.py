"""Ticket summary for the Support Tickets section.

Today the dashboard only holds ticket *counts* per customer (synced from
JIRA), so the narrative is written by staff in the draft. This function is
the seam for the automated version: when a JIRA export plus an AI
summarisation step exists, return its text here and drafts will arrive
with the summary already filled in. Returning None leaves the "to be
written" marker in the draft, which blocks approval until someone
replaces it.
"""

from __future__ import annotations

from datetime import date

from customers.models import Organization


def summarize_tickets(org: Organization, period: date) -> str | None:
    return None
