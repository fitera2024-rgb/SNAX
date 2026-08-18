from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, Request, Response, UploadFile

from snax_import.api import mock_data
from snax_import.api.errors import ApiError
from snax_import.api.models import (
    HealthResponse,
    ImportAccepted,
    ImportRow,
    ImportStatusDetail,
    ImportStatusResponse,
    ImportStatusSummary,
    Problem,
    VersionResponse,
)
from snax_import.application.import_registration import UploadRequest
from snax_import.config import settings
from snax_import.domain.errors import (
    DigestMismatch,
    DomainError,
    DuplicateFile,
    EmptyFile,
    FileTooLarge,
    IdempotencyConflict,
    InvalidValue,
    ObjectStorageError,
    PersistenceConflict,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse, response_model_exclude_none=True)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        dependencies={
            "database": "ok",
            "redis": "ok",
            "minio": "ok",
            "api": "ok",
        },
    )


@router.get("/health/live", response_model=HealthResponse, response_model_exclude_none=True)
def health_live() -> HealthResponse:
    return HealthResponse(status="ok", dependencies={"api": "ok"})


@router.get("/health/ready", response_model=HealthResponse)
def health_ready(request: Request, response: Response) -> HealthResponse:
    dependencies = request.app.state.runtime.readiness(
        redis_url=settings.queue_broker_url or settings.redis_url
    )
    failed = any(value.startswith("error:") for value in dependencies.values())
    if failed:
        response.status_code = 503
    return HealthResponse(
        status="failed" if failed else "ok",
        dependencies=dependencies,
        correlationId=str(request.state.correlation_id),
    )


@router.get("/version", response_model=VersionResponse)
def version(request: Request) -> VersionResponse:
    correlation_id = str(request.state.correlation_id)
    return VersionResponse(
        applicationVersion=settings.app_version,
        commitSha=settings.commit_sha,
        contractVersion=settings.public_version_contract,
        buildMetadata={
            "buildEnvironment": settings.app_env,
            "correlationId": correlation_id,
            "service": "snax-order-import",
        },
    )


@router.get("/demo/imports", response_model=list[ImportStatusSummary])
def list_demo_imports() -> list[ImportStatusSummary]:
    """Synthetic WORK-001 registry, deliberately separated from production import routes."""

    return mock_data.list_imports()


def _raise_registration_error(exc: DomainError) -> NoReturn:
    if isinstance(exc, DuplicateFile):
        raise ApiError(
            code="DUPLICATE_FILE",
            message="Точная копия файла уже зарегистрирована",
            status_code=409,
            retryable=False,
            details={"existingImportId": str(exc.existing_import_id)},
        ) from exc
    if isinstance(exc, IdempotencyConflict):
        raise ApiError(
            code="IDEMPOTENCY_CONFLICT",
            message="Idempotency key уже использован для другого файла",
            status_code=409,
            retryable=False,
            field="X-Idempotency-Key",
        ) from exc
    if isinstance(exc, FileTooLarge):
        raise ApiError(
            code="FILE_TOO_LARGE",
            message="Размер файла превышает установленный лимит",
            status_code=413,
            retryable=False,
            field="file",
            details={"sizeBytes": exc.size, "maxUploadBytes": exc.maximum},
        ) from exc
    if isinstance(exc, EmptyFile):
        raise ApiError(
            code="EMPTY_FILE",
            message=exc.message,
            status_code=422,
            retryable=False,
            field="file",
        ) from exc
    if isinstance(exc, InvalidValue):
        raise ApiError(
            code="INVALID_METADATA",
            message=exc.message,
            status_code=422,
            retryable=False,
            field=exc.field,
        ) from exc
    if isinstance(exc, DigestMismatch):
        raise ApiError(
            code=exc.code,
            message=exc.message,
            status_code=502,
            retryable=True,
            details={"expected": exc.expected, "actual": exc.actual},
        ) from exc
    if isinstance(exc, ObjectStorageError):
        raise ApiError(
            code=exc.code,
            message=exc.message,
            status_code=503,
            retryable=True,
        ) from exc
    if isinstance(exc, PersistenceConflict):
        raise ApiError(
            code="REGISTRATION_CONFLICT",
            message=exc.message,
            status_code=409,
            retryable=True,
        ) from exc
    raise ApiError(
        code="IMPORT_REGISTRATION_FAILED",
        message="Не удалось зарегистрировать импорт",
        status_code=500,
        retryable=False,
    ) from exc


@router.post("/imports", response_model=ImportAccepted, status_code=202)
def create_import(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    supplier_code: str | None = Form(default=None, alias="supplierCode"),
    profile_code: str | None = Form(default=None, alias="profileCode"),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ImportAccepted:
    key = x_idempotency_key or idempotency_key
    if key is None:
        raise ApiError(
            code="IDEMPOTENCY_KEY_REQUIRED",
            message="Требуется X-Idempotency-Key",
            status_code=422,
            retryable=False,
            field="X-Idempotency-Key",
        )
    correlation_id = str(request.state.correlation_id)
    try:
        result = request.app.state.runtime.service.register(
            UploadRequest(
                stream=file.file,
                original_filename=file.filename or "",
                media_type=file.content_type or "application/octet-stream",
                idempotency_key=key,
                correlation_id=correlation_id,
                supplier_code=supplier_code,
                profile_code=profile_code,
            )
        )
    except DomainError as exc:
        _raise_registration_error(exc)
    return ImportAccepted(
        importId=result.import_id,
        status=result.status,
        statusUrl=f"{settings.public_base_url}/imports/{result.import_id}",
    )


@router.get("/imports/{import_id}", response_model=ImportStatusResponse | Problem)
def get_import(request: Request, import_id: UUID) -> ImportStatusResponse:
    result = request.app.state.runtime.service.get(import_id)
    if result is None:
        raise ApiError(
            code="IMPORT_NOT_FOUND",
            message="Импорт не найден",
            status_code=404,
            retryable=False,
            field="importId",
        )
    aggregate, source = result
    return ImportStatusResponse(
        importId=aggregate.id,
        status=aggregate.status,
        createdAt=aggregate.created_at,
        profileCode=aggregate.profile_code,
        summary={
            "sha256": source.sha256.value,
            "objectKey": source.object_key.value,
            "originalFileName": source.original_filename.value,
            "mediaType": source.media_type.value,
            "sizeBytes": source.size.value,
            "supplierCode": aggregate.supplier_code,
            "correlationId": aggregate.correlation_id.value,
            "version": aggregate.version,
        },
    )


@router.get("/demo/imports/{import_id}/rows", response_model=list[ImportRow])
def get_demo_import_rows(import_id: UUID) -> list[ImportRow]:
    summary = mock_data.get_import_summary(import_id)
    if summary is None:
        raise ApiError(
            code="IMPORT_NOT_FOUND", message="Импорт не найден", status_code=404, field="importId"
        )
    return mock_data.get_import_rows(import_id)


@router.get("/demo/imports/{import_id}/steps", response_model=ImportStatusDetail)
def get_demo_import_steps(import_id: UUID) -> ImportStatusDetail:
    detail = mock_data.get_import_detail(import_id)
    if detail is None:
        raise ApiError(
            code="IMPORT_NOT_FOUND", message="Импорт не найден", status_code=404, field="importId"
        )
    return detail
