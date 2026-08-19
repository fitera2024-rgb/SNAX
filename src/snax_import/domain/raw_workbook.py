from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from snax_import.domain.errors import InvalidValue

RawValue = str | int | Decimal | date | datetime | bool | None

_MACHINE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ValueType(StrEnum):
    STRING = "STRING"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    DATE = "DATE"
    DATETIME = "DATETIME"
    BOOLEAN = "BOOLEAN"
    FORMULA = "FORMULA"
    ERROR = "ERROR"
    EMPTY = "EMPTY"
    UNKNOWN = "UNKNOWN"


class WorkbookFormat(StrEnum):
    XLSX = "XLSX"
    XLS = "XLS"
    CSV = "CSV"
    SYNTHETIC = "SYNTHETIC"
    UNKNOWN = "UNKNOWN"


class SheetVisibility(StrEnum):
    VISIBLE = "VISIBLE"
    HIDDEN = "HIDDEN"
    VERY_HIDDEN = "VERY_HIDDEN"


def _require_positive(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidValue(field, "Значение должно быть положительным целым числом")


def _require_non_negative(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidValue(field, "Значение должно быть неотрицательным целым числом")


def _require_non_blank(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidValue(field, "Значение обязательно")


def _require_machine_code(value: str, field: str) -> None:
    _require_non_blank(value, field)
    if _MACHINE_CODE_PATTERN.fullmatch(value) is None:
        raise InvalidValue(field, "Код должен быть стабильным machine code")


def _require_utc(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise InvalidValue(field, "Timestamp должен быть timezone-aware UTC")


def _column_name(column: int) -> str:
    result: list[str] = []
    current = column
    while current:
        current, remainder = divmod(current - 1, 26)
        result.append(chr(ord("A") + remainder))
    return "".join(reversed(result))


def _serialize_value(value: RawValue) -> str | int | bool | None:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _is_raw_value(value: object) -> bool:
    return value is None or isinstance(value, (str, int, Decimal, date, datetime, bool))


@dataclass(frozen=True, slots=True)
class FilenameMetadata:
    name: str
    media_type: str | None = None
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.name, "filename.name")
        if len(self.name) > 500:
            raise InvalidValue("filename.name", "Имя файла не может быть длиннее 500 символов")
        if self.size_bytes is not None:
            _require_non_negative(self.size_bytes, "filename.sizeBytes")
        if self.media_type is not None:
            _require_non_blank(self.media_type, "filename.mediaType")

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "name": self.name,
            "mediaType": self.media_type,
            "sizeBytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class CellCoordinate:
    row: int
    column: int

    def __post_init__(self) -> None:
        _require_positive(self.row, "coordinate.row")
        _require_positive(self.column, "coordinate.column")

    @property
    def a1(self) -> str:
        return f"{_column_name(self.column)}{self.row}"

    def to_dict(self) -> dict[str, int | str]:
        return {"row": self.row, "column": self.column, "a1": self.a1}


@dataclass(frozen=True, slots=True)
class Formula:
    formula_text: str
    cached_result: RawValue = None

    def __post_init__(self) -> None:
        _require_non_blank(self.formula_text, "formula.formulaText")
        if not _is_raw_value(self.cached_result) or isinstance(self.cached_result, float):
            raise InvalidValue("formula.cachedResult", "Cached result должен быть raw scalar")

    def to_dict(self) -> dict[str, str | int | bool | None]:
        return {
            "formulaText": self.formula_text,
            "cachedResult": _serialize_value(self.cached_result),
        }


@dataclass(frozen=True, slots=True)
class MergedRange:
    start_cell: CellCoordinate
    end_cell: CellCoordinate

    def __post_init__(self) -> None:
        if self.start_cell.row > self.end_cell.row:
            raise InvalidValue("mergedRange", "Начальная строка не может быть после конечной")
        if self.start_cell.column > self.end_cell.column:
            raise InvalidValue("mergedRange", "Начальная колонка не может быть после конечной")

    def to_dict(self) -> dict[str, dict[str, int | str]]:
        return {"startCell": self.start_cell.to_dict(), "endCell": self.end_cell.to_dict()}


@dataclass(frozen=True, slots=True)
class Cell:
    coordinate: CellCoordinate
    row_index: int
    column_index: int
    value_type: ValueType
    raw_value: RawValue = None
    display_value: str | None = None
    formula: Formula | None = None
    cached_value: RawValue = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        _require_positive(self.row_index, "cell.rowIndex")
        _require_positive(self.column_index, "cell.columnIndex")
        if self.coordinate.row != self.row_index or self.coordinate.column != self.column_index:
            raise InvalidValue("cell.coordinate", "Coordinate и индексы ячейки должны совпадать")
        if self.value_type is ValueType.FORMULA:
            if self.formula is None:
                raise InvalidValue("cell.formula", "Для FORMULA требуется formula metadata")
            if self.raw_value is not None and self.raw_value != self.formula.formula_text:
                raise InvalidValue(
                    "cell.rawValue", "Исходная формула должна совпадать с formulaText"
                )
        elif self.formula is not None:
            raise InvalidValue("cell.formula", "Formula metadata допустима только для FORMULA")
        if self.formula is not None and self.cached_value != self.formula.cached_result:
            raise InvalidValue(
                "cell.cachedValue", "cachedValue должен совпадать с formula.cachedResult"
            )
        if self.formula is None and self.cached_value is not None:
            raise InvalidValue("cell.cachedValue", "Cached value допустим только для FORMULA")
        if self.value_type is ValueType.ERROR:
            if not isinstance(self.raw_value, str) or not self.raw_value.strip():
                raise InvalidValue("cell.rawValue", "Для ERROR требуется исходное значение ошибки")
            if not self.error_code:
                raise InvalidValue("cell.errorCode", "Для ERROR требуется стабильный error code")
        elif self.error_code is not None and self.value_type is not ValueType.FORMULA:
            raise InvalidValue("cell.errorCode", "Error code допустим только для ERROR или FORMULA")
        if self.error_code is not None:
            _require_machine_code(self.error_code, "cell.errorCode")
        self._validate_raw_value_type()

    def _validate_raw_value_type(self) -> None:
        value = self.raw_value
        if not _is_raw_value(value) or isinstance(value, float):
            raise InvalidValue("cell.rawValue", "rawValue должен быть lossless raw scalar")
        matches = {
            ValueType.STRING: isinstance(value, str),
            ValueType.INTEGER: isinstance(value, int) and not isinstance(value, bool),
            ValueType.DECIMAL: isinstance(value, Decimal),
            ValueType.DATE: isinstance(value, date) and not isinstance(value, datetime),
            ValueType.DATETIME: isinstance(value, datetime),
            ValueType.BOOLEAN: isinstance(value, bool),
            ValueType.FORMULA: value is None or isinstance(value, str),
            ValueType.ERROR: isinstance(value, str),
            ValueType.EMPTY: value is None,
            ValueType.UNKNOWN: True,
        }
        if not matches[self.value_type]:
            raise InvalidValue(
                "cell.rawValue", f"rawValue не соответствует valueType={self.value_type.value}"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "coordinate": self.coordinate.to_dict(),
            "rowIndex": self.row_index,
            "columnIndex": self.column_index,
            "valueType": self.value_type.value,
            "rawValue": _serialize_value(self.raw_value),
            "displayValue": self.display_value,
            "formula": self.formula.to_dict() if self.formula is not None else None,
            "cachedValue": _serialize_value(self.cached_value),
            "errorCode": self.error_code,
        }


@dataclass(frozen=True, slots=True)
class Row:
    index: int
    cells: tuple[Cell, ...] = ()
    hidden: bool = False
    height: Decimal | None = None

    def __post_init__(self) -> None:
        _require_positive(self.index, "row.index")
        coordinates = {(cell.row_index, cell.column_index) for cell in self.cells}
        if len(coordinates) != len(self.cells):
            raise InvalidValue("row.cells", "В строке не должно быть дублирующихся ячеек")
        if any(cell.row_index != self.index for cell in self.cells):
            raise InvalidValue("row.cells", "Ячейка должна принадлежать своей строке")
        if self.height is not None and self.height < 0:
            raise InvalidValue("row.height", "Высота строки не может быть отрицательной")

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "cells": [cell.to_dict() for cell in self.cells],
            "hidden": self.hidden,
            "height": _serialize_value(self.height),
        }


@dataclass(frozen=True, slots=True)
class Sheet:
    name: str
    index: int
    visibility: SheetVisibility
    max_row: int
    max_column: int
    merged_ranges: tuple[MergedRange, ...] = ()
    # A replayable read-only Sequence may be backed by disk or another lazy store.
    # The model therefore does not require all row payloads to live in memory.
    rows: Sequence[Row] = ()

    def __post_init__(self) -> None:
        _require_non_blank(self.name, "sheet.name")
        _require_non_negative(self.index, "sheet.index")
        _require_non_negative(self.max_row, "sheet.maxRow")
        _require_non_negative(self.max_column, "sheet.maxColumn")
        row_indexes: set[int] = set()
        for row in self.rows:
            if row.index in row_indexes:
                raise InvalidValue("sheet.rows", "В листе не должно быть дублирующихся строк")
            row_indexes.add(row.index)
            if row.index > self.max_row:
                raise InvalidValue("sheet.rows", "Строка выходит за maxRow листа")
            if any(cell.column_index > self.max_column for cell in row.cells):
                raise InvalidValue("sheet.rows", "Ячейка выходит за maxColumn листа")
        for merged_range in self.merged_ranges:
            if (
                merged_range.end_cell.row > self.max_row
                or merged_range.end_cell.column > self.max_column
            ):
                raise InvalidValue("sheet.mergedRanges", "Merged range выходит за dimensions листа")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "index": self.index,
            "visibility": self.visibility.value,
            "maxRow": self.max_row,
            "maxColumn": self.max_column,
            "mergedRanges": [merged_range.to_dict() for merged_range in self.merged_ranges],
            "rows": [row.to_dict() for row in self.rows],
        }


@dataclass(frozen=True, slots=True)
class Workbook:
    id: UUID
    source_file_id: UUID
    filename: FilenameMetadata
    format: WorkbookFormat
    created_at: datetime
    sheets: tuple[Sheet, ...] = ()
    workbook_metadata: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        _require_utc(self.created_at, "workbook.createdAt")
        sheet_indexes = [sheet.index for sheet in self.sheets]
        if len(set(sheet_indexes)) != len(sheet_indexes):
            raise InvalidValue("workbook.sheets", "Индексы листов должны быть уникальными")
        if sheet_indexes != sorted(sheet_indexes):
            raise InvalidValue("workbook.sheets", "Листы должны быть упорядочены по index")
        if len({sheet.name for sheet in self.sheets}) != len(self.sheets):
            raise InvalidValue("workbook.sheets", "Имена листов должны быть уникальными")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.workbook_metadata.items()
        ):
            raise InvalidValue("workbook.workbookMetadata", "Metadata должна быть строковой map")
        object.__setattr__(
            self, "workbook_metadata", MappingProxyType(dict(self.workbook_metadata))
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "sourceFileId": str(self.source_file_id),
            "filename": self.filename.to_dict(),
            "format": self.format.value,
            "createdAt": self.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "sheets": [sheet.to_dict() for sheet in self.sheets],
            "workbookMetadata": dict(self.workbook_metadata),
        }


RawWorkbook = Workbook


__all__ = [
    "Cell",
    "CellCoordinate",
    "FilenameMetadata",
    "Formula",
    "MergedRange",
    "RawValue",
    "RawWorkbook",
    "Row",
    "Sheet",
    "SheetVisibility",
    "ValueType",
    "Workbook",
    "WorkbookFormat",
]
