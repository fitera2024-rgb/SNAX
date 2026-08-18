from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL") or not os.environ.get("TEST_S3_ENDPOINT"),
    reason="PostgreSQL and MinIO integration settings are required",
)
def test_api_upload_get_duplicate_and_replay(test_client: TestClient) -> None:
    key = "integration-api-idempotency-0001"
    payload = b"api postgres and minio payload"
    headers = {"X-Idempotency-Key": key, "X-Correlation-ID": "integration-correlation-001"}
    created = test_client.post(
        "/imports",
        headers=headers,
        files={"file": ("integration.bin", payload, "application/octet-stream")},
    )
    assert created.status_code == 202
    import_id = created.json()["importId"]
    assert created.json()["status"] == "STORED"
    assert test_client.get(f"/imports/{import_id}").status_code == 200

    replay = test_client.post(
        "/imports",
        headers=headers,
        files={"file": ("renamed.bin", payload, "application/octet-stream")},
    )
    assert replay.status_code == 202
    assert replay.json()["importId"] == import_id

    duplicate = test_client.post(
        "/imports",
        headers={"X-Idempotency-Key": "integration-api-idempotency-0002"},
        files={"file": ("copy.bin", payload, "application/octet-stream")},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "DUPLICATE_FILE"


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL") or not os.environ.get("TEST_S3_ENDPOINT"),
    reason="PostgreSQL and MinIO integration settings are required",
)
def test_api_accepts_cyrillic_original_filename() -> None:
    from snax_import.main import app

    marker = uuid4().hex
    filename = "Прайс поставщика № 1.xlsx"
    payload = f"unicode-filename-{marker}".encode()
    with TestClient(app) as client:
        created = client.post(
            "/imports",
            headers={
                "X-Idempotency-Key": f"unicode-filename-{marker}",
                "X-Correlation-ID": f"unicode-correlation-{marker}",
            },
            files={"file": (filename, payload, "application/octet-stream")},
        )
        assert created.status_code == 202
        status = client.get(f"/imports/{created.json()['importId']}")
    assert status.status_code == 200
    assert status.json()["summary"]["originalFileName"] == filename
