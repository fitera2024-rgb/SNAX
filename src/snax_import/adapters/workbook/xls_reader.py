from __future__ import annotations

import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import count
from threading import Lock
from typing import Any, BinaryIO, cast
from uuid import uuid4

from snax_import.domain.raw_workbook import (
    Cell,
    CellCoordinate,
    FilenameMetadata,
    Formula,
    MergedRange,
    RawValue,
    Row,
    Sheet,
    SheetVisibility,
    ValueType,
    Workbook,
    WorkbookFormat,
)
from snax_import.ports.workbook_reader import (
    IssueSeverity,
    ReaderIssue,
    ReaderIssueCode,
    ReaderOptions,
    ReaderResult,
    ReaderStatistics,
    WorkbookReader,
)

_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_SIGNATURE = b"PK\x03\x04"
_CHUNK_SIZE = 1024 * 1024
_FORMULA_RECORDS = {0x0006, 0x0206, 0x0406}
_FORMULA_CAPTURE_LOCK = Lock()
_ERROR_TOKENS = {
    0x00: ("#NULL!", "XLS_ERROR_NULL"),
    0x07: ("#DIV/0!", "XLS_ERROR_DIV_ZERO"),
    0x0F: ("#VALUE!", "XLS_ERROR_VALUE"),
    0x17: ("#REF!", "XLS_ERROR_REF"),
    0x1D: ("#NAME?", "XLS_ERROR_NAME"),
    0x24: ("#NUM!", "XLS_ERROR_NUM"),
    0x2A: ("#N/A", "XLS_ERROR_NA"),
}


@dataclass(frozen=True, slots=True)
class _ParseTotals:
    sheets_read: int = 0
    rows_read: int = 0
    cells_read: int = 0
    formula_cells: int = 0
    error_cells: int = 0
    skipped_sheets: int = 0
    skipped_rows: int = 0


