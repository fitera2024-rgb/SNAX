from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


class DomainError(Exception):
    """Base class for typed domain failures."""


@dataclass
class InvalidValue(DomainError):
    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


@dataclass
class InvalidTransition(DomainError):
    previous: str
    requested: str

    def __str__(self) -> str:
        return f"Transition {self.previous} -> {self.requested} is not allowed"


@dataclass
class TerminalStateError(InvalidTransition):
    pass


@dataclass
class EmptyFile(DomainError):
    message: str = "Пустой файл не принимается"


@dataclass
class FileTooLarge(DomainError):
    size: int
    maximum: int


@dataclass
class DuplicateFile(DomainError):
    existing_import_id: UUID


@dataclass
class IdempotencyConflict(DomainError):
    key: str


@dataclass
class PersistenceConflict(DomainError):
    message: str = "Конкурирующая регистрация победила"


@dataclass
class ObjectStorageError(DomainError):
    code: str
    message: str


@dataclass
class DigestMismatch(ObjectStorageError):
    expected: str
    actual: str

    def __init__(self, expected: str, actual: str) -> None:
        super().__init__(
            "OBJECT_DIGEST_MISMATCH",
            "Digest объекта не совпадает",
        )
        object.__setattr__(self, "expected", expected)
        object.__setattr__(self, "actual", actual)
