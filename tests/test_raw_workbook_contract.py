from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"


def _load(relative_path: str) -> object:
    return json.loads((CONTRACTS / relative_path).read_text(encoding="utf-8"))


def test_valid_error_fixture_passes_raw_workbook_schema() -> None:
    validator = Draft202012Validator(_load("raw-workbook.schema.json"))

    assert not list(validator.iter_errors(_load("examples/raw-workbook-error.example.json")))


def test_error_token_used_as_machine_code_fails_raw_workbook_schema() -> None:
    validator = Draft202012Validator(_load("raw-workbook.schema.json"))

    errors = list(validator.iter_errors(_load("invalid/raw-workbook-error-token-as-code.json")))

    assert errors
    assert any(
        child.json_path.endswith(".errorCode") for error in errors for child in error.context
    )
