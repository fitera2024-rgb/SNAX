# WORK-002 — Ядро импорта, PostgreSQL и неизменяемое хранение файлов

## Паспорт

| Поле | Значение |
|---|---|
| Проект | SNAX |
| Репозиторий | `fitera2024-rgb/SNAX` |
| Базовая ветка | `main` |
| Рабочая ветка | `work/002-import-core-storage` |
| Issue | `#6` |
| Основная модель Codex | `GPT-5.3-Codex`, reasoning `high` |
| Вспомогательная модель | не используется |
| Архитектурное ревью | GPT-5.6 Pro |
| Статус | `REVIEW` |
| Связь с backlog | `TASK-002`, `TASK-003`, ограниченный вертикальный срез `TASK-004` |

## Цель

Создать надёжное ядро регистрации импорта: framework-neutral domain model, контролируемый lifecycle, PostgreSQL persistence с Alembic, потоковый SHA-256 и неизменяемое хранение оригинала в MinIO/S3.

После WORK-002 система должна уметь принять файл через API, вычислить digest, сохранить один immutable object, зарегистрировать import в PostgreSQL и вернуть его состояние. Разбор содержимого не выполняется.

## Архитектурные границы

```text
HTTP/FastAPI
    ↓
application service
    ↓
domain entities + state machine
    ↓
ports: repository / unit of work / object storage / clock
    ↓
adapters: SQLAlchemy/PostgreSQL + MinIO/S3
```

Domain-код не импортирует FastAPI, SQLAlchemy, boto3/minio SDK, Pydantic Settings или web-типы.

## Domain model

Минимально необходимы:

- `Sha256Digest`;
- `ObjectKey`;
- `OriginalFileName` как metadata;
- `FileSize`;
- `MediaType`;
- `SourceFile`;
- `Import`;
- `ProcessingRun` либо эквивалентный объект запуска;
- `ImportStatusEvent`;
- domain errors.

Все идентификаторы создаются сервером. Все timestamps — timezone-aware UTC.

### Lifecycle

Названия сначала сверить с `contracts/openapi.yaml`, `docs/TZ.md` и `docs/SPEC.md`. Обязательный смысл:

```text
RECEIVED → STORED → QUEUED → PROCESSING → READY_FOR_REVIEW
                                  └──────→ FAILED
FAILED → QUEUED                  (явный retry)
RECEIVED/STORED/QUEUED → CANCELLED
```

Требования:

- разрешённые переходы определены в одном месте;
- каждый запрещённый переход вызывает типизированную domain error;
- duplicate upload не создаёт новый lifecycle;
- история переходов append-only;
- terminal-state нельзя менять обычным setter;
- переход содержит `occurred_at`, `reason`, `correlation_id` и actor/system source при наличии.

## SHA-256 и immutable object storage

- digest вычисляется потоково, без обязательной загрузки всего файла в RAM;
- формат digest — lowercase 64 hex;
- object key формируется только из digest/server-generated ID, например `raw/sha256/ab/cd/<digest>`;
- original filename не участвует в path;
- повторный `put` того же digest не создаёт второй object;
- при чтении digest может быть перепроверен;
- mismatch блокирует использование объекта и создаёт объяснимую ошибку;
- временный файл/буфер удаляется при успехе и исключении;
- максимальный размер файла задаётся environment-параметром;
- попытки path traversal и управляющие символы в metadata тестируются;
- raw object никогда не перезаписывается.

## PostgreSQL persistence

Использовать SQLAlchemy 2.x и Alembic.

Минимальные таблицы:

- `source_files`;
- `imports`;
- `processing_runs` либо эквивалент;
- `import_status_events`.

Обязательные ограничения:

- уникальный SHA-256 source file;
- уникальный idempotency key в согласованной области;
- внешние ключи и индексы;
- optimistic/version field там, где возможны конкурентные transitions;
- append-only event rows;
- timestamps UTC;
- rollback при исключении.

Repository и unit of work должны скрывать ORM от application/domain слоя.

## Application service

Реализовать use case регистрации файла:

1. проверить headers/metadata и лимит;
2. потоково принять файл и вычислить SHA-256;
3. обработать idempotency key;
4. проверить exact duplicate;
5. сохранить object идемпотентно;
6. создать `SourceFile` и `Import`;
7. зафиксировать lifecycle events;
8. вернуть стабильный application result;
9. при частичном сбое оставить объяснимое состояние и не создать второй blob при retry.

Distributed transaction между PostgreSQL и S3 не имитировать. Codex должен описать выбранную компенсационную стратегию и покрыть её тестом.

