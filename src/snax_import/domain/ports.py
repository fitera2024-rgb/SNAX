from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import BinaryIO, Protocol
from uuid import UUID

from snax_import.domain.entities import Import, ImportStatusEvent, SourceFile
from snax_import.domain.value_objects import ObjectKey, Sha256Digest


@dataclass(frozen=True, slots=True)
class StoredObject:
    object_key: ObjectKey
    created_by_attempt: bool
    size: int
    metadata: dict[str, str]


class ObjectStoragePort(Protocol):
    def put_stream(
        self,
        stream: BinaryIO,
        *,
        object_key: ObjectKey,
        digest: Sha256Digest,
        size: int,
        media_type: str,
        metadata: dict[str, str],
    ) -> StoredObject: ...

    def get_stream(self, object_key: ObjectKey) -> AbstractContextManager[BinaryIO]: ...

    def exists(self, object_key: ObjectKey) -> bool: ...

    def verify_digest(self, object_key: ObjectKey, expected: Sha256Digest) -> None: ...

    def metadata(self, object_key: ObjectKey) -> dict[str, str]: ...

    def delete(self, object_key: ObjectKey) -> None: ...


class ImportRepositoryPort(Protocol):
    def by_id(self, import_id: UUID) -> Import | None: ...

    def by_idempotency(self, key: str) -> Import | None: ...

    def by_digest(self, digest: Sha256Digest) -> Import | None: ...

    def source_for_import(self, import_id: UUID) -> SourceFile | None: ...

    def save_registration(
        self, source_file: SourceFile, aggregate: Import, events: Sequence[ImportStatusEvent]
    ) -> None: ...


class UnitOfWorkPort(Protocol):
    imports: ImportRepositoryPort

    def __enter__(self) -> UnitOfWorkPort: ...

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


UnitOfWorkFactory = Callable[[], UnitOfWorkPort]
