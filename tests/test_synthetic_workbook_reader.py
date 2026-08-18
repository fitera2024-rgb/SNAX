from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from snax_import.adapters.workbook.synthetic import SyntheticWorkbookReader
from snax_import.ports.workbook_reader import ReaderIssueCode, ReaderOptions


def _fixture(*events: dict[str, Any]) -> BytesIO:
    payload = "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)
    return BytesIO(payload.encode("utf-8"))


def _header() -> dict[str, Any]:
    return {
        "type": "workbook",
        "id": "11111111-1111-4111-8111-111111111111",
        "sourceFileId": "22222222-2222-4222-8222-222222222222",
        "filename": {
            "name": "synthetic.jsonl",
            "mediaType": "application/vnd.snax.synthetic+json",
            "sizeBytes": 100,
        },
        "format": "SYNTHETIC",
        "createdAt": "2026-08-18T00:00:00Z",
        "workbookMetadata": {"formulasExecuted": "false"},
    }


def _sheet(name: str, index: int, visibility: str = "VISIBLE") -> dict[str, Any]:
    return {
        "type": "sheet",
        "name": name,
        "index": index,
        "visibility": visibility,
        "maxRow": 2,
        "maxColumn": 3,
        "mergedRanges": [
            {
                "startCell": {"row": 1, "column": 1},
                "endCell": {"row": 1, "column": 3},
            }
        ],
    }


def _row(index: int) -> dict[str, Any]:
    return {
        "type": "row",
        "index": index,
        "hidden": False,
        "height": "18.5",
        "cells": [
            {
                "coordinate": {"row": index, "column": 1},
                "valueType": "STRING",
                "rawValue": "00123",
                "displayValue": "00123",
                "formula": None,
                "cachedValue": None,
                "errorCode": None,
            },
            {
                "coordinate": {"row": index, "column": 2},
                "valueType": "FORMULA",
                "rawValue": None,
                "displayValue": "10",
                "formula": {"formulaText": "=1+9", "cachedResult": 10},
                "cachedValue": 10,
                "errorCode": "FORMULA_ERROR" if index == 2 else None,
            },
            *(
                [
                    {
                        "coordinate": {"row": index, "column": 3},
                        "valueType": "ERROR",
                        "rawValue": "#REF!",
                        "displayValue": "#REF!",
                        "formula": None,
                        "cachedValue": None,
                        "errorCode": "#REF!",
                    }
                ]
                if index == 2
                else []
            ),
        ],
    }


def test_reader_supports_only_synthetic_media_types_and_extensions() -> None:
    reader = SyntheticWorkbookReader()

    assert reader.supports("application/vnd.snax.synthetic+json", ".jsonl")
    assert reader.supports(extension=".NDJSON")
    assert not reader.supports("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert not reader.supports()


def test_empty_workbook_and_raw_values_round_trip() -> None:
    result = SyntheticWorkbookReader().read(
        _fixture(_header(), _sheet("Price", 0), {"type": "end"}),
        ReaderOptions(),
    )

    assert result.success
    assert result.workbook is not None
    assert len(result.workbook.sheets) == 1
    assert result.statistics.rows_read == 0

    empty_result = SyntheticWorkbookReader().read(
        _fixture(_header(), {"type": "end"}), ReaderOptions()
    )
    assert empty_result.success
    assert empty_result.workbook is not None
    assert empty_result.workbook.sheets == ()


def test_hidden_sheet_formula_and_merged_range_are_reported_without_execution() -> None:
    result = SyntheticWorkbookReader().read(
        _fixture(
            _header(),
            _sheet("Price", 0),
            _row(1),
            _row(2),
            _sheet("Hidden", 1, "HIDDEN"),
            _row(1),
            {"type": "end"},
        ),
        ReaderOptions(allow_hidden_sheets=False),
    )

    assert result.workbook is not None
    assert result.workbook.sheets[0].rows[0].cells[0].raw_value == "00123"
    assert result.workbook.sheets[1].rows == ()
    assert result.statistics.formula_cells == 2
    assert result.statistics.error_cells == 1
    assert result.statistics.skipped_sheets == 1
    assert {issue.code for issue in result.warnings} == {
        ReaderIssueCode.FORMULA_PRESENT,
        ReaderIssueCode.FORMULA_ERROR,
        ReaderIssueCode.HIDDEN_SHEET_SKIPPED,
    }
    assert any(issue.code is ReaderIssueCode.CELL_ERROR for issue in result.errors)


def test_limits_stop_streaming_reader_with_stable_issue_codes() -> None:
    result = SyntheticWorkbookReader().read(
        _fixture(_header(), _sheet("Price", 0), _row(1), _row(2), {"type": "end"}),
        ReaderOptions(max_rows=1),
    )

    assert not result.success
    assert result.statistics.rows_read == 1
    assert any(issue.code is ReaderIssueCode.WORKBOOK_TOO_MANY_ROWS for issue in result.errors)

    column_result = SyntheticWorkbookReader().read(
        _fixture(
            _header(),
            {
                **_sheet("Price", 0),
                "maxColumn": 4,
            },
            {"type": "end"},
        ),
        ReaderOptions(max_columns=3),
    )
    assert any(
        issue.code is ReaderIssueCode.WORKBOOK_TOO_MANY_COLUMNS for issue in column_result.errors
    )


def test_malformed_fixture_returns_issue_instead_of_raising() -> None:
    result = SyntheticWorkbookReader().read(
        BytesIO(b"not-json\n"),
        ReaderOptions(),
    )

    assert result.workbook is None
    assert any(issue.code is ReaderIssueCode.MALFORMED_STRUCTURE for issue in result.errors)
