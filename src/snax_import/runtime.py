from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from snax_import.adapters.db.memory import InMemoryDatabase, InMemoryUnitOfWork
from snax_import.adapters.db.session import create_database_engine, create_session_factory
from snax_import.adapters.db.uow import SqlAlchemyUnitOfWork
from snax_import.adapters.storage.s3 import InMemoryObjectStorage, S3ObjectStorage
from snax_import.application.import_registration import ImportRegistrationService
from snax_import.config import Settings
from snax_import.domain.ports import ObjectStoragePort, UnitOfWorkPort


@dataclass(slots=True)
class Runtime:
    service: ImportRegistrationService
    storage: ObjectStoragePort
    database_engine: object | None = None


def build_runtime(config: Settings) -> Runtime:
    has_database = bool(config.database_url)
    has_storage = bool(
        config.s3_endpoint and config.s3_access_key and config.s3_secret_key and config.s3_bucket
    )
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
                temp_directory=config.temp_directory,
            ),
            storage=storage,
            database_engine=engine,
        )

    if not config.allow_in_memory_fallback:
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
            temp_directory=config.temp_directory,
        ),
        storage=storage,
    )
