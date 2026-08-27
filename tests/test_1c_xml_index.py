from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
MCP_CONFIG = ROOT / ".cursor" / "mcp.json"
MCP_SERVER = SCRIPTS / "snax_1c_mcp.py"

CONFIGURATION_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.21">
  <Configuration uuid="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee">
    <Properties>
      <Name>ДемоКонфигурация</Name>
      <Synonym>
        <v8:item xmlns:v8="http://v8.1c.ru/8.1/data/core">
          <v8:lang>ru</v8:lang>
          <v8:content>Демо</v8:content>
        </v8:item>
      </Synonym>
      <Vendor>НПК ФОРУС</Vendor>
      <Version>1.0.0</Version>
    </Properties>
    <ChildObjects>
      <Catalog>СтруктурныеЕдиницы</Catalog>
      <Document>ЗаказПоставщику</Document>
    </ChildObjects>
  </Configuration>
</MetaDataObject>
"""

CATALOG_XML = """<?xml version="1.0" encoding="UTF-8"?>
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
    <ChildObjects>
      <Attribute>
        <Properties>
          <Name>снэксРегион</Name>
          <Synonym>
            <v8:item xmlns:v8="http://v8.1c.ru/8.1/data/core">
              <v8:lang>ru</v8:lang>
              <v8:content>[ФОРУС] Регион</v8:content>
            </v8:item>
          </Synonym>
        </Properties>
      </Attribute>
    </ChildObjects>
  </Catalog>
</MetaDataObject>
"""


def _load_lib():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import index_1c_xml_dump as lib

    return lib


def _load_mcp():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import snax_1c_mcp as mcp

    return mcp


DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.21">
  <Document uuid="99999999-2222-4333-8444-555555555555">
    <Properties>
      <Name>ЗаказПоставщику</Name>
    </Properties>
  </Document>
</MetaDataObject>
"""


def _write_demo_zip(path: Path, *, latin_bsl: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Configuration.xml", CONFIGURATION_XML)
        archive.writestr("Catalogs/СтруктурныеЕдиницы.xml", CATALOG_XML)
        archive.writestr("Catalogs/СтруктурныеЕдиницы/Ext/ObjectModule.bsl", latin_bsl)
        archive.writestr("Documents/ЗаказПоставщику.xml", DOCUMENT_XML)
        archive.writestr("Documents/ЗаказПоставщику/Ext/ObjectModule.bsl", latin_bsl)


def test_latin_forus_in_bsl_does_not_mark_object(tmp_path: Path) -> None:
    lib = _load_lib()
    zip_path = tmp_path / "demo.zip"
    _write_demo_zip(
        zip_path,
        latin_bsl="Процедура ДокументооборотForus()\nКонецПроцедуры\n",
    )
    index = lib.index_zip(zip_path, "DEMO", "RETAIL_CENTRAL")
    catalog = next(item for item in index["objects"] if item["name"] == "СтруктурныеЕдиницы")
    order = next(item for item in index["objects"] if item["name"] == "ЗаказПоставщику")
    assert catalog["forus"] is True
    assert order["forus"] is False
    assert index["forusDump"] is True
    published = lib.public_index(index)
    catalog_pub = next(
        item for item in published["objects"] if item["name"] == "СтруктурныеЕдиницы"
    )
    module = catalog_pub["modules"][0]
    assert "procedures" not in module
    assert module["procedureCount"] == 1


def test_search_includes_configuration_name() -> None:
    lib = _load_lib()
    index = {
        "dumpId": "RETAIL_EXT_FORUS1",
        "forusDump": True,
        "configuration": {
            "Name": "Форус_ОснованиеТоварнойНакладнойВозврат",
            "Synonym": "Форус основание",
        },
        "objects": [
            {
                "kind": "DataProcessor",
                "name": "ПечатьТОРГ12",
                "synonym": None,
                "forus": False,
                "attributes": [],
            }
        ],
    }
    hits = lib.search_objects(index, "форус")
    assert hits[0]["kind"] == "Configuration"
    assert hits[0]["name"] == "Форус_ОснованиеТоварнойНакладнойВозврат"


def test_mcp_project_config_has_snax_1c() -> None:
    payload = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    server = payload["mcpServers"]["snax-1c"]
    assert server["command"] == "python3"
    assert server["args"][0].endswith("scripts/snax_1c_mcp.py")
    assert MCP_SERVER.is_file()
    retail = payload["mcpServers"]["snax-retail-xml"]
    assert retail["args"][0].endswith("scripts/retail_xml_mcp.py")


def test_mcp_loads_compact_and_extension_indexes() -> None:
    mcp = _load_mcp()
    indexes = mcp.load_all_indexes()
    dump_ids = {item.get("dumpId") for item in indexes}
    assert "RETAIL_CONFIG" in dump_ids
    assert "UT_NEW_CONFIG" in dump_ids
    assert "RETAIL_EXT_F2_SNEX_REGIONS" in dump_ids
    listed = mcp.dispatch(indexes, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert "search_1c_metadata" in names
    assert "list_1c_dumps" in names
    found = mcp.dispatch(
        indexes,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search_1c_metadata",
                "arguments": {"query": "СтруктурныеЕдиницы", "kind": "Catalog", "limit": 20},
            },
        },
    )
    hits = json.loads(found["result"]["content"][0]["text"])
    assert any(item["name"] == "СтруктурныеЕдиницы" for item in hits)


def test_mcp_stdio_initialize_with_empty_dir(tmp_path: Path) -> None:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        ensure_ascii=False,
    ).encode("utf-8")
    message = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
    completed = subprocess.run(
        [sys.executable, str(MCP_SERVER), str(tmp_path)],
        input=message,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    header, _, rest = completed.stdout.partition(b"\r\n\r\n")
    length = int(header.split(b":", 1)[1].strip())
    payload = json.loads(rest[:length].decode("utf-8"))
    assert payload["result"]["serverInfo"]["name"] == "snax-1c"
