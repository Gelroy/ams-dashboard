from dataclasses import dataclass

from fastapi import HTTPException, status

from app.config import get_settings


@dataclass
class CurrentUser:
    sub: str
    email: str | None = None
    name: str | None = None


async def get_current_user() -> CurrentUser:
    settings = get_settings()
    if settings.auth_bypass:
        return CurrentUser(sub="dev-bypass", email="dev@local", name="Dev User")
    # Cognito JWT verification lands when we deploy.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Auth not yet implemented",
    )
