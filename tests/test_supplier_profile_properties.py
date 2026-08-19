from __future__ import annotations

from datetime import UTC, datetime, timedelta

from snax_import.domain.supplier_profile import ProfileStatus, SupplierProfile


def test_generated_version_sequences_are_positive_and_archive_is_lossless() -> None:
    base = datetime(2026, 8, 19, tzinfo=UTC)
    for count in range(1, 31):
        profile = SupplierProfile.create(
            supplier_id=f"SYNTHETIC-{count}", name="Generated", now=base
        )
        for version_number in range(1, count):
            profile = profile.create_version(
                schema_version=f"1.{version_number}.0",
                created_by="property-test",
                now=base + timedelta(minutes=version_number),
            )
        active = profile.activate(now=base + timedelta(hours=1))
        assert active.status is ProfileStatus.ACTIVE
        assert [version.version_number for version in active.versions] == list(range(1, count + 1))
        assert all(version.version_number >= 1 for version in active.versions)

        archived = active.archive(now=base + timedelta(hours=2))
        assert archived.status is ProfileStatus.ARCHIVED
        assert len(archived.versions) == count
        assert [version.version_number for version in archived.versions] == list(
            range(1, count + 1)
        )
