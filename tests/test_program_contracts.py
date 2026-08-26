from __future__ import annotations

from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"


def _load(relative_path: str) -> object:
    import json

    return json.loads((CONTRACTS / relative_path).read_text(encoding="utf-8"))


def test_dump_manifest_example_passes() -> None:
    validator = Draft202012Validator(_load("schemas/config-dump-manifest.schema.json"))
    assert not list(validator.iter_errors(_load("examples/config-dump-manifest.example.json")))


def test_dump_manifest_commit_payload_is_rejected() -> None:
    validator = Draft202012Validator(_load("schemas/config-dump-manifest.schema.json"))
    errors = list(validator.iter_errors(_load("invalid/config-dump-manifest-commit-payload.json")))
    assert errors
    assert any("gitPolicy" in error.json_path for error in errors)


def test_store_day_float_amount_is_rejected() -> None:
    validator = Draft202012Validator(_load("schemas/store-day-reconciliation.schema.json"))
    errors = list(
        validator.iter_errors(_load("invalid/store-day-reconciliation-float-amount.json"))
    )
    assert errors
    assert any("amountSum" in error.json_path for error in errors)


def test_mdm_empty_code_is_rejected() -> None:
    validator = Draft202012Validator(_load("schemas/mdm-object-catalog.schema.json"))
    errors = list(validator.iter_errors(_load("invalid/mdm-object-catalog-empty-code.json")))
    assert errors


def test_retail_xml_sanitized_manifest_passes() -> None:
    import json

    validator = Draft202012Validator(_load("schemas/config-dump-manifest.schema.json"))
    manifest_path = (
        ROOT / "docs" / "research" / "2026-08-26" / "config-dump-manifest.retail-xml.sanitized.json"
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert not list(validator.iter_errors(payload))
    assert payload["gitPolicy"] == "DO_NOT_COMMIT_PAYLOAD"
    assert payload["artifacts"][0]["kind"] == "XML_CONFIG"
    assert payload["bases"][0]["status"] == "UNVERIFIED"


def test_retail_xml_payload_is_not_in_git_tree() -> None:
    import subprocess

    listed = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files"],
        text=True,
    )
    lowered = listed.lower()
    assert "roznitsaxml.zip" not in lowered
    assert "розницаxml.zip" not in listed.lower()
    for line in listed.splitlines():
        assert not line.endswith(".dt")
        assert not line.endswith(".cf")
        assert not line.endswith(".cfe")
        assert "/Catalogs/" not in line
