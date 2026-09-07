from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = Field(repr=False)
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    expose_docs: bool = False


@lru_cache
def settings() -> Settings:
    return Settings()