class XlsWorkbookReader(WorkbookReader):
    """Read legacy BIFF workbooks through xlrd without executing formulas."""

    def supports(self, media_type: str | None = None, extension: str | None = None) -> bool:
        normalized_media_type = media_type.lower().split(";", 1)[0] if media_type else None
        normalized_extension = extension.lower() if extension else None
        return normalized_media_type == "application/vnd.ms-excel" or normalized_extension == ".xls"

    def read(self, source: BinaryIO, options: ReaderOptions) -> ReaderResult:
        started = time.monotonic()
        issue_counter = count(1)
        issues: list[ReaderIssue] = []

        def add_issue(
            code: ReaderIssueCode,
            severity: IssueSeverity,
            message: str,
            *,
            sheet_name: str | None = None,
            row_index: int | None = None,
            cell_coordinate: CellCoordinate | None = None,
            retryable: bool = False,
            details: dict[str, str] | None = None,
        ) -> None:
            issues.append(
                ReaderIssue(
                    issue_id=f"xls-reader-{next(issue_counter):06d}",
                    code=code,
                    severity=severity,
                    message=message,
                    sheet_name=sheet_name,
                    row_index=row_index,
                    cell_coordinate=cell_coordinate,
                    retryable=retryable,
                    details=details or {},
                )
            )

        payload = bytearray()
        try:
            while True:
                if self._timed_out(started, options):
                    add_issue(
                        ReaderIssueCode.TIMEOUT_EXCEEDED,
                        IssueSeverity.CRITICAL,
                        "XLS reader timeout exceeded while reading input",
                        retryable=True,
                    )
                    return self._failed_result(issues, len(payload), started)
                chunk = source.read(_CHUNK_SIZE)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise TypeError("Workbook source must return bytes")
                payload.extend(chunk)
                if len(payload) > options.max_file_size:
                    add_issue(
                        ReaderIssueCode.XLS_TOO_LARGE,
                        IssueSeverity.CRITICAL,
                        "XLS file exceeds max_file_size",
                        details={"limit": str(options.max_file_size)},
                    )
                    return self._failed_result(issues, len(payload), started)
        except Exception as exc:
            add_issue(
                ReaderIssueCode.XLS_CORRUPTED,
                IssueSeverity.CRITICAL,
                "Unable to read XLS source",
                details={"error": type(exc).__name__},
            )
            return self._failed_result(issues, len(payload), started)

        data = bytes(payload)
        if data.startswith(_ZIP_SIGNATURE):
            add_issue(
                ReaderIssueCode.XLS_UNSUPPORTED,
                IssueSeverity.ERROR,
                "XLS reader does not accept OOXML/XLSX input",
            )
            return self._failed_result(issues, len(data), started)
        if not data.startswith(_OLE_SIGNATURE):
            add_issue(
                ReaderIssueCode.XLS_CORRUPTED,
                IssueSeverity.CRITICAL,
                "Input is not a compound BIFF workbook",
            )
            return self._failed_result(issues, len(data), started)

        try:
            import xlrd  # type: ignore[import-untyped]
            from xlrd.biffh import XLRDError  # type: ignore[import-untyped]
        except Exception as exc:
            add_issue(
                ReaderIssueCode.XLS_UNSUPPORTED,
                IssueSeverity.CRITICAL,
                "xlrd runtime dependency is not available",
                details={"error": type(exc).__name__},
            )
            return self._failed_result(issues, len(data), started)

        formulas: dict[tuple[int, int, int], str] = {}
        try:
            with _FORMULA_CAPTURE_LOCK:
                book = _open_with_formula_capture(xlrd=xlrd, data=data, formulas=formulas)
        except Exception as exc:
            code = (
                ReaderIssueCode.XLS_PASSWORD_PROTECTED
                if _is_password_error(exc, XLRDError)
                else ReaderIssueCode.XLS_CORRUPTED
            )
            add_issue(
                code,
                IssueSeverity.CRITICAL,
                "XLS workbook cannot be opened",
                details={"error": type(exc).__name__},
            )
            return self._failed_result(issues, len(data), started)

        try:
            workbook, totals = self._parse_book(
                book=book,
                formulas=formulas,
                source_size=len(data),
                options=options,
                started=started,
                add_issue=add_issue,
                xlrd=xlrd,
            )
        except Exception as exc:
            add_issue(
                ReaderIssueCode.XLS_CORRUPTED,
                IssueSeverity.CRITICAL,
                "XLS workbook structure could not be mapped",
                details={"error": type(exc).__name__},
            )
            return self._failed_result(issues, len(data), started)

        return ReaderResult(
            workbook=workbook,
            issues=tuple(issues),
            statistics=ReaderStatistics(
                sheets_read=totals.sheets_read,
                rows_read=totals.rows_read,
                cells_read=totals.cells_read,
                formula_cells=totals.formula_cells,
                error_cells=totals.error_cells,
                skipped_sheets=totals.skipped_sheets,
                skipped_rows=totals.skipped_rows,
                bytes_read=len(data),
                duration_seconds=max(0.0, time.monotonic() - started),
            ),
        )

    def _parse_book(
        self,
        *,
        book: Any,
        formulas: dict[tuple[int, int, int], str],
        source_size: int,
        options: ReaderOptions,
        started: float,
        add_issue: Callable[..., None],
        xlrd: Any,
    ) -> tuple[Workbook, _ParseTotals]:
        sheet_names = book.sheet_names()
        sheet_count = len(sheet_names)
        sheets: list[Sheet] = []
        totals = _ParseTotals()
        if sheet_count > options.max_sheets:
            add_issue(
                ReaderIssueCode.SHEET_LIMIT_EXCEEDED,
                IssueSeverity.CRITICAL,
                "XLS workbook exceeds max_sheets",
                details={"limit": str(options.max_sheets)},
            )

        visibility_source = getattr(book, "sheet_visibility", None)
        if visibility_source is None:
            visibility_source = getattr(book, "_sheet_visibility", ())
        visibility = list(cast(list[int] | tuple[int, ...], visibility_source))
        for sheet_index, sheet_name in enumerate(sheet_names[: options.max_sheets]):
            if self._timed_out(started, options):
                add_issue(
                    ReaderIssueCode.TIMEOUT_EXCEEDED,
                    IssueSeverity.CRITICAL,
                    "XLS reader timeout exceeded while parsing sheets",
                    retryable=True,
                )
                totals = _ParseTotals(
                    sheets_read=totals.sheets_read,
                    rows_read=totals.rows_read,
                    cells_read=totals.cells_read,
                    formula_cells=totals.formula_cells,
                    error_cells=totals.error_cells,
                    skipped_sheets=sheet_count - sheet_index,
                    skipped_rows=totals.skipped_rows,
                )
                break
            sheet = book.sheet_by_index(sheet_index)
            parsed, totals, stopped = self._parse_sheet(
                book=book,
                sheet=sheet,
                sheet_index=sheet_index,
                sheet_name=str(sheet_name),
                visibility=visibility[sheet_index] if sheet_index < len(visibility) else 0,
                formulas=formulas,
                totals=totals,
                options=options,
                started=started,
                add_issue=add_issue,
                xlrd=xlrd,
            )
            sheets.append(parsed)
            if stopped:
                totals = _ParseTotals(
                    sheets_read=totals.sheets_read,
                    rows_read=totals.rows_read,
                    cells_read=totals.cells_read,
                    formula_cells=totals.formula_cells,
                    error_cells=totals.error_cells,
                    skipped_sheets=sheet_count - sheet_index - 1,
                    skipped_rows=totals.skipped_rows,
                )
                break

        if sheet_count > options.max_sheets and totals.skipped_sheets == 0:
            totals = _ParseTotals(
                sheets_read=totals.sheets_read,
                rows_read=totals.rows_read,
                cells_read=totals.cells_read,
                formula_cells=totals.formula_cells,
                error_cells=totals.error_cells,
                skipped_sheets=sheet_count - len(sheets),
                skipped_rows=totals.skipped_rows,
            )

        workbook = Workbook(
            id=uuid4(),
            source_file_id=uuid4(),
            filename=FilenameMetadata(
                name="workbook.xls",
                media_type="application/vnd.ms-excel",
                size_bytes=source_size,
            ),
            format=WorkbookFormat.XLS,
            created_at=datetime.now(UTC),
            sheets=tuple(sheets),
            workbook_metadata={
                "parser": "xlrd",
                "biffVersion": str(book.biff_version),
                "formulaExecution": "disabled",
            },
        )
        return workbook, totals

    def _parse_sheet(
        self,
        *,
        book: Any,
        sheet: Any,
        sheet_index: int,
        sheet_name: str,
        visibility: int,
        formulas: dict[tuple[int, int, int], str],
        totals: _ParseTotals,
        options: ReaderOptions,
        started: float,
        add_issue: Callable[..., None],
        xlrd: Any,
    ) -> tuple[Sheet, _ParseTotals, bool]:
        max_row = int(sheet.nrows)
        max_column = int(sheet.ncols)
        if max_column > options.max_columns:
            add_issue(
                ReaderIssueCode.WORKBOOK_TOO_MANY_COLUMNS,
                IssueSeverity.CRITICAL,
                "XLS sheet exceeds max_columns",
                sheet_name=sheet_name,
                details={"limit": str(options.max_columns)},
            )
        remaining_rows = options.max_rows - totals.rows_read
        if remaining_rows <= 0:
            add_issue(
                ReaderIssueCode.ROW_LIMIT_EXCEEDED,
                IssueSeverity.CRITICAL,
                "XLS workbook exceeds max_rows",
                details={"limit": str(options.max_rows)},
            )
            return (
                Sheet(
                    name=sheet_name,
                    index=sheet_index,
                    visibility=_visibility(visibility),
                    max_row=max_row,
                    max_column=max_column,
                    merged_ranges=_map_merged_ranges(
                        sheet=sheet, sheet_name=sheet_name, add_issue=add_issue
                    ),
                    rows=(),
                ),
                totals,
                True,
            )

        rows_to_read = min(max_row, remaining_rows)
        stopped = max_row > rows_to_read
        if stopped:
            add_issue(
                ReaderIssueCode.ROW_LIMIT_EXCEEDED,
                IssueSeverity.CRITICAL,
                "XLS sheet exceeds max_rows",
                sheet_name=sheet_name,
                details={"limit": str(options.max_rows)},
            )
        columns_to_read = min(max_column, options.max_columns)
        rows: list[Row] = []
        local_cells = 0
        local_formula_cells = 0
        local_error_cells = 0
        for rowx in range(rows_to_read):
            if self._timed_out(started, options):
                add_issue(
                    ReaderIssueCode.TIMEOUT_EXCEEDED,
                    IssueSeverity.CRITICAL,
                    "XLS reader timeout exceeded while parsing rows",
                    sheet_name=sheet_name,
                    retryable=True,
                )
                stopped = True
                break
            cells: list[Cell] = []
            row_info = getattr(sheet, "rowinfo_map", {}).get(rowx)
            row_height: object | None = None
            if row_info is not None:
                row_height = getattr(row_info, "height", None)
            for colx in range(columns_to_read):
                cell = sheet.cell(rowx, colx)
                if cell.ctype in {xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK}:
                    continue
                if totals.cells_read + local_cells >= options.max_cells:
                    add_issue(
                        ReaderIssueCode.CELL_LIMIT_EXCEEDED,
                        IssueSeverity.CRITICAL,
                        "XLS workbook exceeds max_cells",
                        sheet_name=sheet_name,
                        row_index=rowx + 1,
                        details={"limit": str(options.max_cells)},
                    )
                    stopped = True
                    break
                coordinate = CellCoordinate(row=rowx + 1, column=colx + 1)
                mapped = self._map_cell(
                    book=book,
                    cell=cell,
                    coordinate=coordinate,
                    formula_text=formulas.get((sheet_index, rowx, colx)),
                    xlrd=xlrd,
                    add_issue=add_issue,
                    sheet_name=sheet_name,
                )
                cells.append(mapped)
                local_cells += 1
                local_formula_cells += mapped.value_type is ValueType.FORMULA
                local_error_cells += mapped.value_type is ValueType.ERROR
            rows.append(
                Row(
                    index=rowx + 1,
                    cells=tuple(cells),
                    hidden=bool(getattr(row_info, "hidden", False)),
                    height=Decimal(str(row_height)) if row_height else None,
                )
            )
            if stopped:
                break

        parsed_rows = len(rows)
        next_totals = _ParseTotals(
            sheets_read=totals.sheets_read + 1,
            rows_read=totals.rows_read + parsed_rows,
            cells_read=totals.cells_read + local_cells,
            formula_cells=totals.formula_cells + local_formula_cells,
            error_cells=totals.error_cells + local_error_cells,
            skipped_rows=totals.skipped_rows + max(0, max_row - parsed_rows),
        )
        return (
            Sheet(
                name=sheet_name,
                index=sheet_index,
                visibility=_visibility(visibility),
                max_row=max_row,
                max_column=max_column,
                merged_ranges=_map_merged_ranges(
                    sheet=sheet, sheet_name=sheet_name, add_issue=add_issue
                ),
                rows=tuple(rows),
            ),
            next_totals,
            stopped,
        )

    def _map_cell(
        self,
        *,
        book: Any,
        cell: Any,
        coordinate: CellCoordinate,
        formula_text: str | None,
        xlrd: Any,
        add_issue: Callable[..., None],
        sheet_name: str,
    ) -> Cell:
        if formula_text is not None:
            cached, cached_error = _coerce_xls_value(book=book, cell=cell, xlrd=xlrd)
            formula = Formula(formula_text=formula_text, cached_result=cached)
            add_issue(
                ReaderIssueCode.FORMULA_PRESENT,
                IssueSeverity.INFO,
                "Formula stored as raw BIFF text; formula execution is disabled",
                sheet_name=sheet_name,
                row_index=coordinate.row,
                cell_coordinate=coordinate,
            )
            if cached_error is not None:
                add_issue(
                    ReaderIssueCode.FORMULA_ERROR,
                    IssueSeverity.WARNING,
                    "Formula cached value is an error token",
                    sheet_name=sheet_name,
                    row_index=coordinate.row,
                    cell_coordinate=coordinate,
                    details={"errorCode": cached_error[1]},
                )
            return Cell(
                coordinate=coordinate,
                row_index=coordinate.row,
                column_index=coordinate.column,
                value_type=ValueType.FORMULA,
                raw_value=formula_text,
                display_value=_display_value(cached),
                formula=formula,
                cached_value=cached,
                error_code=cached_error[1] if cached_error else None,
            )

        raw_value, error = _coerce_xls_value(book=book, cell=cell, xlrd=xlrd)
        if error is not None:
            add_issue(
                ReaderIssueCode.CELL_ERROR,
                IssueSeverity.ERROR,
                "Cell contains a BIFF error token",
                sheet_name=sheet_name,
                row_index=coordinate.row,
                cell_coordinate=coordinate,
                details={"errorCode": error[1]},
            )
            return Cell(
                coordinate=coordinate,
                row_index=coordinate.row,
                column_index=coordinate.column,
                value_type=ValueType.ERROR,
                raw_value=error[0],
                display_value=error[0],
                error_code=error[1],
            )
        return Cell(
            coordinate=coordinate,
            row_index=coordinate.row,
            column_index=coordinate.column,
            value_type=_value_type(raw_value),
            raw_value=raw_value,
            display_value=_display_value(raw_value),
        )

    @staticmethod
    def _timed_out(started: float, options: ReaderOptions) -> bool:
        return time.monotonic() - started > options.timeout_seconds

    @staticmethod
    def _failed_result(
        issues: list[ReaderIssue], bytes_read: int, started: float
    ) -> ReaderResult:
        return ReaderResult(
            workbook=None,
            issues=tuple(issues),
            statistics=ReaderStatistics(
                bytes_read=bytes_read,
                duration_seconds=max(0.0, time.monotonic() - started),
            ),
        )


