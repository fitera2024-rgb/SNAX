from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from snax_import.application.profile_detector import (
    ProfileDetectionConfig,
    ProfileDetectionWeights,
    SupplierProfileDetector,
)
from snax_import.domain.errors import InvalidValue
from snax_import.domain.profile_detection import (
    DetectionConfidence,
    DetectionResult,
    DetectionStatus,
    confidence_for_score,
)
from snax_import.domain.raw_workbook import (
    Cell,
    CellCoordinate,
    FilenameMetadata,
    RawWorkbook,
    Row,
    Sheet,
    SheetVisibility,
    ValueType,
    WorkbookFormat,
)
from snax_import.domain.supplier_profile import (
    DataType,
    ProfileStatus,
    SheetPurpose,
    SupplierColumnMapping,
    SupplierFileRule,
    SupplierProfile,
    SupplierSheetMapping,
    SupplierTargetField,
)
from snax_import.ports.workbook_reader import ReaderIssueCode

FIXTURES = Path(__file__).parent / "fixtures" / "profile_detection"
NOW = datetime(2026, 8, 19, tzinfo=UTC)


def _fixture(name: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def _workbook(payload: dict[str, object]) -> RawWorkbook:
    sheets: list[Sheet] = []
    for index, raw_sheet in enumerate(cast(list[dict[str, object]], payload["sheets"])):
        headers = cast(list[str], raw_sheet["headers"])
        cells = tuple(
            Cell(
                coordinate=CellCoordinate(1, column),
                row_index=1,
                column_index=column,
                value_type=ValueType.STRING,
                raw_value=header,
                display_value=header,
            )
            for column, header in enumerate(headers, 1)
        )
        sheets.append(
            Sheet(
                name=cast(str, raw_sheet["name"]),
                index=index,
                visibility=SheetVisibility.VISIBLE,
                max_row=1,
                max_column=len(headers),
                rows=(Row(index=1, cells=cells),),
            )
        )
    return RawWorkbook(
        id=uuid4(),
        source_file_id=uuid4(),
        filename=FilenameMetadata(
            name=cast(str, payload["filename"]),
            media_type=cast(str, payload["mediaType"]),
        ),
        format=WorkbookFormat(cast(str, payload["format"])),
        created_at=NOW,
        sheets=tuple(sheets),
    )


def _profile(
    *,
    name: str,
    filename_pattern: str,
    extension: str,
    media_type: str,
    sheet_name: str,
    columns: tuple[tuple[str, SupplierTargetField, DataType], ...],
    expected_sheets: tuple[str, ...] | None = None,
) -> SupplierProfile:
    profile = SupplierProfile.create(
        supplier_id=f"SUPPLIER-{name.upper()}",
        name=name,
        profile_id=uuid4(),
        now=NOW,
        file_rules=(
            SupplierFileRule(
                extensions=(extension,),
                media_types=(media_type,),
                filename_pattern=filename_pattern,
                expected_sheets=expected_sheets if expected_sheets is not None else (sheet_name,),
            ),
        ),
        sheet_mappings=(SupplierSheetMapping(sheet_name, SheetPurpose.PRODUCT_PRICE, True),),
        column_mappings=tuple(
            SupplierColumnMapping(source, target, data_type, True)
            for source, target, data_type in columns
        ),
    )
    return profile.activate(now=NOW + timedelta(minutes=1))


def _supplier_a_profile(
    *,
    filename_pattern: str = "price*",
    media_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
) -> SupplierProfile:
    return _profile(
        name="Supplier A",
        filename_pattern=filename_pattern,
        extension=".xlsx",
        media_type=media_type,
        sheet_name="Прайс",
        columns=(
            ("Артикул", SupplierTargetField.SUPPLIER_CODE, DataType.STRING),
            ("Цена", SupplierTargetField.PRICE, DataType.DECIMAL),
            ("Остаток", SupplierTargetField.STOCK, DataType.INTEGER),
        ),
    )


def test_filename_match_uses_case_insensitive_glob_patterns() -> None:
    workbook = _workbook(_fixture("supplier_a_match.json"))
    detector = SupplierProfileDetector(
        ProfileDetectionConfig(
            weights=ProfileDetectionWeights(filename=1.0, sheet=0.0, columns=0.0, extension=0.0)
        )
    )

    result = detector.detect(workbook, (_supplier_a_profile(filename_pattern="PRICE*"),))

    assert result.selected_profile is not None
    assert result.candidates[0].score == 1.0
    assert "filename pattern: matched" in result.candidates[0].reasons


def test_sheet_match_is_case_and_whitespace_insensitive() -> None:
    workbook = _workbook(_fixture("supplier_a_match.json"))
    profile = _profile(
        name="Sheet profile",
        filename_pattern="never*",
        extension=".xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        sheet_name="  прайс ",
        columns=(),
    )
    detector = SupplierProfileDetector(
        ProfileDetectionConfig(
            weights=ProfileDetectionWeights(filename=0.0, sheet=1.0, columns=0.0, extension=0.0)
        )
    )

    result = detector.detect(workbook, (profile,))

    assert result.selected_profile == profile
    assert result.candidates[0].score == 1.0


def test_column_match_reads_raw_header_cells_without_normalizing_values() -> None:
    workbook = _workbook(_fixture("supplier_a_match.json"))
    profile = _supplier_a_profile()
    detector = SupplierProfileDetector(
        ProfileDetectionConfig(
            weights=ProfileDetectionWeights(filename=0.0, sheet=0.0, columns=1.0, extension=0.0)
        )
    )

    result = detector.detect(workbook, (profile,))

    assert result.selected_profile == profile
    assert result.candidates[0].score == 1.0
    assert "columns: 3/3 matched" in result.candidates[0].reasons


def test_scoring_uses_configured_weights_and_normalizes_active_features() -> None:
    workbook = _workbook(_fixture("supplier_a_match.json"))
    profile = _supplier_a_profile(filename_pattern="other*")

    result = SupplierProfileDetector().detect(workbook, (profile,))

    assert result.candidates[0].score == 0.8
    assert result.candidates[0].confidence is DetectionConfidence.HIGH


def test_confidence_thresholds_are_explicit() -> None:
    assert confidence_for_score(0.95) is DetectionConfidence.HIGH
    assert confidence_for_score(0.60) is DetectionConfidence.MEDIUM
    assert confidence_for_score(0.30) is DetectionConfidence.LOW


def test_det_001_known_supplier_returns_profile_and_explainable_score() -> None:
    workbook = _workbook(_fixture("supplier_a_match.json"))
    profile = _supplier_a_profile()

    result = SupplierProfileDetector().detect(workbook, (profile,))

    assert result.selected_profile == profile
    assert result.status is DetectionStatus.MATCHED
    assert result.confidence is DetectionConfidence.HIGH
    assert {"filename pattern: matched", "sheet names: matched", "extension: matched"}.issubset(
        result.candidates[0].reasons
    )
    candidate = result.candidates[0]
    assert candidate.total_score == 100.0
    assert candidate.fingerprint.filename_pattern == "price*"
    assert candidate.fingerprint.sheet_names == ("прайс",)
    assert candidate.fingerprint.column_names == ("артикул", "цена", "остаток")
    assert candidate.score_components["filename"].to_dict() == {"score": 20.0, "weight": 20.0}
    assert candidate.score_components["columns"].to_dict() == {"score": 40.0, "weight": 40.0}
    assert not result.issues


def test_multiple_candidates_are_returned_without_losing_ranked_scores() -> None:
    workbook = _workbook(_fixture("supplier_a_match.json"))
    first = _supplier_a_profile(filename_pattern="price*")
    second = _supplier_a_profile(filename_pattern="*.xlsx")

    result = SupplierProfileDetector().detect(workbook, (first, second))

    assert len(result.candidates) == 2
    assert result.candidates[0].score == result.candidates[1].score == 1.0
    assert result.selected_profile is None


def test_det_002_unknown_supplier_returns_profile_not_found() -> None:
    workbook = _workbook(_fixture("unknown.json"))
    profile = _supplier_a_profile()

    result = SupplierProfileDetector().detect(workbook, (profile,))

    assert result.selected_profile is None
    assert result.status is DetectionStatus.PROFILE_NOT_FOUND
    assert not result.candidates
    assert result.issues[0].code is ReaderIssueCode.PROFILE_NOT_FOUND


def test_det_003_ambiguous_profiles_never_select_a_profile() -> None:
    workbook = _workbook(_fixture("ambiguous.json"))
    columns = (
        ("Артикул", SupplierTargetField.SUPPLIER_CODE, DataType.STRING),
        ("Цена", SupplierTargetField.PRICE, DataType.DECIMAL),
    )
    first = _profile(
        name="Ambiguous first",
        filename_pattern="other*",
        extension=".xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        sheet_name="Прайс",
        columns=columns,
    )
    second = _profile(
        name="Ambiguous second",
        filename_pattern="price*",
        extension=".csv",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        sheet_name="Прайс",
        columns=columns,
    )
    config = ProfileDetectionConfig(
        weights=ProfileDetectionWeights(
            filename=0.20,
            sheet=0.30,
            columns=0.32,
            extension=0.18,
        ),
    )

    result = SupplierProfileDetector(config).detect(workbook, (first, second))

    assert result.selected_profile is None
    assert result.status is DetectionStatus.AMBIGUOUS_PROFILE
    assert result.issues[0].code is ReaderIssueCode.AMBIGUOUS_PROFILE
    assert result.candidates[0].score == 0.82
    assert result.candidates[1].score == 0.80
    assert result.candidates[0].confidence is DetectionConfidence.HIGH
    assert result.confidence is DetectionConfidence.MEDIUM


def test_supplier_b_csv_profile_is_detected_from_independent_technical_signals() -> None:
    workbook = _workbook(_fixture("supplier_b_match.json"))
    profile = _profile(
        name="Supplier B",
        filename_pattern="stock_*.csv",
        extension=".csv",
        media_type="text/csv",
        sheet_name="Остатки",
        columns=(
            ("Код", SupplierTargetField.SUPPLIER_CODE, DataType.STRING),
            ("Цена", SupplierTargetField.PRICE, DataType.DECIMAL),
            ("Наличие", SupplierTargetField.STOCK, DataType.INTEGER),
        ),
    )

    result = SupplierProfileDetector().detect(workbook, (profile,))

    assert result.selected_profile == profile
    assert profile.status is ProfileStatus.ACTIVE


def test_extra_columns_do_not_penalize_a_profile_match() -> None:
    workbook = _workbook(_fixture("extra_columns.json"))
    profile = _supplier_a_profile()
    detector = SupplierProfileDetector(
        ProfileDetectionConfig(
            weights=ProfileDetectionWeights(filename=0.0, sheet=0.0, columns=1.0, extension=0.0)
        )
    )

    result = detector.detect(workbook, (profile,))

    assert result.selected_profile == profile
    assert result.candidates[0].score == 1.0


def test_extra_sheets_do_not_penalize_a_profile_match() -> None:
    workbook = _workbook(_fixture("extra_sheets.json"))
    profile = _supplier_a_profile()
    detector = SupplierProfileDetector(
        ProfileDetectionConfig(
            weights=ProfileDetectionWeights(filename=0.0, sheet=1.0, columns=0.0, extension=0.0)
        )
    )

    result = detector.detect(workbook, (profile,))

    assert result.selected_profile == profile
    assert result.candidates[0].score == 1.0


def test_det_005_partial_match_is_reported_as_a_fractional_score() -> None:
    workbook = _workbook(_fixture("partial_sheet.json"))
    profile = _profile(
        name="Partial sheet profile",
        filename_pattern="never*",
        extension=".xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        sheet_name="Прайс",
        expected_sheets=("Прайс", "Остатки"),
        columns=(),
    )
    detector = SupplierProfileDetector(
        ProfileDetectionConfig(
            weights=ProfileDetectionWeights(filename=0.0, sheet=1.0, columns=0.0, extension=0.0)
        )
    )

    result = detector.detect(workbook, (profile,))

    assert result.selected_profile == profile
    assert result.candidates[0].score == 0.5
    assert result.confidence is DetectionConfidence.MEDIUM


def test_media_type_weight_changes_the_detection_score() -> None:
    workbook = _workbook(_fixture("supplier_a_match.json"))
    profile = _supplier_a_profile(media_type="text/csv")

    unweighted = SupplierProfileDetector().detect(workbook, (profile,))
    weighted = SupplierProfileDetector(
        ProfileDetectionConfig(
            weights=ProfileDetectionWeights(
                filename=0.0,
                sheet=0.0,
                columns=0.4,
                extension=0.0,
                media_type=0.6,
            )
        )
    ).detect(workbook, (profile,))

    assert unweighted.selected_profile == profile
    assert unweighted.candidates[0].score == 1.0
    assert weighted.selected_profile is None
    assert weighted.candidates[0].score == 0.4
    assert weighted.issues[0].code is ReaderIssueCode.PROFILE_NOT_FOUND


def test_det_004_changed_template_has_distinct_blocking_status() -> None:
    workbook = _workbook(_fixture("template_changed.json"))
    profile = _supplier_a_profile()

    result = SupplierProfileDetector().detect(workbook, (profile,))

    assert result.selected_profile is None
    assert result.status is DetectionStatus.TEMPLATE_CHANGED
    assert result.confidence is DetectionConfidence.LOW
    assert result.candidates[0].score == 0.3
    assert result.issues[0].code is ReaderIssueCode.TEMPLATE_CHANGED


def test_det_006_invalid_file_is_not_misclassified_as_a_supplier() -> None:
    workbook = _workbook(_fixture("unknown.json"))

    result = SupplierProfileDetector().detect(workbook, (_supplier_a_profile(),))

    assert result.status is DetectionStatus.PROFILE_NOT_FOUND
    assert result.selected_profile is None


def test_det_007_large_workbook_is_detected_without_losing_fingerprint() -> None:
    workbook = _workbook(_fixture("supplier_a_match.json"))
    header = workbook.sheets[0].rows[0]
    rows = (header,) + tuple(
        Row(
            index=index,
            cells=(
                Cell(
                    coordinate=CellCoordinate(index, 1),
                    row_index=index,
                    column_index=1,
                    value_type=ValueType.STRING,
                    raw_value=f"SKU-{index}",
                ),
            ),
        )
        for index in range(2, 5_002)
    )
    large_sheet = replace(workbook.sheets[0], max_row=5_001, rows=rows)
    large_workbook = replace(workbook, sheets=(large_sheet,))

    result = SupplierProfileDetector().detect(large_workbook, (_supplier_a_profile(),))

    assert result.status is DetectionStatus.MATCHED
    assert result.candidates[0].fingerprint.column_names == ("артикул", "цена", "остаток")


def test_det_008_result_contract_contains_ui_explanation_fields() -> None:
    result = SupplierProfileDetector().detect(
        _workbook(_fixture("supplier_a_match.json")),
        (_supplier_a_profile(),),
    )

    payload = result.to_dict()
    candidate = cast(list[dict[str, object]], payload["candidates"])[0]
    assert payload["status"] == "MATCHED"
    assert {"profileId", "totalScore", "confidence", "reasons", "scoreComponents"} <= set(candidate)


def test_det_009_manager_approval_has_ranked_candidates_without_auto_selection() -> None:
    workbook = _workbook(_fixture("supplier_a_match.json"))
    first = _supplier_a_profile(filename_pattern="price*")
    second = _supplier_a_profile(filename_pattern="*.xlsx")

    result = SupplierProfileDetector().detect(workbook, (first, second))

    assert result.status is DetectionStatus.AMBIGUOUS_PROFILE
    assert result.selected_profile is None
    assert [candidate.profile_id for candidate in result.candidates] == sorted(
        (first.id, second.id), key=str
    )


def test_no_profile_result_is_low_confidence() -> None:
    workbook = _workbook(_fixture("unknown.json"))

    result = SupplierProfileDetector().detect(workbook, ())

    assert result.selected_profile is None
    assert result.confidence is DetectionConfidence.LOW
    assert result.issues[0].code is ReaderIssueCode.PROFILE_NOT_FOUND


def test_detection_result_rejects_high_confidence_without_selection() -> None:
    with pytest.raises(InvalidValue, match="confidence"):
        DetectionResult(
            selected_profile=None,
            confidence=DetectionConfidence.HIGH,
        )
