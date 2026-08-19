from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from snax_import.domain.supplier_profile import SupplierProfile


class SupplierProfileRepository(Protocol):
    def save(self, profile: SupplierProfile) -> SupplierProfile:
        """Persist an immutable profile snapshot."""

    def get(self, profile_id: UUID) -> SupplierProfile | None:
        """Return a profile by identifier, if it exists."""

    def list(self, supplier_id: str | None = None) -> tuple[SupplierProfile, ...]:
        """List profiles, optionally restricted to one supplier."""

    def archive(self, profile_id: UUID, *, now: datetime | None = None) -> SupplierProfile | None:
        """Archive a profile without changing its version history."""


__all__ = ["SupplierProfileRepository"]
