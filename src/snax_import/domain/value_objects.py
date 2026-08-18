from __future__ import annotations

import re
from dataclasses import dataclass

from snax_import.domain.errors import InvalidValue

_DIGEST_RE = re.compile(r"^[a-f0-9]{64}$")
_MEDIA_TYPE_RE = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")


def _reject_controls(field: str, value: str) -> None:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise InvalidValue(field, "Управляющие символы запрещены")


@dataclass(frozen=True, slots=True)
class Sha256Digest:
    value: str

    def __post_init__(self) -> None:
        if not _DIGEST_RE.fullmatch(self.value):
            raise InvalidValue("sha256", "Ожидается lowercase SHA-256 из 64 hex-символов")

    @classmethod
    def from_hex(cls, value: str) -> Sha256Digest:
        return cls(value)


@dataclass(frozen=True, slots=True)
class ObjectKey:
    value: str

    def __post_init__(self) -> None:
        if not self.value.startswith("raw/sha256/"):
            raise InvalidValue("objectKey", "Ключ должен начинаться с raw/sha256/")
        if any(part in {"", ".", ".."} for part in self.value.split("/")):
            raise InvalidValue("objectKey", "Недопустимый сегмент object key")
        if any(ord(char) < 32 or ord(char) == 127 for char in self.value):
            raise InvalidValue("objectKey", "Управляющие символы запрещены")

    @classmethod
    def for_digest(cls, digest: Sha256Digest) -> ObjectKey:
        value = digest.value
        return cls(f"raw/sha256/{value[:2]}/{value[2:4]}/{value}")


@dataclass(frozen=True, slots=True)
class OriginalFileName:
    value: str

    def __post_init__(self) -> None:
        if not self.value or len(self.value) > 255:
            raise InvalidValue("originalFileName", "Имя файла должно содержать 1-255 символов")
        _reject_controls("originalFileName", self.value)
        if "/" in self.value or "\\" in self.value or self.value in {".", ".."}:
            raise InvalidValue("originalFileName", "Пути и path traversal в имени запрещены")


@dataclass(frozen=True, slots=True)
class FileSize:
    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise InvalidValue("sizeBytes", "Размер не может быть отрицательным")


@dataclass(frozen=True, slots=True)
class MediaType:
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if not _MEDIA_TYPE_RE.fullmatch(normalized):
            raise InvalidValue("mediaType", "Некорректный media type")
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    value: str

    def __post_init__(self) -> None:
        if not 16 <= len(self.value) <= 200:
            raise InvalidValue("idempotencyKey", "Ключ должен содержать 16-200 символов")
        _reject_controls("idempotencyKey", self.value)


@dataclass(frozen=True, slots=True)
class CorrelationId:
    value: str

    def __post_init__(self) -> None:
        if not self.value or len(self.value) > 100:
            raise InvalidValue("correlationId", "Correlation ID должен содержать 1-100 символов")
        _reject_controls("correlationId", self.value)
