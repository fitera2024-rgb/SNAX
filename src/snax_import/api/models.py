from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Problem(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9_]+$")
    message: str
    retryable: bool = False
    correlationId: str
    field: str | None = None
    details: dict[str, object] | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "failed"]
    dependencies: dict[str, str]


class VersionResponse(BaseModel):
    applicationName: Literal["SNAX"] = "SNAX"
    applicationVersion: str
    commitSha: str
    contractVersion: str
    buildMetadata: dict[str, str | None]


class ImportStatusSummary(BaseModel):
    id: UUID
    supplier: str
    fileName: str
    profile: str
    rows: int
    errors: int
    status: str
    createdAt: datetime


class ImportStatusDetail(BaseModel):
    id: UUID
    supplier: str
    fileName: str
    profile: str
    rows: int
    errors: int
    status: str
    createdAt: datetime
    steps: list[str]


class ImportRow(BaseModel):
    row: int
    sku: str
    supplierSku: str
    name: str
    status: str
    amount: int