def _open_with_formula_capture(
    *, xlrd: Any, data: bytes, formulas: dict[tuple[int, int, int], str]
) -> Any:
    from xlrd.book import Book  # type: ignore[import-untyped]
    from xlrd.formula import FMLA_TYPE_CELL, decompile_formula  # type: ignore[import-untyped]

    original = Book.get_record_parts

    def captured(book: Any) -> tuple[int, int, bytes]:
        record_code, record_length, record_data = original(book)
        if record_code in _FORMULA_RECORDS and len(record_data) >= 22:
            try:
                rowx, colx = struct.unpack("<HH", record_data[:4])
                formula_length = struct.unpack("<H", record_data[20:22])[0]
                token_data = record_data[22 : 22 + formula_length]
                formula_text = decompile_formula(
                    book,
                    token_data,
                    formula_length,
                    FMLA_TYPE_CELL,
                    browx=rowx,
                    bcolx=colx,
                )
                sheet_list = getattr(book, "_sheet_list", ())
                sheet_index = next(
                    (index for index, value in enumerate(sheet_list) if value is None),
                    len(sheet_list) - 1,
                )
                if isinstance(formula_text, str) and formula_text.strip():
                    formulas[(sheet_index, rowx, colx)] = formula_text
            except Exception:
                pass
        return record_code, record_length, record_data

    Book.get_record_parts = captured
    try:
        return xlrd.open_workbook(
            file_contents=data,
            formatting_info=True,
            on_demand=False,
            ragged_rows=False,
        )
    finally:
        Book.get_record_parts = original


