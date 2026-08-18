from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient


def test_health_is_stable(test_client: TestClient) -> None:
    response = test_client.get("/health", headers={"X-Correlation-ID": "test-health"})
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "test-health"
    assert response.json() == {
        "status": "ok",
        "dependencies": {"database": "ok", "redis": "ok", "minio": "ok", "api": "ok"},
    }


def test_version_contains_build_metadata(test_client: TestClient) -> None:
    response = test_client.get("/version", headers={"X-Correlation-ID": "test-version"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["applicationName"] == "SNAX"
    assert payload["applicationVersion"] == "0.1.0"
    assert payload["contractVersion"] == "1.1.0"
    assert payload["buildMetadata"]["correlationId"] == "test-version"


def test_import_registry_uses_synthetic_data(test_client: TestClient) -> None:
    response = test_client.get("/imports")
    assert response.status_code == 200
    assert len(response.json()) == 2
    assert all(item["supplier"].startswith("Демо-поставщик") for item in response.json())


def test_missing_import_has_stable_problem(test_client: TestClient) -> None:
    response = test_client.get(f"/imports/{uuid4()}", headers={"X-Correlation-ID": "missing"})
    assert response.status_code == 404
    assert response.json() == {
        "code": "IMPORT_NOT_FOUND",
        "message": "Импорт не найден",
        "retryable": False,
        "correlationId": "missing",
        "field": "importId",
        "details": None,
    }


def test_invalid_import_id_is_classified(test_client: TestClient) -> None:
    response = test_client.get("/imports/not-a-uuid")
    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_post_import_get_and_idempotency_replay(test_client: TestClient) -> None:
    headers = {
        "X-Correlation-ID": "api-correlation-001",
        "X-Idempotency-Key": "api-idempotency-0001",
    }
    response = test_client.post(
        "/imports",
        headers=headers,
        files={"file": ("price.xlsx", b"api payload", "application/octet-stream")},
        data={"supplierCode": "DEMO", "profileCode": "DEMO_PROFILE"},
    )
    assert response.status_code == 202
    accepted = response.json()
    assert accepted["status"] == "STORED"
    assert response.headers["X-Correlation-ID"] == headers["X-Correlation-ID"]

    status = test_client.get(accepted["statusUrl"].replace("http://localhost:8000", ""))
    assert status.status_code == 200
    assert status.json()["importId"] == accepted["importId"]
    assert status.json()["status"] == "STORED"
    assert status.json()["summary"]["originalFileName"] == "price.xlsx"

    replay = test_client.post(
        "/imports",
        headers=headers,
        files={"file": ("renamed.xlsx", b"api payload", "application/octet-stream")},
    )
    assert replay.status_code == 200
    assert replay.json() == accepted


def test_post_import_conflicts_are_stable(test_client: TestClient) -> None:
    first = test_client.post(
        "/imports",
        headers={"X-Idempotency-Key": "api-idempotency-0002"},
        files={"file": ("one.xlsx", b"unique api payload", "application/octet-stream")},
    )
    assert first.status_code == 202

    idempotency_conflict = test_client.post(
        "/imports",
        headers={"X-Idempotency-Key": "api-idempotency-0002"},
        files={"file": ("one.xlsx", b"different payload", "application/octet-stream")},
    )
    assert idempotency_conflict.status_code == 409
    assert idempotency_conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"

    duplicate = test_client.post(
        "/imports",
        headers={"X-Idempotency-Key": "api-idempotency-0003"},
        files={"file": ("copy.xlsx", b"unique api payload", "application/octet-stream")},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "DUPLICATE_FILE"
    assert duplicate.json()["details"]["existingImportId"] == first.json()["importId"]


def test_post_import_size_and_metadata_validation(test_client: TestClient) -> None:
    service = test_client.app.state.runtime.service
    old_limit = service.max_upload_bytes
    service.max_upload_bytes = 3
    try:
        too_large = test_client.post(
            "/imports",
            headers={"X-Idempotency-Key": "api-idempotency-0004"},
            files={"file": ("large.xlsx", b"1234", "application/octet-stream")},
        )
        assert too_large.status_code == 413
        assert too_large.json()["code"] == "FILE_TOO_LARGE"
    finally:
        service.max_upload_bytes = old_limit

    traversal = test_client.post(
        "/imports",
        headers={"X-Idempotency-Key": "api-idempotency-0005"},
        files={"file": ("../secret.xlsx", b"data", "application/octet-stream")},
    )
    assert traversal.status_code == 422
    assert traversal.json()["code"] == "INVALID_METADATA"
