from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
RESEARCH = ROOT / "docs" / "research"
INDEX_2026 = RESEARCH / "2026-08-26" / "retail-catalogs-index.json"
INDEX_2027_RETAIL = RESEARCH / "2026-08-27" / "retail-config-index.json"
INDEX_2027_UT = RESEARCH / "2026-08-27" / "ut-config-index.json"
MCP_CONFIG = ROOT / ".cursor" / "mcp.json"

SAMPLE_CONFIGURATION = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.21">
  <Configuration uuid="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee">
    <Properties>
      <Name>Розница</Name>
      <Synonym>
        <v8:item xmlns:v8="http://v8.1c.ru/8.1/data/core">
          <v8:lang>ru</v8:lang>
          <v8:content>Розница, редакция 3.0</v8:content>
        </v8:item>
      </Synonym>
      <Vendor>Фирма "1С"</Vendor>
      <Version>3.0.13.342</Version>
      <CompatibilityMode>Version8_5_1</CompatibilityMode>
    </Properties>
    <ChildObjects>
      <Catalog>СтруктурныеЕдиницы</Catalog>
      <Document>ПриходнаяНакладная</Document>
      <ExchangePlan>СинхронизацияДанныхЧерезУниверсальныйФормат</ExchangePlan>
    </ChildObjects>
  </Configuration>
</MetaDataObject>
"""

SAMPLE_CATALOG = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.21">
  <Catalog uuid="11111111-2222-4333-8444-555555555555">
    <Properties>
      <Name>СтруктурныеЕдиницы</Name>
      <Synonym>
        <v8:item xmlns:v8="http://v8.1c.ru/8.1/data/core">
          <v8:lang>ru</v8:lang>
          <v8:content>Структурные единицы</v8:content>
        </v8:item>
      </Synonym>
    </Properties>
  </Catalog>
</MetaDataObject>
"""

SAMPLE_BSL = "Процедура ПередЗаписью(Отказ)\nКонецПроцедуры\n"


def _load_config_indexer():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import index_1c_xml_config_dump as lib

    return lib


def test_config_indexer_public_index_omits_bsl_procedure_names(tmp_path: Path) -> None:
    lib = _load_config_indexer()
    zip_path = tmp_path / "ConfigFiles.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("Configuration.xml", SAMPLE_CONFIGURATION)
        archive.writestr("ConfigDumpInfo.xml", "<dump/>")
        archive.writestr("Catalogs/СтруктурныеЕдиницы.xml", SAMPLE_CATALOG)
        archive.writestr("Catalogs/СтруктурныеЕдиницы/Ext/ObjectModule.bsl", SAMPLE_BSL)
    index = lib.public_index(
        lib.index_zip(
            zip_path,
            intake_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            source_file_name="ConfigFiles.zip",
        )
    )
    blob = json.dumps(index, ensure_ascii=False)
    assert "ПередЗаписью" not in blob
    assert "Процедура " not in blob
    assert index["configuration"]["name"] == "Розница"
    assert index["configuration"]["version"] == "3.0.13.342"
    assert index["mdmHints"]["hasCatalogStrukturnyeEdinicy"] is True
    assert index["mdmHints"]["hasCatalogMagaziny"] is False
    assert index["bslModuleCount"] == 1


def test_committed_full_config_indexes_match_intake() -> None:
    retail = json.loads(INDEX_2027_RETAIL.read_text(encoding="utf-8"))
    ut = json.loads(INDEX_2027_UT.read_text(encoding="utf-8"))
    catalogs = json.loads(INDEX_2026.read_text(encoding="utf-8"))
    assert retail["configuration"]["name"] == "Розница"
    assert retail["configuration"]["version"] == "3.0.13.342"
    assert retail["sourceArtifactSha256"] == (
        "8dba2d5703f2041c3b67ee1d22329b919761d9fb3b069272573934e49ef44a76"
    )
    assert ut["configuration"]["name"] == "УправлениеТорговлей"
    assert ut["configuration"]["version"] == "11.5.22.164"
    assert retail["mdmHints"]["storeObjectHypothesis"] == "СтруктурныеЕдиницы"
    assert ut["mdmHints"]["hasCatalogSklady"] is True
    assert ut["mdmHints"]["storeObjectHypothesis"] is None
    retail_catalogs = {item["name"] for item in retail["objects"]["Catalog"]}
    old_catalogs = {item["name"] for item in catalogs["catalogs"]}
    assert retail_catalogs == old_catalogs
    for payload in (retail, ut):
        blob = json.dumps(payload, ensure_ascii=False)
        assert "Procedure " not in blob
        assert "Процедура " not in blob
        assert "Connect=" not in blob


def test_share_inventory_redacts_secrets_and_skips_payload() -> None:
    payload = json.loads(
        (RESEARCH / "2026-08-27" / "share-inventory.json").read_text(encoding="utf-8")
    )
    assert payload["publicUrl"] == "https://disk.yandex.ru/d/dfKzWDC27vtTFg"
    blob = json.dumps(payload, ensure_ascii=False)
    assert "Connect=" not in blob
    assert "Srvr=" not in blob
    assert "40702810950000046129" not in blob
    classes = {item["class"] for item in payload["files"]}
    assert "ONEC_XML_DUMP" in classes
    assert "IBASES_LISTFILE_REDACTED" in classes
    listfile = next(
        item for item in payload["files"] if item["class"] == "IBASES_LISTFILE_REDACTED"
    )
    assert listfile.get("sha256") is None


def test_ibases_note_has_display_names_only() -> None:
    text = (RESEARCH / "2026-08-27" / "ibases-display-names.md").read_text(encoding="utf-8")
    assert "Розница" in text
    assert "УТ" in text
    assert "Connect=" not in text
    assert "Srvr=" not in text
    assert "Pwd=" not in text


def test_mcp_keeps_retail_server_and_adds_1c() -> None:
    payload = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    retail = payload["mcpServers"]["snax-retail-xml"]
    extra = payload["mcpServers"]["snax-1c"]
    assert retail["args"][0].endswith("scripts/retail_xml_mcp.py")
    assert extra["args"][0].endswith("scripts/snax_1c_mcp.py")


def test_extension_indexes_omit_procedure_name_lists() -> None:
    folder = RESEARCH / "2026-08-27" / "indexes"
    files = list(folder.glob("*.json"))
    assert files
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        blob = json.dumps(payload, ensure_ascii=False)
        assert '"procedures"' not in blob
        assert "Процедура " not in blob
        for item in payload.get("objects") or []:
            for module in item.get("modules") or []:
                assert "procedures" not in module
                assert "procedureCount" in module
