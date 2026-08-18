# WORK-003 — Очередь обработки, transactional outbox и worker

## Паспорт

| Поле | Значение |
|---|---|
| Проект | SNAX Order Import |
| Репозиторий | `fitera2024-rgb/SNAX` |
| Base | `main` |
| Branch | `work/003-queue-outbox-worker` |
| PR | `[WORK-003] Queue, transactional outbox and worker` (Draft) |
| Backlog | `TASK-005` |
| Статус | `REVIEW` |
| Независимое ревью | GPT-5.6 Pro |
| Merge | запрещён до независимого решения |

## Цель и архитектурный инвариант

Создать проверяемый фундамент фоновой обработки на PostgreSQL, transactional outbox,
Redis и Celery. PostgreSQL остаётся источником истины для import lifecycle, processing runs,
retry, lease, heartbeat, dead-letter и outbox. Redis — только at-least-once transport. Domain
не зависит от FastAPI, Celery, Redis, SQLAlchemy, S3 SDK или конфигурационного framework.

```text
API/CLI → application → domain/ports → PostgreSQL/S3/Celery adapters

API → PostgreSQL transaction → outbox → dispatcher → Redis
    → Celery worker → processing service → PostgreSQL lifecycle
```

HTTP не публикует прямо в Redis; сетевой publish не выполняется внутри DB transaction.

## Обязательный результат

- atomic `STORED → QUEUED` вместе с append-only event, новым `ProcessingRun` и
  `OutboxMessage`;
- `PROCESSING_AUTOSTART=false` сохраняет import как `STORED` без run/outbox;
- idempotent scheduler для ранее сохранённых imports;
- outbox claim через `FOR UPDATE SKIP LOCKED`, publish вне transaction, stale-lock recovery;
- Redis queue `snax.import.processing.v1`, JSON only, no result backend, no pickle;
- strict `ProcessingJobMessageV1` JSON Schema и valid/invalid fixtures;
- atomic worker claim, server lease token, worker ID, heartbeat и optimistic version;
- duplicate delivery даёт один claim/effect и не дублирует events/runs;
- test-only `SourceIntegrityTestProcessor`: existence/size/SHA-256 без parsing;
- explicit PostgreSQL retry с exponential backoff и injectable bounded jitter;
- новый run для каждого processing retry, immutable previous runs;
- durable PostgreSQL dead-letter и operator query CLI;
- manual retry CLI с actor/reason/correlation/idempotency key;
- stale `PROCESSING` sweeper и heartbeat-vs-sweeper safety;
- old `QUEUED` reconciler с новой dispatch generation без нового run;
- реальные readiness checks PostgreSQL/Redis/MinIO/config;
- structured safe logs без payload, filename, credentials и lease token;
- Compose processes: api, worker, outbox-dispatcher, recovery-sweeper, postgres, redis,
  minio, web;
- live PostgreSQL/Redis/Celery/MinIO tests и queue smoke;
- зелёная регрессия WORK-001/002 и frontend.

## State machines

### Import

```text
RECEIVED → STORED → QUEUED → PROCESSING → READY_FOR_REVIEW
                                  └──────→ FAILED
FAILED → QUEUED (явный retry)
RECEIVED/STORED/QUEUED → CANCELLED
```

### ProcessingRun

```text
QUEUED → PROCESSING → SUCCEEDED
                    → FAILED
                    → TIMED_OUT
                    → DEAD_LETTERED
QUEUED → CANCELLED
```

Retry всегда создаёт новый `QUEUED` run. `SUCCEEDED`, `DEAD_LETTERED`, `CANCELLED`
терминальны. Completion/failure/heartbeat требуют действующего lease token.

### OutboxMessage

```text
PENDING → PUBLISHING → PUBLISHED
                     → PENDING (retry/recovered lock)
                     → DEAD
```

## Message V1

Обязательные поля: `schemaVersion=1`, `messageId`,
`eventType=IMPORT_PROCESSING_REQUESTED`, `importId`, `processingRunId`, `runNumber`,
`dispatchGeneration`, `correlationId`, `requestedAt`; допустим nullable `retryOfRunId`.
Запрещены bytes, filename, commercial rows/prices, object key/path и credentials.

## Delivery и exactly-once effect

