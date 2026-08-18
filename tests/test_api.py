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