def _coerce_xls_value(
    *, book: Any, cell: Any, xlrd: Any
) -> tuple[RawValue, tuple[str, str] | None]:
    if cell.ctype == xlrd.XL_CELL_ERROR:
        token = _error_token(cell.value)
        return token[0], token
    if cell.ctype == xlrd.XL_CELL_DATE:
        value = xlrd.xldate_as_datetime(cell.value, book.datemode)
        return (value.date() if value.time() == datetime.min.time() else value), None
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value), None
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        number = float(cell.value)
        return (int(number) if number.is_integer() else Decimal(str(number))), None
    if cell.ctype == xlrd.XL_CELL_TEXT:
        return str(cell.value), None
    if cell.value is None:
        return None, None
    return str(cell.value), None


def _error_token(value: object) -> tuple[str, str]:
    if isinstance(value, bool):
        return "#ERROR!", "XLS_ERROR"
    if isinstance(value, int):
        code = value
    elif isinstance(value, str) and value.isdigit():
        code = int(value)
    else:
        return "#ERROR!", "XLS_ERROR"
    return _ERROR_TOKENS.get(code, (f"#XLS_ERROR_{code:02X}!", f"XLS_ERROR_{code:02X}"))


def _value_type(value: RawValue) -> ValueType:
    if value is None:
        return ValueType.EMPTY
    if isinstance(value, bool):
        return ValueType.BOOLEAN
    if isinstance(value, int):
        return ValueType.INTEGER
    if isinstance(value, Decimal):
        return ValueType.DECIMAL
    if isinstance(value, datetime):
        return ValueType.DATETIME
    if isinstance(value, date):
        return ValueType.DATE
    if isinstance(value, str):
        return ValueType.STRING
    return ValueType.UNKNOWN


