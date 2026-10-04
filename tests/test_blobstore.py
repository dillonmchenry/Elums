"""M7: pure unit tests for `elums.blobs.store.LocalBlobStore` — no DB, no
live stack. Uses pytest's `tmp_path` as `BLOB_ROOT` so every test gets a
clean, disposable store.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from elums.blobs.store import BlobNotFoundError, LocalBlobStore


@pytest.fixture
def store(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(tmp_path)


def test_put_open_round_trip(store: LocalBlobStore) -> None:
    payload = b"the quick brown fox jumps over the lazy dog"
    ref = store.put(io.BytesIO(payload), content_type="text/plain")

    assert ref.sha256 == hashlib.sha256(payload).hexdigest()
    assert ref.size_bytes == len(payload)

    with store.open(ref.sha256) as f:
        assert f.read() == payload


def test_identical_bytes_produce_one_hash_and_one_file(store: LocalBlobStore) -> None:
    payload = b"deduplicate me"
    ref1 = store.put(io.BytesIO(payload), content_type="text/plain")
    ref2 = store.put(io.BytesIO(payload), content_type="text/plain")

    assert ref1.sha256 == ref2.sha256
    local_path = store.local_path(ref1.sha256)
    assert local_path is not None
    assert local_path.read_bytes() == payload

    # Fanout dir holds exactly one file for this hash — no "-copy" or
    # second write landed anywhere.
    assert list(local_path.parent.iterdir()) == [local_path]


def test_open_unknown_hash_raises_typed_error_not_file_not_found_error(
    store: LocalBlobStore,
) -> None:
    fake_sha256 = "0" * 64
    with pytest.raises(BlobNotFoundError):
        store.open(fake_sha256)


def test_exists_and_local_path_agree_for_unknown_hash(store: LocalBlobStore) -> None:
    fake_sha256 = "f" * 64
    assert store.exists(fake_sha256) is False
    assert store.local_path(fake_sha256) is None


class _RaisesPartway(io.RawIOBase):
    """A file-like object that yields a few real bytes, then raises —
    simulating a crash (or a size-cap abort) mid-upload."""

    def __init__(self, good_chunk: bytes) -> None:
        self._good_chunk = good_chunk
        self._served = False

    def read(self, size: int = -1) -> bytes:
        if not self._served:
            self._served = True
            return self._good_chunk
        raise RuntimeError("simulated crash mid-write")


def test_crash_between_temp_write_and_replace_leaves_no_blob_at_target_path(
    store: LocalBlobStore, tmp_path: Path
) -> None:
    with pytest.raises(RuntimeError, match="simulated crash"):
        store.put(_RaisesPartway(b"partial data that never finishes"), content_type="text/plain")

    # No final blob exists anywhere under the store root at any hash —
    # the only files on disk are the orphaned temp file(s) in `.staging`.
    staging_dir = tmp_path / ".staging"
    non_staging_files = [
        p for p in tmp_path.rglob("*") if p.is_file() and staging_dir not in p.parents
    ]
    assert non_staging_files == []
