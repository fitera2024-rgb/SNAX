from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from snax_import.application.profile_validator import ProfileValidator
from snax_import.domain.supplier_profile import (
    SupplierColumnMapping,
    SupplierFileRule,
    SupplierProfile,
    SupplierProfileVersion,
    SupplierSheetMapping,
    SupplierValidationRule,
)
from snax_import.ports.supplier_profile_repository import SupplierProfileRepository


class SupplierProfileNotFound(LookupError):
    """Requested Supplier Profile does not exist."""


@dataclass(frozen=True, slots=True)
class CreateSupplierProfile:
    repository: SupplierProfileRepository
    validator: ProfileValidator = field(default_factory=ProfileValidator)

    def execute(
        self,
        *,
        supplier_id: str,
        name: str,
        description: str | None = None,
        schema_version: str | None = None,
        created_by: str = "system",
        file_rules: tuple[SupplierFileRule, ...] = (),
        sheet_mappings: tuple[SupplierSheetMapping, ...] = (),
        column_mappings: tuple[SupplierColumnMapping, ...] = (),
        validation_rules: tuple[SupplierValidationRule, ...] = (),
        now: datetime | None = None,
    ) -> SupplierProfile:
        initial_schema_version = schema_version if schema_version is not None else "1.0.0"
        profile = SupplierProfile.create(
            supplier_id=supplier_id,
            name=name,
            description=description,
            now=now,
            schema_version=initial_schema_version,
            created_by=created_by,
            file_rules=file_rules,
            sheet_mappings=sheet_mappings,
            column_mappings=column_mappings,
            validation_rules=validation_rules,
        )
        self.validator.validate_or_raise(profile)
        return self.repository.save(profile)


@dataclass(frozen=True, slots=True)
class UpdateSupplierProfileVersion:
    repository: SupplierProfileRepository
    validator: ProfileValidator = field(default_factory=ProfileValidator)

    def execute(
        self,
        *,
        profile_id: UUID,
        schema_version: str,
        created_by: str,
        file_rules: tuple[SupplierFileRule, ...] = (),
        sheet_mappings: tuple[SupplierSheetMapping, ...] = (),
        column_mappings: tuple[SupplierColumnMapping, ...] = (),
        validation_rules: tuple[SupplierValidationRule, ...] = (),
        now: datetime | None = None,
    ) -> SupplierProfile:
        profile = self.repository.get(profile_id)
        if profile is None:
            raise SupplierProfileNotFound(str(profile_id))
        updated = profile.create_version(
            schema_version=schema_version,
            created_by=created_by,
            now=now,
            file_rules=file_rules,
            sheet_mappings=sheet_mappings,
            column_mappings=column_mappings,
            validation_rules=validation_rules,
        )
        self.validator.validate_or_raise(updated)
        return self.repository.save(updated)


@dataclass(frozen=True, slots=True)
class GetSupplierProfile:
    repository: SupplierProfileRepository

    def execute(self, profile_id: UUID) -> SupplierProfile | None:
        return self.repository.get(profile_id)


def current_version(profile: SupplierProfile) -> SupplierProfileVersion:
    """Return the current immutable version for composition code."""
    return profile.version()


__all__ = [
    "CreateSupplierProfile",
    "GetSupplierProfile",
    "SupplierProfileNotFound",
    "UpdateSupplierProfileVersion",
    "current_version",
]
