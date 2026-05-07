import argparse
import asyncio
import logging

from app.db import SessionLocal
from app.jira.sync import sync_organizations, sync_ticket_counts


async def _run(action: str) -> dict:
    async with SessionLocal() as db:
        if action == "orgs":
            return await sync_organizations(db)
        if action == "tickets":
            return await sync_ticket_counts(db)
        raise ValueError(f"unknown action: {action}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="jira_sync")
    parser.add_argument("action", choices=["orgs", "tickets"])
    args = parser.parse_args()
    result = asyncio.run(_run(args.action))
    print(result)


if __name__ == "__main__":
    main()
