# Архитектурное ревью WORK-002

## Паспорт

| Поле | Значение |
|---|---|
| Работа | `WORK-002` |
| Репозиторий | `fitera2024-rgb/SNAX` |
| Pull request | `#7` |
| Ветка | `work/002-import-core-storage` |
| Основная модель | `GPT-5.3-Codex`, reasoning `high` |
| Независимое ревью | GPT-5.6 Pro |
| Проверенный кодовый head | `42e25b78f6f75856d1cf315c50adcb0189ea14dc` |
| Проверочный CI | run `32097256999`, run number `62` |
| Решение | `READY_TO_MERGE` при зелёном CI итогового head |

## Проверенный результат

WORK-002 реализует ядро регистрации неизменяемого исходного файла без разбора XLS/XLSX/CSV:

- framework-neutral domain value objects, entities, typed errors и state machine;
- append-only события статусов и optimistic version для aggregate импорта;
- SQLAlchemy 2.x repositories и transactional unit of work;
- PostgreSQL 16 и Alembic initial migration;
- потоковый SHA-256, ограничение размера и удаление временного файла в `finally`;
- content-addressed object key `raw/sha256/{aa}/{bb}/{digest}`;
- MinIO/S3 adapter с no-overwrite, HEAD/stat, digest/size verification и безопасным retry;
- idempotency replay, `IDEMPOTENCY_CONFLICT` и `DUPLICATE_FILE`;
- production-path `POST /imports` и PostgreSQL-backed `GET /imports/{importId}`;
- сохранение `X-Correlation-ID` в HTTP-ответе и зарегистрированном aggregate;
- отделение synthetic WORK-001 endpoints в namespace `/demo/imports`;
- live PostgreSQL/MinIO integration tests, включая concurrent duplicate race;
- сохранение frontend-регрессии WORK-001.

`docs/etalon` не изменён. Реальные прайс-листы, персональные и коммерческие данные не добавлены. Parsing, queue/outbox, profiles, normalization, package builder, 1С, OCR, приёмка и production authorization не реализовывались.

## State transition matrix

| From / To | RECEIVED | STORED | QUEUED | PROCESSING | READY_FOR_REVIEW | FAILED | CANCELLED |
|---|---:|---:|---:|---:|---:|---:|---:|
| RECEIVED | — | Да | — | — | — | — | Да |
| STORED | — | — | Да | — | — | — | Да |
| QUEUED | — | — | — | Да | — | — | Да |
| PROCESSING | — | — | — | — | Да | Да | — |
| READY_FOR_REVIEW | — | — | — | — | — | — | — |
| FAILED | — | — | Да* | — | — | — | — |
| CANCELLED | — | — | — | — | — | — | — |

`Да*` — только явный `retry()`. Все остальные переходы отклоняются typed domain error; terminal states защищены.

## Миграция и persistence

Migration graph:

```text
<base> -> 20260818_0001_initial_import_core (head)
```

Таблицы:

- `source_files`;
- `imports`;
- `processing_runs`;
- `import_status_events`.

Проверены уникальные ограничения digest/object key/idempotency/source import, FK, check constraints размера/версии/sequence и индексы для статуса, времени и aggregate history. CI выполнил `upgrade head -> downgrade base -> upgrade head` на PostgreSQL.

## PostgreSQL и S3/MinIO

PostgreSQL и object storage не моделируются как единая транзакция. Поток сначала сохраняется во временный server-generated файл, вычисляются digest и размер, raw object создаётся идемпотентно по content-addressed key, затем регистрация фиксируется одной PostgreSQL-транзакцией.

При неопределённом результате S3 выполняются HEAD и проверка digest/size. При DB-конфликте raw object синхронно не удаляется: удаление способно затронуть concurrent winner того же digest. Безопасная политика — оставить неиспользуемый content-addressed object для повторного завершения или будущего grace-period garbage collector. Этот выбор устраняет риск потери оригинала, но требует отдельной задачи cleanup/reconciliation.

## Доказательство duplicate race

Интеграционный тест `tests/integration/test_registration_race.py` запускает два параллельных запроса одинаковых bytes с разными idempotency keys против live PostgreSQL и MinIO и проверяет:

- один успешный `RegistrationResult`;
- один `DuplicateFile` с ID победителя;
- ровно один `source_files` row по digest;
- ровно один `imports` row по digest;
- ровно один MinIO object по deterministic key;
- повторное чтение после создания нового service instance;
- повторную проверку SHA-256 объекта.

## Исправления независимого ревью

Перед одобрением внесены следующие изменения:

1. correlation ID берётся из middleware state, а не независимо из optional header;
2. synthetic mock endpoints вынесены из production namespace в `/demo/imports`;
3. idempotency replay приведён к документированному HTTP `202`;
4. добавлен реальный PostgreSQL+MinIO concurrent duplicate race test;
5. усилены инварианты `SourceFile`, `Import`, `ImportStatusEvent` и `ProcessingRun`;
6. object key проверяется на соответствие digest;
7. partial PostgreSQL/S3 configuration теперь отклоняется вместо молчаливого fallback;
8. пустой `TEMP_DIRECTORY` нормализуется в system temporary directory;
9. добавлена проверка Cyrillic original filename через live PostgreSQL/MinIO;
10. добавлен `scripts/validate_manifest.py` и manifest gate в CI;
11. актуализированы SHA-256 изменённых baseline-файлов.

## Доказательства CI

CI run `32097256999` завершён успешно по четырём jobs:

- `backend`: Ruff, format check, mypy, pytest, OpenAPI/JSON Schema и manifest validation;
- `frontend`: npm ci, lint, typecheck, Vitest и production build;
- `docker`: Compose config/build/up, Alembic upgrade, MinIO preparation, smoke и down;
- `database-storage-api`: PostgreSQL migration up/down/up и integration suite против live PostgreSQL/MinIO.

## Неблокирующий технический долг

1. Реальные readiness probes PostgreSQL/Redis/S3 заменят scaffold statuses в отдельной работе.
2. Queue/worker/outbox и переход из `STORED` в дальнейшую обработку не входят в WORK-002.
3. Требуется grace-period orphan reconciliation/garbage collection для content-addressed storage.
4. Production auth, secrets manager, antivirus, retention, backup/restore и signed URLs остаются вне scope.
5. Starlette TestClient/httpx deprecation warning переносится до стабилизации поддерживаемой связки.
6. GitHub Actions следует обновить после выпуска action versions без Node 20 compatibility warning.
7. Dependency version hardening и non-root container runtime входят в production hardening.

## Итог

WORK-002 соответствует утверждённым границам и архитектурным инвариантам. После зелёного CI итогового head PR №7 может быть переведён из draft и слит в `main` методом squash.
