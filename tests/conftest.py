from __future__ import annotations

from fastapi.testclient import TestClient

from snax_import.main import app


def test_client() -> TestClient:
    return TestClient(app)
