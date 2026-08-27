"""Публичный индекс XML-выгрузки конфигурации 1С (без тел/имён процедур BSL и без данных ИБ)."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

# Parse object XML only for MDM/exchange-relevant kinds. Other names come from Configuration.xml.
DETAIL_KINDS = frozenset(
    {
        "Catalog",
        "Document",
        "ExchangePlan",
        "InformationRegister",
        "DataProcessor",
        "HTTPService",
        "WebService",
        "ChartOfCharacteristicTypes",
    }
)
KIND_DIRS = {
    "Catalogs": "Catalog",
    "Documents": "Document",
    "ExchangePlans": "ExchangePlan",
    "InformationRegisters": "InformationRegister",
    "AccumulationRegisters": "AccumulationRegister",
    "DataProcessors": "DataProcessor",
    "Reports": "Report",
    "Enums": "Enum",
    "Constants": "Constant",
    "CommonModules": "CommonModule",
    "EventSubscriptions": "EventSubscription",
    "ScheduledJobs": "ScheduledJob",
    "HTTPServices": "HTTPService",
    "WebServices": "WebService",
    "Subsystems": "Subsystem",
    "ChartsOfCharacteristicTypes": "ChartOfCharacteristicTypes",
}
FORUS_MARKERS = ("снэкс", "форус")


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


def first_child(element: ET.Element | None, name: str) -> ET.Element | None:
    if element is None:
        return None
    for child in list(element):
        if local_tag(child.tag) == name:
            return child
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def looks_forus(text: str | None) -> bool:
    blob = (text or "").casefold()
    return any(marker in blob for marker in FORUS_MARKERS)


def parse_configuration_xml(raw: bytes) -> dict[str, object]:
    root = ET.fromstring(raw)
    conf = first_child(root, "Configuration")
    props = first_child(conf, "Properties")
    children = first_child(conf, "ChildObjects")
    counts: dict[str, int] = {}
    names_by_kind: dict[str, list[str]] = {}
    if children is not None:
        for child in list(children):
            kind = local_tag(child.tag)
            text = (child.text or "").strip()
            counts[kind] = counts.get(kind, 0) + 1
            if text:
                names_by_kind.setdefault(kind, []).append(text)
    return {
        "metaDataObjectVersion": root.attrib.get("version"),
        "uuid": conf.attrib.get("uuid") if conf is not None else None,
        "name": ru_text(first_child(props, "Name")),
        "synonym": ru_text(first_child(props, "Synonym")),
        "vendor": ru_text(first_child(props, "Vendor")),
        "version": ru_text(first_child(props, "Version")),
        "compatibilityMode": ru_text(first_child(props, "CompatibilityMode")),
        "configurationExtensionCompatibilityMode": ru_text(
            first_child(props, "ConfigurationExtensionCompatibilityMode")
        ),
        "configurationExtensionPurpose": ru_text(
            first_child(props, "ConfigurationExtensionPurpose")
        ),
        "namePrefix": ru_text(first_child(props, "NamePrefix")),
        "briefInformation": ru_text(first_child(props, "BriefInformation")),
        "objectCounts": dict(sorted(counts.items())),
        "objectNames": {kind: names_by_kind[kind] for kind in sorted(names_by_kind)},
    }


def parse_object_header(raw: bytes) -> dict[str, object]:
    root = ET.fromstring(raw)
    obj = next((child for child in list(root) if local_tag(child.tag) != "Properties"), root)
    props = first_child(obj, "Properties")
    return {
        "kind": local_tag(obj.tag),
        "uuid": obj.attrib.get("uuid"),
        "name": ru_text(first_child(props, "Name")),
        "synonym": ru_text(first_child(props, "Synonym")),
        "objectBelonging": ru_text(first_child(props, "ObjectBelonging")),
    }


def zip_signature(path: Path) -> str:
    with path.open("rb") as handle:
        magic = handle.read(4)
    if magic[:2] == b"PK":
        return "ZIP"
    return magic.hex()


def index_zip(zip_path: Path, *, intake_id: str, source_file_name: str) -> dict[str, object]:
    digest = sha256_file(zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        names = [name.replace("\\", "/") for name in archive.namelist() if not name.endswith("/")]
        if "Configuration.xml" not in names:
            raise SystemExit(f"{zip_path}: Configuration.xml is missing")
        configuration = parse_configuration_xml(archive.read("Configuration.xml"))
        detailed: dict[str, list[dict[str, object]]] = {}
        for name in names:
            parts = name.split("/")
            if len(parts) != 2 or not parts[1].endswith(".xml"):
                continue
            kind = KIND_DIRS.get(parts[0])
            if kind not in DETAIL_KINDS:
                continue
            header = parse_object_header(archive.read(name))
            record = {
                "name": header.get("name") or Path(parts[1]).stem,
                "uuid": header.get("uuid"),
                "synonym": header.get("synonym"),
            }
            detailed.setdefault(kind, []).append(record)
        bsl_count = sum(1 for name in names if name.lower().endswith(".bsl"))
        inner_cf = [
            {
                "path": name,
                "sizeBytes": archive.getinfo(name).file_size,
                "kind": "CF",
            }
            for name in names
            if name.lower().endswith(".cf")
        ]
        uncompressed = sum(archive.getinfo(name).file_size for name in names)

    for kind in detailed:
        detailed[kind] = sorted(detailed[kind], key=lambda item: str(item["name"]))

    object_names = configuration.pop("objectNames")
    assert isinstance(object_names, dict)
    public_name_kinds = DETAIL_KINDS | {
        "AccumulationRegister",
        "BusinessProcess",
        "CommonCommand",
        "CommonForm",
        "CommonModule",
        "Constant",
        "Enum",
        "EventSubscription",
        "Report",
        "Role",
        "ScheduledJob",
        "Subsystem",
    }
    public_names = {
        kind: names for kind, names in object_names.items() if kind in public_name_kinds
    }
    forus_objects = []
    for kind, records in detailed.items():
        for record in records:
            blob = " ".join(str(record.get(key) or "") for key in ("name", "synonym", "uuid"))
            if looks_forus(blob):
                forus_objects.append({"kind": kind, **record})

    catalog_names = {item["name"] for item in detailed.get("Catalog", [])}
    return {
        "schemaVersion": "1.0.0",
        "intakeId": intake_id,
        "generatedAt": (
            datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        ),
        "sourceFileName": source_file_name,
        "sourceArtifactSha256": digest,
        "zipSignature": zip_signature(zip_path),
        "sizeBytes": zip_path.stat().st_size,
        "uncompressedBytes": uncompressed,
        "fileCount": len(names),
        "bslModuleCount": bsl_count,
        "hasConfigurationXml": True,
        "hasConfigDumpInfo": "ConfigDumpInfo.xml" in names,
        "incompleteDump": False,
        "missing": ["DT", "infobase-data", "CFE-binary"],
        "configuration": configuration,
        "objectNames": public_names,
        "objects": detailed,
        "forusNamedObjects": forus_objects,
        "innerBinaries": inner_cf,
        "mdmHints": {
            "hasCatalogMagaziny": "Магазины" in catalog_names,
            "hasCatalogStrukturnyeEdinicy": "СтруктурныеЕдиницы" in catalog_names,
            "hasCatalogSklady": "Склады" in catalog_names,
            "hasCatalogOrganizacii": "Организации" in catalog_names,
            "storeObjectHypothesis": (
                "СтруктурныеЕдиницы" if "СтруктурныеЕдиницы" in catalog_names else None
            ),
        },
    }


def public_index(index: dict[str, object]) -> dict[str, object]:
    clone = json.loads(json.dumps(index))
    blob = json.dumps(clone, ensure_ascii=False)
    if "Procedure " in blob or "Процедура " in blob or "Function " in blob:
        raise ValueError("public index must not contain BSL procedure markers")
    return clone


def build_command(args: argparse.Namespace) -> None:
    index = public_index(
        index_zip(args.zip, intake_id=args.intake_id, source_file_name=args.source_file_name)
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"indexed {index['sourceFileName']} -> {args.json_out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Индекс XML-выгрузки конфигурации 1С")
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--intake-id", required=True)
    parser.add_argument("--source-file-name", required=True)
    args = parser.parse_args()
    build_command(args)


if __name__ == "__main__":
    main()
