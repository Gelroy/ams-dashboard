from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str
    auth_bypass: bool = False

    jira_url: str = ""
    jira_email: str = ""
    jira_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
