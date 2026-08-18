from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header

from snax_import.api import mock_data
from snax_import.api.errors import ApiError
from snax_import.api.models import (
    HealthResponse,
    ImportRow,
    ImportStatusDetail,
    ImportStatusSummary,
    Problem,
    VersionResponse,
)
from snax_import.config import settings

router = APIRouter()


def _correlation_id(
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
) -> str:
    return x_correlation_id or "unset"


@router.get("/health", response_model=HealthResponse)
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


@router.get("/health/live", response_model=HealthResponse)
def health_live() -> HealthResponse:
    return HealthResponse(status="ok", dependencies={"api": "ok"})


@router.get("/health/ready", response_model=HealthResponse)
def health_ready() -> HealthResponse:
    return HealthResponse(
        status="ok",
        dependencies={
            "database": "ok",
            "redis": "ok",
            "minio": "ok",
        },
    )


@router.get("/version", response_model=VersionResponse)
def version(
    correlation_id: str = Header(default="unknown", alias="X-Correlation-ID"),
) -> VersionResponse:
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


@router.get("/imports", response_model=list[ImportStatusSummary])
def list_imports() -> list[ImportStatusSummary]:
    return mock_data.list_imports()


@router.get("/imports/{import_id}", response_model=ImportStatusSummary | Problem)
def get_import(import_id: UUID) -> ImportStatusSummary:
    summary = mock_data.get_import_summary(import_id)
    if summary is None:
        raise ApiError(
            code="IMPORT_NOT_FOUND",
            message="Импорт не найден",
            status_code=404,
            retryable=False,
            field="importId",
        )
    return summary


@router.get("/imports/{import_id}/rows", response_model=list[ImportRow])
def get_import_rows(import_id: UUID) -> list[ImportRow]:
    summary = mock_data.get_import_summary(import_id)
    if summary is None:
        raise ApiError(
            code="IMPORT_NOT_FOUND", message="Импорт не найден", status_code=404, field="importId"
        )
    return mock_data.get_import_rows(import_id)


@router.get("/imports/{import_id}/steps", response_model=ImportStatusDetail)
def get_import_steps(import_id: UUID) -> ImportStatusDetail:
    detail = mock_data.get_import_detail(import_id)
    if detail is None:
        raise ApiError(
            code="IMPORT_NOT_FOUND", message="Импорт не найден", status_code=404, field="importId"
        )
    return detail
