from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from snax_import.adapters.memory.supplier_profile_repository import (
    InMemorySupplierProfileRepository,
)
from snax_import.domain.errors import InvalidTransition
from snax_import.domain.supplier_profile import ProfileStatus, SupplierProfile

NOW = datetime(2026, 8, 19, tzinfo=UTC)


def test_repository_save_get_list_and_archive_keep_history() -> None:
    repository = InMemorySupplierProfileRepository()
    profile = SupplierProfile.create(supplier_id="SYNTHETIC-A", name="A", now=NOW)
    saved = repository.save(profile)

    assert repository.get(saved.id) == saved
    assert repository.list("SYNTHETIC-A") == (saved,)
    archived = repository.archive(saved.id, now=NOW + timedelta(hours=1))
    assert archived is not None
    assert archived.status is ProfileStatus.ARCHIVED
    assert repository.get(saved.id) == archived


def test_active_profile_cannot_be_edited_directly() -> None:
    repository = InMemorySupplierProfileRepository()
    draft = SupplierProfile.create(supplier_id="SYNTHETIC-A", name="A", now=NOW).create_version(
        schema_version="1.0.0", created_by="tester", now=NOW
    )
    active = draft.activate(now=NOW)
    repository.save(active)

    edited = replace(active, name="edited", updated_at=NOW + timedelta(minutes=1))
    with pytest.raises(InvalidTransition):
        repository.save(edited)


def test_active_profile_allows_append_only_new_version() -> None:
    repository = InMemorySupplierProfileRepository()
    active = (
        SupplierProfile.create(supplier_id="SYNTHETIC-A", name="A", now=NOW)
        .create_version(schema_version="1.0.0", created_by="tester", now=NOW)
        .activate(now=NOW)
    )
    repository.save(active)
    updated = active.create_version(
        schema_version="1.1.0", created_by="tester", now=NOW + timedelta(hours=1)
    )

    assert repository.save(updated) == updated
    assert repository.get(active.id) == updated
