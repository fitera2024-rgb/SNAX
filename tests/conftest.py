from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from snax_import.main import app


@pytest.fixture
def test_client() -> TestClient:
    return TestClient(app)
