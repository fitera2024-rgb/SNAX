from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
FORMAT_CHECKER = FormatChecker()


def _load(relative_path: str) -> object:
    return json.loads((CONTRACTS / relative_path).read_text(encoding="utf-8"))


def test_supplier_profile_valid_examples_pass_schema() -> None:
    schema = _load("supplier-profile.schema.json")
    validator = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)
    for name in (
        "supplier-profile.simple_supplier_profile.json",
        "supplier-profile.multi_sheet_profile.json",
        "supplier-profile.versioned_profile.json",
    ):
        assert not list(validator.iter_errors(_load(f"examples/{name}"))), name


def test_supplier_profile_invalid_examples_fail_schema() -> None:
    schema = _load("supplier-profile.schema.json")
    validator = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)
    for name in (
        "supplier-profile.missing-supplier-id.json",
        "supplier-profile.invalid-status.json",
        "supplier-profile.invalid-target-field.json",
        "supplier-profile.invalid-version.json",
        "supplier-profile.invalid-uuid.json",
        "supplier-profile.invalid-datetime.json",
    ):
        assert list(validator.iter_errors(_load(f"invalid/{name}"))), name
