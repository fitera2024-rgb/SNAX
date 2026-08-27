from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
DOCX = ROOT / "docs" / "ФИТЭРА_SNAX_Программный_контракт_для_руководителя_v3.0-exec.docx"
LOGO = ROOT / "docs" / "assets" / "fitera-mark.png"
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _plain_text(xml_bytes: bytes) -> str:
    return re.sub(r"<[^>]+>", " ", xml_bytes.decode("utf-8"))


def test_fitera_mark_is_png() -> None:
    data = LOGO.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(data) < 50_000


def test_exec_contract_docx_is_fitera_styled_a4() -> None:
    assert DOCX.is_file()
    with ZipFile(DOCX) as archive:
        names = set(archive.namelist())
        document = archive.read("word/document.xml")
        header = archive.read("word/header2.xml")
        footer = archive.read("word/footer1.xml")
        assert "word/media/image1.png" in names
        assert archive.read("word/media/image1.png") == LOGO.read_bytes()

    text = _plain_text(document)
    header_text = _plain_text(header)
    footer_text = _plain_text(footer)

    assert "ООО «ФИТЭРА»" in text
    assert "ИНН 2543052510" in text
    assert "КПП 254301001" in text
    assert "info@fitera-dv.ru" in text
    assert "практический взгляд на процессы" in text
    assert "Программный контракт для руководителя" in text
    assert "14.05.2027" in text
    assert "Не строим второй расчёт заказа вне 1С" in text
    assert "Не обещаем в этой волне" in text
    assert "D-28" in text
    assert "PAGE" in footer_text
    assert "ФИТЭРА" in header_text
    assert "ПРОГРАММНЫЙ КОНТРАКТ" in header_text

    root = ElementTree.fromstring(document)
    sect = root.find(f".//{W_NS}sectPr")
    assert sect is not None
    page = sect.find(f"{W_NS}pgSz")
    assert page is not None
    assert page.get(f"{W_NS}w") == "11906"
    assert page.get(f"{W_NS}h") == "16838"
    assert sect.find(f"{W_NS}titlePg") is not None
    fills = {node.get(f"{W_NS}fill") for node in root.iter(f"{W_NS}shd") if node.get(f"{W_NS}fill")}
    assert "1F6D45" in fills
    assert "EAF4E3" in fills
    assert "FFF2CC" in fills
    assert "EEF5FB" in fills