def _display_value(value: RawValue) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _visibility(value: int) -> SheetVisibility:
    return {
        0: SheetVisibility.VISIBLE,
        1: SheetVisibility.HIDDEN,
        2: SheetVisibility.VERY_HIDDEN,
    }.get(value, SheetVisibility.VISIBLE)


def _map_merged_ranges(
    *, sheet: Any, sheet_name: str, add_issue: Callable[..., None]
) -> tuple[MergedRange, ...]:
    mapped: list[MergedRange] = []
    for row_start, row_end, column_start, column_end in getattr(sheet, "merged_cells", ()):
        try:
            mapped.append(
                MergedRange(
                    start_cell=CellCoordinate(row=row_start + 1, column=column_start + 1),
                    end_cell=CellCoordinate(row=row_end, column=column_end),
                )
            )
        except (TypeError, ValueError):
            add_issue(
                ReaderIssueCode.MERGED_RANGE_INVALID,
                IssueSeverity.ERROR,
                "XLS merged range could not be mapped",
                sheet_name=sheet_name,
            )
    return tuple(mapped)


def _is_password_error(exc: Exception, xlrd_error: type[BaseException]) -> bool:
    message = str(exc).lower()
    return isinstance(exc, xlrd_error) and any(
        marker in message for marker in ("encrypt", "password", "filepass")
    )


__all__ = ["XlsWorkbookReader"]
