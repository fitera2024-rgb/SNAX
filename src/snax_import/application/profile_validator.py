from __future__ import annotations

from dataclasses import dataclass

from snax_import.domain.errors import DomainError
from snax_import.domain.supplier_profile import (
    ProfileStatus,
    SupplierProfile,
    SupplierProfileVersion,
)


@dataclass(frozen=True, slots=True)
class ProfileValidationIssue:
    field: str
    code: str
    message: str


class ProfileValidationError(DomainError):
    def __init__(self, issues: tuple[ProfileValidationIssue, ...]) -> None:
        self.issues = issues
        super().__init__("Supplier Profile не прошёл валидацию")


class ProfileValidator:
    def validate(self, profile: SupplierProfile) -> tuple[ProfileValidationIssue, ...]:
        issues: list[ProfileValidationIssue] = []
        versions = profile.versions
        version_numbers = sorted(version.version_number for version in versions)
        if version_numbers and version_numbers != list(range(1, len(version_numbers) + 1)):
            issues.append(
                ProfileValidationIssue(
                    "versions",
                    "VERSION_SEQUENCE_INVALID",
                    "Номера версий должны начинаться с 1 и идти последовательно",
                )
            )
        if profile.status is ProfileStatus.ACTIVE:
            if profile.current_version is None:
                issues.append(
                    ProfileValidationIssue(
                        "currentVersion",
                        "ACTIVE_VERSION_REQUIRED",
                        "ACTIVE профиль требует currentVersion",
                    )
                )
            else:
                current = self._find_version(versions, profile.current_version)
                if current is None:
                    issues.append(
                        ProfileValidationIssue(
                            "currentVersion",
                            "CURRENT_VERSION_NOT_FOUND",
                            "Текущая версия отсутствует в истории",
                        )
                    )
                elif current.effective_from is None or current.effective_to is not None:
                    issues.append(
                        ProfileValidationIssue(
                            "currentVersion",
                            "CURRENT_VERSION_NOT_ACTIVE",
                            "Текущая версия ACTIVE профиля должна быть effective",
                        )
                    )
        for index, version in enumerate(versions):
            self._validate_version(version, index, issues)
        return tuple(issues)

    def validate_or_raise(self, profile: SupplierProfile) -> None:
        issues = self.validate(profile)
        if issues:
            raise ProfileValidationError(issues)

    @staticmethod
    def _find_version(
        versions: tuple[SupplierProfileVersion, ...], version_number: int
    ) -> SupplierProfileVersion | None:
        return next(
            (version for version in versions if version.version_number == version_number),
            None,
        )

    @staticmethod
    def _validate_version(
        version: SupplierProfileVersion,
        index: int,
        issues: list[ProfileValidationIssue],
    ) -> None:
        prefix = f"versions[{index}]"
        if version.version_number < 1:
            issues.append(
                ProfileValidationIssue(
                    f"{prefix}.versionNumber",
                    "VERSION_NUMBER_INVALID",
                    "Номер версии должен быть >= 1",
                )
            )
        for mapping_index, sheet_mapping in enumerate(version.sheet_mappings):
            if not sheet_mapping.sheet_name.strip():
                issues.append(
                    ProfileValidationIssue(
                        f"{prefix}.sheetMappings[{mapping_index}].sheetName",
                        "SHEET_NAME_REQUIRED",
                        "Имя листа обязательно",
                    )
                )
        for mapping_index, column_mapping in enumerate(version.column_mappings):
            if not column_mapping.source_column.strip():
                issues.append(
                    ProfileValidationIssue(
                        f"{prefix}.columnMappings[{mapping_index}].sourceColumn",
                        "SOURCE_COLUMN_REQUIRED",
                        "Исходная колонка обязательна",
                    )
                )
        for rule_index, rule in enumerate(version.validation_rules):
            if not rule.field.strip():
                issues.append(
                    ProfileValidationIssue(
                        f"{prefix}.validationRules[{rule_index}].field",
                        "RULE_FIELD_REQUIRED",
                        "Поле правила обязательно",
                    )
                )


__all__ = [
    "ProfileValidationError",
    "ProfileValidationIssue",
    "ProfileValidator",
]