## API

Использовать существующий контракт:

- `POST /imports` — multipart upload;
- `GET /imports/{importId}` — реальное состояние из PostgreSQL.

Обязательное поведение:

- `202` — новый import зарегистрирован;
- повтор того же idempotency key и того же payload возвращает исходный результат;
- тот же key с другим payload — `409 IDEMPOTENCY_CONFLICT`;
- exact duplicate другого запроса — `409 DUPLICATE_FILE`, в `details` есть существующий import ID;
- превышение размера — `413 FILE_TOO_LARGE`;
- некорректные metadata — стабильный `422/400` problem response согласно контракту;
- `X-Correlation-ID` возвращается и сохраняется в событии;
- `GET` после перезапуска API возвращает тот же import;
- существующие mock endpoints не должны маскировать production path.

Публичный контракт не менять без доказанной несовместимости. Любое изменение OpenAPI сопровождается contract tests и объяснением.

## Docker и конфигурация

- PostgreSQL и MinIO из WORK-001 используются как реальные adapters;
- MinIO image остаётся закреплённым на версии;
- секреты только локальные/dev, без production credentials;
- конфигурация через environment;
- Alembic migration запускается отдельной командой и в CI;
- startup API не должен скрыто изменять schema в production-режиме.

## Обязательные тесты

### Unit

- valid/invalid `Sha256Digest`;
- file size и filename metadata validation;
- каждый разрешённый transition;
- каждый запрещённый transition;
- terminal-state protection;
- source metadata immutability;
- deterministic object key;
- application compensation paths.

### PostgreSQL integration

- `alembic upgrade head`;
- `alembic downgrade base`;
- повторный `upgrade head`;
- repository round-trip;
- event history ordering;
- rollback;
- unique digest;
- unique idempotency key;
- optimistic conflict;
- concurrent duplicate registration создаёт один import.

### MinIO integration

- streaming put/get;
- same digest → one object;
- download digest verification;
- corruption/mismatch handling;
- path traversal attempts;
- metadata round-trip;
- object remains unchanged after repeated request.

### API

- `202`, `200`, `409`, `413`, validation error;
- idempotency replay;
- idempotency conflict;
- duplicate file;
- persistence after API restart;
- correlation ID propagation.

## Quality gates

```bash
ruff check .
ruff format --check .
mypy src
pytest -q
python scripts/validate_contracts.py

alembic upgrade head
alembic downgrade base
alembic upgrade head

docker compose config
docker compose up -d --build
pytest -q -m integration
python scripts/smoke_test.py
docker compose down -v
```

Регрессия WORK-001:

```bash
cd apps/web
npm ci
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

## CI

Добавить/расширить jobs так, чтобы проверялись:

- domain/backend lint, typecheck, unit tests;
- contract validation;
- PostgreSQL migration up/down/up;
- PostgreSQL repository/concurrency tests;
- MinIO object storage tests;
- API upload/get/duplicate tests;
- Docker build/up/smoke/down;
- frontend regression gates.

Нельзя объявлять успешным тест, который фактически не запускался.

## Out of scope

- XLS/XLSX/CSV parsing;
- raw workbook model;
- queue/outbox;
- profile detection;
- normalization/DQ;
- полноценный frontend upload flow;
- fuzzy matching;
- расчёт заказа;
- интеграция с 1С;
- OCR и контур приёмки;
- production auth;
- antivirus, retention, backup, signed URLs;
- production hardening контейнеров.

## Порядок выполнения

1. Прочитать `AGENTS.md`, ТЗ, SPEC, ADR, OpenAPI, WORK-001 review и эту task card.
2. Опубликовать краткий план и список файлов.
3. Реализовать domain и unit tests.
4. **После первого рабочего вертикального среза немедленно опубликовать branch/PR.**
5. Добавить persistence и migrations.
6. Добавить object storage adapter.
7. Подключить application service и API.
8. Добавить integration/CI gates.
9. Обновить README только фактическими командами.
10. Зафиксировать review evidence и technical debt.

## Definition of Done

Работа получает `DONE` только когда:

- PR опубликован и не draft;
- итоговый head имеет зелёный CI;
- миграция up/down/up доказана;
- PostgreSQL и MinIO integration tests зелёные;
- duplicate race создаёт один import и один object;
- API даёт стабильные ответы 202/200/409/413;
- README воспроизводим;
- реальных файлов и секретов в Git нет;
- `docs/etalon` не изменён;
- создан `docs/reviews/WORK-002-review.md`;
- GPT-5.6 Pro подтвердил `READY_TO_MERGE`.
