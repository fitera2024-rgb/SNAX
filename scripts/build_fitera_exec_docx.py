"""Собрать Word программного контракта в стиле документов ООО «ФИТЭРА»."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from docx.text.run import Run

ROOT = Path(__file__).resolve().parents[1]
LOGO_PATH = ROOT / "docs" / "assets" / "fitera-mark.png"
DEFAULT_OUTPUT = ROOT / "docs" / "ФИТЭРА_SNAX_Программный_контракт_для_руководителя_v3.0-exec.docx"

GREEN = RGBColor(0x1F, 0x6D, 0x45)
GREEN_CONTACT = RGBColor(0x1F, 0x6B, 0x43)
NAVY = RGBColor(0x17, 0x36, 0x5D)
GRAY = RGBColor(0x66, 0x66, 0x66)
DARK = RGBColor(0x33, 0x33, 0x33)
BODY = RGBColor(0x20, 0x21, 0x24)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
YELLOW_TEXT = RGBColor(0xD6, 0x9E, 0x2E)

FILL_GREEN = "EAF4E3"
FILL_BLUE = "EEF5FB"
FILL_BLUE_DEEP = "D9EAF7"
FILL_YELLOW = "FFF2CC"
FILL_HEADER = "1F6D45"
LIME = "8DC63F"
YELLOW_BORDER = "F1B434"

CONTENT_WIDTH_MM = 176


def _rfonts(element, ascii_name: str, east_name: str = "Arial") -> None:
    rPr = element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), ascii_name)
    rFonts.set(qn("w:hAnsi"), ascii_name)
    rFonts.set(qn("w:cs"), east_name)
    rFonts.set(qn("w:eastAsia"), east_name)


def clear_paragraph(paragraph: Paragraph) -> None:
    element = paragraph._p
    for child in list(element):
        if child.tag != qn("w:pPr"):
            element.remove(child)


def set_run_font(
    run: Run,
    *,
    name: str = "Aptos",
    size_pt: float | None = None,
    bold: bool | None = None,
    color: RGBColor | None = None,
    italic: bool | None = None,
) -> None:
    run.font.name = name
    _rfonts(run._element, name)
    if size_pt is not None:
        run.font.size = Pt(size_pt)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color is not None:
        run.font.color.rgb = color


def add_text(
    paragraph: Paragraph,
    text: str,
    *,
    name: str = "Aptos",
    size_pt: float = 11,
    bold: bool = False,
    color: RGBColor = BODY,
    italic: bool = False,
) -> Run:
    run = paragraph.add_run(text)
    set_run_font(run, name=name, size_pt=size_pt, bold=bold, color=color, italic=italic)
    return run


def set_paragraph_spacing(
    paragraph: Paragraph,
    *,
    before: float = 0,
    after: float = 6,
    line: float | None = 1.15,
    align: WD_ALIGN_PARAGRAPH | None = None,
    keep_with_next: bool = False,
) -> None:
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(before)
    fmt.space_after = Pt(after)
    if line is not None:
        fmt.line_spacing = line
        fmt.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    if align is not None:
        paragraph.alignment = align
    fmt.keep_with_next = keep_with_next


def shade_cell(cell: _Cell, fill: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = tcPr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tcPr.append(shd)
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell: _Cell, top: int, start: int, bottom: int, end: int) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    existing = tcPr.find(qn("w:tcMar"))
    if existing is not None:
        tcPr.remove(existing)
    tc_mar = OxmlElement("w:tcMar")
    for tag, value in (
        ("top", top),
        ("left", start),
        ("bottom", bottom),
        ("right", end),
    ):
        node = OxmlElement(f"w:{tag}")
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")
        tc_mar.append(node)
    tcPr.append(tc_mar)


def set_cell_borders(
    cell: _Cell,
    *,
    color: str,
    size: str = "8",
    sides: tuple[str, ...] = ("top", "left", "bottom", "right"),
    extra: dict[str, tuple[str, str]] | None = None,
) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    existing = tcPr.find(qn("w:tcBorders"))
    if existing is not None:
        tcPr.remove(existing)
    borders = OxmlElement("w:tcBorders")
    specified = extra or {}
    for side in ("top", "left", "bottom", "right"):
        node = OxmlElement(f"w:{side}")
        if side in specified:
            val, col = specified[side]
            node.set(qn("w:val"), val)
            node.set(qn("w:sz"), size if val != "nil" else "0")
            node.set(qn("w:color"), col)
        elif side in sides:
            node.set(qn("w:val"), "single")
            node.set(qn("w:sz"), size)
            node.set(qn("w:space"), "0")
            node.set(qn("w:color"), color)
        else:
            node.set(qn("w:val"), "nil")
        borders.append(node)
    tcPr.append(borders)


def valign_center(cell: _Cell) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    vAlign = tcPr.find(qn("w:vAlign"))
    if vAlign is None:
        vAlign = OxmlElement("w:vAlign")
        tcPr.append(vAlign)
    vAlign.set(qn("w:val"), "center")


def configure_table(table: Table, widths_mm: list[float]) -> None:
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    if hasattr(table, "allow_autofit"):
        table.allow_autofit = False
    widths_dxa = [int(width * 56.7) for width in widths_mm]
    total = sum(widths_dxa)
    tbl = table._tbl
    tbl_pr = tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(total))
    tbl_w.set(qn("w:type"), "dxa")
    jc = tbl_pr.find(qn("w:jc"))
    if jc is None:
        jc = OxmlElement("w:jc")
        tbl_pr.append(jc)
    jc.set(qn("w:val"), "center")
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "fixed")
    grid = tbl.find(qn("w:tblGrid"))
    if grid is not None:
        for index, width in enumerate(widths_dxa):
            grid[index].set(qn("w:w"), str(width))
    for row in table.rows:
        for index, width in enumerate(widths_dxa):
            cell = row.cells[index]
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                tc_pr.append(tc_w)
            tc_w.set(qn("w:w"), str(width))
            tc_w.set(qn("w:type"), "dxa")


def prevent_row_split(table: Table) -> None:
    for row in table.rows:
        tr_pr = row._tr.get_or_add_trPr()
        cant = tr_pr.find(qn("w:cantSplit"))
        if cant is None:
            cant = OxmlElement("w:cantSplit")
            tr_pr.append(cant)


def clear_cell(cell: _Cell) -> Paragraph:
    for extra in cell.paragraphs[1:]:
        extra._element.getparent().remove(extra._element)
    paragraph = cell.paragraphs[0]
    clear_paragraph(paragraph)
    return paragraph


def add_page_number(paragraph: Paragraph) -> None:
    run = paragraph.add_run("Стр. ")
    set_run_font(run, size_pt=9, color=GRAY)
    begin = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    begin._r.append(fld_begin)
    instr_run = paragraph.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    instr_run._r.append(instr)
    end = paragraph.add_run()
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    end._r.append(fld_end)


def add_paragraph_border(paragraph: Paragraph, color: str = LIME, size: str = "12") -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), size)
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    p_bdr.append(bottom)
    p_pr.append(p_bdr)


def configure_styles(document: Document) -> None:
    styles = document.styles
    normal = styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(11)
    normal.font.color.rgb = BODY
    _rfonts(normal.element, "Aptos")
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.15

    title = styles["Title"]
    title.font.name = "Aptos"
    title.font.size = Pt(25)
    title.font.bold = True
    title.font.color.rgb = NAVY
    _rfonts(title.element, "Aptos")
    title.paragraph_format.space_after = Pt(6)
    title.paragraph_format.line_spacing = 1.0

    subtitle = styles["Subtitle"]
    subtitle.font.name = "Aptos"
    subtitle.font.size = Pt(13)
    subtitle.font.color.rgb = GREEN
    subtitle.font.italic = False
    _rfonts(subtitle.element, "Aptos")
    subtitle.paragraph_format.space_after = Pt(8)

    heading1 = styles["Heading 1"]
    heading1.font.name = "Aptos"
    heading1.font.size = Pt(17)
    heading1.font.bold = True
    heading1.font.color.rgb = GREEN
    _rfonts(heading1.element, "Aptos")
    heading1.paragraph_format.space_before = Pt(16)
    heading1.paragraph_format.space_after = Pt(8)

    heading2 = styles["Heading 2"]
    heading2.font.name = "Aptos"
    heading2.font.size = Pt(12.5)
    heading2.font.bold = True
    heading2.font.color.rgb = GREEN
    _rfonts(heading2.element, "Aptos")
    heading2.paragraph_format.space_before = Pt(10)
    heading2.paragraph_format.space_after = Pt(4)


def add_callout(
    document: Document,
    title: str,
    body: str,
    *,
    fill: str = FILL_GREEN,
    border: str = FILL_HEADER,
    title_color: RGBColor = GREEN,
    border_size: str = "10",
    left_only: bool = False,
) -> Table:
    table = document.add_table(rows=1, cols=1)
    configure_table(table, [CONTENT_WIDTH_MM])
    cell = table.cell(0, 0)
    shade_cell(cell, fill)
    if left_only:
        set_cell_borders(
            cell,
            color=border,
            size="22",
            sides=("left",),
            extra={
                "top": ("nil", "auto"),
                "bottom": ("nil", "auto"),
                "right": ("nil", "auto"),
                "left": ("single", border),
            },
        )
    else:
        set_cell_borders(cell, color=border, size=border_size)
    set_cell_margins(cell, 120, 160, 120, 160)
    title_p = clear_cell(cell)
    set_paragraph_spacing(title_p, after=2, line=1.0)
    add_text(title_p, title, size_pt=11, bold=True, color=title_color)
    body_p = cell.add_paragraph()
    set_paragraph_spacing(body_p, after=0, line=1.1)
    add_text(body_p, body, size_pt=10.5, color=BODY)
    prevent_row_split(table)
    spacer = document.add_paragraph()
    set_paragraph_spacing(spacer, after=8, before=0)
    spacer.paragraph_format.space_after = Pt(8)
    return table


def add_kpi_tiles(document: Document, tiles: list[tuple[str, str]]) -> None:
    cols = 4
    rows = (len(tiles) + cols - 1) // cols
    table = document.add_table(rows=rows, cols=cols)
    configure_table(table, [CONTENT_WIDTH_MM / cols] * cols)
    for index in range(rows * cols):
        row, col = divmod(index, cols)
        cell = table.cell(row, col)
        shade_cell(cell, FILL_BLUE)
        set_cell_margins(cell, 100, 80, 100, 80)
        set_cell_borders(cell, color="FFFFFF", size="8")
        paragraph = clear_cell(cell)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_paragraph_spacing(paragraph, after=0, line=1.0)
        if index < len(tiles):
            value, label = tiles[index]
            add_text(paragraph, value, size_pt=14, bold=True, color=NAVY)
            caption = cell.add_paragraph()
            caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
            set_paragraph_spacing(caption, after=0, line=1.0)
            add_text(caption, label, size_pt=8.5, color=GRAY)
    prevent_row_split(table)
    spacer = document.add_paragraph()
    set_paragraph_spacing(spacer, after=6)


def add_data_table(
    document: Document,
    headers: list[str],
    rows: list[list[str]],
    widths_mm: list[float],
) -> Table:
    table = document.add_table(rows=1 + len(rows), cols=len(headers))
    configure_table(table, widths_mm)
    for index, header in enumerate(headers):
        cell = table.cell(0, index)
        shade_cell(cell, FILL_HEADER)
        set_cell_margins(cell, 90, 90, 90, 90)
        valign_center(cell)
        paragraph = clear_cell(cell)
        set_paragraph_spacing(paragraph, after=0, line=1.0)
        add_text(paragraph, header, size_pt=10, bold=True, color=WHITE)
    for row_index, row in enumerate(rows, start=1):
        fill = "FFFFFF" if row_index % 2 else FILL_GREEN
        for col_index, value in enumerate(row):
            cell = table.cell(row_index, col_index)
            shade_cell(cell, fill)
            set_cell_margins(cell, 80, 90, 80, 90)
            valign_center(cell)
            paragraph = clear_cell(cell)
            set_paragraph_spacing(paragraph, after=0, line=1.05)
            add_text(paragraph, value, size_pt=10, color=BODY)
    prevent_row_split(table)
    spacer = document.add_paragraph()
    set_paragraph_spacing(spacer, after=8)
    return table


def add_heading(document: Document, text: str, level: int = 1) -> Paragraph:
    paragraph = document.add_heading(text, level=level)
    paragraph.paragraph_format.keep_with_next = True
    return paragraph


def add_body(document: Document, text: str, *, after: float = 6) -> Paragraph:
    paragraph = document.add_paragraph()
    set_paragraph_spacing(paragraph, after=after)
    add_text(paragraph, text, size_pt=11)
    return paragraph


def add_bullet(document: Document, text: str, *, bold_prefix: str | None = None) -> None:
    paragraph = document.add_paragraph()
    set_paragraph_spacing(paragraph, after=3, line=1.12)
    fmt = paragraph.paragraph_format
    fmt.left_indent = Mm(6)
    add_text(paragraph, "•  ", size_pt=11, color=GREEN, bold=True)
    if bold_prefix:
        add_text(paragraph, bold_prefix, size_pt=11, bold=True)
        add_text(paragraph, text, size_pt=11)
    else:
        add_text(paragraph, text, size_pt=11)


def add_numbered(
    document: Document,
    number: int,
    text: str,
    *,
    bold_lead: str | None = None,
) -> None:
    paragraph = document.add_paragraph()
    set_paragraph_spacing(paragraph, after=3, line=1.12)
    paragraph.paragraph_format.left_indent = Mm(6)
    add_text(paragraph, f"{number}.  ", size_pt=11, bold=True, color=GREEN)
    if bold_lead:
        add_text(paragraph, bold_lead, size_pt=11, bold=True)
        add_text(paragraph, text, size_pt=11)
    else:
        add_text(paragraph, text, size_pt=11)


def add_checkbox(document: Document, label: str, *, bold_lead: str | None = None) -> None:
    paragraph = document.add_paragraph()
    set_paragraph_spacing(paragraph, after=4, line=1.15)
    paragraph.paragraph_format.left_indent = Mm(4)
    add_text(paragraph, "☐   ", size_pt=12, color=GREEN)
    if bold_lead:
        add_text(paragraph, bold_lead, size_pt=11, bold=True)
        add_text(paragraph, label, size_pt=11)
    else:
        add_text(paragraph, label, size_pt=11)


def setup_section(document: Document) -> None:
    section = document.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.left_margin = Mm(17)
    section.right_margin = Mm(17)
    section.top_margin = Mm(16)
    section.bottom_margin = Mm(16)
    section.header_distance = Mm(8)
    section.footer_distance = Mm(8)
    section.different_first_page_header_footer = True

    first_header = section.first_page_header
    first_header.paragraphs[0].text = ""
    running = section.header.paragraphs[0]
    running.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    clear_paragraph(running)
    add_text(
        running,
        "ФИТЭРА  ·  SNAX  ·  ПРОГРАММНЫЙ КОНТРАКТ",
        name="Aptos",
        size_pt=8.5,
        bold=True,
        color=GREEN,
    )

    def fill_footer(footer) -> None:
        paragraph = footer.paragraphs[0]
        clear_paragraph(paragraph)
        add_text(
            paragraph,
            "ООО «ФИТЭРА»  ·  редакция 3.0-exec  ·  25.08.2026  ·  для подтверждения G0",
            size_pt=8,
            color=GRAY,
        )
        page = footer.add_paragraph()
        page.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        set_paragraph_spacing(page, after=0, before=0, line=1.0)
        add_page_number(page)

    fill_footer(section.first_page_footer)
    fill_footer(section.footer)


def add_letterhead(document: Document) -> None:
    table = document.add_table(rows=1, cols=2)
    configure_table(table, [28, CONTENT_WIDTH_MM - 28])
    logo_cell = table.cell(0, 0)
    text_cell = table.cell(0, 1)
    set_cell_borders(logo_cell, color="FFFFFF", sides=())
    set_cell_borders(text_cell, color="FFFFFF", sides=())
    set_cell_margins(logo_cell, 0, 0, 0, 80)
    set_cell_margins(text_cell, 40, 80, 0, 0)
    valign_center(logo_cell)
    valign_center(text_cell)

    logo_p = clear_cell(logo_cell)
    set_paragraph_spacing(logo_p, after=0, line=1.0)
    if LOGO_PATH.is_file():
        run = logo_p.add_run()
        run.add_picture(str(LOGO_PATH), width=Mm(22))
    else:
        add_text(logo_p, "ФИТЭРА", name="Arial", size_pt=14, bold=True, color=GREEN)

    name_p = clear_cell(text_cell)
    set_paragraph_spacing(name_p, after=1, line=1.0)
    add_text(name_p, "ООО «ФИТЭРА»", name="Arial", size_pt=15, bold=True, color=DARK)
    city = text_cell.add_paragraph()
    set_paragraph_spacing(city, after=0, line=1.0)
    add_text(city, "Приморский край, г. Владивосток", name="Arial", size_pt=9, color=GRAY)
    inn = text_cell.add_paragraph()
    set_paragraph_spacing(inn, after=0, line=1.0)
    add_text(inn, "ИНН 2543052510, КПП 254301001", name="Arial", size_pt=8.5, color=GRAY)
    contact = text_cell.add_paragraph()
    set_paragraph_spacing(contact, after=0, line=1.0)
    add_text(
        contact,
        "8-914-078-94-33  •  info@fitera-dv.ru",
        name="Arial",
        size_pt=9,
        bold=True,
        color=GREEN_CONTACT,
    )
    prevent_row_split(table)

    slogan = document.add_paragraph()
    set_paragraph_spacing(slogan, before=4, after=2, line=1.0)
    add_text(
        slogan,
        "практический взгляд на процессы, учёт и автоматизацию",
        name="Arial",
        size_pt=9,
        italic=True,
        color=GRAY,
    )
    rule = document.add_paragraph()
    set_paragraph_spacing(rule, before=0, after=10, line=1.0)
    add_paragraph_border(rule)


def add_architecture_cards(document: Document) -> None:
    cards = (
        (
            FILL_BLUE_DEEP,
            "Сервис",
            "Разбирает файлы поставщиков: сохраняет оригинал, "
            "не теряет строки, не исполняет макросы Excel.",
        ),
        (
            FILL_GREEN,
            "1С — master",
            "Номенклатура, связи, остатки, расчёт потребности, заказ и проведение поступления.",
        ),
        (
            FILL_YELLOW,
            "Магазин",
            "Фиксирует факт сканером. Проводит документ только уполномоченный сотрудник.",
        ),
    )
    table = document.add_table(rows=1, cols=3)
    configure_table(table, [CONTENT_WIDTH_MM / 3] * 3)
    for index, (fill, title, body) in enumerate(cards):
        cell = table.cell(0, index)
        shade_cell(cell, fill)
        set_cell_margins(cell, 120, 120, 120, 120)
        set_cell_borders(cell, color="FFFFFF", size="12")
        paragraph = clear_cell(cell)
        set_paragraph_spacing(paragraph, after=4, line=1.0)
        add_text(paragraph, title, size_pt=11, bold=True, color=NAVY)
        body_p = cell.add_paragraph()
        set_paragraph_spacing(body_p, after=0, line=1.08)
        add_text(body_p, body, size_pt=9.5, color=BODY)
    prevent_row_split(table)
    note = document.add_paragraph()
    set_paragraph_spacing(note, before=6, after=8)
    add_text(
        note,
        "Сервис не считает, сколько заказать, и не создаёт заказ поставщику. "
        "Новые магазины получают данные из центральной 1С, а не сырой файл поставщика. "
        "Это схема «Форус» плюс сервис нормализации как помощник центральной УТ.",
        size_pt=10.5,
    )


def add_signature_table(document: Document) -> None:
    roles = [
        "Спонсор / собственник",
        "Финансовый директор",
        "Руководитель категорийного менеджмента",
        "Руководитель розницы",
        "Операционный директор",
        "Владелец 1С",
        "Координатор / ФИТЭРА",
    ]
    headers = ["Роль", "ФИО", "Подпись", "Дата"]
    widths = [58, 48, 42, 28]
    table = document.add_table(rows=1 + len(roles), cols=4)
    configure_table(table, widths)
    for index, header in enumerate(headers):
        cell = table.cell(0, index)
        shade_cell(cell, FILL_HEADER)
        set_cell_margins(cell, 80, 90, 80, 90)
        valign_center(cell)
        paragraph = clear_cell(cell)
        set_paragraph_spacing(paragraph, after=0, line=1.0)
        add_text(paragraph, header, size_pt=10, bold=True, color=WHITE)
    for row_index, role in enumerate(roles, start=1):
        for col_index in range(4):
            cell = table.cell(row_index, col_index)
            shade_cell(cell, "FFFFFF")
            set_cell_margins(cell, 140, 90, 80, 90)
            valign_center(cell)
            extra = {
                "top": ("nil", "auto"),
                "left": ("nil", "auto"),
                "right": ("nil", "auto"),
                "bottom": ("single", "B0B0B0"),
            }
            set_cell_borders(cell, color="B0B0B0", extra=extra)
            paragraph = clear_cell(cell)
            set_paragraph_spacing(paragraph, after=0, line=1.0)
            if col_index == 0:
                add_text(paragraph, role, size_pt=10, color=BODY)
            else:
                add_text(paragraph, " ", size_pt=10)
    prevent_row_split(table)


def build_document() -> Document:
    document = Document()
    configure_styles(document)
    setup_section(document)
    add_letterhead(document)

    kicker = document.add_paragraph()
    set_paragraph_spacing(kicker, after=2, line=1.0, keep_with_next=True)
    add_text(
        kicker,
        "SNAX  ·  ПРОГРАММА СТАБИЛИЗАЦИИ ДАННЫХ, ЗАКУПОК, ПРИЁМКИ И УПРАВЛЕНЧЕСКОГО КОНТУРА",
        size_pt=10,
        bold=True,
        color=GREEN,
    )

    title = document.add_paragraph("Программный контракт для руководителя", style="Title")
    title.paragraph_format.keep_with_next = True
    subtitle = document.add_paragraph(
        "Краткая форма на подтверждение ворот G0 · границы первой волны и календарь до 14 мая 2027",
        style="Subtitle",
    )
    set_paragraph_spacing(subtitle, after=4, line=1.1)

    version = document.add_paragraph()
    set_paragraph_spacing(version, after=10)
    add_text(
        version,
        "Версия 3.0-exec  ·  25 августа 2026 года  ·  "
        "Статус: проект для управленческого подтверждения",
        size_pt=10,
        color=GRAY,
    )

    add_callout(
        document,
        "Назначение документа",
        "Дать собственнику и руководителям одну страницу решений: что получит бизнес, "
        "как устроена система без жаргона, какие сроки подтверждаем и что нужно от заказчика. "
        "После подписи этот лист становится входом ворот G0. Полная техническая редакция — "
        "PROJECT_CONTRACT.md, календарь — SCHEDULE.md.",
    )

    add_kpi_tiles(
        document,
        [
            ("01.09.2026", "старт T0"),
            ("11.09.2026", "ворота G0"),
            ("19.02.2027", "пилот заказа"),
            ("14.05.2027", "передача G7"),
            ("185", "требований v1.2"),
            ("113", "требований P0"),
            ("34 нед.", "горизонт работы"),
            ("3–5", "пилотных поставщиков"),
        ],
    )

    add_heading(document, "1. В одном абзаце")
    add_body(
        document,
        "SNAX сейчас держится на людях, Excel и нескольких базах 1С. Отчёты могут выглядеть "
        "полными, даже если точка не выгрузилась, документ записан, но не проведён, а заказ "
        "собран вручную. Программа сначала восстанавливает достоверность данных и правила, "
        "затем запускает два пилота (заказ поставщику и приёмка), и только после этого — "
        "управленческие отчёты и тиражирование регионов.",
    )
    add_callout(
        document,
        "Главный принцип",
        "Данные и правила → пилот → отчёты и масштабирование. Не наоборот.",
    )

    add_heading(document, "2. Что получит бизнес")
    add_data_table(
        document,
        ["Когда", "Что можно проверить руками"],
        [
            [
                "Октябрь 2026",
                "Один магазин, один день: документы, суммы и остатки сходятся "
                "либо у расхождения есть хозяин.",
            ],
            [
                "Ноябрь 2026",
                "Утверждены формулы заказа, остатка, цены, факта продажи и P&L.",
            ],
            [
                "Февраль 2027",
                "3–5 поставщиков: файл → связанный товар → черновик заказа в 1С без дубля.",
            ],
            [
                "Апрель 2027",
                "Магазин сканирует поставку; товаровед проводит готовый документ, "
                "не набирая строки заново.",
            ],
            [
                "14 мая 2027",
                "Передача: обучение, регламент поддержки, резервное копирование.",
            ],
        ],
        [38, CONTENT_WIDTH_MM - 38],
    )
    add_callout(
        document,
        "Не обещаем в этой волне",
        "Новую 1С «с нуля»; заказ, который считает внешний сайт; автоматическое создание "
        "карточек товара; «умный» разбор фото накладной как факт приёмки; красивый BI до "
        "сверки источников; подключение всех поставщиков сразу.",
        fill=FILL_YELLOW,
        border=YELLOW_BORDER,
        title_color=YELLOW_TEXT,
        left_only=True,
        border_size="22",
    )

    add_heading(document, "3. Как устроена система")
    add_architecture_cards(document)

    add_heading(document, "4. Сроки, которые подтверждаем")
    add_body(
        document,
        "Старт: 1 сентября 2026. Передача: 14 мая 2027. Это 34 недели работы плюс праздники "
        "(Новый год и май). Если выгрузки баз 1С придут позже 11 сентября, контрольный день "
        "сдвигается: дата выгрузки + 4 недели, дальше сдвигается вся цепочка.",
    )
    add_data_table(
        document,
        ["Ворота", "Дата", "Смысл для руководителя"],
        [
            ["Старт", "01.09.2026", "Назначены роли, единый список задач"],
            ["G0", "11.09.2026", "Подтверждён этот лист, доступы, план выгрузок"],
            ["G1", "09.10.2026", "Сверка одного дня"],
            ["G2", "06.11.2026", "Подписаны формулы"],
            ["G3", "22.01.2027", "Платформа разбора файлов готова к пилоту"],
            ["G4", "19.02.2027", "Пилот заказа"],
            ["G5", "02.04.2027", "Пилот приёмки"],
            ["G6", "23.04.2027", "P&L и продажи сходятся до документа"],
            ["G7", "14.05.2027", "Сдано в эксплуатацию"],
        ],
        [28, 32, CONTENT_WIDTH_MM - 60],
    )
    add_body(
        document,
        "Каркас сервиса в репозитории уже начат. Это не ускоряет пилот заказа: без выгрузок 1С "
        "и утверждённых формул пилот запускать нельзя.",
        after=8,
    )

    add_heading(document, "5. Что нужно от заказчика")
    add_numbered(
        document,
        1,
        " спонсора и владельцев: закупки, финансы, розница, продажи, 1С.",
        bold_lead="Назначить",
    )
    add_numbered(
        document,
        2,
        " у прежнего подрядчика исходники, расширения, доступы и резервные копии.",
        bold_lead="Забрать",
    )
    add_numbered(
        document,
        3,
        " выгрузки баз (или согласованный доступ только на чтение). Файлы баз в Git не кладутся.",
        bold_lead="Передать",
    )
    add_numbered(
        document,
        4,
        " 3–5 пилотных поставщиков, контрольный магазин, день и 30–50 товаров.",
        bold_lead="Выбрать",
    )
    add_numbered(
        document,
        5,
        " спорные правила за 5 рабочих дней (цена, упаковка, факт продажи, P&L). "
        "Если решения нет — двигаем срок, а не «пусть разработчик угадает».",
        bold_lead="Решать",
    )
    add_callout(
        document,
        "Бюджет людей (D-28) в этом листе не утверждён",
        "Если команда меньше, чем в паспорте проекта, дата 14.05.2027 пересматривается явно, "
        "а не формулировкой «успеем теми же людьми».",
        fill=FILL_YELLOW,
        border=YELLOW_BORDER,
        title_color=YELLOW_TEXT,
        left_only=True,
    )

    document.add_page_break()
    add_heading(document, "6. Подтверждение руководителя")
    add_body(document, "Отметьте одно:", after=4)
    add_checkbox(
        document,
        " программу, границы первой волны и календарь до 14.05.2027 (при выгрузках до 11.09.2026).",
        bold_lead="Подтверждаю",
    )
    add_checkbox(
        document,
        " (вписать ниже).",
        bold_lead="Подтверждаю с замечаниями",
    )
    add_checkbox(
        document,
        " — вернуть на доработку.",
        bold_lead="Не подтверждаю",
    )

    add_heading(document, "Обязательные галочки, если выбрано «подтверждаю»", level=2)
    add_checkbox(document, "Не строим второй расчёт заказа вне 1С.")
    add_checkbox(
        document,
        "Не публикуем управленческий BI как официальный, "
        "пока не пройдены сверка дня (G1) и формулы (G2).",
    )
    add_checkbox(
        document,
        "Выгрузки баз передаём по отдельному регламенту; коммерческие базы в Git не попадают.",
    )
    add_checkbox(
        document,
        "Пилот — на ограниченном наборе поставщиков и точек, не на всей сети сразу.",
    )

    remarks_title = document.add_paragraph()
    set_paragraph_spacing(remarks_title, before=10, after=4)
    add_text(remarks_title, "Замечания", size_pt=12.5, bold=True, color=GREEN)
    for _ in range(3):
        line = document.add_paragraph()
        set_paragraph_spacing(line, after=10, before=4)
        add_paragraph_border(line, color="B0B0B0", size="6")
        add_text(line, " ", size_pt=11)

    add_signature_table(document)

    closing = document.add_paragraph()
    set_paragraph_spacing(closing, before=12, after=0)
    add_text(
        closing,
        "После подписи этот лист становится входом ворот G0. Детали реализации не заменяют его "
        "и не расширяют объём без отдельного решения.",
        size_pt=10,
        italic=True,
        color=GRAY,
    )

    core = document.core_properties
    core.author = "ООО «ФИТЭРА»"
    core.last_modified_by = "ООО «ФИТЭРА»"
    core.title = "SNAX — программный контракт для руководителя"
    core.subject = "Краткая форма на подтверждение ворот G0"
    core.category = "Программный контракт"
    core.comments = (
        "Редакция 3.0-exec. Оформление по эталону документов ООО «ФИТЭРА». "
        "Коммерческие выгрузки баз в файл не входят."
    )
    core.created = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
    core.modified = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
    core.revision = 1
    return document


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Собрать Word программного контракта в стиле ФИТЭРА."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Путь к DOCX",
    )
    args = parser.parse_args()
    output: Path = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    document = build_document()
    document.save(output)
    print(f"wrote {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
