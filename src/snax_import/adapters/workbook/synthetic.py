from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, BinaryIO
from uuid import UUID

from snax_import.domain.errors import InvalidValue
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
    RawWorkbookResult,
    ReaderIssue,
    ReaderIssueCode,
    ReaderOptions,
    ReaderStatistics,
    WorkbookReader,
)


@dataclass(slots=True)
class _MutableSheet:
    name: str
    index: int
    visibility: SheetVisibility
    max_row: int
    max_column: int
    merged_ranges: list[MergedRange] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    hidden_skipped: bool = False


class SyntheticWorkbookReader(WorkbookReader):
    """Safe line-oriented fixture reader used before a real XLSX adapter exists.

    The fixture is UTF-8 NDJSON. The first record is a ``workbook`` header, followed
    by ``sheet``, ``row`` and ``end`` records. Each input line is processed once, so
    synthetic large-workbook tests exercise streaming iteration and early limits.
    """

    MEDIA_TYPE = "application/vnd.snax.synthetic+json"
    EXTENSIONS = {".jsonl", ".ndjson", ".snax"}

    def supports(self, media_type: str | None = None, extension: str | None = None) -> bool:
        media_matches = media_type is None or media_type.lower().split(";", 1)[0] == self.MEDIA_TYPE
        extension_matches = extension is None or extension.lower() in self.EXTENSIONS
        return (
            (media_type is not None or extension is not None)
            and media_matches
            and extension_matches
        )

    def read(self, source: BinaryIO, options: ReaderOptions) -> RawWorkbookResult:
        started = time.monotonic()
        issues: list[ReaderIssue] = []
        sheets: list[_MutableSheet] = []
        current_sheet: _MutableSheet | None = None
        workbook_header: dict[str, Any] | None = None
        bytes_read = 0
        estimated_memory = 0
        rows_read = 0
        cells_read = 0
        formula_cells = 0
        error_cells = 0
        skipped_sheets = 0
        skipped_rows = 0
        issue_number = 0
        stopped = False

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
            nonlocal issue_number
            issue_number += 1
            issues.append(
                ReaderIssue(
                    issue_id=f"synthetic-reader-{issue_number:06d}",
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

        for raw_line in source:
            if stopped:
                break
            bytes_read += len(raw_line)
            estimated_memory += len(raw_line)
            if bytes_read > options.max_file_size:
                add_issue(
                    ReaderIssueCode.FILE_TOO_LARGE,
                    IssueSeverity.CRITICAL,
                    "Synthetic source exceeded max_file_size",
                    details={"limitBytes": str(options.max_file_size)},
                )
                break
            if estimated_memory > options.memory_limit:
                add_issue(
                    ReaderIssueCode.MEMORY_LIMIT_EXCEEDED,
                    IssueSeverity.CRITICAL,
                    "Synthetic reader memory budget exceeded",
                    details={"limitBytes": str(options.memory_limit)},
                )
                break
            if time.monotonic() - started > options.timeout_seconds:
                add_issue(
                    ReaderIssueCode.TIMEOUT_EXCEEDED,
                    IssueSeverity.CRITICAL,
                    "Workbook reader timeout exceeded",
                    retryable=True,
                )
                break
            if not raw_line.strip():
                continue
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                add_issue(
                    ReaderIssueCode.MALFORMED_STRUCTURE,
                    IssueSeverity.ERROR,
                    "Synthetic fixture contains malformed JSON",
                    details={"error": type(exc).__name__},
                )
                continue
            if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                add_issue(
                    ReaderIssueCode.MALFORMED_STRUCTURE,
                    IssueSeverity.ERROR,
                    "Synthetic fixture event must be an object with type",
                )
                continue

            event_type = event["type"]
            if event_type == "workbook":
                if workbook_header is not None:
                    add_issue(
                        ReaderIssueCode.MALFORMED_STRUCTURE,
                        IssueSeverity.ERROR,
                        "Synthetic fixture contains multiple workbook headers",
                    )
                    continue
                workbook_header = event
                continue
            if event_type == "sheet":
                current_sheet = self._parse_sheet(event, options, add_issue)
                if current_sheet is None:
                    stopped = True
                    continue
                if len(sheets) >= options.max_sheets:
                    add_issue(
                        ReaderIssueCode.WORKBOOK_TOO_MANY_SHEETS,
                        IssueSeverity.CRITICAL,
                        "Workbook exceeds max_sheets",
                        details={"limit": str(options.max_sheets)},
                    )
                    stopped = True
                    continue
                if current_sheet.max_column > options.max_columns:
                    add_issue(
                        ReaderIssueCode.WORKBOOK_TOO_MANY_COLUMNS,
                        IssueSeverity.CRITICAL,
                        "Workbook exceeds max_columns",
                        sheet_name=current_sheet.name,
                        details={"limit": str(options.max_columns)},
                    )
                    stopped = True
                    continue
                sheets.append(current_sheet)
                if current_sheet.hidden_skipped:
                    skipped_sheets += 1
                    add_issue(
                        ReaderIssueCode.HIDDEN_SHEET_SKIPPED,
                        IssueSeverity.WARNING,
                        "Hidden sheet was excluded by ReaderOptions",
                        sheet_name=current_sheet.name,
                    )
                continue
            if event_type == "row":
                if current_sheet is None:
                    add_issue(
                        ReaderIssueCode.MALFORMED_STRUCTURE,
                        IssueSeverity.ERROR,
                        "Row record appeared before a sheet record",
                    )
                    continue
                if rows_read >= options.max_rows:
                    add_issue(
                        ReaderIssueCode.WORKBOOK_TOO_MANY_ROWS,
                        IssueSeverity.CRITICAL,
                        "Workbook exceeds max_rows",
                        sheet_name=current_sheet.name,
                        details={"limit": str(options.max_rows)},
                    )
                    stopped = True
                    continue
                if current_sheet.hidden_skipped:
                    skipped_rows += 1
                    continue
                row, cell_count, row_formula_count, row_error_count = self._parse_row(
                    event, current_sheet, options, add_issue
                )
                if row is None:
                    continue
                if cells_read + cell_count > options.max_cells:
                    add_issue(
                        ReaderIssueCode.CELL_LIMIT_EXCEEDED,
                        IssueSeverity.CRITICAL,
                        "Workbook exceeds max_cells",
                        sheet_name=current_sheet.name,
                        row_index=row.index,
                        details={"limit": str(options.max_cells)},
                    )
                    stopped = True
                    continue
                current_sheet.rows.append(row)
                rows_read += 1
                cells_read += cell_count
                formula_cells += row_formula_count
                error_cells += row_error_count
                continue
            if event_type == "end":
                break
            add_issue(
                ReaderIssueCode.MALFORMED_STRUCTURE,
                IssueSeverity.ERROR,
                f"Unsupported synthetic event type: {event_type}",
            )

        if workbook_header is None:
            add_issue(
                ReaderIssueCode.MALFORMED_STRUCTURE,
                IssueSeverity.ERROR,
                "Synthetic fixture must start with a workbook header",
            )
        workbook = self._build_workbook(workbook_header, sheets, add_issue)
        duration = time.monotonic() - started
        statistics = ReaderStatistics(
            sheets_read=len(sheets),
            rows_read=rows_read,
            cells_read=cells_read,
            formula_cells=formula_cells,
            error_cells=error_cells,
            skipped_sheets=skipped_sheets,
            skipped_rows=skipped_rows,
            bytes_read=bytes_read,
            duration_seconds=duration,
        )
        return RawWorkbookResult(workbook=workbook, issues=tuple(issues), statistics=statistics)

    @staticmethod
    def _parse_sheet(
        event: dict[str, Any],
        options: ReaderOptions,
        add_issue: Any,
    ) -> _MutableSheet | None:
        try:
            visibility = SheetVisibility(str(event.get("visibility", "VISIBLE")))
            sheet = _MutableSheet(
                name=str(event["name"]),
                index=int(event["index"]),
                visibility=visibility,
                max_row=int(event.get("maxRow", 0)),
                max_column=int(event.get("maxColumn", 0)),
                hidden_skipped=(
                    visibility is not SheetVisibility.VISIBLE and not options.allow_hidden_sheets
                ),
            )
            for raw_range in event.get("mergedRanges", []):
                start = raw_range["startCell"]
                end = raw_range["endCell"]
                sheet.merged_ranges.append(
                    MergedRange(
                        CellCoordinate(int(start["row"]), int(start["column"])),
                        CellCoordinate(int(end["row"]), int(end["column"])),
                    )
                )
            return sheet
        except (KeyError, TypeError, ValueError, InvalidOperation, InvalidValue) as exc:
            add_issue(
                ReaderIssueCode.MERGED_RANGE_INVALID
                if "merged" in str(exc).lower()
                else ReaderIssueCode.SHEET_READ_FAILED,
                IssueSeverity.ERROR,
                "Synthetic sheet metadata is invalid",
                details={"error": type(exc).__name__},
            )
            return None

    @staticmethod
    def _parse_row(
        event: dict[str, Any],
        sheet: _MutableSheet,
        options: ReaderOptions,
        add_issue: Any,
    ) -> tuple[Row | None, int, int, int]:
        try:
            row_index = int(event["index"])
            cells: list[Cell] = []
            formula_count = 0
            error_count = 0
            for raw_cell in event.get("cells", []):
                raw_coordinate = raw_cell["coordinate"]
                if int(raw_coordinate["column"]) > options.max_columns:
                    add_issue(
                        ReaderIssueCode.WORKBOOK_TOO_MANY_COLUMNS,
                        IssueSeverity.CRITICAL,
                        "Row contains a cell beyond max_columns",
                        sheet_name=sheet.name,
                        row_index=row_index,
                        details={"limit": str(options.max_columns)},
                    )
                    return None, 0, 0, 0
                cell = SyntheticWorkbookReader._parse_cell(
                    raw_cell, options, add_issue, sheet.name, row_index
                )
                if cell is None:
                    continue
                cells.append(cell)
                formula_count += cell.value_type is ValueType.FORMULA
                error_count += cell.value_type is ValueType.ERROR
            height_value = event.get("height")
            height = Decimal(str(height_value)) if height_value is not None else None
            return (
                Row(
                    index=row_index,
                    cells=tuple(cells),
                    hidden=bool(event.get("hidden", False)),
                    height=height,
                ),
                len(cells),
                formula_count,
                error_count,
            )
        except (KeyError, TypeError, ValueError, InvalidOperation, InvalidValue) as exc:
            add_issue(
                ReaderIssueCode.ROW_READ_FAILED,
                IssueSeverity.ERROR,
                "Synthetic row metadata is invalid",
                sheet_name=sheet.name,
                details={"error": type(exc).__name__},
            )
            return None, 0, 0, 0

    @staticmethod
    def _parse_cell(
        raw_cell: Any,
        options: ReaderOptions,
        add_issue: Any,
        sheet_name: str,
        row_index: int,
    ) -> Cell | None:
        try:
            coordinate_payload = raw_cell["coordinate"]
            coordinate = CellCoordinate(
                int(coordinate_payload["row"]), int(coordinate_payload["column"])
            )
            value_type = ValueType(str(raw_cell["valueType"]))
            raw_value = SyntheticWorkbookReader._raw_value(raw_cell.get("rawValue"))
            cached_value = SyntheticWorkbookReader._raw_value(raw_cell.get("cachedValue"))
            formula_payload = raw_cell.get("formula")
            formula = None
            if formula_payload is not None and options.preserve_formulas:
                formula = Formula(
                    str(formula_payload["formulaText"]),
                    SyntheticWorkbookReader._raw_value(formula_payload.get("cachedResult")),
                )
            if value_type is ValueType.FORMULA:
                add_issue(
                    ReaderIssueCode.FORMULA_PRESENT,
                    IssueSeverity.INFO,
                    "Formula stored as data; it is never executed",
                    sheet_name=sheet_name,
                    row_index=row_index,
                    cell_coordinate=coordinate,
                )
                if not options.preserve_formulas:
                    formula = None
            if raw_cell.get("errorCode"):
                add_issue(
                    ReaderIssueCode.FORMULA_ERROR
                    if value_type is ValueType.FORMULA
                    else ReaderIssueCode.CELL_ERROR,
                    (
                        IssueSeverity.WARNING
                        if value_type is ValueType.FORMULA
                        else IssueSeverity.ERROR
                    ),
                    "Cell contains an error code",
                    sheet_name=sheet_name,
                    row_index=row_index,
                    cell_coordinate=coordinate,
                )
            return Cell(
                coordinate=coordinate,
                row_index=coordinate.row,
                column_index=coordinate.column,
                value_type=value_type,
                raw_value=raw_value,
                display_value=raw_cell.get("displayValue"),
                formula=formula,
                cached_value=cached_value,
                error_code=raw_cell.get("errorCode"),
            )
        except (KeyError, TypeError, ValueError, InvalidOperation, InvalidValue) as exc:
            add_issue(
                ReaderIssueCode.ROW_READ_FAILED,
                IssueSeverity.ERROR,
                "Synthetic cell metadata is invalid",
                sheet_name=sheet_name,
                row_index=row_index,
                details={"error": type(exc).__name__},
            )
            return None

    @staticmethod
    def _raw_value(value: Any) -> RawValue:
        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            return Decimal(str(value))
        if isinstance(value, dict) and value.get("kind") in {"date", "datetime"}:
            parsed = datetime.fromisoformat(str(value["value"]).replace("Z", "+00:00"))
            return parsed.date() if value["kind"] == "date" else parsed
        raise ValueError("Synthetic raw values must be scalar JSON values")

    @staticmethod
    def _build_workbook(
        header: dict[str, Any] | None,
        sheets: list[_MutableSheet],
        add_issue: Any,
    ) -> Workbook | None:
        if header is None:
            return None
        try:
            created_at = datetime.fromisoformat(str(header["createdAt"]).replace("Z", "+00:00"))
            return Workbook(
                id=UUID(str(header["id"])),
                source_file_id=UUID(str(header["sourceFileId"])),
                filename=FilenameMetadata(
                    name=str(header["filename"]["name"]),
                    media_type=header["filename"].get("mediaType"),
                    size_bytes=header["filename"].get("sizeBytes"),
                ),
                format=WorkbookFormat(str(header.get("format", "SYNTHETIC"))),
                created_at=created_at.astimezone(UTC),
                sheets=tuple(
                    Sheet(
                        name=sheet.name,
                        index=sheet.index,
                        visibility=sheet.visibility,
                        max_row=sheet.max_row,
                        max_column=sheet.max_column,
                        merged_ranges=tuple(sheet.merged_ranges),
                        rows=tuple(sheet.rows),
                    )
                    for sheet in sorted(sheets, key=lambda item: item.index)
                ),
                workbook_metadata={
                    str(key): str(value)
                    for key, value in header.get("workbookMetadata", {}).items()
                },
            )
        except (KeyError, TypeError, ValueError, InvalidValue) as exc:
            add_issue(
                ReaderIssueCode.SHEET_READ_FAILED,
                IssueSeverity.ERROR,
                "Synthetic workbook header is invalid",
                details={"error": type(exc).__name__},
            )
            return None


__all__ = ["SyntheticWorkbookReader"]
