"""MCP: поиск по проиндексированным XML-конфигурациям и расширениям 1С."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from index_1c_xml_dump import load_index, search_objects  # noqa: E402

PROTOCOL = "2024-11-05"
INDEX_DIRS = [
    ROOT / "docs" / "research" / "2026-08-27" / "indexes",
    ROOT / "docs" / "research" / "2026-08-27",
    ROOT / "docs" / "research" / "2026-08-26",
]
SKIP_INDEX_NAMES = {
    "config-dump-manifest.retail-xml.sanitized.json",
    "config-dump-manifest.yandex-share.sanitized.json",
    "retail-catalogs-forus-delta.json",
    "share-inventory.json",
    "extension-index.json",
    "extension-passport.draft.sanitized.json",
}
COMPACT_DUMP_IDS = {
    "retail-config-index.json": ("RETAIL_CONFIG", "RETAIL_CENTRAL"),
    "ut-config-index.json": ("UT_NEW_CONFIG", "UT_CENTRAL"),
}


def resolve_index_dirs(argv: list[str] | None = None) -> list[Path]:
    argv = list(sys.argv if argv is None else argv)
    script = Path(__file__).resolve()
    if argv and Path(argv[0]).resolve() == script and len(argv) > 1:
        return [Path(argument) for argument in argv[1:]]
    return list(INDEX_DIRS)


def load_all_indexes(folders: list[Path] | None = None) -> list[dict[str, Any]]:
    indexes: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for folder in folders or resolve_index_dirs():
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            if path in seen or "manifest" in path.name or "forus-delta" in path.name:
                continue
            if path.name in SKIP_INDEX_NAMES:
                continue
            seen.add(path)
            payload = normalize_index_payload(load_index(path), path)
            if payload.get("objects"):
                indexes.append(payload)
    return indexes


def _as_object_record(kind: str, record: dict[str, Any], *, forus: bool = False) -> dict[str, Any]:
    return {
        "kind": kind,
        "folder": kind,
        "name": record.get("name"),
        "uuid": record.get("uuid"),
        "synonym": record.get("synonym"),
        "forus": bool(record.get("forus") or forus),
        "attributes": record.get("attributes") or [],
        "tabularSections": record.get("tabularSections") or [],
        "modules": record.get("modules") or [],
    }


def normalize_index_payload(payload: dict[str, Any], path: Path) -> dict[str, Any]:
    if "objects" not in payload and "catalogs" in payload:
        catalogs = [_as_object_record("Catalog", item) for item in payload["catalogs"]]
        return {
            "dumpId": (
                payload.get("dumpId") or payload.get("intakeId") or "RETAIL_CATALOGS_2026_08_26"
            ),
            "contour": payload.get("contour") or "RETAIL_CENTRAL",
            "configuration": payload.get("configuration") or {},
            "objectCount": payload.get("catalogCount") or len(catalogs),
            "kindCounts": {"Catalog": payload.get("catalogCount") or len(catalogs)},
            "forusObjectCount": sum(1 for item in catalogs if item.get("forus")),
            "sourceArtifactSha256": payload.get("sourceArtifactSha256"),
            "sourceFile": payload.get("sourceFile") or payload.get("sourceFileName"),
            "objects": catalogs,
        }
    objects = payload.get("objects")
    if isinstance(objects, dict):
        dump_id, contour = COMPACT_DUMP_IDS.get(path.name, (path.stem, payload.get("contour")))
        forus_keys = {
            (str(item.get("kind")), str(item.get("name")))
            for item in payload.get("forusNamedObjects") or []
        }
        flat: list[dict[str, Any]] = []
        seen_names: set[tuple[str, str]] = set()
        for kind, records in objects.items():
            for record in records:
                name = str(record.get("name") or "")
                seen_names.add((kind, name))
                flat.append(_as_object_record(kind, record, forus=(kind, name) in forus_keys))
        for kind, names in (payload.get("objectNames") or {}).items():
            for name in names:
                key = (kind, str(name))
                if key in seen_names:
                    continue
                seen_names.add(key)
                flat.append(_as_object_record(kind, {"name": name}, forus=key in forus_keys))
        configuration = payload.get("configuration") or {}
        if "Name" not in configuration and "name" in configuration:
            configuration = {
                "Name": configuration.get("name"),
                "Synonym": configuration.get("synonym"),
                "Version": configuration.get("version"),
                "Vendor": configuration.get("vendor"),
                "CompatibilityMode": configuration.get("compatibilityMode"),
                "NamePrefix": configuration.get("namePrefix"),
            }
        counts: dict[str, int] = {}
        for item in flat:
            kind = str(item.get("kind") or "Unknown")
            counts[kind] = counts.get(kind, 0) + 1
        payload = {
            **payload,
            "dumpId": payload.get("dumpId") or dump_id,
            "contour": payload.get("contour") or contour,
            "configuration": configuration,
            "sourceFile": payload.get("sourceFile") or payload.get("sourceFileName"),
            "objectCount": payload.get("objectCount") or len(flat),
            "kindCounts": payload.get("kindCounts") or counts,
            "forusObjectCount": sum(1 for item in flat if item.get("forus")),
            "objects": flat,
        }
    return payload


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
            "name": "search_1c_metadata",
            "description": "Search indexed 1C metadata (configs and extensions).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "kind": {"type": "string"},
                    "dumpId": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["query"],
            },
        },
        {
            "name": "get_1c_object",
            "description": "Return one metadata object by dumpId and name.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "dumpId": {"type": "string"},
                    "kind": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        {
            "name": "list_1c_dumps",
            "description": "List indexed 1C dumps and extensions with object counts.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "search_retail_catalogs",
            "description": "Backward-compatible search of Retail catalog metadata.",
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
            "description": "Backward-compatible get of one Retail catalog.",
            "inputSchema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
        {
            "name": "retail_dump_stats",
            "description": "Backward-compatible stats for the Retail catalog dump.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]


def call_tool(indexes: list[dict[str, Any]], name: str, arguments: dict[str, Any]) -> str:
    if name in {"search_1c_metadata", "search_retail_catalogs"}:
        query = str(arguments.get("query", ""))
        kind = arguments.get("kind")
        dump_id = arguments.get("dumpId")
        limit = int(arguments.get("limit", 20))
        hits: list[dict[str, Any]] = []
        for index in indexes:
            if dump_id and str(index.get("dumpId")) != str(dump_id):
                continue
            if name == "search_retail_catalogs":
                kind = "Catalog"
            hits.extend(search_objects(index, query, limit=limit, kind=kind))
            if len(hits) >= limit:
                hits = hits[:limit]
                break
        return json.dumps(hits, ensure_ascii=False, indent=2)
    if name in {"get_1c_object", "get_retail_catalog"}:
        wanted = str(arguments.get("name", "")).casefold()
        dump_id = arguments.get("dumpId")
        kind = arguments.get("kind")
        for index in indexes:
            if dump_id and str(index.get("dumpId")) != str(dump_id):
                continue
            for item in index.get("objects", []):
                if str(item.get("name", "")).casefold() != wanted:
                    continue
                if kind and str(item.get("kind", "")).casefold() != str(kind).casefold():
                    continue
                payload = dict(item)
                payload["dumpId"] = index.get("dumpId")
                return json.dumps(payload, ensure_ascii=False, indent=2)
        return json.dumps({"error": "not_found", "name": arguments.get("name")}, ensure_ascii=False)
    if name in {"list_1c_dumps", "retail_dump_stats"}:
        rows = []
        for index in indexes:
            rows.append(
                {
                    "dumpId": index.get("dumpId"),
                    "contour": index.get("contour"),
                    "configuration": index.get("configuration"),
                    "objectCount": index.get("objectCount"),
                    "kindCounts": index.get("kindCounts"),
                    "forusObjectCount": index.get("forusObjectCount"),
                    "sourceArtifactSha256": index.get("sourceArtifactSha256"),
                    "sourceFile": index.get("sourceFile"),
                }
            )
        if name == "retail_dump_stats":
            rows = [row for row in rows if "RETAIL" in str(row.get("dumpId") or "").upper()]
        return json.dumps(rows, ensure_ascii=False, indent=2)
    return json.dumps({"error": "unknown_tool", "name": name})


def dispatch(indexes: list[dict[str, Any]], message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "snax-1c", "version": "1.0.0"},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result(request_id, {"tools": _tools()})
    if method == "tools/call":
        params = message.get("params") or {}
        text = call_tool(indexes, params.get("name", ""), params.get("arguments") or {})
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


def main() -> None:
    indexes = load_all_indexes(resolve_index_dirs())
    while True:
        message = _read_message()
        if message is None:
            break
        response = dispatch(indexes, message)
        if response is not None:
            _write_message(response)


if __name__ == "__main__":
    main()
