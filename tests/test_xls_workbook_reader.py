from __future__ import annotations

from io import BytesIO
from pathlib import Path

from snax_import.adapters.workbook.xls_reader import XlsWorkbookReader
from snax_import.domain.raw_workbook import (
    CellCoordinate,
    SheetVisibility,
    ValueType,
    WorkbookFormat,
)
from snax_import.ports.workbook_reader import ReaderIssueCode, ReaderOptions

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic" / "xls"


def _read(name: str, options: ReaderOptions | None = None):
    return XlsWorkbookReader().read(
        BytesIO((FIXTURES / name).read_bytes()), options or ReaderOptions()
    )


def test_maps_xls_rows_cells_types_and_coordinates() -> None:
    result = _read("simple.xls")

    assert result.success
    assert result.workbook is not None
    assert result.workbook.format is WorkbookFormat.XLS
    assert result.workbook.sheets[0].rows[0].cells[0].coordinate.a1 == "A1"
    assert result.workbook.sheets[0].rows[0].cells[0].value_type is ValueType.STRING
    assert result.workbook.sheets[0].rows[1].cells[1].value_type is ValueType.INTEGER
    assert result.workbook.sheets[0].merged_ranges[0].start_cell == CellCoordinate(4, 1)
    assert result.workbook.sheets[0].merged_ranges[0].end_cell == CellCoordinate(4, 2)


def test_preserves_leading_zero_text() -> None:
    result = _read("leading_zero.xls")

    assert result.workbook is not None
    cell = result.workbook.sheets[0].rows[0].cells[0]
    assert cell.raw_value == "001234"
    assert cell.display_value == "001234"


def test_maps_multiple_and_hidden_sheets() -> None:
    result = _read("hidden_sheet.xls")

    assert result.workbook is not None
    assert len(result.workbook.sheets) == 2
    assert result.workbook.sheets[1].visibility is SheetVisibility.HIDDEN


def test_maps_formula_without_execution_and_keeps_cached_value() -> None:
    result = _read("formula.xls")

    assert result.workbook is not None
    cell = result.workbook.sheets[0].rows[0].cells[2]
    assert cell.value_type is ValueType.FORMULA
    assert cell.formula is not None
    assert cell.formula.formula_text == "A1+B1"
    assert cell.cached_value == 3
    assert any(issue.code is ReaderIssueCode.FORMULA_PRESENT for issue in result.warnings)


def test_maps_cell_errors() -> None:
    result = _read("errors.xls")

    assert result.workbook is not None
    cell = result.workbook.sheets[0].rows[0].cells[0]
    assert cell.value_type is ValueType.FORMULA
    assert cell.cached_value == "#DIV/0!"
    assert cell.error_code == "XLS_ERROR_DIV_ZERO"
    assert any(issue.code is ReaderIssueCode.FORMULA_ERROR for issue in result.warnings)


def test_maps_corrupt_and_password_files_to_controlled_errors() -> None:
    corrupt = _read("corrupted.xls")
    password = _read("password_protected.xls")

    assert any(issue.code is ReaderIssueCode.XLS_CORRUPTED for issue in corrupt.errors)
    assert any(issue.code is ReaderIssueCode.XLS_PASSWORD_PROTECTED for issue in password.errors)


def test_enforces_xls_limits() -> None:
    result = _read("simple.xls", ReaderOptions(max_cells=1))

    assert any(issue.code is ReaderIssueCode.CELL_LIMIT_EXCEEDED for issue in result.errors)


def test_enforces_file_sheet_row_and_column_limits() -> None:
    too_large = _read("simple.xls", ReaderOptions(max_file_size=1))
    too_many_sheets = _read("multi_sheet.xls", ReaderOptions(max_sheets=1))
    too_many_rows = _read("simple.xls", ReaderOptions(max_rows=1))
    too_many_columns = _read("simple.xls", ReaderOptions(max_columns=1))

    assert any(issue.code is ReaderIssueCode.XLS_TOO_LARGE for issue in too_large.errors)
    assert any(
        issue.code is ReaderIssueCode.SHEET_LIMIT_EXCEEDED for issue in too_many_sheets.errors
    )
    assert any(issue.code is ReaderIssueCode.ROW_LIMIT_EXCEEDED for issue in too_many_rows.errors)
    assert any(
        issue.code is ReaderIssueCode.WORKBOOK_TOO_MANY_COLUMNS for issue in too_many_columns.errors
    )


def test_rejects_xlsx_signature() -> None:
    result = XlsWorkbookReader().read(BytesIO(b"PK\x03\x04"), ReaderOptions())

    assert any(issue.code is ReaderIssueCode.XLS_UNSUPPORTED for issue in result.errors)
