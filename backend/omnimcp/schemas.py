"""Pydantic v2 API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    model_config = ConfigDict(str_strip_whitespace=True)


class UserOut(BaseModel):
    id: str
    email: str
    role: str
    is_active: bool
    created_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    client_flavor: str = "generic"


class AgentOut(BaseModel):
    id: str
    name: str
    description: str
    client_flavor: str
    enabled: bool
    allowed_tools: list[str]
    created_at: datetime


class AgentCreated(AgentOut):
    token: str  # shown exactly once


class ConnectorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: str
    endpoint_url: str = ""
    spec: dict = Field(default_factory=dict)
    enabled: bool = False

    @field_validator("kind")
    @classmethod
    def kind_allowed(cls, v: str) -> str:
        allowed = {"mcp", "http", "openapi", "grpc", "webhook", "internal"}
        if v not in allowed:
            raise ValueError(f"kind must be one of {sorted(allowed)}")
        return v


class ConnectorOut(BaseModel):
    id: str
    name: str
    kind: str
    endpoint_url: str
    enabled: bool
    health: str
    health_detail: str
    spec: dict
    last_check: datetime | None
    created_at: datetime


class WorkerRegister(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    version: str = "unknown"
    capabilities: dict = Field(default_factory=dict)
    max_active_jobs: int = Field(default=1, ge=1, le=64)
    trust_level: str = Field(default="untrusted", pattern="^(untrusted|standard|trusted)$")


class WorkerOut(BaseModel):
    id: str
    name: str
    health: str
    version: str
    capabilities: dict
    limits: dict
    trust_level: str
    active_jobs: int
    max_active_jobs: int
    last_heartbeat: datetime | None
    registered_at: datetime


class HeartbeatIn(BaseModel):
    capabilities: dict = Field(default_factory=dict)
    version: str | None = None
    active_jobs: int = Field(default=0, ge=0)
    ram_available_mb: int | None = None
    health: str | None = None


class ClaimOut(BaseModel):
    job_id: str | None = None
    kind: str | None = None
    payload: dict = Field(default_factory=dict)
    cancel_requested: bool = False
    timeout_s: int = 3600


class JobCreate(BaseModel):
    kind: str = "exec"
    payload: dict = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=255)
    workspace_id: str | None = None
    required_capabilities: list[str] = Field(default_factory=list)
    required_os: str | None = None
    required_arch: str | None = None
    min_cpu: int = Field(default=1, ge=1)
    min_ram_mb: int = Field(default=256, ge=64)
    required_gpu_mb: int = Field(default=0, ge=0)
    untrusted: bool = False
    timeout_s: int | None = None
    priority: int = Field(default=5, ge=0, le=9)
    max_retries: int | None = Field(default=None, ge=0, le=10)


class JobOut(BaseModel):
    id: str
    kind: str
    state: str
    payload: dict
    priority: int
    workspace_id: str | None
    worker_id: str | None
    required_capabilities: list[str]
    min_ram_mb: int
    min_cpu: int
    timeout_s: int
    attempt: int
    max_retries: int
    result: dict | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobStatusIn(BaseModel):
    success: bool
    result: dict = Field(default_factory=dict)
    error: str | None = None


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    description: str = ""
    repo_url: str | None = None
    branch: str | None = None


class WorkspaceOut(BaseModel):
    id: str
    name: str
    description: str
    project_type: str
    created_at: datetime


class FileWriteIn(BaseModel):
    path: str
    content: str
    overwrite: bool = True


class StorageObjectOut(BaseModel):
    id: str
    filename: str
    provider: str
    bucket_or_repository: str
    object_path: str
    size_bytes: int
    sha256: str
    content_type: str
    workspace_id: str | None
    owner_id: str | None
    kind: str
    retention: str
    version: int
    created_at: datetime


class UploadSessionCreate(BaseModel):
    filename: str
    kind: str = "artifact"
    size_bytes: int = Field(default=0, ge=0)
    sha256: str = Field(default="", max_length=64)
    content_type: str = "application/octet-stream"
    workspace_id: str | None = None


class AuditOut(BaseModel):
    id: int
    ts: datetime
    actor_type: str
    actor_id: str
    action: str
    resource_type: str
    resource_id: str
    detail: dict
    approval: bool
    outcome: str
