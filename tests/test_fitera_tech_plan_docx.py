from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
DOCX = ROOT / "docs" / "ФИТЭРА_SNAX_Технический_план_действий_v3.0.docx"
LOGO = ROOT / "docs" / "assets" / "fitera-mark.png"
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _plain_text(xml_bytes: bytes) -> str:
    return re.sub(r"<[^>]+>", " ", xml_bytes.decode("utf-8"))


def test_tech_plan_docx_covers_architecture_and_as_is_actions() -> None:
    assert DOCX.is_file()
    with ZipFile(DOCX) as archive:
        document = archive.read("word/document.xml")
        header = archive.read("word/header2.xml")
        footer = archive.read("word/footer1.xml")
        assert archive.read("word/media/image1.png") == LOGO.read_bytes()

    text = _plain_text(document)
    for needle in (
        "ООО «ФИТЭРА»",
        "ИНН 2543052510",
        "Технический план действий",
        "AP-001",
        "AP-101",
        "AP-305",
        "WORK-005",
        "TASK-012",
        "TASK-037",
        "onec-extension",
        "ПомощникЗакупок",
        "dumpLagWeeks",
        "DO_NOT_COMMIT_PAYLOAD",
        "ARC-010",
        "D-37",
        "D-44",
        "D-47",
        "14.05.2027",
        "Не строим второй расчёт заказа вне 1С",
        "локальный gate",
        "DIRECT_TO_STORE",
    ):
        assert needle in text, needle

    assert "ФИТЭРА" in _plain_text(header)
    assert "ТЕХНИЧЕСКИЙ ПЛАН" in _plain_text(header)
    assert "PAGE" in _plain_text(footer)

    root = ElementTree.fromstring(document)
    sect = root.find(f".//{W_NS}sectPr")
    assert sect is not None
    page = sect.find(f"{W_NS}pgSz")
    assert page is not None
    assert page.get(f"{W_NS}w") == "11906"
    assert page.get(f"{W_NS}h") == "16838"
    fills = {node.get(f"{W_NS}fill") for node in root.iter(f"{W_NS}shd") if node.get(f"{W_NS}fill")}
    assert "1F6D45" in fills
    assert "EAF4E3" in fills
    assert "FFF2CC" in fills
