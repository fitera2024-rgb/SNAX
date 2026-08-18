from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import cast

from redis import Redis
from sqlalchemy import text
from sqlalchemy.engine import Engine

from snax_import.adapters.db.memory import InMemoryDatabase, InMemoryUnitOfWork
from snax_import.adapters.db.session import create_database_engine, create_session_factory
from snax_import.adapters.db.uow import SqlAlchemyUnitOfWork
from snax_import.adapters.storage.s3 import InMemoryObjectStorage, S3ObjectStorage
from snax_import.application.import_registration import ImportRegistrationService
from snax_import.config import Settings
from snax_import.domain.ports import ObjectStoragePort, UnitOfWorkFactory, UnitOfWorkPort

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Runtime:
    service: ImportRegistrationService
    storage: ObjectStoragePort
    uow_factory: UnitOfWorkFactory
    database_engine: Engine | None = None

    def readiness(self, *, redis_url: str | None) -> dict[str, str]:
        statuses: dict[str, str] = {}
        if self.database_engine is None:
            statuses["database"] = "ok:in-memory"
        else:
            try:
                with self.database_engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                statuses["database"] = "ok"
            except Exception as exc:
                logger.warning("READINESS_DATABASE_FAILED", exc_info=exc)
                statuses["database"] = "error:DATABASE_UNAVAILABLE"
        if redis_url is None:
            statuses["redis"] = "ok:not-required"
        else:
            try:
                client = Redis.from_url(
                    redis_url,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                client.ping()
                client.close()
                statuses["redis"] = "ok"
            except Exception as exc:
                logger.warning("READINESS_REDIS_FAILED", exc_info=exc)
                statuses["redis"] = "error:REDIS_UNAVAILABLE"
        try:
            self.storage.healthcheck()
            statuses["minio"] = "ok"
        except Exception as exc:
            logger.warning("READINESS_STORAGE_FAILED", exc_info=exc)
            statuses["minio"] = "error:OBJECT_STORAGE_UNAVAILABLE"
        statuses["configuration"] = "ok"
        return statuses


def build_runtime(config: Settings) -> Runtime:
    has_database = bool(config.database_url)
    storage_values = (
        config.s3_endpoint,
        config.s3_access_key,
        config.s3_secret_key,
        config.s3_bucket,
    )
    has_storage = all(storage_values)
    has_partial_storage = any(storage_values) and not has_storage

    if has_partial_storage or has_database != has_storage:
        raise RuntimeError("DATABASE_URL and complete S3 configuration must be configured together")

    temp_directory = config.temp_directory or None
    if has_database and has_storage:
        engine = create_database_engine(config.database_url or "")
        factory = create_session_factory(engine)

        def sql_uow_factory() -> UnitOfWorkPort:
            return SqlAlchemyUnitOfWork(factory)

        storage: ObjectStoragePort = S3ObjectStorage(
            endpoint=config.s3_endpoint or "",
            access_key=config.s3_access_key or "",
            secret_key=config.s3_secret_key or "",
            bucket=config.s3_bucket or "",
            region=config.s3_region,
            force_path_style=config.s3_force_path_style,
            verify_on_put=config.verify_object_digest,
        )
        return Runtime(
            service=ImportRegistrationService(
                uow_factory=sql_uow_factory,
                storage=storage,
                max_upload_bytes=config.max_upload_bytes,
                temp_directory=temp_directory,
                processing_autostart=config.processing_autostart,
            ),
            storage=storage,
            uow_factory=sql_uow_factory,
            database_engine=engine,
        )

    if not config.allow_in_memory_fallback or config.app_env.lower() not in {"local", "test"}:
        raise RuntimeError("DATABASE_URL and complete S3 configuration are required")
    database = InMemoryDatabase()
    storage = InMemoryObjectStorage()

    def memory_uow_factory() -> UnitOfWorkPort:
        return cast(UnitOfWorkPort, InMemoryUnitOfWork(database))

    return Runtime(
        service=ImportRegistrationService(
            uow_factory=memory_uow_factory,
            storage=storage,
            max_upload_bytes=config.max_upload_bytes,
            temp_directory=temp_directory,
            processing_autostart=config.processing_autostart,
        ),
        storage=storage,
        uow_factory=memory_uow_factory,
    )
