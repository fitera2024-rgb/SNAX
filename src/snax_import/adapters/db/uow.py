from __future__ import annotations

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from snax_import.adapters.db.outbox_repository import SqlAlchemyOutboxRepository
from snax_import.adapters.db.processing_repository import SqlAlchemyProcessingRunRepository
from snax_import.adapters.db.repositories import SqlAlchemyImportRepository
from snax_import.domain.errors import PersistenceConflict
from snax_import.domain.ports import (
    ImportRepositoryPort,
    OutboxRepositoryPort,
    ProcessingRunRepositoryPort,
    UnitOfWorkPort,
)


class SqlAlchemyUnitOfWork:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory
        self.session: Session | None = None
        self.imports: ImportRepositoryPort
        self.processing_runs: ProcessingRunRepositoryPort
        self.outbox: OutboxRepositoryPort

    def __enter__(self) -> UnitOfWorkPort:
        self.session = self.factory()
        self.imports = SqlAlchemyImportRepository(self.session)
        self.processing_runs = SqlAlchemyProcessingRunRepository(self.session)
        self.outbox = SqlAlchemyOutboxRepository(self.session)
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self.session is not None:
            if exc_type is not None:
                self.session.rollback()
            self.session.close()

    def commit(self) -> None:
        if self.session is None:
            raise RuntimeError("Unit of work is not active")
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise PersistenceConflict() from exc
        except SQLAlchemyError:
            self.session.rollback()
            raise

    def rollback(self) -> None:
        if self.session is not None:
            self.session.rollback()
