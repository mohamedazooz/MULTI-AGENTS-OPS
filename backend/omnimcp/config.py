"""OmniMCP control plane configuration.

All runtime configuration is environment-driven (12-factor). Secrets are never
defaulted to fixed values in production: when `OMNIMCP_ENV=production` the app
refuses to boot without an explicitly provided `OMNIMCP_SECRET_KEY`.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OMNIMCP_", env_file=".env", extra="ignore")

    env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000

    database_url: str = "sqlite+aiosqlite:///./omnimcp.db"

    # Auth
    secret_key: str = ""
    jwt_algorithm: str = "HS256"
    token_ttl_seconds: int = 43200  # 12h access tokens
    worker_token_ttl_seconds: int = 30 * 86400  # 30d device tokens
    token_revocation_window_seconds: int = 30

    # Rate limits (attempts per 60s window)
    register_rate_limit: int = 10
    login_rate_limit: int = 20
    worker_register_rate_limit: int = 30

    # Scheduling
    scheduler_enabled: bool = True
    scheduler_interval_seconds: float = 1.0
    worker_offline_after_seconds: int = 45
    max_retries: int = 2
    default_job_timeout_seconds: int = 3600

    # Storage / workspaces
    storage_root: Path = Path("./data/storage")
    workspace_root: Path = Path("./data/workspaces")
    max_workspace_bytes: int = 2 * 1024**3
    max_archive_entry_bytes: int = 512 * 1024**2
    max_archive_entries: int = 10000
    max_upload_bytes: int = 10 * 1024**3

    # Observability
    log_level: str = "INFO"
    metrics_enabled: bool = True

    # MCP server auth (empty = allow loopback-only unauthenticated access)
    mcp_token: str = ""

    # In production, require admin auth for new registrations
    allow_open_registration: bool = False

    # Whether normal users may register workers (operator/admin always can)
    allow_worker_registration_by_user: bool = False

    # Bootstrap: initial admin created at startup when present
    bootstrap_admin_email: str = "admin@omnimcp.local"
    bootstrap_admin_password: str = ""


settings = Settings()
