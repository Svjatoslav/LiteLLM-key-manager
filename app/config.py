from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(default="sqlite:///./litellm_keys.db", alias="DATABASE_URL")
    litellm_base_url: str = Field(default="http://localhost:4000", alias="LITELLM_BASE_URL")
    litellm_master_key: str = Field(default="sk-local-dev", alias="LITELLM_MASTER_KEY")
    app_secret_key: str = Field(default="change-me-for-local-dev", alias="APP_SECRET_KEY")
    session_secret: str = Field(default="change-me-session", alias="SESSION_SECRET")
    bootstrap_admin_email: str = Field(default="admin@example.com", alias="BOOTSTRAP_ADMIN_EMAIL")
    bootstrap_admin_password: str = Field(default="admin", alias="BOOTSTRAP_ADMIN_PASSWORD")
    public_base_url: str = Field(default="http://localhost:8000", alias="PUBLIC_BASE_URL")
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")
    auto_create_tables: bool = Field(default=False, alias="AUTO_CREATE_TABLES")

    model_config = SettingsConfigDict(env_file=".env", populate_by_name=True, extra="ignore")

    @field_validator("litellm_base_url", "public_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()

