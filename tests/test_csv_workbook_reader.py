from __future__ import annotations

from io import BytesIO

import pytest

import snax_import.adapters.workbook.csv_reader as csv_reader_module
from snax_import.adapters.workbook import CsvWorkbookReader
from snax_import.domain.raw_workbook import ValueType, WorkbookFormat
from snax_import.ports.workbook_reader import ReaderIssueCode, ReaderOptions


def test_csv_reader_supports_csv_media_and_extension_only() -> None:
    reader = CsvWorkbookReader()

    assert reader.supports("text/csv", ".csv")
    assert reader.supports("text/csv;charset=windows-1251")
    assert reader.supports(extension=".CSV")
    assert not reader.supports("application/pdf")
    assert not reader.supports()


def test_csv_reader_preserves_utf8_values_coordinates_and_quoted_newlines() -> None:
    source = b'code,description\r\n001234,"first line\nsecond line"\r\n'

    result = CsvWorkbookReader().read(BytesIO(source), ReaderOptions())

    assert result.success
    assert result.workbook is not None
    assert result.workbook.format is WorkbookFormat.CSV
    assert result.workbook.workbook_metadata["encoding"] == "utf-8"
    assert result.workbook.workbook_metadata["delimiter"] == ","
    sheet = result.workbook.sheets[0]
    assert sheet.max_row == 2
    assert sheet.max_column == 2
    assert sheet.rows[1].cells[0].coordinate.a1 == "A2"
    assert sheet.rows[1].cells[0].raw_value == "001234"
    assert sheet.rows[1].cells[0].value_type is ValueType.STRING
    assert sheet.rows[1].cells[1].raw_value == "first line\nsecond line"


def test_csv_reader_handles_escaped_quotes_without_losing_rows() -> None:
    source = b'id,note\r\n1,"He said ""hello"""\r\n2,"first line\r\nsecond line"\r\n3,last\r\n'

    result = CsvWorkbookReader().read(
        BytesIO(source),
        ReaderOptions(csv_delimiter=","),
    )

    assert result.success
    assert result.workbook is not None
    rows = result.workbook.sheets[0].rows
    assert [row.index for row in rows] == [1, 2, 3, 4]
    assert rows[1].cells[1].raw_value == 'He said "hello"'
    assert rows[2].cells[1].raw_value == "first line\r\nsecond line"
    assert rows[3].cells[1].raw_value == "last"


def test_csv_reader_preserves_spaces_and_never_coerces_numbers() -> None:
    source = b"code, description\r\n 001234 ,  padded value  \r\n"

    result = CsvWorkbookReader().read(
        BytesIO(source),
        ReaderOptions(csv_delimiter=","),
    )

    assert result.success
    assert result.workbook is not None
    rows = result.workbook.sheets[0].rows
    assert rows[0].cells[1].raw_value == " description"
    assert rows[1].cells[0].raw_value == " 001234 "
    assert rows[1].cells[1].raw_value == "  padded value  "
    assert all(cell.value_type is ValueType.STRING for row in rows for cell in row.cells)


def test_csv_reader_detects_windows_1251_and_semicolon() -> None:
    source = "код;описание\r\n001;Товар\r\n".encode("cp1251")

    result = CsvWorkbookReader().read(BytesIO(source), ReaderOptions())

    assert result.success
    assert result.workbook is not None
    assert result.workbook.workbook_metadata["encoding"] == "cp1251"
    assert result.workbook.workbook_metadata["delimiter"] == ";"
    assert result.workbook.sheets[0].rows[1].cells[1].raw_value == "Товар"


def test_csv_reader_honors_encoding_and_dialect_overrides() -> None:
    source = "код\t'описание товара'\r\n001\t'Товар'\r\n".encode("cp1251")
    options = ReaderOptions(
        csv_encoding="windows-1251",
        csv_dialect="excel-tab",
        csv_quotechar="'",
    )

    result = CsvWorkbookReader().read(BytesIO(source), options)

    assert result.success
    assert result.workbook is not None
    assert result.workbook.workbook_metadata["delimiter"] == "\t"
    assert result.workbook.sheets[0].rows[0].cells[1].raw_value == "описание товара"


