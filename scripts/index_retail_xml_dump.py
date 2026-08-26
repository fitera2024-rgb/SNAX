"""Индекс XML-выгрузки справочников 1С:Розница и локальный MCP для поиска метаданных."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZIP = ROOT / ".local" / "dumps" / "incoming" / "RoznitsaXML.zip"
DEFAULT_JSON = ROOT / "docs" / "research" / "2026-08-26" / "retail-catalogs-index.json"
DEFAULT_SQLITE = ROOT / ".local" / "dumps" / "index" / "retail-catalogs.sqlite"
INTAKE_ID = "8f3c2a91-6d4e-4b7a-9c12-0e5d8f1a2b33"
EXPECTED_SHA256 = "8304f8976638243c3629825b3ab1453f474384cdb8774ae7b76f11fa6c38a4b4"

BSL_PROC = re.compile(
    r"(?im)^\s*(?:procedure|function|процедура|функция)\s+([A-Za-zА-Яа-я_][A-Za-zА-Яа-я0-9_]*)"
)


def local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def ru_text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    contents: list[str] = []
    for child in element.iter():
        if local_tag(child.tag) == "content" and (child.text or "").strip():
            contents.append(child.text.strip())
    if contents:
        return contents[0]
    text = (element.text or "").strip()
    return text or None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def module_role(relpath: str) -> str:
    name = Path(relpath).name
    parent = Path(relpath).parent.name
    if name.endswith("Module.bsl") and parent == "Form":
        return "FormModule"
    return Path(name).stem


def extract_procedures(source: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for match in BSL_PROC.finditer(source):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def parse_catalog_xml(raw: bytes) -> dict[str, object]:
    root = ET.fromstring(raw)
    catalog = next(child for child in root if local_tag(child.tag) == "Catalog")
    record: dict[str, object] = {
        "name": "",
        "uuid": catalog.attrib.get("uuid", ""),
        "synonym": None,
        "hierarchical": False,
        "codeLength": None,
        "descriptionLength": None,
        "attributes": [],
        "tabularSections": [],
        "forms": [],
        "templates": [],
        "modules": [],
        "forus": False,
    }
    attributes: list[dict[str, str | None]] = []
    tabular: list[dict[str, str | None]] = []
    forms: list[str] = []
    templates: list[str] = []
    for child in catalog:
        kind = local_tag(child.tag)
        if kind == "Properties":
            for prop in child:
                name = local_tag(prop.tag)
                if name == "Name":
                    record["name"] = (prop.text or "").strip()
                elif name == "Synonym":
                    record["synonym"] = ru_text(prop)
                elif name == "Hierarchical":
                    record["hierarchical"] = (prop.text or "").strip().lower() == "true"
                elif name == "CodeLength":
                    try:
                        record["codeLength"] = int((prop.text or "").strip())
                    except ValueError:
                        record["codeLength"] = None
                elif name == "DescriptionLength":
                    try:
                        record["descriptionLength"] = int((prop.text or "").strip())
                    except ValueError:
                        record["descriptionLength"] = None
        elif kind == "ChildObjects":
            for obj in child:
                obj_kind = local_tag(obj.tag)
                props = next(
                    (item for item in obj if local_tag(item.tag) == "Properties"),
                    None,
                )
                obj_name = None
                obj_synonym = None
                if props is not None:
                    for prop in props:
                        if local_tag(prop.tag) == "Name":
                            obj_name = (prop.text or "").strip()
                        elif local_tag(prop.tag) == "Synonym":
                            obj_synonym = ru_text(prop)
                if obj_kind == "Attribute" and obj_name:
                    attributes.append({"name": obj_name, "synonym": obj_synonym})
                elif obj_kind == "TabularSection" and obj_name:
                    tabular.append({"name": obj_name, "synonym": obj_synonym})
                elif obj_kind == "Form":
                    form_name = obj_name or (obj.text or "").strip()
                    if form_name:
                        forms.append(form_name)
                elif obj_kind == "Template" and obj_name:
                    templates.append(obj_name)
    record["attributes"] = attributes
    record["tabularSections"] = tabular
    record["forms"] = forms
    record["templates"] = templates
    blob = json.dumps(record, ensure_ascii=False)
    record["forus"] = "снэкс" in blob.lower() or "форус" in blob.lower()
    return record


def index_zip(zip_path: Path) -> dict[str, object]:
    digest = sha256_file(zip_path)
    catalogs: dict[str, dict[str, object]] = {}
    modules_local: list[tuple[str, str, str]] = []
    with zipfile.ZipFile(zip_path) as archive:
        names = [name.replace("\\", "/") for name in archive.namelist() if not name.endswith("/")]
        for name in names:
            parts = name.split("/")
            if len(parts) == 3 and parts[1] == "Catalogs" and parts[2].endswith(".xml"):
                catalog_name = Path(parts[2]).stem
                catalogs[catalog_name] = parse_catalog_xml(archive.read(name))
            elif name.endswith(".bsl") and "/Catalogs/" in name:
                source = archive.read(name).decode("utf-8", errors="replace")
                catalog_name = parts[2] if len(parts) > 2 else ""
                modules_local.append((catalog_name, name, source))
    for catalog_name, relpath, source in modules_local:
        record = catalogs.get(catalog_name)
        if record is None:
            continue
        modules = record.setdefault("modules", [])
        assert isinstance(modules, list)
        procedures = extract_procedures(source)
        modules.append(
            {
                "role": module_role(relpath),
                "path": "/".join(relpath.split("/")[2:]),
                "procedures": procedures,
                "procedureCount": len(procedures),
            }
        )
        if "снэкс" in source.lower() or "форус" in source.lower():
            record["forus"] = True
    ordered = [catalogs[key] for key in sorted(catalogs)]
    return {
        "schemaVersion": "1.0.0",
        "intakeId": INTAKE_ID,
        "generatedAt": datetime.now(tz=UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "sourceArtifactSha256": digest,
        "objectKind": "Catalog",
        "incompleteDump": True,
        "missing": [
            "Configuration.xml",
            "ConfigDumpInfo.xml",
            "Documents",
            "ExchangePlans",
            "InformationRegisters",
            "CFE",
        ],
        "catalogCount": len(ordered),
        "catalogs": ordered,
    }


def write_sqlite(index: dict[str, object], sqlite_path: Path, zip_path: Path) -> None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    if sqlite_path.exists():
        sqlite_path.unlink()
    connection = sqlite3.connect(sqlite_path)
    try:
        connection.execute(
            """
            CREATE TABLE catalogs (
                name TEXT PRIMARY KEY,
                uuid TEXT,
                synonym TEXT,
                hierarchical INTEGER,
                forus INTEGER,
                json TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE VIRTUAL TABLE catalogs_fts USING fts5(
                name,
                synonym,
                attributes,
                procedures
            )
            """
        )
        for catalog in index["catalogs"]:
            assert isinstance(catalog, dict)
            attributes = " ".join(
                item.get("name") or ""
                for item in catalog.get("attributes", [])  # type: ignore[union-attr]
            )
            procedures = " ".join(
                proc
                for module in catalog.get("modules", [])  # type: ignore[union-attr]
                for proc in module.get("procedures", [])
            )
            synonym = catalog.get("synonym") or ""
            connection.execute(
                "INSERT INTO catalogs"
                "(name, uuid, synonym, hierarchical, forus, json) VALUES (?,?,?,?,?,?)",
                (
                    catalog["name"],
                    catalog["uuid"],
                    synonym,
                    1 if catalog.get("hierarchical") else 0,
                    1 if catalog.get("forus") else 0,
                    json.dumps(catalog, ensure_ascii=False),
                ),
            )
            connection.execute(
                "INSERT INTO catalogs_fts(name, synonym, attributes, procedures) VALUES (?,?,?,?)",
                (catalog["name"], synonym, attributes, procedures),
            )
        connection.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
        connection.execute(
            "INSERT INTO meta VALUES ('sourceSha256', ?), ('zipPath', ?)",
            (index["sourceArtifactSha256"], str(zip_path)),
        )
        connection.commit()
    finally:
        connection.close()


def search_index(index: dict[str, object], query: str, limit: int = 20) -> list[dict[str, object]]:
    needle = query.casefold().strip()
    if not needle:
        return []
    hits: list[dict[str, object]] = []
    for catalog in index["catalogs"]:
        assert isinstance(catalog, dict)
        hay = json.dumps(catalog, ensure_ascii=False).casefold()
        if needle not in hay:
            continue
        hits.append(
            {
                "name": catalog["name"],
                "synonym": catalog.get("synonym"),
                "uuid": catalog.get("uuid"),
                "forus": catalog.get("forus"),
                "attributeCount": len(catalog.get("attributes", [])),  # type: ignore[arg-type]
            }
        )
        if len(hits) >= limit:
            break
    return hits


def load_index(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def public_index(index: dict[str, object]) -> dict[str, object]:
    clone = json.loads(json.dumps(index))
    for catalog in clone["catalogs"]:
        for module in catalog.get("modules", []):
            module.pop("procedures", None)
    return clone


def build_command(args: argparse.Namespace) -> None:
    zip_path: Path = args.zip
    if not zip_path.is_file():
        raise SystemExit(f"dump zip not found: {zip_path}")
    digest = sha256_file(zip_path)
    if digest != EXPECTED_SHA256:
        print(f"warning: sha256 {digest} != intake {EXPECTED_SHA256}", file=sys.stderr)
    index = index_zip(zip_path)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    published = public_index(index)
    args.json_out.write_text(
        json.dumps(published, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.sqlite_out:
        write_sqlite(index, args.sqlite_out, zip_path)
    print(
        f"indexed {index['catalogCount']} catalogs -> {args.json_out}"
        + (f" and {args.sqlite_out}" if args.sqlite_out else "")
    )


def search_command(args: argparse.Namespace) -> None:
    index = load_index(args.json_in)
    hits = search_index(index, args.query, limit=args.limit)
    print(json.dumps(hits, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Индекс XML справочников Розницы")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Построить индекс из zip")
    build.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    build.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    build.add_argument("--sqlite-out", type=Path, default=DEFAULT_SQLITE)
    build.add_argument("--no-sqlite", action="store_true")
    search = sub.add_parser("search", help="Поиск по опубликованному JSON-индексу")
    search.add_argument("query")
    search.add_argument("--json-in", type=Path, default=DEFAULT_JSON)
    search.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if args.command == "build":
        if args.no_sqlite:
            args.sqlite_out = None
        build_command(args)
    else:
        search_command(args)


if __name__ == "__main__":
    main()
