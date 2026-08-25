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
        "schemas/config-dump-manifest.schema.json",
        "examples/config-dump-manifest.example.json",
    ),
    (
        "schemas/mdm-object-catalog.schema.json",
        "examples/mdm-object-catalog.example.json",
    ),
    (
        "schemas/extension-passport.schema.json",
        "examples/extension-passport.example.json",
    ),
    ("schemas/exchange-catalog.schema.json", "examples/exchange-catalog.example.json"),
    (
        "schemas/store-day-reconciliation.schema.json",
        "examples/store-day-reconciliation.example.json",
    ),
    ("schemas/kpi-passport.schema.json", "examples/kpi-passport.example.json"),
)
INVALID_PAIRS = (
    (
        "schemas/processing-job-message.schema.json",
        "invalid/processing-job-message-dangerous-payload.json",
    ),
    (
        "schemas/config-dump-manifest.schema.json",
        "invalid/config-dump-manifest-commit-payload.json",
    ),
    (
        "schemas/store-day-reconciliation.schema.json",
        "invalid/store-day-reconciliation-float-amount.json",
    ),
    (
        "schemas/mdm-object-catalog.schema.json",
        "invalid/mdm-object-catalog-empty-code.json",
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
