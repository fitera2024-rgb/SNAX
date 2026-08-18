from __future__ import annotations

import logging
import uuid
from typing import cast

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from snax_import.api.errors import ApiError
from snax_import.api.models import Problem
from snax_import.api.routes import router as api_router
from snax_import.config import settings
from snax_import.logging_config import setup_logging

setup_logging(settings.log_level)

app = FastAPI(
    title="SNAX Order Import API",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    request_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    request.state.correlation_id = request_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = request_id
    return response


@app.get("/ping")
def ping() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(ApiError)
async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    request_id = getattr(request.state, "correlation_id", "unknown")
    payload = Problem(
        code=exc.code,
        message=exc.message,
        retryable=exc.retryable,
        correlationId=request_id,
        field=exc.field,
        details=exc.details,
    ).model_dump()
    return JSONResponse(status_code=exc.status_code, content=payload, headers={"X-Correlation-ID": request_id})


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = getattr(request.state, "correlation_id", "unknown")
    payload = Problem(
        code="VALIDATION_ERROR",
        message="Ошибка валидации запроса",
        retryable=False,
        correlationId=request_id,
        details={"issues": exc.errors()},
    ).model_dump()
    logging.getLogger(__name__).warning("validation.error", extra={"error_count": len(exc.errors())})
    return JSONResponse(status_code=400, content=payload, headers={"X-Correlation-ID": request_id})


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    request_id = getattr(request.state, "correlation_id", "unknown")
    code = "HTTP_ERROR"
    message = exc.detail if isinstance(exc.detail, str) else "Request error"
    payload = Problem(
        code=code,
        message=cast(str, message),
        retryable=False,
        correlationId=request_id,
    ).model_dump()
    return JSONResponse(status_code=exc.status_code, content=payload, headers={"X-Correlation-ID": request_id})


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "correlation_id", "unknown")
    logging.getLogger(__name__).exception("unhandled.error", exc_info=exc)
    payload = Problem(
        code="UNHANDLED_ERROR",
        message="Внутренняя ошибка сервиса",
        retryable=False,
        correlationId=request_id,
    ).model_dump()
    return JSONResponse(status_code=500, content=payload, headers={"X-Correlation-ID": request_id})


app.include_router(api_router)
