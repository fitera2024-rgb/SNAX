from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from snax_import.application.profile_validator import ProfileValidator
from snax_import.application.supplier_profile import (
    CreateSupplierProfile,
    GetSupplierProfile,
    SupplierProfileNotFound,
    UpdateSupplierProfileVersion,
)
from snax_import.domain.supplier_profile import (
    SupplierColumnMapping,
    SupplierFileRule,
    SupplierProfile,
    SupplierSheetMapping,
    SupplierValidationRule,
)
from snax_import.ports.supplier_profile_repository import SupplierProfileRepository


@dataclass(frozen=True, slots=True)
class CreateSupplierProfileVersion:
    """Application contract for adding an immutable profile version."""

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
        activate: bool = False,
        now: datetime | None = None,
    ) -> SupplierProfile:
        command = UpdateSupplierProfileVersion(
            repository=self.repository,
            validator=self.validator,
        )
        profile = command.execute(
            profile_id=profile_id,
            schema_version=schema_version,
            created_by=created_by,
            file_rules=file_rules,
            sheet_mappings=sheet_mappings,
            column_mappings=column_mappings,
            validation_rules=validation_rules,
            now=now,
        )
        if activate and profile.status.value == "DRAFT":
            activated = profile.activate(now=now)
            self.validator.validate_or_raise(activated)
            profile = self.repository.save(activated)
        return profile


@dataclass(frozen=True, slots=True)
class ArchiveSupplierProfile:
    """Application contract for archiving a profile without deleting history."""

    repository: SupplierProfileRepository

    def execute(self, profile_id: UUID, *, now: datetime | None = None) -> SupplierProfile:
        archived = self.repository.archive(profile_id, now=now)
        if archived is None:
            raise SupplierProfileNotFound(str(profile_id))
        return archived


__all__ = [
    "ArchiveSupplierProfile",
    "CreateSupplierProfile",
    "CreateSupplierProfileVersion",
    "GetSupplierProfile",
    "SupplierProfileNotFound",
    "UpdateSupplierProfileVersion",
]
