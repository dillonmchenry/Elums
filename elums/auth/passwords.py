"""Argon2id password hashing — argon2-cffi's defaults (time_cost=3,
memory_cost=64 MiB, parallelism=4) are the OWASP-recommended baseline and
deliberately not tuned further for a 9-day project; revisit only if a
load test says otherwise."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        # Covers both a wrong password (VerifyMismatchError) and a
        # malformed/foreign hash (InvalidHashError) — either way, "no".
        return False
