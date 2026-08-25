from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
DOCX = ROOT / "docs" / "ФИТЭРА_SNAX_Технический_контракт_для_руководителя_v3.0.docx"
LOGO = ROOT / "docs" / "assets" / "fitera-mark.png"
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _plain_text(xml_bytes: bytes) -> str:
    return re.sub(r"<[^>]+>", " ", xml_bytes.decode("utf-8"))


def test_tech_exec_docx_is_manager_readable_fitera_styled() -> None:
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
        "практический взгляд на процессы",
        "Технический контракт для руководителя",
        "1С остаётся главной",
        "Не строим второй расчёт заказа вне 1С",
        "Похожее название не равно связанному товару",
        "Помощник закупок",
        "Записан, но не проведён",
        "Фото накладной не заменяет",
        "14 мая 2027",
        "3–5 поставщиков",
        "Не обещаем в этой волне",
        "Принимаю",
    ):
        assert needle in text, needle

    assert "TASK-012" not in text
    assert "JSON Schema" not in text
    assert "Celery" not in text
    assert "openpyxl" not in text

    assert "ФИТЭРА" in _plain_text(header)
    assert "ТЕХНИЧЕСКИЙ КОНТРАКТ" in _plain_text(header)
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
    assert "EEF5FB" in fills
