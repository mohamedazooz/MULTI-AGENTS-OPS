"""Agent registry routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record
from ..db import get_session
from ..deps import current_user, require_admin
from ..errors import Conflict, NotFound
from ..models import Agent, User
from ..schemas import AgentCreate, AgentCreated, AgentOut
from ..security import generate_key

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def _out(a: Agent) -> AgentOut:
    return AgentOut(
        id=a.id,
        name=a.name,
        description=a.description,
        client_flavor=a.client_flavor,
        enabled=a.enabled,
        allowed_tools=a.allowed_tools or [],
        created_at=a.created_at,
    )


@router.post("", response_model=AgentCreated, status_code=201)
async def create(
    body: AgentCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    exists = (
        await session.execute(select(Agent).where(Agent.name == body.name))
    ).scalar_one_or_none()
    if exists is not None:
        raise Conflict(f"agent name {body.name!r} already registered")
    raw, token_hash = generate_key("omniagent")
    agent = Agent(
        name=body.name,
        description=body.description,
        client_flavor=body.client_flavor,
        token_hash=token_hash,
        owner_id=user.id,
    )
    session.add(agent)
    await record(
        session,
        actor_type="user",
        actor_id=user.email,
        action="agent.create",
        resource_type="agent",
        resource_id=agent.name,
    )
    await session.commit()
    await session.refresh(agent)
    return AgentCreated(
        **_out(agent).model_dump(), token=raw  # type: ignore[arg-type]
    )


@router.get("", response_model=list[AgentOut])
async def list_agents(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(current_user),
):
    agents = (await session.execute(select(Agent).order_by(Agent.created_at))).scalars().all()
    return [_out(a) for a in agents]


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(current_user),
):
    a = await session.get(Agent, agent_id)
    if a is None:
        raise NotFound("agent not found")
    return _out(a)


@router.post("/{agent_id}/disable", response_model=AgentOut)
async def disable(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    a = await session.get(Agent, agent_id)
    if a is None:
        raise NotFound("agent not found")
    a.enabled = False
    await session.commit()
    return _out(a)


@router.post("/{agent_id}/enable", response_model=AgentOut)
async def enable(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    a = await session.get(Agent, agent_id)
    if a is None:
        raise NotFound("agent not found")
    a.enabled = True
    await session.commit()
    return _out(a)
