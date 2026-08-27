from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
INDEX = ROOT / "docs" / "research" / "2026-08-26" / "retail-catalogs-index.json"
MCP_CONFIG = ROOT / ".cursor" / "mcp.json"
MCP_SERVER = SCRIPTS / "retail_xml_mcp.py"

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses"
 xmlns:v8="http://v8.1c.ru/8.1/data/core" version="2.21">
  <Catalog uuid="11111111-2222-4333-8444-555555555555">
    <Properties>
      <Name>СтруктурныеЕдиницы</Name>
      <Synonym>
        <v8:item>
          <v8:lang>ru</v8:lang>
          <v8:content>Структурные единицы</v8:content>
        </v8:item>
      </Synonym>
      <Hierarchical>true</Hierarchical>
      <CodeLength>9</CodeLength>
      <DescriptionLength>50</DescriptionLength>
    </Properties>
    <ChildObjects>
      <Attribute>
        <Properties>
          <Name>снэксРегион</Name>
          <Synonym>
            <v8:item>
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
    import index_retail_xml_dump as lib

    return lib


def test_parse_catalog_marks_forus_attribute() -> None:
    lib = _load_lib()
    record = lib.parse_catalog_xml(SAMPLE.encode("utf-8"))
    assert record["name"] == "СтруктурныеЕдиницы"
    assert record["hierarchical"] is True
    assert record["forus"] is True
    assert record["attributes"][0]["name"] == "снэксРегион"


def test_search_index_finds_by_synonym() -> None:
    lib = _load_lib()
    record = lib.parse_catalog_xml(SAMPLE.encode("utf-8"))
    index = {"catalogs": [record]}
    hits = lib.search_index(index, "форус")
    assert hits[0]["name"] == "СтруктурныеЕдиницы"


def test_committed_retail_index_covers_dump_baseline() -> None:
    payload = json.loads(INDEX.read_text(encoding="utf-8"))
    assert payload["intakeId"] == "8f3c2a91-6d4e-4b7a-9c12-0e5d8f1a2b33"
    assert payload["catalogCount"] == 735
    assert payload["sourceArtifactSha256"] == (
        "8304f8976638243c3629825b3ab1453f474384cdb8774ae7b76f11fa6c38a4b4"
    )
    names = {item["name"] for item in payload["catalogs"]}
    assert "СтруктурныеЕдиницы" in names
    assert "снэксРегионы" in names
    assert "Магазины" not in names
    structural = next(item for item in payload["catalogs"] if item["name"] == "СтруктурныеЕдиницы")
    attr_names = {item["name"] for item in structural["attributes"]}
    assert "снэксРегион" in attr_names
    assert "снэксЗакупочнаяЦена" in attr_names
    joined = json.dumps(payload)
    assert "Procedure " not in joined
    assert "Процедура " not in joined
    for catalog in payload["catalogs"]:
        for module in catalog.get("modules", []):
            assert "procedures" not in module
            assert "procedureCount" in module
    # 735 catalogs with attribute metadata; bodies of BSL are not committed.
    assert INDEX.stat().st_size < 2_500_000


def test_public_index_strips_procedure_names() -> None:
    lib = _load_lib()
    published = lib.public_index(
        {
            "catalogs": [
                {
                    "name": "Demo",
                    "modules": [
                        {
                            "role": "ObjectModule",
                            "path": "Demo/Ext/ObjectModule.bsl",
                            "procedures": ["ПередЗаписью"],
                            "procedureCount": 1,
                        }
                    ],
                }
            ]
        }
    )
    assert "procedures" not in published["catalogs"][0]["modules"][0]
    assert published["catalogs"][0]["modules"][0]["procedureCount"] == 1


def test_write_sqlite_roundtrip(tmp_path: Path) -> None:
    lib = _load_lib()
    record = lib.parse_catalog_xml(SAMPLE.encode("utf-8"))
    index = {
        "catalogs": [record],
        "sourceArtifactSha256": "abc",
    }
    sqlite_path = tmp_path / "retail-catalogs.sqlite"
    lib.write_sqlite(index, sqlite_path, tmp_path / "RoznitsaXML.zip")
    connection = sqlite3.connect(sqlite_path)
    try:
        row = connection.execute(
            "SELECT name FROM catalogs_fts WHERE catalogs_fts MATCH ?",
            ('"снэксРегион"',),
        ).fetchone()
        assert row[0] == "СтруктурныеЕдиницы"
    finally:
        connection.close()


def _load_mcp():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import retail_xml_mcp as mcp

    return mcp


def test_mcp_project_config_points_at_server() -> None:
    payload = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    server = payload["mcpServers"]["snax-retail-xml"]
    assert server["command"] == "python3"
    assert server["args"][0].endswith("scripts/retail_xml_mcp.py")
    assert MCP_SERVER.is_file()


def test_mcp_tools_search_and_get_catalog() -> None:
    mcp = _load_mcp()
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    listed = mcp.dispatch(index, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == {"search_retail_catalogs", "get_retail_catalog", "retail_dump_stats"}
    found = mcp.dispatch(
        index,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search_retail_catalogs",
                "arguments": {"query": "форус", "limit": 10},
            },
        },
    )
    hits = json.loads(found["result"]["content"][0]["text"])
    assert {item["name"] for item in hits} >= {
        "СтруктурныеЕдиницы",
        "снэксРегионы",
    }
    stats = mcp.dispatch(
        index,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "retail_dump_stats"},
        },
    )
    payload = json.loads(stats["result"]["content"][0]["text"])
    assert payload["catalogCount"] == 735
    assert payload["forusCatalogs"] == 5


def test_mcp_stdio_initialize() -> None:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        ensure_ascii=False,
    ).encode("utf-8")
    message = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
    completed = subprocess.run(
        [sys.executable, str(MCP_SERVER), str(INDEX)],
        input=message,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    stdout = completed.stdout
    header, _, rest = stdout.partition(b"\r\n\r\n")
    assert b"Content-Length:" in header
    length = int(header.split(b":", 1)[1].strip())
    payload = json.loads(rest[:length].decode("utf-8"))
    assert payload["result"]["serverInfo"]["name"] == "snax-retail-xml"
