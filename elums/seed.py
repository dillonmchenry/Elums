"""`make seed` entrypoint. Per ELUMS_TECHNICAL_APPROACH.md's auth section:
"Ship 8-10 demo users with known passwords, a pre-populated social graph...
The difference between 'auth works' and 'I can log in as @dana and see her
feed' is most of the perceived quality of a take-home."

Idempotent: upserts by email, safe to re-run (`docker compose restart db`
during the week shouldn't require remembering this command's exact
invocation history).

F8 (Session C, IMPLEMENTATION_PLAN_2026-10-09.md) extends this to give
`dana` >= `_DANA_PERFORMANCE_COUNT` SUCCEEDED `Performance` rows against
one dummy song, so the progress endpoint's three-way verdict (gated at
`metrics.VERDICT_GATE_N` = 8) has a demo account that actually clears
the gate, without lowering that gate itself. Scores are synthetic
(no audio/f0/analysis blob -- those three columns stay NULL, same as
any performance that failed before scoring got that far) but
monotonically improving, so the seeded account visibly demonstrates
every verdict a reviewer would want to see besides "sing N more":
the FIRST `metrics.VERDICT_GATE_N` are seeded flat/mediocre, and the
rest trend upward, so dana's own history crosses from
"insufficient_data" to "improving" partway through -- exactly the
transition the gate exists to guard.
"""

from __future__ import annotations

import asyncio
import io

from sqlalchemy import select

from elums.auth.passwords import hash_password
from elums.blobs.service import record_blob
from elums.blobs.store import LocalBlobStore
from elums.config import settings
from elums.db import session_scope
from elums.models.follow import Follow
from elums.models.performance import Performance, PerformanceKind, PerformanceStatus
from elums.models.song import Song, SongVisibility
from elums.models.user import User
from elums.progress import metrics

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

# One more than `metrics.VERDICT_GATE_N` so dana's seeded history
# clears the gate with margin, not exactly at the boundary -- a
# reviewer re-running `make seed` shouldn't see an off-by-one flake if
# the gate constant ever shifts by one in either direction.
_DANA_PERFORMANCE_COUNT = metrics.VERDICT_GATE_N + 2
_DANA_SONG_TITLE = "Progress Demo Song"
# score_overall per seeded performance, oldest first: a flat/mediocre
# run for the first VERDICT_GATE_N takes (so the gate's own
# "insufficient_data" state has real history to show up to that
# point), then a clearly improving run after -- the exact transition
# the three-way verdict exists to detect.
_DANA_SCORES = [0.55, 0.58, 0.52, 0.6, 0.56, 0.59, 0.54, 0.57, 0.68, 0.82]
assert len(_DANA_SCORES) == _DANA_PERFORMANCE_COUNT


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

        dana = emails_to_user[DEMO_USERS[0][0]]
        await _seed_dana_performances(db, dana)

    print(f"Seeded {len(DEMO_USERS)} demo users (password: {DEMO_PASSWORD!r}) and their follow graph.")
    print("Try: curl -c cookies.txt -X POST .../api/auth/login -d '{\"email\":\"dana@elums.demo\",...}'")


async def _seed_dana_performances(db, dana: User) -> None:
    existing_song = (
        await db.execute(
            select(Song).where(
                Song.uploaded_by_user_id == dana.id, Song.title == _DANA_SONG_TITLE
            )
        )
    ).scalar_one_or_none()

    if existing_song is not None:
        existing_count = (
            await db.execute(
                select(Performance).where(
                    Performance.song_id == existing_song.id,
                    Performance.user_id == dana.id,
                    Performance.status == PerformanceStatus.SUCCEEDED,
                )
            )
        ).scalars().all()
        if len(existing_count) >= _DANA_PERFORMANCE_COUNT:
            return  # already seeded by an earlier `make seed` run

    # A tiny dummy "source" blob -- this song exists only to anchor
    # `Performance.song_id`'s FK and never goes through the real
    # ingest pipeline (no stems, no chart, no F0 reference), so no
    # real audio bytes are needed, just a valid content-addressed row.
    store = LocalBlobStore(settings.blob_root)
    ref = store.put(io.BytesIO(b"elums-progress-demo-song-placeholder"), content_type="audio/wav")
    await record_blob(db, ref)

    song = existing_song
    if song is None:
        song = Song(
            uploaded_by_user_id=dana.id,
            title=_DANA_SONG_TITLE,
            artist="Elums Demo",
            source_blob_sha256=ref.sha256,
            visibility=SongVisibility.PRIVATE,
        )
        db.add(song)
        await db.flush()

    for score in _DANA_SCORES:
        db.add(
            Performance(
                song_id=song.id,
                user_id=dana.id,
                kind=PerformanceKind.SOLO,
                status=PerformanceStatus.SUCCEEDED,
                score_overall=score,
                pct_in_tune=min(1.0, score + 0.1),
                median_cents=(1.0 - score) * 40.0,
                arrival_offset_ms_median=(1.0 - score) * 60.0,
                device_label="laptop-mic",
            )
        )
    await db.commit()


def main() -> None:
    asyncio.run(_seed())


if __name__ == "__main__":
    main()
