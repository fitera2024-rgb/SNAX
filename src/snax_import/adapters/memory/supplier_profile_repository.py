from __future__ import annotations

from dataclasses import replace
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
            if profile.status is ProfileStatus.ARCHIVED:
                if not self._is_archive_transition(existing, profile):
                    raise InvalidTransition(existing.status.value, "ARCHIVE")
            elif existing.status is ProfileStatus.ACTIVE:
                if not self._is_version_append(existing, profile):
                    raise InvalidTransition(existing.status.value, "EDIT")
            elif profile.status is ProfileStatus.ACTIVE and not self._is_activation(
                existing, profile
            ):
                raise InvalidTransition(existing.status.value, "ACTIVATE")
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
            or candidate.created_at != existing.created_at
            or candidate.updated_at < existing.updated_at
            or candidate.name != existing.name
            or candidate.description != existing.description
            or candidate.supplier_id != existing.supplier_id
        ):
            return False
        current = existing.version()
        for before, after in zip(existing.versions, candidate.versions[:-1], strict=True):
            if before.version_number == current.version_number:
                if before.effective_to is not None:
                    return False
                if after != replace(before, effective_to=candidate.updated_at):
                    return False
            elif before != after:
                return False
        newest = candidate.versions[-1]
        return (
            newest.profile_id == existing.id
            and newest.version_number == candidate.current_version
            and newest.created_at == candidate.updated_at
            and newest.effective_from == candidate.updated_at
            and newest.effective_to is None
        )

    @staticmethod
    def _is_activation(existing: SupplierProfile, candidate: SupplierProfile) -> bool:
        if (
            candidate.status is not ProfileStatus.ACTIVE
            or candidate.current_version != existing.current_version
            or candidate.created_at != existing.created_at
            or candidate.updated_at < existing.updated_at
            or candidate.name != existing.name
            or candidate.description != existing.description
            or candidate.supplier_id != existing.supplier_id
            or len(candidate.versions) != len(existing.versions)
        ):
            return False
        current = existing.version()
        activated = replace(current, effective_from=candidate.updated_at)
        for before, after in zip(existing.versions, candidate.versions, strict=True):
            if before.version_number == current.version_number:
                if before.effective_from is not None or before.effective_to is not None:
                    return False
                if after != activated:
                    return False
            elif before != after:
                return False
        return True

    @staticmethod
    def _is_archive_transition(existing: SupplierProfile, candidate: SupplierProfile) -> bool:
        return (
            candidate.status is ProfileStatus.ARCHIVED
            and candidate.updated_at >= existing.updated_at
            and candidate.id == existing.id
            and candidate.supplier_id == existing.supplier_id
            and candidate.name == existing.name
            and candidate.description == existing.description
            and candidate.created_at == existing.created_at
            and candidate.current_version == existing.current_version
            and candidate.versions == existing.versions
        )


__all__ = ["InMemorySupplierProfileRepository"]
