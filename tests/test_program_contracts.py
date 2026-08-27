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


def test_yandex_share_sanitized_manifest_passes() -> None:
    import json

    validator = Draft202012Validator(_load("schemas/config-dump-manifest.schema.json"))
    manifest_path = (
        ROOT
        / "docs"
        / "research"
        / "2026-08-27"
        / "config-dump-manifest.yandex-share.sanitized.json"
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert not list(validator.iter_errors(payload))
    assert payload["gitPolicy"] == "DO_NOT_COMMIT_PAYLOAD"
    assert payload["bases"][0]["status"] == "VERIFIED"
    assert payload["bases"][1]["status"] == "VERIFIED"
    assert payload["bases"][0]["platformVersion"] is None
    assert payload["bases"][1]["platformVersion"] is None
    assert "Infobase data is not verified" in (payload["notes"] or "")
    assert payload["bases"][0]["configurationVersion"] == "3.0.13.342"
    assert payload["bases"][1]["configurationVersion"] == "11.5.22.164"
    assert {item["kind"] for item in payload["artifacts"]} == {"XML_CONFIG"}
    assert {item["fileName"] for item in payload["artifacts"]} == {
        "ConfigFiles.zip",
        "F.zip",
        "F-2.zip",
        "Forus-1.zip",
        "maxma.zip",
        "YT.zip",
        "YT-1.zip",
        "YT-2.zip",
    }


def test_extension_passport_draft_passes() -> None:
    import json

    validator = Draft202012Validator(_load("schemas/extension-passport.schema.json"))
    path = ROOT / "docs" / "research" / "2026-08-27" / "extension-passport.draft.sanitized.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert not list(validator.iter_errors(payload))
    assert all(item["disposition"] == "UNDECIDED" for item in payload["extensions"])
    assert all(item["status"] == "UNVERIFIED" for item in payload["extensions"])
    assert len(payload["extensions"]) == 6


def test_retail_xml_payload_is_not_in_git_tree() -> None:
    import subprocess

    listed = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files"],
        text=True,
    )
    lowered = listed.lower()
    assert "roznitsaxml.zip" not in lowered
    assert "розницаxml.zip" not in listed.lower()
    assert "configfiles.zip" not in lowered
    assert "ibases_snax" not in lowered
    forbidden_suffixes = (".v8i", ".dt", ".cf", ".cfe")
    for line in listed.splitlines():
        lower_line = line.lower()
        assert not lower_line.endswith(forbidden_suffixes)
        assert "/catalogs/" not in lower_line
        assert "parentconfigurations/" not in lower_line
        assert Path(line).name.lower() not in {"yt.zip", "configfiles.zip", "f.zip", "maxma.zip"}
