import os
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


def host_allowlist() -> list[str]:
    hosts = list(settings().allowed_hosts)
    for key in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
        raw = os.environ.get(key)
        if not raw:
            continue
        host = raw.removeprefix("https://").removeprefix("http://").split("/", 1)[0]
        if host and host not in hosts:
            hosts.append(host)
    return hosts
