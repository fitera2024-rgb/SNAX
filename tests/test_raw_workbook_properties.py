from __future__ import annotations

import random

from snax_import.domain.raw_workbook import Cell, CellCoordinate, ValueType


def test_property_round_trip_preserves_random_string_codes() -> None:
    generator = random.Random(20260818)
    for _ in range(500):
        width = generator.randint(1, 12)
        code = "".join(generator.choice("0123456789") for _ in range(width))
        cell = Cell(
            coordinate=CellCoordinate(1, 1),
            row_index=1,
            column_index=1,
            value_type=ValueType.STRING,
            raw_value=code,
            display_value=code,
        )
        assert cell.raw_value == code
        assert cell.to_dict()["rawValue"] == code


def test_property_random_scalar_cells_do_not_raise_or_change_type() -> None:
    generator = random.Random(42)
    for row in range(1, 101):
        for column in range(1, 6):
            choice = generator.randrange(4)
            if choice == 0:
                value: str | int | bool | None = f"{generator.randrange(100000):05d}"
                value_type = ValueType.STRING
            elif choice == 1:
                value = generator.randrange(100000)
                value_type = ValueType.INTEGER
            elif choice == 2:
                value = generator.choice([True, False])
                value_type = ValueType.BOOLEAN
            else:
                value = None
                value_type = ValueType.EMPTY
            cell = Cell(
                coordinate=CellCoordinate(row, column),
                row_index=row,
                column_index=column,
                value_type=value_type,
                raw_value=value,
            )
            assert cell.value_type is value_type
            assert cell.raw_value == value
