"""Индекс XML-выгрузки конфигурации или расширения 1С (без тел BSL в Git)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE = ROOT / ".local" / "dumps" / "index" / "configs.sqlite"
PUBLIC_DIR = ROOT / "docs" / "research" / "2026-08-27" / "indexes"

BSL_PROC = re.compile(
    r"(?im)^\s*(?:procedure|function|процедура|функция)\s+([A-Za-zА-Яа-я_][A-Za-zА-Яа-я0-9_]*)"
)
FORUS_MARK = re.compile(r"(снэкс|форус)", re.IGNORECASE)

META_FOLDERS: dict[str, str] = {
    "Catalogs": "Catalog",
    "Documents": "Document",
    "DocumentJournals": "DocumentJournal",
    "Enums": "Enum",
    "Reports": "Report",
    "DataProcessors": "DataProcessor",
    "ChartsOfCharacteristicTypes": "ChartOfCharacteristicTypes",
    "ChartsOfAccounts": "ChartOfAccounts",
    "ChartsOfCalculationTypes": "ChartOfCalculationTypes",
    "InformationRegisters": "InformationRegister",
    "AccumulationRegisters": "AccumulationRegister",
    "AccountingRegisters": "AccountingRegister",
    "CalculationRegisters": "CalculationRegister",
    "BusinessProcesses": "BusinessProcess",
    "Tasks": "Task",
    "ExchangePlans": "ExchangePlan",
    "FilterCriteria": "FilterCriterion",
    "SettingsStorages": "SettingsStorage",
    "EventSubscriptions": "EventSubscription",
    "ScheduledJobs": "ScheduledJob",
    "FunctionalOptions": "FunctionalOption",
    "FunctionalOptionsParameters": "FunctionalOptionsParameter",
    "DefinedTypes": "DefinedType",
    "CommonModules": "CommonModule",
    "SessionParameters": "SessionParameter",
    "Roles": "Role",
    "CommonTemplates": "CommonTemplate",
    "CommonCommands": "CommonCommand",
    "CommandGroups": "CommandGroup",
    "Constants": "Constant",
    "CommonForms": "CommonForm",
    "CommonPictures": "CommonPicture",
    "XDTOPackages": "XDTOPackage",
    "WebServices": "WebService",
    "WSReferences": "WSReference",
    "StyleItems": "StyleItem",
    "Styles": "Style",
    "Languages": "Language",
    "Subsystems": "Subsystem",
    "HTTPServices": "HTTPService",
    "Bots": "Bot",
    "IntegrationServices": "IntegrationService",
    "ExternalDataSources": "ExternalDataSource",
}


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


def extract_procedures(source: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for match in BSL_PROC.finditer(source):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def configuration_is_forus(configuration: dict[str, str | None]) -> bool:
    blob = json.dumps(configuration, ensure_ascii=False)
    return FORUS_MARK.search(blob) is not None


def parse_configuration_xml(raw: bytes) -> dict[str, str | None]:
    root = ET.fromstring(raw)
    wanted = {
        "Name",
        "Synonym",
        "Comment",
        "Vendor",
        "Version",
        "NamePrefix",
        "ConfigurationExtensionPurpose",
        "CompatibilityMode",
        "DefaultLanguage",
        "ScriptVariant",
        "DefaultRoles",
    }
    props: dict[str, str | None] = {}
    for element in root.iter():
        kind = local_tag(element.tag)
        if kind in wanted and kind not in props:
            if kind == "Synonym":
                props[kind] = ru_text(element)
            else:
                text = ru_text(element) or (element.text or "").strip()
                props[kind] = text or None
    return props


def parse_object_xml(raw: bytes) -> dict[str, object]:
    root = ET.fromstring(raw)
    body = next((child for child in root if local_tag(child.tag) != "InternalInfo"), None)
    if body is None:
        body = root
    record: dict[str, object] = {
        "kind": local_tag(body.tag),
        "name": "",
        "uuid": body.attrib.get("uuid", ""),
        "synonym": None,
        "attributes": [],
        "tabularSections": [],
        "forus": False,
        "modules": [],
    }
    attributes: list[dict[str, str | None]] = []
    tabular: list[dict[str, str | None]] = []
    for child in body:
        kind = local_tag(child.tag)
        if kind == "Properties":
            for prop in child:
                name = local_tag(prop.tag)
                if name == "Name":
                    record["name"] = (prop.text or "").strip()
                elif name == "Synonym":
                    record["synonym"] = ru_text(prop)
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
                elif obj_kind in {"Resource", "Dimension"} and obj_name:
                    attributes.append({"name": obj_name, "synonym": obj_synonym})
    record["attributes"] = attributes
    record["tabularSections"] = tabular
    probe = {
        "name": record["name"],
        "synonym": record["synonym"],
        "attributes": attributes,
        "tabularSections": tabular,
    }
    blob = json.dumps(probe, ensure_ascii=False)
    record["forus"] = FORUS_MARK.search(blob) is not None
    return record


def _object_from_path(relpath: str) -> tuple[str, str] | None:
    parts = [part for part in relpath.replace("\\", "/").split("/") if part]
    for index, part in enumerate(parts[:-1]):
        if part in META_FOLDERS and parts[-1].endswith(".xml") and index == len(parts) - 2:
            return META_FOLDERS[part], Path(parts[-1]).stem
    return None


def index_zip(zip_path: Path, dump_id: str, contour: str | None = None) -> dict[str, object]:
    digest = sha256_file(zip_path)
    objects: dict[tuple[str, str], dict[str, object]] = {}
    modules: list[tuple[str, str, str, str]] = []
    configuration: dict[str, str | None] = {}
    bsl_count = 0
    xml_count = 0
    with zipfile.ZipFile(zip_path) as archive:
        names = [name.replace("\\", "/") for name in archive.namelist() if not name.endswith("/")]
        for name in names:
            lower = name.lower()
            if lower.endswith("configuration.xml") and name.count("/") <= 1:
                configuration = parse_configuration_xml(archive.read(name))
            if name.endswith(".xml"):
                xml_count += 1
                parsed = _object_from_path(name)
                if parsed is not None:
                    folder_kind, object_name = parsed
                    try:
                        record = parse_object_xml(archive.read(name))
                    except ET.ParseError:
                        continue
                    record["folder"] = folder_kind
                    objects[(folder_kind, str(record.get("name") or object_name))] = record
            elif name.endswith(".bsl"):
                bsl_count += 1
                source = archive.read(name).decode("utf-8", errors="replace")
                parsed = None
                parts = name.split("/")
                for index, part in enumerate(parts):
                    if part in META_FOLDERS and index + 1 < len(parts):
                        parsed = (META_FOLDERS[part], parts[index + 1])
                        break
                if parsed is not None:
                    modules.append((parsed[0], parsed[1], name, source))
    for folder_kind, object_name, relpath, source in modules:
        record = objects.get((folder_kind, object_name))
        if record is None:
            continue
        stored = record.setdefault("modules", [])
        assert isinstance(stored, list)
        procedures = extract_procedures(source)
        stored.append(
            {
                "path": relpath,
                "procedureCount": len(procedures),
                "procedures": procedures,
            }
        )
        if FORUS_MARK.search(source):
            record["forus"] = True
    ordered = [objects[key] for key in sorted(objects)]
    counts: dict[str, int] = {}
    for item in ordered:
        kind = str(item.get("kind") or "Unknown")
        counts[kind] = counts.get(kind, 0) + 1
    catalogs_incomplete = "Catalog" in counts and "Document" not in counts
    incomplete_dump = catalogs_incomplete and not configuration.get("Name")
    return {
        "schemaVersion": "1.0.0",
        "dumpId": dump_id,
        "contour": contour,
        "generatedAt": datetime.now(tz=UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "sourceFile": zip_path.name,
        "sourceArtifactSha256": digest,
        "sourceSizeBytes": zip_path.stat().st_size,
        "configuration": configuration,
        "incompleteDump": incomplete_dump,
        "fileCounts": {"xml": xml_count, "bsl": bsl_count, "zipEntries": xml_count + bsl_count},
        "kindCounts": counts,
        "objectCount": len(ordered),
        "forusDump": configuration_is_forus(configuration),
        "forusObjectCount": sum(1 for item in ordered if item.get("forus")),
        "objects": ordered,
    }


def public_index(index: dict[str, object]) -> dict[str, object]:
    clone = json.loads(json.dumps(index))
    public_objects: list[dict[str, object]] = []
    for item in clone.get("objects", []):
        modules = []
        for module in item.get("modules") or []:
            modules.append(
                {
                    "path": module.get("path"),
                    "procedureCount": module.get("procedureCount", 0),
                }
            )
        public_objects.append(
            {
                "kind": item.get("kind"),
                "folder": item.get("folder"),
                "name": item.get("name"),
                "uuid": item.get("uuid"),
                "synonym": item.get("synonym"),
                "forus": item.get("forus"),
                "attributeCount": len(item.get("attributes") or []),
                "attributes": item.get("attributes") or [],
                "tabularSections": item.get("tabularSections") or [],
                "modules": modules,
            }
        )
    clone["objects"] = public_objects
    return clone


def write_index_files(index: dict[str, object], json_out: Path, sqlite_path: Path) -> None:
    json_out.parent.mkdir(parents=True, exist_ok=True)
    published = public_index(index)
    json_out.write_text(
        json.dumps(published, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(sqlite_path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS objects (
                dump_id TEXT,
                kind TEXT,
                name TEXT,
                uuid TEXT,
                synonym TEXT,
                forus INTEGER,
                json TEXT,
                PRIMARY KEY (dump_id, kind, name)
            )
            """
        )
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS objects_fts USING fts5(
                dump_id, kind, name, synonym, attributes
            )
            """
        )
        dump_id = str(index["dumpId"])
        connection.execute("DELETE FROM objects WHERE dump_id = ?", (dump_id,))
        connection.execute("DELETE FROM objects_fts WHERE dump_id = ?", (dump_id,))
        for item in index["objects"]:
            assert isinstance(item, dict)
            attributes = " ".join(
                (entry.get("name") or "") + " " + (entry.get("synonym") or "")
                for entry in item.get("attributes") or []  # type: ignore[union-attr]
            )
            connection.execute(
                "INSERT INTO objects(dump_id, kind, name, uuid, synonym, forus, json) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    dump_id,
                    item.get("kind"),
                    item.get("name"),
                    item.get("uuid"),
                    item.get("synonym"),
                    1 if item.get("forus") else 0,
                    json.dumps(item, ensure_ascii=False),
                ),
            )
            connection.execute(
                "INSERT INTO objects_fts(dump_id, kind, name, synonym, attributes) "
                "VALUES (?,?,?,?,?)",
                (
                    dump_id,
                    item.get("kind"),
                    item.get("name"),
                    item.get("synonym") or "",
                    attributes,
                ),
            )
        connection.commit()
    finally:
        connection.close()


def search_objects(
    index: dict[str, object], query: str, limit: int = 20, kind: str | None = None
) -> list[dict[str, object]]:
    needle = query.casefold().strip()
    if not needle:
        return []
    hits: list[dict[str, object]] = []
    configuration = index.get("configuration") or {}
    dump_probe = json.dumps(
        {
            "dumpId": index.get("dumpId"),
            "sourceFile": index.get("sourceFile"),
            "configuration": configuration,
        },
        ensure_ascii=False,
    ).casefold()
    if needle in dump_probe and (not kind or str(kind).casefold() == "configuration"):
        assert isinstance(configuration, dict)
        hits.append(
            {
                "dumpId": index.get("dumpId"),
                "kind": "Configuration",
                "name": configuration.get("Name") or index.get("dumpId"),
                "synonym": configuration.get("Synonym"),
                "forus": bool(index.get("forusDump")),
                "attributeCount": 0,
            }
        )
    for item in index.get("objects", []):
        assert isinstance(item, dict)
        if kind and str(item.get("kind") or "").casefold() != kind.casefold():
            continue
        hay = json.dumps(item, ensure_ascii=False).casefold()
        if needle not in hay:
            continue
        hits.append(
            {
                "dumpId": index.get("dumpId"),
                "kind": item.get("kind"),
                "name": item.get("name"),
                "synonym": item.get("synonym"),
                "forus": item.get("forus"),
                "attributeCount": len(item.get("attributes") or []),
            }
        )
        if len(hits) >= limit:
            break
    return hits


def load_index(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Индекс XML конфигурации/расширения 1С")
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--dump-id", required=True)
    parser.add_argument("--contour", default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--sqlite-out", type=Path, default=DEFAULT_SQLITE)
    args = parser.parse_args()
    if not args.zip_path.is_file():
        raise SystemExit(f"zip not found: {args.zip_path}")
    json_out = args.json_out or (PUBLIC_DIR / f"{args.dump_id}.json")
    index = index_zip(args.zip_path, args.dump_id, args.contour)
    write_index_files(index, json_out, args.sqlite_out)
    print(
        json.dumps(
            {
                "dumpId": index["dumpId"],
                "objectCount": index["objectCount"],
                "kindCounts": index["kindCounts"],
                "configuration": index["configuration"],
                "json": str(json_out),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
