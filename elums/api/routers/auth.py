"""M6: register/login/logout — the exact scheme from
ELUMS_TECHNICAL_APPROACH.md's auth section (plain FastAPI sessions, Argon2id,
HttpOnly/Secure/SameSite=Lax cookie, revocation by DELETE).

`GET /api/me` and `GET /api/users/{id}/following` live in
elums/api/routers/users.py, not here — the implementation plan's M6 route
list puts `/me` outside the `/auth` prefix."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from elums.api.deps import get_db
from elums.api.errors import ApiError
from elums.auth.passwords import hash_password, verify_password
from elums.auth.sessions import create_session, delete_session, get_session_by_token
from elums.config import settings
from elums.models.user import User
from elums.schemas.auth import LoginRequest, RegisterRequest, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=30 * 24 * 60 * 60,  # 30 days, matches auth/sessions.py's SESSION_TTL
    )


@router.post("/register", response_model=UserPublic, status_code=201)
async def register(
    body: RegisterRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> User:
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise ApiError("email_taken", "An account with this email already exists.", status_code=409)

    user = User(
        email=body.email,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.flush()

    _, raw_token = await create_session(db, user.id)
    await db.commit()

    _set_session_cookie(response, raw_token)
    return user


@router.post("/login", response_model=UserPublic)
async def login(body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)) -> User:
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    # Deliberately the same error for "no such user" and "wrong password" —
    # distinguishing them tells an attacker which emails are registered.
    if user is None or not verify_password(user.password_hash, body.password):
        raise ApiError("invalid_credentials", "Incorrect email or password.", status_code=401)

    _, raw_token = await create_session(db, user.id)
    await db.commit()

    _set_session_cookie(response, raw_token)
    return user


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> None:
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token is not None:
        session = await get_session_by_token(db, raw_token)
        if session is not None:
            await delete_session(db, session)
            await db.commit()
    response.delete_cookie(settings.session_cookie_name)
