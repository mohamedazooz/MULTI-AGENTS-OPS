"""SQLAlchemy 2.0 models for the OmniMCP control plane."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_id() -> str:
    return uuid.uuid4().hex


class Role(str, enum.Enum):
    admin = "admin"
    operator = "operator"
    user = "user"


class JobState(str, enum.Enum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    QUEUED = "QUEUED"
    SCHEDULING = "SCHEDULING"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    EXPIRED = "EXPIRED"


class WorkerHealth(str, enum.Enum):
    online = "online"
    offline = "offline"
    degraded = "degraded"
    busy = "busy"
    draining = "draining"
    maintenance = "maintenance"
    quarantined = "quarantined"


class ConnectorKind(str, enum.Enum):
    mcp = "mcp"
    http = "http"
    openapi = "openapi"
    grpc = "grpc"
    webhook = "webhook"
    internal = "internal"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), default=Role.user)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    revocation_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    client_flavor: Mapped[str] = mapped_column(String(64), default="generic")
    token_hash: Mapped[str] = mapped_column(String(64))
    owner_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    allowed_tools: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Worker(Base):
    __tablename__ = "workers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    owner_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    health: Mapped[WorkerHealth] = mapped_column(
        Enum(WorkerHealth, native_enum=False), default=WorkerHealth.offline
    )
    version: Mapped[str] = mapped_column(String(64), default="unknown")
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    limits: Mapped[dict] = mapped_column(JSON, default=dict)  # configured resource limits
    active_jobs: Mapped[int] = mapped_column(Integer, default=0)
    max_active_jobs: Mapped[int] = mapped_column(Integer, default=1)
    trust_level: Mapped[str] = mapped_column(String(32), default="untrusted")
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("ix_workers_health", "health"),)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(64), index=True)  # e.g. exec, build, test
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    owner_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state: Mapped[JobState] = mapped_column(
        Enum(JobState, native_enum=False), default=JobState.CREATED, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=5)  # lower = more urgent
    required_capabilities: Mapped[list] = mapped_column(JSON, default=list)  # e.g. ["docker"]
    required_os: Mapped[str | None] = mapped_column(String(32), nullable=True)
    required_arch: Mapped[str | None] = mapped_column(String(32), nullable=True)
    min_cpu: Mapped[int] = mapped_column(Integer, default=1)
    min_ram_mb: Mapped[int] = mapped_column(Integer, default=256)
    required_gpu_mb: Mapped[int] = mapped_column(Integer, default=0)
    untrusted: Mapped[bool] = mapped_column(Boolean, default=False)
    timeout_s: Mapped[int] = mapped_column(Integer, default=3600)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    worker_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key", name="uq_jobs_idempotency"),
        Index("ix_jobs_state_priority", "state", "priority"),
    )


class JobLog(Base):
    __tablename__ = "job_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(32), ForeignKey("jobs.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    stream: Mapped[str] = mapped_column(String(16), default="stdout")
    line: Mapped[str] = mapped_column(Text, default="")


class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(32), ForeignKey("jobs.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    state: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    owner_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    project_type: Mapped[str] = mapped_column(String(64), default="unknown")
    approval_delete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StorageObject(Base):
    __tablename__ = "storage_objects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(32), index=True)  # local|gcs|hf
    bucket_or_repository: Mapped[str] = mapped_column(String(255), default="")
    object_path: Mapped[str] = mapped_column(String(1024))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    content_type: Mapped[str] = mapped_column(String(127), default="application/octet-stream")
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="artifact")  # artifact|model|dataset|backup
    retention: Mapped[str] = mapped_column(String(32), default="default")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UploadSession(Base):
    __tablename__ = "upload_sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32), default="artifact")
    provider: Mapped[str] = mapped_column(String(32), default="local")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    bytes_received: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    content_type: Mapped[str] = mapped_column(String(127), default="application/octet-stream")
    tmp_path: Mapped[str] = mapped_column(String(2048), default="")
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    object_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Connector(Base):
    __tablename__ = "connectors"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    kind: Mapped[ConnectorKind] = mapped_column(Enum(ConnectorKind, native_enum=False))
    endpoint_url: Mapped[str] = mapped_column(String(2048), default="")
    spec: Mapped[dict] = mapped_column(JSON, default=dict)  # tool descriptions / openapi ref
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    health: Mapped[str] = mapped_column(String(32), default="unknown")
    health_detail: Mapped[str] = mapped_column(Text, default="")
    last_check: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor_type: Mapped[str] = mapped_column(String(32))  # user|agent|worker|system
    actor_id: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str] = mapped_column(String(64), default="")
    resource_id: Mapped[str] = mapped_column(String(255), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    workflow_id: Mapped[str] = mapped_column(String(64), default="")
    approval: Mapped[bool] = mapped_column(Boolean, default=False)
    outcome: Mapped[str] = mapped_column(String(32), default="success")


class MetricSample(Base):
    """Rolling scheduler/uptime counters persisted for restart survival."""

    __tablename__ = "metric_samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[float] = mapped_column(Float, default=0.0)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
