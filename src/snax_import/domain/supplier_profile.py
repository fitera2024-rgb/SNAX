from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from snax_import.domain.errors import InvalidTransition, InvalidValue


def _validate_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise InvalidValue(field_name, "Timestamp должен быть timezone-aware UTC")


def _timestamp(value: datetime | None) -> datetime:
    result = value or datetime.now(UTC)
    _validate_utc(result, "timestamp")
    return result


def _require_text(value: str, field_name: str, *, maximum: int = 500) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidValue(field_name, "Значение должно содержать непустой текст")
    if len(value) > maximum:
        raise InvalidValue(field_name, f"Длина не может превышать {maximum} символов")


def _require_enum(value: object, enum_type: type[StrEnum], field_name: str) -> None:
    if not isinstance(value, enum_type):
        raise InvalidValue(field_name, f"Значение должно быть одним из {enum_type.__name__}")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class ProfileStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class SheetPurpose(StrEnum):
    PRODUCT_PRICE = "PRODUCT_PRICE"
    STOCK = "STOCK"
    CATALOG = "CATALOG"
    REFERENCE = "REFERENCE"
    UNKNOWN = "UNKNOWN"


class TargetField(StrEnum):
    SUPPLIER_CODE = "SUPPLIER_CODE"
    NAME = "NAME"
    DESCRIPTION = "DESCRIPTION"
    PRICE = "PRICE"
    STOCK = "STOCK"
    BARCODE = "BARCODE"
    UNIT = "UNIT"
    CATEGORY = "CATEGORY"
    UNKNOWN = "UNKNOWN"


class DataType(StrEnum):
    STRING = "STRING"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    DATE = "DATE"
    BOOLEAN = "BOOLEAN"
    UNKNOWN = "UNKNOWN"


class ValidationRuleType(StrEnum):
    REQUIRED = "REQUIRED"
    MAX_LENGTH = "MAX_LENGTH"
    REGEX = "REGEX"
    VALUE_RANGE = "VALUE_RANGE"


class ValidationSeverity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    CRITICAL = "CRITICAL"


# Explicit names mirror the task vocabulary while the shorter names remain
# compatible with the first in-progress implementation in this checkout.
SupplierProfileStatus = ProfileStatus
SupplierTargetField = TargetField
SupplierDataType = DataType
SupplierValidationRuleType = ValidationRuleType


@dataclass(frozen=True, slots=True)
class SupplierFileRule:
    extensions: tuple[str, ...]
    media_types: tuple[str, ...]
    filename_pattern: str | None
    expected_sheets: tuple[str, ...]

    def __post_init__(self) -> None:
        extensions = tuple(self.extensions)
        media_types = tuple(self.media_types)
        expected_sheets = tuple(self.expected_sheets)
        object.__setattr__(self, "extensions", extensions)
        object.__setattr__(self, "media_types", media_types)
        object.__setattr__(self, "expected_sheets", expected_sheets)
        if not extensions and not media_types:
            raise InvalidValue("fileRule", "Нужно указать extension или media type")
        if any(not isinstance(item, str) or not item.startswith(".") for item in extensions):
            raise InvalidValue("extensions", "Расширение должно начинаться с точки")
        if len(set(extensions)) != len(extensions):
            raise InvalidValue("extensions", "Расширения не должны повторяться")
        if any(not isinstance(item, str) or not item.strip() for item in media_types):
            raise InvalidValue("mediaTypes", "Media type должен быть непустым")
        if len(set(media_types)) != len(media_types):
            raise InvalidValue("mediaTypes", "Media types не должны повторяться")
        if any(not isinstance(item, str) or not item.strip() for item in expected_sheets):
            raise InvalidValue("expectedSheets", "Имя листа должно быть непустым")
        if len(set(expected_sheets)) != len(expected_sheets):
            raise InvalidValue("expectedSheets", "Листы не должны повторяться")
        if self.filename_pattern is not None and not self.filename_pattern.strip():
            raise InvalidValue("filenamePattern", "Pattern не может быть пустым")

    def to_dict(self) -> dict[str, object]:
        return {
            "extensions": list(self.extensions),
            "mediaTypes": list(self.media_types),
            "filenamePattern": self.filename_pattern,
            "expectedSheets": list(self.expected_sheets),
        }


@dataclass(frozen=True, slots=True)
class SupplierSheetMapping:
    sheet_name: str
    purpose: SheetPurpose
    required: bool
    priority: int = 0

    def __post_init__(self) -> None:
        _require_text(self.sheet_name, "sheetName", maximum=200)
        _require_enum(self.purpose, SheetPurpose, "purpose")
        if not isinstance(self.required, bool):
            raise InvalidValue("required", "Признак required должен быть boolean")
        if (
            isinstance(self.priority, bool)
            or not isinstance(self.priority, int)
            or self.priority < 0
        ):
            raise InvalidValue("priority", "Priority не может быть отрицательным")

    def to_dict(self) -> dict[str, object]:
        return {
            "sheetName": self.sheet_name,
            "purpose": self.purpose.value,
            "required": self.required,
            "priority": self.priority,
        }