Celery: `acks_late`, reject-on-worker-lost, prefetch 1, UTC, JSON, explicit queue,
soft/hard limits и visibility timeout выше hard limit. Physical delivery at-least-once.
Exactly-once effect обеспечивают durable run, unique run number/dedup key, partial unique
active-run index, atomic claim, lease token, version, terminal checks, append-only events и
повторно безопасный technical handler.

## Retry, lease и recovery

Processing delay:

```text
min(max_delay, base_delay * multiplier ** (attempt_number - 1)) + bounded jitter
```

Publisher retry не меняет `run_number`. Processing retry закрывает текущий run и атомарно
создаёт следующий run/outbox. 4xx/schema/digest mismatch/processor disabled — nonretryable;
temporary DB/Redis/S3/network failures — retryable.

Heartbeat interval положителен, lease больше heartbeat и минимум рекомендованно `3×`.
Soft limit меньше hard limit; hard limit меньше Redis visibility timeout. Sweeper повторно
проверяет expiry под row lock. Потерянное после `PUBLISHED` Redis message восстанавливается
новой outbox generation для того же `QUEUED` run.

## Persistence

Migration `20260818_0002_queue_outbox_worker` расширяет `processing_runs` и создаёт
`outbox_messages`, не изменяя revision 0001. Обязательны:

- unique `(import_id, run_number)` и partial unique active run;
- positive run/version/schema version, nonnegative delivery/publish attempts;
- retry self-reference prohibition, FK retry parent и processing run;
- timestamp, terminal и lease consistency;
- unique outbox `deduplication_key`, JSON-object payload;
- indexes due outbox/lock expiry, run status/lease/queued age, aggregate/run/correlation/time;
- working `0001→0002→0001→0002` and `base→head→base→head`.

## Crash/recovery acceptance

A DB rollback leaves no queued state/run/outbox. B dispatcher downtime leaves PENDING. C a
pre-publish crash is recovered by lock expiry. D post-publish/pre-mark crash may duplicate,
handled idempotently. E lost Redis task is redispatched. F duplicate delivery has one effect.
G worker death expires lease and produces retry. H handler-success/pre-completion crash is
safe because the current handler is read-only. I stale worker gets `JOB_LEASE_LOST`. J DB
outage creates no effect. K MinIO outage is retryable. L digest mismatch is nonretryable. M
max attempts dead-letter. N manual retry creates a new immutable run.

## Tests and gates

Unit coverage includes every ProcessingRun/Outbox transition and invariant, retry/jitter,
message validation, duplicate claim/completion, lost lease, retry/dead-letter/manual retry,
cancelled import and invalid configuration. PostgreSQL tests cover migrations, round-trips,
atomic rollback, constraints, optimistic conflicts and scheduler/dispatcher/worker/sweeper
races. Live Redis/Celery/MinIO tests cover outbox-to-worker, duplicate delivery, two workers,
broker outage/recovery, crash window, redispatch, worker death, retryable/nonretryable/max
attempts and heartbeat. API/E2E covers autostart on/off, persistence/restarts and immutable
deduplication.

Mandatory commands are the complete set from the WORK-003 постановка: Ruff, format, mypy,
pytest, contract/manifest, pip check; all migration directions; Compose config/build/up,
migration/storage/queue smoke/Celery ping/integration/logs/down; and frontend npm ci, lint,
typecheck, Vitest and build. A skipped live integration test is not evidence of success.

## CI

Required gates: `backend`, `frontend`, `migration`, `outbox-postgres`, `queue-worker`,
`docker`, with real services and safe logs on failure. Dependency ranges are bounded;
license and high/critical vulnerability results are recorded.

## Out of scope

No XLS/XLSX/CSV reader, raw workbook, parsing, formulas, normalization/DQ, profiles, package
builder, matching, order calculation, 1C, OCR/PDF, receipt flow, barcode, production auth,
retention/backup/signed URLs or operator UI. Only synthetic bytes are allowed. No commercial
files, personal data, credentials or changes under `docs/etalon`.

## Handoff

Before review: create `docs/reviews/WORK-003-review-draft.md`, record branch/head/PR, topology,
state matrices, contract, migration/tables/constraints/indexes, queue settings, algorithms,
crash matrix, evidence, every command/result, CI run ID, changed files, risks/debt/boundaries;
set this card to `REVIEW`, keep PR Draft, do not merge and do not claim `READY_TO_MERGE`.
