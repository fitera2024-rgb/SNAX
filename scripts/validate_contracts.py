from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
PAIRS = (
    ("schemas/import-package.schema.json", "examples/import-package.example.json"),
    ("schemas/mapping-sync.schema.json", "examples/mapping-sync.example.json"),
    ("schemas/receipt-package.schema.json", "examples/receipt-package.example.json"),
    (
        "schemas/processing-job-message.schema.json",
        "examples/processing-job-message.example.json",
    ),
    ("raw-workbook.schema.json", "examples/raw-workbook.example.json"),
    ("raw-workbook.schema.json", "examples/raw-workbook-error.example.json"),
    (
        "supplier-profile.schema.json",
        "examples/supplier-profile.simple_supplier_profile.json",
    ),
    (
        "supplier-profile.schema.json",
        "examples/supplier-profile.multi_sheet_profile.json",
    ),
    (
        "supplier-profile.schema.json",
        "examples/supplier-profile.versioned_profile.json",
    ),
)
INVALID_PAIRS = (
    (
        "schemas/processing-job-message.schema.json",
        "invalid/processing-job-message-dangerous-payload.json",
    ),
    ("raw-workbook.schema.json", "invalid/raw-workbook-invalid-value-type.json"),
    ("raw-workbook.schema.json", "invalid/raw-workbook-missing-workbook.json"),
    ("raw-workbook.schema.json", "invalid/raw-workbook-error-token-as-code.json"),
    (
        "raw-workbook.schema.json",
        "invalid/raw-workbook-string-converted-to-number.json",
    ),
    (
        "raw-workbook.schema.json",
        "invalid/raw-workbook-formula-metadata-missing.json",
    ),
    (
        "supplier-profile.schema.json",
        "invalid/supplier-profile.missing-supplier-id.json",
    ),
    (
        "supplier-profile.schema.json",
        "invalid/supplier-profile.invalid-status.json",
    ),
    (
        "supplier-profile.schema.json",
        "invalid/supplier-profile.invalid-target-field.json",
    ),
    (
        "supplier-profile.schema.json",
        "invalid/supplier-profile.invalid-version.json",
    ),
)


def load_json(relative_path: str) -> object:
    return json.loads((CONTRACTS / relative_path).read_text(encoding="utf-8"))


def main() -> None:
    openapi_path = CONTRACTS / "openapi.yaml"
    openapi = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))
    validate(openapi, base_uri=openapi_path.as_uri())
    for schema_path, example_path in PAIRS:
        schema = load_json(schema_path)
        example = load_json(example_path)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(example)
        print(f"validated {example_path} against {schema_path}")
    for schema_path, example_path in INVALID_PAIRS:
        schema = load_json(schema_path)
        example = load_json(example_path)
        if not list(Draft202012Validator(schema).iter_errors(example)):
            raise SystemExit(f"invalid fixture unexpectedly passed: {example_path}")
        print(f"rejected {example_path} against {schema_path}")
    print("validated contracts/openapi.yaml")


if __name__ == "__main__":
    main()
