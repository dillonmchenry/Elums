"""`make seed` entrypoint. Per ELUMS_TECHNICAL_APPROACH.md's auth section:
"Ship 8-10 demo users with known passwords, a pre-populated social graph...
The difference between 'auth works' and 'I can log in as @dana and see her
feed' is most of the perceived quality of a take-home."

Idempotent: upserts by email, safe to re-run (`docker compose restart db`
during the week shouldn't require remembering this command's exact
invocation history).

Performances aren't seeded yet — that needs the ingest pipeline (M8+,
Day 1), not auth (M6). Revisit once there's something to attach to a user.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from elums.auth.passwords import hash_password
from elums.db import session_scope
from elums.models.follow import Follow
from elums.models.user import User

# All ten share the same known password so the reviewer only needs to
# remember one credential — the point of seeding is "log in as @dana",
# not "guess dana's password".
DEMO_PASSWORD = "elums-demo-2026"

DEMO_USERS = [
    ("dana@elums.demo", "dana", "Dana"),
    ("milo@elums.demo", "milo", "Milo"),
    ("priya@elums.demo", "priya", "Priya"),
    ("jules@elums.demo", "jules", "Jules"),
    ("theo@elums.demo", "theo", "Theo"),
    ("ana@elums.demo", "ana", "Ana"),
    ("sam@elums.demo", "sam", "Sam"),
    ("kiko@elums.demo", "kiko", "Kiko"),
    ("remy@elums.demo", "remy", "Remy"),
    ("wren@elums.demo", "wren", "Wren"),
]

# A small social graph, not a complete one: a few well-connected "hub"
# users (dana, milo) and some sparser ones, so follower-count/feed logic
# has something non-uniform to work against. Indices into DEMO_USERS.
FOLLOW_EDGES = [
    (0, 1), (0, 2), (0, 3), (0, 4),  # dana follows milo, priya, jules, theo
    (1, 0), (1, 2), (1, 5),           # milo follows dana, priya, ana
    (2, 0), (2, 1),                   # priya follows dana, milo
    (3, 0), (3, 4), (3, 6),           # jules follows dana, theo, sam
    (4, 0), (4, 3),                   # theo follows dana, jules
    (5, 1), (5, 7),                   # ana follows milo, kiko
    (6, 3), (6, 8),                   # sam follows jules, remy
    (7, 5), (7, 9),                   # kiko follows ana, wren
    (8, 6),                           # remy follows sam
    (9, 7), (9, 0),                   # wren follows kiko, dana
]


async def _seed() -> None:
    async with session_scope() as db:
        password_hash = hash_password(DEMO_PASSWORD)
        emails_to_user = {}

        for email, handle, display_name in DEMO_USERS:
            existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
            if existing is not None:
                emails_to_user[email] = existing
                continue
            user = User(email=email, display_name=f"{display_name} (@{handle})", password_hash=password_hash)
            db.add(user)
            await db.flush()
            emails_to_user[email] = user

        for follower_idx, followee_idx in FOLLOW_EDGES:
            follower = emails_to_user[DEMO_USERS[follower_idx][0]]
            followee = emails_to_user[DEMO_USERS[followee_idx][0]]
            existing_edge = (
                await db.execute(
                    select(Follow).where(
                        Follow.follower_id == follower.id, Follow.followee_id == followee.id
                    )
                )
            ).scalar_one_or_none()
            if existing_edge is None:
                db.add(Follow(follower_id=follower.id, followee_id=followee.id))

        await db.commit()

    print(f"Seeded {len(DEMO_USERS)} demo users (password: {DEMO_PASSWORD!r}) and their follow graph.")
    print("Try: curl -c cookies.txt -X POST .../api/auth/login -d '{\"email\":\"dana@elums.demo\",...}'")


def main() -> None:
    asyncio.run(_seed())


if __name__ == "__main__":
    main()
