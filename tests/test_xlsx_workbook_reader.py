from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from openpyxl import Workbook

from snax_import.adapters.workbook import XlsxWorkbookReader
from snax_import.domain.raw_workbook import SheetVisibility, ValueType
from snax_import.ports.workbook_reader import ReaderIssueCode, ReaderOptions


def _set_formula_cache(raw: bytes, cell_ref: str, formula: str, cached: str) -> bytes:
    with ZipFile(BytesIO(raw), "r") as zin:
        sheet_xml = zin.read("xl/worksheets/sheet1.xml").decode("utf-8")
        old = f'<c r="{cell_ref}"><f>{formula}</f><v /></c>'
        new = f'<c r="{cell_ref}"><f>{formula}</f><v>{cached}</v></c>'
        if old not in sheet_xml:
            raise AssertionError(f"Unexpected formula cell layout for {cell_ref}")
        sheet_xml = sheet_xml.replace(old, new, 1)

        out = BytesIO()
        with ZipFile(out, "w") as zout:
            for name in zin.namelist():
                content = (
                    sheet_xml.encode("utf-8")
                    if name == "xl/worksheets/sheet1.xml"
                    else zin.read(name)
                )
                zout.writestr(name, content)
        return out.getvalue()


def _build_sample_workbook() -> bytes:
    workbook = Workbook()
    visible = workbook.active
    visible.title = "Visible"
    visible["A1"] = "001234"
    visible["B1"] = 10
    visible["B2"] = "=B1*2"
    visible.merge_cells("C1:E1")
    visible["C3"] = "#N/A"
    visible["C3"].data_type = "e"

    visible["D2"] = "#REF!"
    visible["D2"].data_type = "e"
    visible["E2"] = "#VALUE!"
    visible["E2"].data_type = "e"
    visible["F2"] = "#DIV/0!"
    visible["F2"].data_type = "e"

    hidden = workbook.create_sheet("Hidden")
    hidden.sheet_state = "hidden"
    hidden["A1"] = "Hidden value"

    buffer = BytesIO()
    workbook.save(buffer)
    return _set_formula_cache(buffer.getvalue(), cell_ref="B2", formula="B1*2", cached="20")


def _build_formula_error_workbook() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Errors"
    sheet["A1"] = 1
    sheet["A2"] = "#REF!"
    sheet["A2"].data_type = "e"
    sheet["B2"] = "#VALUE!"
    sheet["B2"].data_type = "e"
    sheet["C2"] = "#DIV/0!"
    sheet["C2"].data_type = "e"
    sheet["D1"] = "=A1+2"
    buffer = BytesIO()
    workbook.save(buffer)
    return _set_formula_cache(buffer.getvalue(), cell_ref="D1", formula="A1+2", cached="3")


def test_xlsx_reader_supports_xlsx_media_and_extensions_only() -> None:
    reader = XlsxWorkbookReader()

    assert reader.supports(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"
    )
    assert reader.supports(
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;charset=utf-8"
    )
    assert reader.supports(extension=".XLSM")
    assert not reader.supports("application/pdf")
    assert not reader.supports()


def test_xlsx_reader_reads_hidden_sheet_formulas_error_cells_and_merged_ranges() -> None:
    reader = XlsxWorkbookReader()
    result = reader.read(BytesIO(_build_sample_workbook()), ReaderOptions())

    assert result.workbook is not None
    assert result.workbook.format.value == "XLSX"
    assert len(result.workbook.sheets) == 2

    visible = result.workbook.sheets[0]
    hidden = result.workbook.sheets[1]
    assert visible.visibility is SheetVisibility.VISIBLE
    assert hidden.visibility is SheetVisibility.HIDDEN
    assert visible.max_row >= 3
    assert len(visible.merged_ranges) == 1
    assert visible.rows[0].cells[0].raw_value == "001234"

    formula_cell = next(
        cell for row in visible.rows for cell in row.cells if cell.value_type is ValueType.FORMULA
    )
    assert formula_cell.formula is not None
    assert formula_cell.formula.formula_text == "=B1*2"
    assert formula_cell.raw_value == "=B1*2"
    assert formula_cell.cached_value == 20
    assert formula_cell.display_value == "20"

    assert any(issue.code is ReaderIssueCode.FORMULA_PRESENT for issue in result.warnings)
    assert any(issue.code is ReaderIssueCode.CELL_ERROR for issue in result.errors)


def test_xlsx_reader_preserves_error_tokens_with_stable_codes() -> None:
    result = XlsxWorkbookReader().read(BytesIO(_build_formula_error_workbook()), ReaderOptions())

    assert result.workbook is not None
    sheet = result.workbook.sheets[0]
    cells_by_value = {
        cell.raw_value: cell.error_code
        for row in sheet.rows
        for cell in row.cells
        if cell.value_type is ValueType.ERROR
    }

    assert cells_by_value["#REF!"] == "FORMULA_ERROR_REF"
    assert cells_by_value["#VALUE!"] == "FORMULA_ERROR_VALUE"
    assert cells_by_value["#DIV/0!"] == "FORMULA_ERROR_DIV_ZERO"

    assert any(issue.code is ReaderIssueCode.CELL_ERROR for issue in result.errors)
    assert result.statistics.error_cells == 3


def test_xlsx_reader_stops_on_cells_limit_with_error_issue() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = 1
    sheet["B1"] = 2
    sheet["C1"] = 3
    buffer = BytesIO()
    workbook.save(buffer)

    result = XlsxWorkbookReader().read(BytesIO(buffer.getvalue()), ReaderOptions(max_cells=2))

    assert not result.success
    assert any(issue.code is ReaderIssueCode.CELL_LIMIT_EXCEEDED for issue in result.errors)
    assert result.statistics.cells_read == 2


def test_xlsx_reader_returns_error_on_invalid_source() -> None:
    result = XlsxWorkbookReader().read(BytesIO(b"not-an-xlsx"), ReaderOptions())

    assert not result.success
    assert result.workbook is None
    assert any(issue.code is ReaderIssueCode.UNSUPPORTED_FORMAT for issue in result.errors)
