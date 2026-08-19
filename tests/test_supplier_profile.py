from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from snax_import.domain.errors import InvalidValue
from snax_import.domain.supplier_profile import (
    DataType,
    ProfileStatus,
    SheetPurpose,
    SupplierColumnMapping,
    SupplierFileRule,
    SupplierProfile,
    SupplierProfileValidator,
    SupplierProfileVersion,
    SupplierSheetMapping,
    SupplierTargetField,
    SupplierValidationRule,
    ValidationRuleType,
    ValidationSeverity,
)

NOW = datetime(2026, 8, 19, tzinfo=UTC)


def _profile() -> SupplierProfile:
    return SupplierProfile.create(
        supplier_id="SYNTHETIC-SUPPLIER",
        name="Synthetic profile",
        description="Test only",
        now=NOW,
    )


def _version_mappings() -> dict[str, tuple[object, ...]]:
    return {
        "file_rules": (
            SupplierFileRule(
                extensions=(".xlsx", ".csv"),
                media_types=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
                filename_pattern="price*",
                expected_sheets=("Price",),
            ),
        ),
        "sheet_mappings": (
            SupplierSheetMapping("Price", SheetPurpose.PRODUCT_PRICE, True, priority=1),
        ),
        "column_mappings": (
            SupplierColumnMapping("Code", SupplierTargetField.SUPPLIER_CODE, DataType.STRING, True),
            SupplierColumnMapping("Name", SupplierTargetField.NAME, DataType.STRING, True),
        ),
        "validation_rules": (
            SupplierValidationRule(
                "Code", ValidationRuleType.REQUIRED, severity=ValidationSeverity.ERROR
            ),
        ),
    }


def test_profile_create_and_status_transitions_are_immutable() -> None:
    profile = _profile()
    assert profile.status is ProfileStatus.DRAFT
    draft_with_version = profile.create_version(
        schema_version="1.0.0",
        created_by="tester",
        now=NOW,
        **_version_mappings(),
    )
    assert draft_with_version.current_version == 1
    assert draft_with_version.status is ProfileStatus.DRAFT

    active = draft_with_version.activate(now=NOW + timedelta(minutes=1))
    assert active.status is ProfileStatus.ACTIVE
    assert active.version().effective_from == NOW + timedelta(minutes=1)

    with pytest.raises(FrozenInstanceError):
        active.name = "not supported"  # type: ignore[misc]


def test_active_version_is_replaced_by_append_only_version() -> None:
    profile = _profile().create_version(
        schema_version="1.0.0", created_by="tester", now=NOW, **_version_mappings()
    )
    active = profile.activate(now=NOW)
    versioned = active.create_version(
        schema_version="1.1.0", created_by="tester", now=NOW + timedelta(days=1)
    )

    assert versioned.status is ProfileStatus.ACTIVE
    assert versioned.current_version == 2
    assert len(versioned.versions) == 2
    assert versioned.versions[0].effective_to == NOW + timedelta(days=1)
    assert versioned.versions[1].effective_to is None
    assert active.versions[0].effective_to is None


def test_archive_closes_open_versions_and_preserves_history() -> None:
    profile = _profile().create_version(schema_version="1.0.0", created_by="tester", now=NOW)
    active = profile.activate(now=NOW)
    archived = active.archive(now=NOW + timedelta(hours=1))

    assert archived.status is ProfileStatus.ARCHIVED
    assert archived.current_version == 1
    assert len(archived.versions) == 1
    assert archived.versions[0].effective_to is None
    assert active.status is ProfileStatus.ACTIVE


def test_invalid_mapping_and_rule_values_are_rejected() -> None:
    with pytest.raises(InvalidValue):
        SupplierColumnMapping("Code", "NOT_A_TARGET", DataType.STRING, True)  # type: ignore[arg-type]
    with pytest.raises(InvalidValue):
        SupplierColumnMapping("Code", SupplierTargetField.SUPPLIER_CODE, "FLOAT", True)  # type: ignore[arg-type]
    with pytest.raises(InvalidValue):
        SupplierValidationRule("Code", ValidationRuleType.MAX_LENGTH, value=0)
    with pytest.raises(InvalidValue):
        SupplierValidationRule("Code", ValidationRuleType.REGEX, value="[")

    duplicate_target = (
        SupplierColumnMapping("Code", SupplierTargetField.SUPPLIER_CODE, DataType.STRING, True),
        SupplierColumnMapping(
            "Alt code", SupplierTargetField.SUPPLIER_CODE, DataType.STRING, False
        ),
    )
    with pytest.raises(InvalidValue):
        SupplierProfileVersion.create(
            profile_id=uuid4(),
            version_number=1,
            schema_version="1.0.0",
            created_by="tester",
            now=NOW,
            column_mappings=duplicate_target,
        )


def test_domain_validator_accepts_valid_profile_and_rejects_active_without_version() -> None:
    validator = SupplierProfileValidator()
    assert validator.is_valid(_profile())
    with pytest.raises(InvalidValue):
        SupplierProfile(
            id=uuid4(),
            supplier_id="SYNTHETIC-SUPPLIER",
            name="Invalid active profile",
            description=None,
            status=ProfileStatus.ACTIVE,
            current_version=1,
            created_at=NOW,
            updated_at=NOW,
            versions=(),
        )
