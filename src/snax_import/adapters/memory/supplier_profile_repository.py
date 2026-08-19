from __future__ import annotations

from datetime import datetime
from uuid import UUID

from snax_import.domain.errors import InvalidTransition
from snax_import.domain.supplier_profile import (
    ProfileStatus,
    SupplierProfile,
    SupplierProfileValidator,
)


class InMemorySupplierProfileRepository:
    def __init__(self) -> None:
        self._profiles: dict[UUID, SupplierProfile] = {}
        self._validator = SupplierProfileValidator()

    def save(self, profile: SupplierProfile) -> SupplierProfile:
        self._validator.validate(profile)
        existing = self._profiles.get(profile.id)
        if existing is not None and existing != profile:
            if existing.status is ProfileStatus.ARCHIVED:
                raise InvalidTransition(existing.status.value, "EDIT")
            if (
                existing.status is ProfileStatus.ACTIVE
                and profile.status is not ProfileStatus.ARCHIVED
                and not self._is_version_append(existing, profile)
            ):
                raise InvalidTransition(existing.status.value, "EDIT")
        self._profiles[profile.id] = profile
        return profile

    def get(self, profile_id: UUID) -> SupplierProfile | None:
        return self._profiles.get(profile_id)

    def list(self, supplier_id: str | None = None) -> tuple[SupplierProfile, ...]:
        profiles = tuple(self._profiles.values())
        if supplier_id is None:
            return profiles
        return tuple(profile for profile in profiles if profile.supplier_id == supplier_id)

    def archive(self, profile_id: UUID, *, now: datetime | None = None) -> SupplierProfile | None:
        profile = self.get(profile_id)
        if profile is None:
            return None
        archived = profile.archive(now=now)
        return self.save(archived)

    @staticmethod
    def _is_version_append(existing: SupplierProfile, candidate: SupplierProfile) -> bool:
        if (
            candidate.status is not ProfileStatus.ACTIVE
            or candidate.current_version != (existing.current_version or 0) + 1
            or len(candidate.versions) != len(existing.versions) + 1
            or candidate.name != existing.name
            or candidate.description != existing.description
            or candidate.supplier_id != existing.supplier_id
        ):
            return False
        for before, after in zip(existing.versions, candidate.versions[:-1], strict=True):
            if before.id != after.id:
                return False
            if before.effective_to is None and after.effective_to is None:
                return False
            if before.effective_from != after.effective_from:
                return False
            if before.schema_version != after.schema_version:
                return False
            if before.file_rules != after.file_rules:
                return False
            if before.sheet_mappings != after.sheet_mappings:
                return False
            if before.column_mappings != after.column_mappings:
                return False
            if before.validation_rules != after.validation_rules:
                return False
        newest = candidate.versions[-1]
        return newest.version_number == candidate.current_version and newest.effective_to is None


__all__ = ["InMemorySupplierProfileRepository"]
