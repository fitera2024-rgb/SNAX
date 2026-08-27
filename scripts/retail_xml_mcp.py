"""Локальный MCP: поиск по индексу XML справочников Розницы (без payload дампа)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from index_retail_xml_dump import DEFAULT_JSON, load_index, search_index  # noqa: E402

PROTOCOL = "2024-11-05"


def _read_message() -> dict[str, Any] | None:
    header: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        decoded = line.decode("utf-8").strip()
        if ":" in decoded:
            key, value = decoded.split(":", 1)
            header[key.strip().lower()] = value.strip()
    length = int(header.get("content-length", "0"))
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def _write_message(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def _result(request_id: object, result: object) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "search_retail_catalogs",
            "description": (
                "Search indexed 1C Retail catalog metadata from the 2026-08-26 XML dump."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["query"],
            },
        },
        {
            "name": "get_retail_catalog",
            "description": "Return one catalog metadata record by 1C name.",
            "inputSchema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
        {
            "name": "retail_dump_stats",
            "description": "Index statistics for the partial Retail XML dump.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]


def dispatch(index: dict[str, Any], message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "snax-retail-xml", "version": "1.0.0"},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result(request_id, {"tools": _tools()})
    if method == "tools/call":
        params = message.get("params") or {}
        text = call_tool(index, params.get("name", ""), params.get("arguments") or {})
        return _result(request_id, {"content": [{"type": "text", "text": text}]})
    if method == "ping":
        return _result(request_id, {})
    if request_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Unknown method {method}"},
        }
    return None


def call_tool(index: dict[str, Any], name: str, arguments: dict[str, Any]) -> str:
    if name == "search_retail_catalogs":
        hits = search_index(index, str(arguments.get("query", "")), int(arguments.get("limit", 20)))
        return json.dumps(hits, ensure_ascii=False, indent=2)
    if name == "get_retail_catalog":
        wanted = str(arguments.get("name", "")).casefold()
        for catalog in index.get("catalogs", []):
            if str(catalog.get("name", "")).casefold() == wanted:
                return json.dumps(catalog, ensure_ascii=False, indent=2)
        return json.dumps({"error": "not_found", "name": arguments.get("name")}, ensure_ascii=False)
    if name == "retail_dump_stats":
        catalogs = index.get("catalogs", [])
        forus = sum(1 for item in catalogs if item.get("forus"))
        return json.dumps(
            {
                "catalogCount": index.get("catalogCount"),
                "forusCatalogs": forus,
                "incompleteDump": index.get("incompleteDump"),
                "missing": index.get("missing"),
                "sourceArtifactSha256": index.get("sourceArtifactSha256"),
            },
            ensure_ascii=False,
            indent=2,
        )
    return json.dumps({"error": "unknown_tool", "name": name})


def main() -> None:
    index_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_JSON
    index = load_index(index_path)
    while True:
        message = _read_message()
        if message is None:
            break
        response = dispatch(index, message)
        if response is not None:
            _write_message(response)


if __name__ == "__main__":
    main()