def test_csv_reader_reports_inconsistent_and_malformed_rows() -> None:
    inconsistent = CsvWorkbookReader().read(
        BytesIO(b"a,b\r\n1\r\n2,3,4\r\n"),
        ReaderOptions(),
    )
    malformed = CsvWorkbookReader().read(
        BytesIO(b'a,b\r\n"unterminated,b'),
        ReaderOptions(csv_delimiter=","),
    )

    assert inconsistent.workbook is not None
    assert [issue.row_index for issue in inconsistent.errors] == [2, 3]
    assert all(issue.code is ReaderIssueCode.MALFORMED_STRUCTURE for issue in inconsistent.errors)
    assert malformed.workbook is not None
    assert any(issue.code is ReaderIssueCode.MALFORMED_STRUCTURE for issue in malformed.errors)


def test_csv_reader_returns_issue_for_invalid_encoding_and_empty_file() -> None:
    invalid_encoding = CsvWorkbookReader().read(
        BytesIO("код,описание\r\n".encode("cp1251")),
        ReaderOptions(csv_encoding="utf-8"),
    )
    empty = CsvWorkbookReader().read(BytesIO(b""), ReaderOptions())

    assert invalid_encoding.workbook is None
    assert any(
        issue.code is ReaderIssueCode.UNSUPPORTED_FORMAT for issue in invalid_encoding.errors
    )
    assert empty.success
    assert empty.workbook is not None
    assert len(empty.workbook.sheets) == 1
    assert empty.workbook.sheets[0].rows == ()
    assert empty.statistics.sheets_read == 1
    assert empty.statistics.rows_read == 0


def test_csv_reader_enforces_file_row_column_cell_and_memory_limits() -> None:
    source = b"a,b,c\r\n1,2,3\r\n"

    too_large = CsvWorkbookReader().read(BytesIO(source), ReaderOptions(max_file_size=1))
    too_many_rows = CsvWorkbookReader().read(BytesIO(source), ReaderOptions(max_rows=1))
    too_many_columns = CsvWorkbookReader().read(BytesIO(source), ReaderOptions(max_columns=2))
    too_many_cells = CsvWorkbookReader().read(BytesIO(source), ReaderOptions(max_cells=2))
    too_much_memory = CsvWorkbookReader().read(BytesIO(source), ReaderOptions(memory_limit=1))

    assert any(issue.code is ReaderIssueCode.FILE_TOO_LARGE for issue in too_large.errors)
    assert any(issue.code is ReaderIssueCode.ROW_LIMIT_EXCEEDED for issue in too_many_rows.errors)
    assert any(
        issue.code is ReaderIssueCode.WORKBOOK_TOO_MANY_COLUMNS for issue in too_many_columns.errors
    )
    assert any(issue.code is ReaderIssueCode.CELL_LIMIT_EXCEEDED for issue in too_many_cells.errors)
    assert any(
        issue.code is ReaderIssueCode.MEMORY_LIMIT_EXCEEDED for issue in too_much_memory.errors
    )
    assert too_many_cells.statistics.cells_read == 2


def test_csv_reader_timeout_returns_issue_instead_of_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter((0.0, 2.0, 2.0))
    monkeypatch.setattr(
        csv_reader_module.time,
        "monotonic",
        lambda: next(ticks, 2.0),
    )

    result = CsvWorkbookReader().read(
        BytesIO(b"a,b\r\n1,2\r\n"),
        ReaderOptions(timeout_seconds=1.0),
    )

    assert result.workbook is None
    assert any(issue.code is ReaderIssueCode.TIMEOUT_EXCEEDED for issue in result.errors)


def test_csv_reader_rejects_unknown_encoding_and_dialect_overrides() -> None:
    unknown_encoding = CsvWorkbookReader().read(
        BytesIO(b"a,b\n"),
        ReaderOptions(csv_encoding="not-an-encoding"),
    )
    unknown_dialect = CsvWorkbookReader().read(
        BytesIO(b"a,b\n"),
        ReaderOptions(csv_dialect="not-a-dialect"),
    )

    assert unknown_encoding.workbook is None
    assert unknown_dialect.workbook is None
    assert any(
        issue.code is ReaderIssueCode.UNSUPPORTED_FORMAT for issue in unknown_encoding.errors
    )
    assert any(issue.code is ReaderIssueCode.UNSUPPORTED_FORMAT for issue in unknown_dialect.errors)
