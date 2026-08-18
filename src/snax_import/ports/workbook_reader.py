from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import BinaryIO, Protocol, runtime_checkable

from snax_import.domain.errors import InvalidValue
from snax_import.domain.raw_workbook import CellCoordinate, Workbook


class ReaderIssueCode(StrEnum):
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    WORKBOOK_TOO_MANY_SHEETS = "WORKBOOK_TOO_MANY_SHEETS"
    WORKBOOK_TOO_MANY_ROWS = "WORKBOOK_TOO_MANY_ROWS"
    WORKBOOK_TOO_MANY_COLUMNS = "WORKBOOK_TOO_MANY_COLUMNS"
    CELL_LIMIT_EXCEEDED = "CELL_LIMIT_EXCEEDED"
    TIMEOUT_EXCEEDED = "TIMEOUT_EXCEEDED"
    MEMORY_LIMIT_EXCEEDED = "MEMORY_LIMIT_EXCEEDED"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    FORMULA_PRESENT = "FORMULA_PRESENT"
    FORMULA_ERROR = "FORMULA_ERROR"
    CELL_ERROR = "CELL_ERROR"
    MERGED_RANGE_INVALID = "MERGED_RANGE_INVALID"
    SHEET_READ_FAILED = "SHEET_READ_FAILED"
    ROW_READ_FAILED = "ROW_READ_FAILED"
    HIDDEN_SHEET_SKIPPED = "HIDDEN_SHEET_SKIPPED"
    MALFORMED_STRUCTURE = "MALFORMED_STRUCTURE"


class IssueSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


def _non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidValue(field_name, "Значение обязательно")


def _positive(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidValue(field_name, "Значение должно быть положительным целым числом")


@dataclass(frozen=True, slots=True)
class ReaderOptions:
    max_file_size: int = 50 * 1024 * 1024
    max_sheets: int = 100
    max_rows: int = 1_000_000
    max_columns: int = 10_000
    max_cells: int = 10_000_000
    timeout_seconds: float = 60.0
    memory_limit: int = 512 * 1024 * 1024
    allow_hidden_sheets: bool = False
    preserve_formulas: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "max_file_size",
            "max_sheets",
            "max_rows",
            "max_columns",
            "max_cells",
            "memory_limit",
        ):
            _positive(getattr(self, field_name), field_name)
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise InvalidValue("timeoutSeconds", "Timeout должен быть положительным числом")


@dataclass(frozen=True, slots=True)
class ReaderIssue:
    issue_id: str
    code: ReaderIssueCode
    severity: IssueSeverity
    message: str
    sheet_name: str | None = None
    row_index: int | None = None
    cell_coordinate: CellCoordinate | None = None
    retryable: bool = False
    details: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _non_blank(self.issue_id, "issueId")
        _non_blank(self.message, "message")
        if self.sheet_name is not None:
            _non_blank(self.sheet_name, "sheetName")
        if self.row_index is not None and self.row_index < 1:
            raise InvalidValue("rowIndex", "Номер строки должен быть положительным")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.details.items()
        ):
            raise InvalidValue("details", "Issue details должны быть строковой map")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    def to_dict(self) -> dict[str, object]:
        return {
            "issueId": self.issue_id,
            "code": self.code.value,
            "severity": self.severity.value,
            "message": self.message,
            "sheetName": self.sheet_name,
            "rowIndex": self.row_index,
            "cellCoordinate": self.cell_coordinate.to_dict()
            if self.cell_coordinate is not None
            else None,
            "retryable": self.retryable,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class ReaderStatistics:
    sheets_read: int = 0
    rows_read: int = 0
    cells_read: int = 0
    formula_cells: int = 0
    error_cells: int = 0
    skipped_sheets: int = 0
    skipped_rows: int = 0
    bytes_read: int = 0
    duration_seconds: float = 0.0

    def __post_init__(self) -> None:
        for field_name in (
            "sheets_read",
            "rows_read",
            "cells_read",
            "formula_cells",
            "error_cells",
            "skipped_sheets",
            "skipped_rows",
            "bytes_read",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InvalidValue(
                    field_name, "Статистика должна быть неотрицательным целым числом"
                )
        if self.duration_seconds < 0:
            raise InvalidValue("durationSeconds", "Длительность не может быть отрицательной")

    def to_dict(self) -> dict[str, int | float]:
        return {
            "sheetsRead": self.sheets_read,
            "rowsRead": self.rows_read,
            "cellsRead": self.cells_read,
            "formulaCells": self.formula_cells,
            "errorCells": self.error_cells,
            "skippedSheets": self.skipped_sheets,
            "skippedRows": self.skipped_rows,
            "bytesRead": self.bytes_read,
            "durationSeconds": self.duration_seconds,
        }


@dataclass(frozen=True, slots=True)
class ReaderResult:
    workbook: Workbook | None
    issues: tuple[ReaderIssue, ...] = ()
    statistics: ReaderStatistics = field(default_factory=ReaderStatistics)
    warnings: tuple[ReaderIssue, ...] = ()
    errors: tuple[ReaderIssue, ...] = ()

    def __post_init__(self) -> None:
        issues = tuple(self.issues)
        warnings = tuple(
            issue
            for issue in issues
            if issue.severity in {IssueSeverity.INFO, IssueSeverity.WARNING}
        )
        errors = tuple(
            issue
            for issue in issues
            if issue.severity in {IssueSeverity.ERROR, IssueSeverity.CRITICAL}
        )
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "errors", errors)

    @property
    def success(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "workbook": self.workbook.to_dict() if self.workbook is not None else None,
            "issues": [issue.to_dict() for issue in self.issues],
            "statistics": self.statistics.to_dict(),
            "warnings": [issue.to_dict() for issue in self.warnings],
            "errors": [issue.to_dict() for issue in self.errors],
        }


RawWorkbookResult = ReaderResult


@runtime_checkable
class WorkbookReader(Protocol):
    def supports(self, media_type: str | None = None, extension: str | None = None) -> bool:
        """Return whether this reader accepts the supplied media type/extension."""

    def read(self, source: BinaryIO, options: ReaderOptions) -> RawWorkbookResult:
        """Read untrusted bytes into the raw model without business interpretation."""


__all__ = [
    "IssueSeverity",
    "RawWorkbookResult",
    "ReaderIssue",
    "ReaderIssueCode",
    "ReaderOptions",
    "ReaderResult",
    "ReaderStatistics",
    "WorkbookReader",
]