@dataclass(frozen=True, slots=True)
class SupplierColumnMapping:
    source_column: str
    target_field: TargetField
    data_type: DataType
    required: bool
    description: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_column, "sourceColumn", maximum=200)
        _require_enum(self.target_field, TargetField, "targetField")
        _require_enum(self.data_type, DataType, "dataType")
        if not isinstance(self.required, bool):
            raise InvalidValue("required", "Признак required должен быть boolean")
        if self.description is not None and len(self.description) > 1000:
            raise InvalidValue("description", "Описание не может превышать 1000 символов")

    def to_dict(self) -> dict[str, object]:
        return {
            "sourceColumn": self.source_column,
            "targetField": self.target_field.value,
            "dataType": self.data_type.value,
            "required": self.required,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class SupplierValidationRule:
    field: str
    rule_type: ValidationRuleType
    value: object | None = None
    severity: ValidationSeverity = ValidationSeverity.ERROR

    def __post_init__(self) -> None:
        _require_text(self.field, "field", maximum=200)
        _require_enum(self.rule_type, ValidationRuleType, "ruleType")
        _require_enum(self.severity, ValidationSeverity, "severity")
        if self.rule_type is ValidationRuleType.REQUIRED and self.value is not None:
            raise InvalidValue("value", "REQUIRED не принимает value")
        if self.rule_type is ValidationRuleType.MAX_LENGTH and (
            not isinstance(self.value, int) or isinstance(self.value, bool) or self.value < 1
        ):
            raise InvalidValue("value", "MAX_LENGTH требует положительное целое число")
        if self.rule_type is ValidationRuleType.REGEX:
            if not isinstance(self.value, str) or not self.value:
                raise InvalidValue("value", "REGEX требует непустую строку")
            try:
                re.compile(self.value)
            except re.error as error:
                raise InvalidValue("value", "REGEX содержит ошибочный шаблон") from error
        if self.rule_type is ValidationRuleType.VALUE_RANGE and (
            not isinstance(self.value, Mapping)
            or not ("minimum" in self.value or "maximum" in self.value)
        ):
            raise InvalidValue("value", "VALUE_RANGE требует minimum или maximum")

    def to_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "ruleType": self.rule_type.value,
            "value": self.value,
            "severity": self.severity.value,
        }


@dataclass(frozen=True, slots=True)
class SupplierProfileVersion:
    id: UUID
    profile_id: UUID
    version_number: int
    schema_version: str
    effective_from: datetime | None
    effective_to: datetime | None
    created_at: datetime
    created_by: str
    file_rules: tuple[SupplierFileRule, ...] = ()
    sheet_mappings: tuple[SupplierSheetMapping, ...] = ()
    column_mappings: tuple[SupplierColumnMapping, ...] = ()
    validation_rules: tuple[SupplierValidationRule, ...] = ()

    def __post_init__(self) -> None:
        if self.version_number < 1:
            raise InvalidValue("versionNumber", "Номер версии должен быть >= 1")
        _require_text(self.schema_version, "schemaVersion", maximum=50)
        _require_text(self.created_by, "createdBy", maximum=200)
        for field_name, value in (
            ("effectiveFrom", self.effective_from),
            ("effectiveTo", self.effective_to),
            ("createdAt", self.created_at),
        ):
            if value is not None:
                _validate_utc(value, field_name)
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise InvalidValue("effectiveTo", "effectiveTo не может быть раньше effectiveFrom")
        file_rules = tuple(self.file_rules)
        sheet_mappings = tuple(self.sheet_mappings)
        column_mappings = tuple(self.column_mappings)
        validation_rules = tuple(self.validation_rules)
        object.__setattr__(self, "file_rules", file_rules)
        object.__setattr__(self, "sheet_mappings", sheet_mappings)
        object.__setattr__(self, "column_mappings", column_mappings)
        object.__setattr__(self, "validation_rules", validation_rules)
        sheet_names = [mapping.sheet_name for mapping in sheet_mappings]
        source_columns = [mapping.source_column for mapping in column_mappings]
        if len(set(sheet_names)) != len(sheet_names):
            raise InvalidValue("sheetMappings", "Лист не может быть описан дважды")
        if len(set(source_columns)) != len(source_columns):
            raise InvalidValue("columnMappings", "Source column не может быть описан дважды")
        target_fields = [mapping.target_field.value for mapping in column_mappings]
        if len(set(target_fields)) != len(target_fields):
            raise InvalidValue("columnMappings", "Target field не может быть описан дважды")
        rule_keys = [(rule.field.casefold(), rule.rule_type.value) for rule in validation_rules]
        if len(set(rule_keys)) != len(rule_keys):
            raise InvalidValue("validationRules", "Правило для поля не должно дублироваться")

    @classmethod
    def create(
        cls,
        *,
        profile_id: UUID,
        version_number: int,
        schema_version: str,
        created_by: str,
        now: datetime | None = None,
        effective_from: datetime | None = None,
        file_rules: tuple[SupplierFileRule, ...] = (),
        sheet_mappings: tuple[SupplierSheetMapping, ...] = (),
        column_mappings: tuple[SupplierColumnMapping, ...] = (),
        validation_rules: tuple[SupplierValidationRule, ...] = (),
    ) -> Self:
        timestamp = _timestamp(now)
        if effective_from is not None:
            _validate_utc(effective_from, "effectiveFrom")
        return cls(
            id=uuid4(),
            profile_id=profile_id,
            version_number=version_number,
            schema_version=schema_version,
            effective_from=effective_from,
            effective_to=None,
            created_at=timestamp,
            created_by=created_by,
            file_rules=file_rules,
            sheet_mappings=sheet_mappings,
            column_mappings=column_mappings,
            validation_rules=validation_rules,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "profileId": str(self.profile_id),
            "versionNumber": self.version_number,
            "schemaVersion": self.schema_version,
            "effectiveFrom": _iso(self.effective_from),
            "effectiveTo": _iso(self.effective_to),
            "createdAt": self.created_at.isoformat(),
            "createdBy": self.created_by,
            "fileRules": [rule.to_dict() for rule in self.file_rules],
            "sheetMappings": [mapping.to_dict() for mapping in self.sheet_mappings],
            "columnMappings": [mapping.to_dict() for mapping in self.column_mappings],
            "validationRules": [rule.to_dict() for rule in self.validation_rules],
        }


