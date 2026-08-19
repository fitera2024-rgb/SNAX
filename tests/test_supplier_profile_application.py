from __future__ import annotations

from datetime import UTC, datetime

from snax_import.adapters.memory.supplier_profile_repository import (
    InMemorySupplierProfileRepository,
)
from snax_import.application.supplier_profile import (
    CreateSupplierProfile,
    GetSupplierProfile,
)
from snax_import.application.supplier_profiles import (
    ArchiveSupplierProfile,
    CreateSupplierProfileVersion,
)
from snax_import.domain.supplier_profile import ProfileStatus

NOW = datetime(2026, 8, 19, tzinfo=UTC)


def test_application_contracts_create_version_get_and_archive() -> None:
    repository = InMemorySupplierProfileRepository()
    created = CreateSupplierProfile(repository).execute(
        supplier_id="SYNTHETIC-APP",
        name="Synthetic application profile",
        schema_version="1.0.0",
        created_by="tester",
        now=NOW,
    )
    assert created.current_version == 1

    updated = CreateSupplierProfileVersion(repository).execute(
        profile_id=created.id,
        schema_version="1.1.0",
        created_by="tester",
        activate=True,
        now=NOW,
    )
    assert updated.status is ProfileStatus.ACTIVE
    assert updated.current_version == 2
    assert GetSupplierProfile(repository).execute(updated.id) == updated

    archived = ArchiveSupplierProfile(repository).execute(updated.id, now=NOW)
    assert archived.status is ProfileStatus.ARCHIVED
    assert len(archived.versions) == 2
