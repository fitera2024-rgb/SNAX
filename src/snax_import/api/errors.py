from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApiError(Exception):
    code: str
    message: str
    status_code: int = 500
    retryable: bool = False
    field: str | None = None
    details: dict[str, object] | None = None
    correlation_id: str | None = None
