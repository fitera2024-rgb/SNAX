from __future__ import annotations

import json
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs" / "research" / "2026-08-27"
CONTRACTS = ROOT / "contracts"
INTAKE_ID = "a19e6c40-7b2d-4f11-8c55-2d9a0b47e801"


def _schema(name: str) -> Draft202012Validator:
    payload = json.loads((CONTRACTS / "schemas" / name).read_text(encoding="utf-8"))
    return Draft202012Validator(payload)


def test_yandex_manifest_is_schema_valid() -> None:
    manifest = json.loads(
        (RESEARCH / "config-dump-manifest.yandex-share.sanitized.json").read_text(encoding="utf-8")
    )
    assert not list(_schema("config-dump-manifest.schema.json").iter_errors(manifest))
    assert manifest["intakeId"] == INTAKE_ID
    assert manifest["gitPolicy"] == "DO_NOT_COMMIT_PAYLOAD"
    versions = {item["baseCode"]: item for item in manifest["bases"]}
    assert versions["RETAIL_DUMP_01"]["configurationVersion"] == "3.0.13.342"
    assert versions["UT_DUMP_01"]["configurationVersion"] == "11.5.22.164"
    assert versions["RETAIL_DUMP_01"]["status"] == "VERIFIED"
    assert versions["UT_DUMP_01"]["status"] == "VERIFIED"
    assert versions["RETAIL_DUMP_01"]["contour"] == "RETAIL_CENTRAL"
    assert versions["UT_DUMP_01"]["contour"] == "UT_CENTRAL"
    assert versions["RETAIL_DUMP_01"]["platformVersion"] is None
    assert versions["UT_DUMP_01"]["platformVersion"] is None
    notes = manifest["notes"] or ""
    assert "Infobase data is not verified" in notes
    assert "hypothesis" not in notes.lower()
    for item in manifest["bases"]:
        reason = (item.get("unknownReason") or "").lower()
        assert "hypothesis" not in reason
        assert "platformversion" in reason
        assert "infobase data is not verified" in reason
        assert "working set" in reason
    assert {item["fileName"] for item in manifest["artifacts"]} >= {
        "ConfigFiles.zip",
        "YT.zip",
        "F.zip",
        "F-2.zip",
        "Forus-1.zip",
        "maxma.zip",
        "YT-1.zip",
        "YT-2.zip",
    }


def test_extension_passport_draft_is_schema_valid() -> None:
    passport = json.loads(
        (RESEARCH / "extension-passport.draft.sanitized.json").read_text(encoding="utf-8")
    )
    assert not list(_schema("extension-passport.schema.json").iter_errors(passport))
    assert passport["intakeId"] == INTAKE_ID
    assert {item["disposition"] for item in passport["extensions"]} == {"UNDECIDED"}
    assert all(item["status"] == "UNVERIFIED" for item in passport["extensions"])
    assert all(item["active"] is True for item in passport["extensions"])
    names = {item["name"] for item in passport["extensions"]}
    assert "ПомощникЗакупок" not in names
    for item in passport["extensions"]:
        notes = item["notes"]
        assert "work with the six transferred XMLs" in notes
        assert "IB enabled-list completeness not confirmed" in notes
        assert "KEEP" not in notes
        assert "RETIRE" not in notes


def test_customer_1_1_answers_are_recorded_without_opening_g1() -> None:
    plan = (RESEARCH / "ACTION_PLAN.md").read_text(encoding="utf-8")
    intake = (RESEARCH / "dump-intake-YANDEX-2026-08-27.md").read_text(encoding="utf-8")
    assert "ответы получены" in plan.lower()
    assert "**да**" in plan
    assert "**это будем позже**" in plan
    assert "**пока какие есть**" in plan
    assert "dumpLagWeeks" in plan
    assert "**не** включать" in plan
    assert "G1 **не открывается**" in plan
    assert "G1 **не** открывается" in intake
    assert "`dumpLagWeeks` **не** включать" in intake
    assert "центральная рабочая Розница" in intake
    assert "центральная УТ **пилота**" in intake
    assert "не закрыт" in intake
    assert "ПомощникЗакупок" in intake
    assert "отсутствующим в ИБ" in intake


def test_compact_indexes_match_configuration_xml_facts() -> None:
    retail = json.loads((RESEARCH / "retail-config-index.json").read_text(encoding="utf-8"))
    ut_new = json.loads((RESEARCH / "ut-config-index.json").read_text(encoding="utf-8"))
    assert retail["intakeId"] == INTAKE_ID
    assert ut_new["intakeId"] == INTAKE_ID
    assert retail["configuration"]["name"] == "Розница"
    assert retail["configuration"]["version"] == "3.0.13.342"
    assert retail["mdmHints"]["hasCatalogMagaziny"] is False
    assert retail["mdmHints"]["hasCatalogStrukturnyeEdinicy"] is True
    assert retail["mdmHints"]["storeObjectHypothesis"] == "СтруктурныеЕдиницы"
    catalog_names = {item["name"] for item in retail["objects"]["Catalog"]}
    assert "СтруктурныеЕдиницы" in catalog_names
    assert "Магазины" not in catalog_names
    assert "снэксРегионы" in catalog_names
    assert ut_new["configuration"]["name"] == "УправлениеТорговлей"
    assert ut_new["configuration"]["version"] == "11.5.22.164"
    ut_plans = {item["name"] for item in ut_new["objects"]["ExchangePlan"]}
    assert "ОбменУправлениеТорговлейРозница" in ut_plans
    for payload in (retail, ut_new):
        blob = json.dumps(payload)
        assert "Procedure " not in blob
        assert "Процедура " not in blob


def test_share_inventory_has_ninety_one_files_and_redacts_account() -> None:
    inventory = json.loads((RESEARCH / "share-inventory.json").read_text(encoding="utf-8"))
    assert inventory["fileCount"] == 91
    assert inventory["publicUrl"] == "https://disk.yandex.ru/d/dfKzWDC27vtTFg"
    blob = json.dumps(inventory)
    assert "407028" not in blob
    assert "snax.ru" not in blob
    assert "Connect=" not in blob


def test_yandex_payload_is_not_in_git_tree() -> None:
    listed = subprocess.check_output(["git", "-C", str(ROOT), "ls-files"], text=True)
    lowered = listed.lower()
    for needle in (
        "configfiles.zip",
        "yt.zip",
        "roznitsaxml.zip",
        "parentconfigurations",
    ):
        assert needle not in lowered
    for line in listed.splitlines():
        assert not line.endswith(".dt")
        assert not line.endswith(".cf")
        assert not line.endswith(".cfe")
        assert not line.endswith(".v8i")
        assert not line.endswith(".webm")
