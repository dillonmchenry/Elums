"""M6: `GET /api/me` and `GET /api/users/{id}/following`. Split out from
auth.py because the implementation plan's M6 route list names `/api/me`
directly, outside the `/auth` prefix the login/logout/register routes use.

`/users/{id}/following` is deliberately public (no `get_current_user`
dependency) — it's A9's social-graph check and the eventual public
"who does X follow" listing, not account-private data."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from elums.api.deps import get_current_user, get_db
from elums.api.errors import ApiError
from elums.models.follow import Follow
from elums.models.user import User
from elums.schemas.auth import UserPublic

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserPublic)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("/users/{user_id}/following", response_model=list[UserPublic])
async def get_following(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[User]:
    target = await db.get(User, user_id)
    if target is None:
        raise ApiError("not_found", "No such user.", status_code=404)

    result = await db.execute(
        select(User)
        .join(Follow, Follow.followee_id == User.id)
        .where(Follow.follower_id == user_id)
        .order_by(User.display_name)
    )
    return list(result.scalars().all())
