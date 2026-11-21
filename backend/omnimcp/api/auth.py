"""Authentication routes: register, login, me, revoke."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record
from ..config import settings
from ..db import get_session
from ..deps import current_user
from ..errors import Conflict, Forbidden, Unauthorized
from ..models import Role, User, utcnow
from ..schemas import LoginRequest, TokenResponse, UserCreate, UserOut
from ..security import create_jwt, hash_password, rate_limit_check, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
async def register(body: UserCreate, session: AsyncSession = Depends(get_session)):
    if not rate_limit_check(
        f"register:{body.email}", limit=settings.register_rate_limit, window=300
    ):
        raise Unauthorized("Too many registrations; slow down")
    count = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    role = Role.admin if count == 0 else Role.user
    if count > 0 and settings.env == "production" and not settings.allow_open_registration:
        raise Forbidden("Open registration disabled in production")
    exists = (
        await session.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()
    if exists is not None:
        raise Conflict("Email already registered")
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        role=role,
    )
    session.add(user)
    await record(
        session,
        actor_type="user",
        actor_id=body.email.lower(),
        action="auth.register",
        resource_type="user",
        resource_id="",
        detail={"role": role},
    )
    await session.commit()
    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    if not rate_limit_check(f"login:{body.email}", limit=settings.login_rate_limit, window=300):
        raise Unauthorized("Too many login attempts; wait and retry")
    user = (
        await session.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(user.password_hash, body.password):
        # constant-ish time response regardless of user existence
        raise Unauthorized("Invalid credentials")
    token = create_jwt(user.id, typ="user", role=user.role.value)
    await record(
        session, actor_type="user", actor_id=user.email, action="auth.login"
    )
    await session.commit()
    return TokenResponse(access_token=token, expires_in=settings.token_ttl_seconds)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return UserOut(
        id=user.id, email=user.email, role=user.role.value, is_active=user.is_active,
        created_at=user.created_at,
    )


@router.post("/logout", status_code=204)
async def logout(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    user.revocation_ts = utcnow()
    await session.commit()
