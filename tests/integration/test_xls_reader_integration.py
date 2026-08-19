from __future__ import annotations

from io import BytesIO
from pathlib import Path

from snax_import.adapters.workbook.xls_reader import XlsWorkbookReader
from snax_import.domain.raw_workbook import WorkbookFormat
from snax_import.ports.workbook_reader import ReaderIssueCode, ReaderOptions

FIXTURES = Path(__file__).parents[1] / "fixtures" / "synthetic" / "xls"


def test_xls_reader_to_raw_workbook_flow() -> None:
    result = XlsWorkbookReader().read(
        BytesIO((FIXTURES / "multi_sheet.xls").read_bytes()), ReaderOptions()
    )

    assert result.workbook is not None
    assert result.workbook.format is WorkbookFormat.XLS
    assert [sheet.name for sheet in result.workbook.sheets] == ["First", "Second"]
    assert result.statistics.sheets_read == 2


def test_xls_reader_flow_surfaces_limits_without_business_logic() -> None:
    result = XlsWorkbookReader().read(
        BytesIO((FIXTURES / "simple.xls").read_bytes()),
        ReaderOptions(max_rows=1),
    )

    assert result.workbook is not None
    assert any(issue.code is ReaderIssueCode.ROW_LIMIT_EXCEEDED for issue in result.errors)
