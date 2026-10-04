"""Content-addressed blob storage — M7.

The seam from ELUMS_TECHNICAL_APPROACH.md §4: "a BlobStore Protocol with
one local implementation and a documented ~40-line S3BlobStore" (not
written today; the seam is what matters so a later S3 backend is an
addition, not a refactor). `local_path` returning `None` is what lets a
hypothetical remote backend degrade Caddy's fast path to a streaming
response, instead of the Protocol pretending every store is a filesystem.

Layout: `${BLOB_ROOT}/<ab>/<cd>/<sha256>` — two levels of two-hex-char
fanout, so no directory exceeds a few thousand entries even at catalog
scale. Writes go to a temp file in the store's own staging directory and
then `os.replace`, which is atomic on one filesystem: a crash mid-write
(or a rejected upload — see `put`'s size-cap note) leaves an orphaned temp
file, never a corrupt blob at a valid hash. Hashing happens while
streaming so a large upload is never fully buffered in memory.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


class BlobNotFoundError(Exception):
    """Raised by `open` for an unknown hash — never a raw
    FileNotFoundError, which would leak the fanout layout into callers."""

    def __init__(self, sha256: str) -> None:
        self.sha256 = sha256
        super().__init__(f"No blob for sha256={sha256!r}")


@dataclass(frozen=True)
class BlobRef:
    sha256: str
    size_bytes: int
    content_type: str


class BlobStore(Protocol):
    def put(self, data: BinaryIO, *, content_type: str) -> BlobRef: ...
    def open(self, sha256: str) -> BinaryIO: ...
    def exists(self, sha256: str) -> bool: ...
    def url(self, sha256: str) -> str: ...
    def local_path(self, sha256: str) -> Path | None: ...  # None for non-local backends


class LocalBlobStore:
    """The one implementation that exists today. `root` is `Settings.blob_root`
    — never a literal path anywhere that constructs one of these."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path_for(self, sha256: str) -> Path:
        return self._root / sha256[:2] / sha256[2:4] / sha256

    def put(self, data: BinaryIO, *, content_type: str) -> BlobRef:
        """Streams `data` to a temp file while hashing, then atomically
        publishes it at its content address.

        If `data.read()` raises partway through (the caller's size-cap
        enforcement, or a genuinely broken upload), this method never
        reaches `os.replace` — the temp file is left behind, orphaned, and
        no blob exists at any hash. That's the "simulated crash" case
        `tests/test_blobstore.py` exercises directly.
        """
        staging_dir = self._root / ".staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = staging_dir / f".tmp-{uuid.uuid4().hex}"

        hasher = hashlib.sha256()
        size_bytes = 0
        with tmp_path.open("wb") as tmp_file:
            while chunk := data.read(_CHUNK_SIZE):
                hasher.update(chunk)
                size_bytes += len(chunk)
                tmp_file.write(chunk)

        sha256 = hasher.hexdigest()
        final_path = self._path_for(sha256)
        final_path.parent.mkdir(parents=True, exist_ok=True)

        if final_path.exists():
            # Content-addressed dedup: identical bytes already landed at
            # this hash from an earlier `put`. The write above was
            # redundant but harmless; just discard the duplicate temp file
            # rather than replacing a file that's already byte-identical.
            tmp_path.unlink()
        else:
            os.replace(tmp_path, final_path)  # atomic on one filesystem

        return BlobRef(sha256=sha256, size_bytes=size_bytes, content_type=content_type)

    def open(self, sha256: str) -> BinaryIO:
        path = self._path_for(sha256)
        if not path.exists():
            raise BlobNotFoundError(sha256)
        return path.open("rb")

    def exists(self, sha256: str) -> bool:
        return self._path_for(sha256).exists()

    def url(self, sha256: str) -> str:
        return f"/blobs/{sha256[:2]}/{sha256[2:4]}/{sha256}"

    def local_path(self, sha256: str) -> Path | None:
        path = self._path_for(sha256)
        return path if path.exists() else None
