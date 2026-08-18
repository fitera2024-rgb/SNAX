from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from threading import RLock
from typing import Any, BinaryIO

import boto3  # type: ignore[import-untyped]
from botocore.client import BaseClient  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from snax_import.domain.errors import DigestMismatch, ObjectStorageError
from snax_import.domain.ports import ObjectStoragePort, StoredObject
from snax_import.domain.value_objects import ObjectKey, Sha256Digest

_CHUNK_SIZE = 1024 * 1024


def _is_not_found(exc: ClientError) -> bool:
    return str(exc.response.get("Error", {}).get("Code")) in {"404", "NoSuchKey", "NotFound"}


def _is_precondition_or_conflict(exc: ClientError) -> bool:
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    code = str(exc.response.get("Error", {}).get("Code"))
    return status in {409, 412} or code in {"PreconditionFailed", "ConditionalRequestConflict"}


class S3ObjectStorage(ObjectStoragePort):
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
        force_path_style: bool = True,
        verify_on_put: bool = True,
    ) -> None:
        self.bucket = bucket
        self.verify_on_put = verify_on_put
        self.client: BaseClient = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(s3={"addressing_style": "path" if force_path_style else "auto"}),
        )

    def _head(self, object_key: ObjectKey) -> dict[str, Any]:
        try:
            return dict(self.client.head_object(Bucket=self.bucket, Key=object_key.value))
        except ClientError as exc:
            if _is_not_found(exc):
                raise KeyError(object_key.value) from exc
            raise ObjectStorageError(
                "OBJECT_HEAD_FAILED", "Не удалось получить metadata объекта"
            ) from exc

    def _validate_head(
        self, head: dict[str, Any], digest: Sha256Digest, size: int
    ) -> dict[str, str]:
        metadata = {str(key).lower(): str(value) for key, value in head.get("Metadata", {}).items()}
        actual_digest = metadata.get("sha256")
        if actual_digest != digest.value:
            raise DigestMismatch(digest.value, actual_digest or "missing")
        if int(head.get("ContentLength", -1)) != size:
            raise ObjectStorageError("OBJECT_SIZE_MISMATCH", "Размер объекта не совпадает")
        return metadata

    def put_stream(
        self,
        stream: BinaryIO,
        *,
        object_key: ObjectKey,
        digest: Sha256Digest,
        size: int,
        media_type: str,
        metadata: dict[str, str],
    ) -> StoredObject:
        try:
            head = self._head(object_key)
        except KeyError:
            pass
        else:
            stored_metadata = self._validate_head(head, digest, size)
            if self.verify_on_put:
                self.verify_digest(object_key, digest)
            return StoredObject(object_key, False, size, stored_metadata)

        object_metadata = {"sha256": digest.value, "size": str(size), **metadata}
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=object_key.value,
                Body=stream,
                ContentLength=size,
                ContentType=media_type,
                Metadata=object_metadata,
                IfNoneMatch="*",
            )
        except ClientError as exc:
            if not _is_precondition_or_conflict(exc):
                try:
                    head = self._head(object_key)
                except KeyError:
                    raise ObjectStorageError(
                        "OBJECT_PUT_FAILED", "Не удалось сохранить объект"
                    ) from exc
                stored_metadata = self._validate_head(head, digest, size)
                if self.verify_on_put:
                    self.verify_digest(object_key, digest)
                return StoredObject(object_key, False, size, stored_metadata)
            try:
                head = self._head(object_key)
            except KeyError as missing:
                raise ObjectStorageError(
                    "OBJECT_PUT_UNCERTAIN", "Результат записи объекта не определён"
                ) from missing
            stored_metadata = self._validate_head(head, digest, size)
            if self.verify_on_put:
                self.verify_digest(object_key, digest)
            return StoredObject(object_key, False, size, stored_metadata)
        except BotoCoreError:
            try:
                head = self._head(object_key)
            except KeyError as missing:
                raise ObjectStorageError(
                    "OBJECT_PUT_UNCERTAIN", "Результат записи объекта не определён"
                ) from missing
            stored_metadata = self._validate_head(head, digest, size)
            if self.verify_on_put:
                self.verify_digest(object_key, digest)
            return StoredObject(object_key, False, size, stored_metadata)

        if self.verify_on_put:
            self.verify_digest(object_key, digest)
        return StoredObject(
            object_key, True, size, {key.lower(): value for key, value in object_metadata.items()}
        )

    @contextmanager
    def get_stream(self, object_key: ObjectKey) -> Iterator[BinaryIO]:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=object_key.value)
        except ClientError as exc:
            raise ObjectStorageError("OBJECT_GET_FAILED", "Не удалось прочитать объект") from exc
        body = response["Body"]
        try:
            yield body
        finally:
            body.close()

    def exists(self, object_key: ObjectKey) -> bool:
        try:
            self._head(object_key)
        except KeyError:
            return False
        return True

    def verify_digest(self, object_key: ObjectKey, expected: Sha256Digest) -> None:
        actual = hashlib.sha256()
        with self.get_stream(object_key) as stream:
            while chunk := stream.read(_CHUNK_SIZE):
                actual.update(chunk)
        actual_digest = actual.hexdigest()
        if actual_digest != expected.value:
            raise DigestMismatch(expected.value, actual_digest)

    def metadata(self, object_key: ObjectKey) -> dict[str, str]:
        try:
            head = self._head(object_key)
        except KeyError as exc:
            raise ObjectStorageError("OBJECT_NOT_FOUND", "Объект не найден") from exc
        return {str(key).lower(): str(value) for key, value in head.get("Metadata", {}).items()}

    def delete(self, object_key: ObjectKey) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=object_key.value)
        except ClientError as exc:
            raise ObjectStorageError("OBJECT_DELETE_FAILED", "Не удалось удалить объект") from exc


