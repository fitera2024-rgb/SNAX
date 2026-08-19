# Supplier profile detection test matrix

Scope: `TASK-011`, `FR-SVC-009`, `FR-SVC-010`.

All fixtures are synthetic. Reader adapters, `RawWorkbook`, UI, 1C, Mapping Engine, and
normalization are not modified by these scenarios.

| ID | Scenario | Expected result | Automated evidence |
|---|---|---|---|
| DET-001 | Known supplier | `MATCHED`, selected profile, complete explanation | `test_det_001_known_supplier_returns_profile_and_explainable_score` |
| DET-002 | Unknown supplier | `PROFILE_NOT_FOUND`, no selection, `LOW` | `test_det_002_unknown_supplier_returns_profile_not_found` |
| DET-003 | Scores 82 and 80 | `AMBIGUOUS_PROFILE`, no selection, result confidence `MEDIUM` | `test_det_003_ambiguous_profiles_never_select_a_profile` |
| DET-004 | Known filename/format, changed sheet and columns | `TEMPLATE_CHANGED`, no selection | `test_det_004_changed_template_has_distinct_blocking_status` |
| DET-005 | Partial structural match | Fractional score and configured selection behavior | `test_det_005_partial_match_is_reported_as_a_fractional_score` |
| DET-006 | Invalid/unsupported file metadata | Not misclassified as a supplier | `test_det_006_invalid_file_is_not_misclassified_as_a_supplier`; reader failure paths remain in reader suites |
| DET-007 | Large raw workbook | Detection completes and fingerprint is preserved | `test_det_007_large_workbook_is_detected_without_losing_fingerprint` (5,001 rows) |
| DET-008 | UI consumption scenario | Serialized result includes status, ranking, reasons, and score components | `test_det_008_result_contract_contains_ui_explanation_fields` |
| DET-009 | Manager approval hand-off | Ambiguous candidates remain ranked and no profile is auto-selected | `test_det_009_manager_approval_has_ranked_candidates_without_auto_selection` |

Contract scenarios are validated from:

- `profile-detection.example.json` — success;
- `profile-detection.ambiguous.example.json` — ambiguity;
- `profile-detection.template-changed.example.json` — known supplier with drift;
- `profile-detection.unknown.example.json` — unknown supplier.