@dataclass(frozen=True, slots=True)
class SupplierProfile:
    id: UUID
    supplier_id: str
    name: str
    description: str | None
    status: ProfileStatus
    current_version: int | None
    created_at: datetime
    updated_at: datetime
    versions: tuple[SupplierProfileVersion, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_text(self.supplier_id, "supplierId", maximum=100)
        _require_text(self.name, "name", maximum=200)
        _require_enum(self.status, ProfileStatus, "status")
        if self.description is not None and len(self.description) > 2000:
            raise InvalidValue("description", "Описание не может превышать 2000 символов")
        _validate_utc(self.created_at, "createdAt")
        _validate_utc(self.updated_at, "updatedAt")
        if self.updated_at < self.created_at:
            raise InvalidValue("updatedAt", "updatedAt не может быть раньше createdAt")
        versions = tuple(self.versions)
        object.__setattr__(self, "versions", versions)
        version_numbers = [version.version_number for version in versions]
        if len(set(version_numbers)) != len(version_numbers):
            raise InvalidValue("versions", "Номера версий не должны повторяться")
        if version_numbers != sorted(version_numbers):
            raise InvalidValue("versions", "Версии должны быть упорядочены")
        if version_numbers and version_numbers != list(range(1, len(version_numbers) + 1)):
            raise InvalidValue("versions", "Версии должны начинаться с 1 и идти последовательно")
        if any(version.profile_id != self.id for version in versions):
            raise InvalidValue("versions", "Версия должна ссылаться на свой профиль")
        if self.current_version is not None and self.current_version not in version_numbers:
            raise InvalidValue("currentVersion", "Текущая версия отсутствует в истории")
        if self.current_version is not None and self.current_version < 1:
            raise InvalidValue("currentVersion", "Текущая версия должна быть >= 1")
        if self.status is ProfileStatus.ACTIVE:
            if self.current_version is None:
                raise InvalidValue("currentVersion", "ACTIVE профиль требует текущую версию")
            current = self.version(self.current_version)
            if current.effective_from is None or current.effective_to is not None:
                raise InvalidValue("currentVersion", "ACTIVE профиль требует активную версию")

    @classmethod
    def create(
        cls,
        *,
        supplier_id: str,
        name: str,
        description: str | None = None,
        profile_id: UUID | None = None,
        now: datetime | None = None,
    ) -> Self:
        timestamp = _timestamp(now)
        return cls(
            id=profile_id or uuid4(),
            supplier_id=supplier_id,
            name=name,
            description=description,
            status=ProfileStatus.DRAFT,
            current_version=None,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def version(self, version_number: int | None = None) -> SupplierProfileVersion:
        requested = version_number if version_number is not None else self.current_version
        if requested is None:
            raise InvalidValue("currentVersion", "У профиля нет текущей версии")
        for version in self.versions:
            if version.version_number == requested:
                return version
        raise InvalidValue("currentVersion", "Версия отсутствует в истории")

    def create_version(
        self,
        *,
        schema_version: str,
        created_by: str,
        now: datetime | None = None,
        file_rules: tuple[SupplierFileRule, ...] = (),
        sheet_mappings: tuple[SupplierSheetMapping, ...] = (),
        column_mappings: tuple[SupplierColumnMapping, ...] = (),
        validation_rules: tuple[SupplierValidationRule, ...] = (),
    ) -> Self:
        if self.status is ProfileStatus.ARCHIVED:
            raise InvalidTransition(self.status.value, "CREATE_VERSION")
        timestamp = _timestamp(now)
        version_number = max((version.version_number for version in self.versions), default=0) + 1
        new_version = SupplierProfileVersion.create(
            profile_id=self.id,
            version_number=version_number,
            schema_version=schema_version,
            created_by=created_by,
            now=timestamp,
            effective_from=timestamp if self.status is ProfileStatus.ACTIVE else None,
            file_rules=file_rules,
            sheet_mappings=sheet_mappings,
            column_mappings=column_mappings,
            validation_rules=validation_rules,
        )
        versions = list(self.versions)
        if self.status is ProfileStatus.ACTIVE:
            current = self.version()
            versions = [
                replace(version, effective_to=timestamp) if version.id == current.id else version
                for version in versions
            ]
        return replace(
            self,
            current_version=version_number,
            updated_at=timestamp,
            versions=tuple((*versions, new_version)),
        )

    def activate(self, *, now: datetime | None = None) -> Self:
        if self.status is ProfileStatus.ARCHIVED:
            raise InvalidTransition(self.status.value, ProfileStatus.ACTIVE.value)
        if self.status is ProfileStatus.ACTIVE:
            return self
        timestamp = _timestamp(now)
        current = self.version()
        activated = replace(current, effective_from=current.effective_from or timestamp)
        versions = [activated if version.id == current.id else version for version in self.versions]
        versions = [
            replace(version, effective_to=timestamp)
            if version.id != current.id
            and version.effective_from is not None
            and version.effective_to is None
            else version
            for version in versions
        ]
        return replace(
            self,
            status=ProfileStatus.ACTIVE,
            updated_at=timestamp,
            versions=tuple(versions),
        )

    def archive(self, *, now: datetime | None = None) -> Self:
        if self.status is ProfileStatus.ARCHIVED:
            return self
        timestamp = _timestamp(now)
        return replace(self, status=ProfileStatus.ARCHIVED, updated_at=timestamp)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "supplierId": self.supplier_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "currentVersion": self.current_version,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
            "versions": [version.to_dict() for version in self.versions],
        }

    @property
    def active_version(self) -> SupplierProfileVersion | None:
        if self.current_version is None:
            return None
        return next(
            (
                version
                for version in self.versions
                if version.version_number == self.current_version
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class SupplierProfileValidationIssue:
    field: str
    message: str


class SupplierProfileValidator:
    """Framework-neutral aggregate validation used before persistence."""

    def collect(self, profile: SupplierProfile) -> tuple[SupplierProfileValidationIssue, ...]:
        issues: list[SupplierProfileValidationIssue] = []
        version_numbers = [version.version_number for version in profile.versions]
        if version_numbers and version_numbers != list(range(1, len(version_numbers) + 1)):
            issues.append(
                SupplierProfileValidationIssue(
                    "versions", "Номера версий должны начинаться с 1 и идти последовательно"
                )
            )
        if profile.status is ProfileStatus.ACTIVE and profile.active_version is None:
            issues.append(
                SupplierProfileValidationIssue(
                    "currentVersion", "ACTIVE профиль требует текущую версию"
                )
            )
        if (
            profile.status is ProfileStatus.ACTIVE
            and profile.active_version is not None
            and (
                profile.active_version.effective_from is None
                or profile.active_version.effective_to is not None
            )
        ):
            issues.append(
                SupplierProfileValidationIssue(
                    "currentVersion", "Текущая версия ACTIVE профиля должна быть открыта"
                )
            )
        return tuple(issues)

    def validate(self, profile: SupplierProfile) -> None:
        issues = self.collect(profile)
        if issues:
            raise InvalidValue(issues[0].field, issues[0].message)

    def is_valid(self, profile: SupplierProfile) -> bool:
        return not self.collect(profile)


__all__ = [
    "DataType",
    "ProfileStatus",
    "SheetPurpose",
    "SupplierColumnMapping",
    "SupplierFileRule",
    "SupplierProfile",
    "SupplierProfileStatus",
    "SupplierProfileValidationIssue",
    "SupplierProfileValidator",
    "SupplierProfileVersion",
    "SupplierSheetMapping",
    "SupplierValidationRule",
    "SupplierValidationRuleType",
    "SupplierTargetField",
    "SupplierDataType",
    "TargetField",
    "ValidationRuleType",
    "ValidationSeverity",
]
