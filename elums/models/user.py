from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from elums.models.base import Base, TimestampMixin, uuidv7_pk


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id = uuidv7_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Argon2id, via argon2-cffi's PasswordHasher — see elums/auth/passwords.py.
    # Not bcrypt/scrypt: Argon2id is the OWASP-recommended default and the
    # one explicitly named in ELUMS_TECHNICAL_APPROACH.md's auth section.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