class InMemoryObjectStorage(ObjectStoragePort):
    """Small deterministic adapter used by unit/API tests and local no-service mode."""

    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, dict[str, str]]] = {}
        self._lock = RLock()

    def put_stream(
        self,
        stream: BinaryIO,
        *,
        object_key: ObjectKey,
        digest: Sha256Digest,
        size: int,
        media_type: str,
        metadata: dict[str, str],
    ) -> StoredObject:
        data = bytearray()
        actual = hashlib.sha256()
        while chunk := stream.read(_CHUNK_SIZE):
            data.extend(chunk)
            actual.update(chunk)
        actual_hex = actual.hexdigest()
        if actual_hex != digest.value:
            raise DigestMismatch(digest.value, actual_hex)
        if len(data) != size:
            raise ObjectStorageError("OBJECT_SIZE_MISMATCH", "Размер потока не совпадает")
        stored_metadata = {
            "sha256": digest.value,
            "size": str(size),
            "content-type": media_type,
            **metadata,
        }
        with self._lock:
            existing = self._objects.get(object_key.value)
            if existing is not None:
                existing_data, existing_metadata = existing
                if (
                    hashlib.sha256(existing_data).hexdigest() != digest.value
                    or len(existing_data) != size
                ):
                    raise DigestMismatch(digest.value, hashlib.sha256(existing_data).hexdigest())
                return StoredObject(object_key, False, len(existing_data), dict(existing_metadata))
            self._objects[object_key.value] = (bytes(data), stored_metadata)
        return StoredObject(object_key, True, size, stored_metadata)

    @contextmanager
    def get_stream(self, object_key: ObjectKey) -> Iterator[BinaryIO]:
        with self._lock:
            try:
                data = self._objects[object_key.value][0]
            except KeyError as exc:
                raise ObjectStorageError("OBJECT_NOT_FOUND", "Объект не найден") from exc
        yield BytesIO(data)

    def exists(self, object_key: ObjectKey) -> bool:
        with self._lock:
            return object_key.value in self._objects

    def verify_digest(self, object_key: ObjectKey, expected: Sha256Digest) -> None:
        with self.get_stream(object_key) as stream:
            actual = hashlib.sha256(stream.read()).hexdigest()
        if actual != expected.value:
            raise DigestMismatch(expected.value, actual)

    def metadata(self, object_key: ObjectKey) -> dict[str, str]:
        with self._lock:
            try:
                return dict(self._objects[object_key.value][1])
            except KeyError as exc:
                raise ObjectStorageError("OBJECT_NOT_FOUND", "Объект не найден") from exc

    def delete(self, object_key: ObjectKey) -> None:
        with self._lock:
            self._objects.pop(object_key.value, None)

    def object_count(self) -> int:
        with self._lock:
            return len(self._objects)
