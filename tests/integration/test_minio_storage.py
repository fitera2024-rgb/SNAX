from __future__ import annotations

import hashlib
import os
from io import BytesIO

import pytest

from snax_import.adapters.storage.s3 import S3ObjectStorage
from snax_import.domain.errors import DigestMismatch
from snax_import.domain.value_objects import ObjectKey, Sha256Digest

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not os.environ.get("TEST_S3_ENDPOINT"), reason="TEST_S3_ENDPOINT is required")
def test_minio_streaming_put_get_is_immutable() -> None:
    payload = b"minio integration payload"
    digest = Sha256Digest(hashlib.sha256(payload).hexdigest())
    storage = S3ObjectStorage(
        endpoint=os.environ["TEST_S3_ENDPOINT"],
        access_key=os.environ["TEST_S3_ACCESS_KEY"],
        secret_key=os.environ["TEST_S3_SECRET_KEY"],
        bucket=os.environ["TEST_S3_BUCKET"],
    )
    key = ObjectKey.for_digest(digest)
    first = storage.put_stream(
        BytesIO(payload),
        object_key=key,
        digest=digest,
        size=len(payload),
        media_type="application/octet-stream",
        metadata={"original-filename": "integration.bin"},
    )
    second = storage.put_stream(
        BytesIO(payload),
        object_key=key,
        digest=digest,
        size=len(payload),
        media_type="application/octet-stream",
        metadata={"original-filename": "different.bin"},
    )
    assert first.created_by_attempt is True
    assert second.created_by_attempt is False
    assert storage.metadata(key)["sha256"] == digest.value
    assert storage.metadata(key)["original-filename"] == "integration.bin"
    with storage.get_stream(key) as stream:
        assert stream.read() == payload
    storage.verify_digest(key, digest)
    with pytest.raises(DigestMismatch):
        storage.verify_digest(key, Sha256Digest("f" * 64))
