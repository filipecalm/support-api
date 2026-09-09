import os
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = Field(repr=False)
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    allowed_origins: list[str] = []
    expose_docs: bool = False
    neon_auth_base_url: str | None = None
    neon_auth_jwks_url: str | None = None


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


def neon_auth_origin() -> str | None:
    base = settings().neon_auth_base_url
    if not base:
        return None
    parsed = urlparse(base)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def neon_jwks_url() -> str | None:
    configured = settings().neon_auth_jwks_url
    if configured:
        return configured
    base = settings().neon_auth_base_url
    if not base:
        return None
    return f"{base.rstrip('/')}/.well-known/jwks.json"
