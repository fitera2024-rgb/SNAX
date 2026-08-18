from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from snax_import.domain.errors import InvalidValue
from snax_import.domain.raw_workbook import (
    Cell,
    CellCoordinate,
    FilenameMetadata,
    Formula,
    MergedRange,
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
    ReaderResult,
)


def _cell(row: int, column: int, value: str) -> Cell:
    return Cell(
        coordinate=CellCoordinate(row, column),
        row_index=row,
        column_index=column,
        value_type=ValueType.STRING,
        raw_value=value,
        display_value=value,
    )


def test_coordinate_a1_and_string_values_preserve_leading_zeroes() -> None:
    cell = _cell(12, 28, "001234")

    assert cell.coordinate.a1 == "AB12"
    assert cell.raw_value == "001234"
    assert cell.to_dict()["rawValue"] == "001234"


def test_formula_is_data_with_cached_value_and_is_not_evaluated() -> None:
    formula = Formula("=A1+B1", Decimal("10.50"))
    cell = Cell(
        coordinate=CellCoordinate(3, 2),
        row_index=3,
        column_index=2,
        value_type=ValueType.FORMULA,
        raw_value="=A1+B1",
        display_value="10.50",
        formula=formula,
        cached_value=Decimal("10.50"),
    )

    assert cell.formula is formula
    assert cell.formula.formula_text == "=A1+B1"
    assert cell.cached_value == Decimal("10.50")
    assert cell.to_dict()["formula"] == {
        "formulaText": "=A1+B1",
        "cachedResult": "10.50",
    }
    assert cell.to_dict()["rawValue"] == "=A1+B1"
    assert cell.to_dict()["cachedValue"] == "10.50"


def test_error_cell_and_merged_range_are_structured() -> None:
    error_cell = Cell(
        coordinate=CellCoordinate(2, 2),
        row_index=2,
        column_index=2,
        value_type=ValueType.ERROR,
        raw_value="#N/A",
        display_value="#N/A",
        error_code="CELL_NOT_AVAILABLE",
    )
    merged = MergedRange(CellCoordinate(1, 1), CellCoordinate(2, 3))
    sheet = Sheet(
        name="Data",
        index=0,
        visibility=SheetVisibility.VISIBLE,
        max_row=2,
        max_column=3,
        merged_ranges=(merged,),
        rows=(Row(index=2, cells=(error_cell,)),),
    )

    assert sheet.merged_ranges[0].start_cell.a1 == "A1"
    assert sheet.merged_ranges[0].end_cell.a1 == "C2"
    assert sheet.rows[0].cells[0].error_code == "CELL_NOT_AVAILABLE"


@pytest.mark.parametrize(
    ("raw_value", "error_code"),
    [
        ("#REF!", "FORMULA_ERROR_REF"),
        ("#DIV/0!", "FORMULA_ERROR_DIV_ZERO"),
        ("#VALUE!", "FORMULA_ERROR_VALUE"),
    ],
)
def test_excel_error_cells_preserve_raw_token_and_stable_code(
    raw_value: str, error_code: str
) -> None:
    cell = Cell(
        coordinate=CellCoordinate(1, 1),
        row_index=1,
        column_index=1,
        value_type=ValueType.ERROR,
        raw_value=raw_value,
        display_value=raw_value,
        error_code=error_code,
    )

    assert cell.to_dict()["rawValue"] == raw_value
    assert cell.to_dict()["errorCode"] == error_code


def test_workbook_contains_metadata_and_utc_timestamp() -> None:
    workbook = Workbook(
        id=uuid4(),
        source_file_id=uuid4(),
        filename=FilenameMetadata("price.xlsx", "application/octet-stream", 0),
        format=WorkbookFormat.XLSX,
        created_at=datetime(2026, 8, 18, tzinfo=UTC),
        workbook_metadata={"producer": "synthetic"},
    )

    assert workbook.workbook_metadata["producer"] == "synthetic"
    assert workbook.to_dict()["format"] == "XLSX"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: CellCoordinate(0, 1),
        lambda: CellCoordinate(1, 0),
        lambda: Formula(""),
        lambda: MergedRange(CellCoordinate(2, 1), CellCoordinate(1, 1)),
        lambda: Cell(
            coordinate=CellCoordinate(1, 1),
            row_index=1,
            column_index=1,
            value_type=ValueType.ERROR,
            raw_value=None,
            error_code="FORMULA_ERROR_REF",
        ),
        lambda: Cell(
            coordinate=CellCoordinate(1, 1),
            row_index=1,
            column_index=1,
            value_type=ValueType.ERROR,
            raw_value="#REF!",
            error_code="#REF!",
        ),
        lambda: Row(index=1, cells=(_cell(2, 1, "wrong row"),)),
        lambda: Sheet(
            name="Data",
            index=0,
            visibility=SheetVisibility.VISIBLE,
            max_row=1,
            max_column=1,
            rows=(Row(index=2),),
        ),
    ],
)
def test_model_validation_rejects_invalid_structures(factory: object) -> None:
    with pytest.raises(InvalidValue):
        factory()  # type: ignore[operator]


def test_formula_requires_cached_value_consistency() -> None:
    with pytest.raises(InvalidValue):
        Cell(
            coordinate=CellCoordinate(1, 1),
            row_index=1,
            column_index=1,
            value_type=ValueType.FORMULA,
            formula=Formula("=1", 1),
            cached_value=2,
        )


@pytest.mark.parametrize(
    ("value_type", "raw_value"),
    [
        (ValueType.STRING, 1234),
        (ValueType.INTEGER, "001234"),
        (ValueType.DECIMAL, "10.50"),
        (ValueType.BOOLEAN, 1),
        (ValueType.EMPTY, ""),
    ],
)
def test_value_type_mismatch_is_rejected_without_silent_conversion(
    value_type: ValueType, raw_value: object
) -> None:
    with pytest.raises(InvalidValue):
        Cell(
            coordinate=CellCoordinate(1, 1),
            row_index=1,
            column_index=1,
            value_type=value_type,
            raw_value=raw_value,  # type: ignore[arg-type]
        )


class _LazyRows(Sequence[Row]):
    def __init__(self, count: int) -> None:
        self.count = count

    def __len__(self) -> int:
        return self.count

    def __getitem__(self, index: int | slice) -> Row | list[Row]:
        if isinstance(index, slice):
            return [Row(item + 1) for item in range(*index.indices(self.count))]
        if index < 0:
            index += self.count
        if index < 0 or index >= self.count:
            raise IndexError(index)
        return Row(index + 1)


def test_sheet_accepts_replayable_lazy_rows_without_materializing_to_tuple() -> None:
    rows = _LazyRows(3)

    sheet = Sheet(
        name="Lazy",
        index=0,
        visibility=SheetVisibility.VISIBLE,
        max_row=3,
        max_column=0,
        rows=rows,
    )

    assert sheet.rows is rows
    assert [row.index for row in sheet.rows] == [1, 2, 3]


def test_reader_result_requires_explicit_error_when_workbook_is_absent() -> None:
    with pytest.raises(InvalidValue):
        ReaderResult(workbook=None)

    issue = ReaderIssue(
        issue_id="reader-1",
        code=ReaderIssueCode.MALFORMED_STRUCTURE,
        severity=IssueSeverity.ERROR,
        message="Invalid workbook",
    )
    result = ReaderResult(workbook=None, issues=(issue,))

    assert not result.success
    assert result.errors == (issue,)
