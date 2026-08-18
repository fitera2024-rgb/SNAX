# ADR-003: PostgreSQL transactional outbox, Redis transport и Celery worker

- **Статус:** принято для реализации WORK-003
- **Дата:** 2026-08-18
- **Связь:** `TASK-005`, `WORK-003`, ADR-001

## Контекст

После WORK-002 import и immutable raw object durable, но `STORED` import не имеет промышленно
безопасного перехода в фоновые задачи. Нельзя атомарно коммитить PostgreSQL и Redis. Broker
может повторять или терять физические сообщения, worker может умереть после claim, а будущая
обработка должна оставаться повторяемой и прослеживаемой.

## Решение

PostgreSQL является источником истины. Постановка создаёт `ProcessingRun`, import lifecycle
event и `OutboxMessage` в одной transaction. Dispatcher claim-ит due rows короткой transaction
через `FOR UPDATE SKIP LOCKED`, публикует в Redis вне DB transaction и затем коротко отмечает
результат. Celery используется как JSON-only at-least-once transport без result backend.

Worker выполняет atomic PostgreSQL claim, создаёт server lease token, продлевает lease
heartbeat-ом и фиксирует completion/failure только при совпадении token/worker/version. Retry
создаёт новый immutable run и новый outbox. Durable dead-letter хранится в PostgreSQL.

## Message contract

`ProcessingJobMessageV1` содержит только schema/message/import/run IDs, run number, dispatch
generation, correlation ID, requested time и optional retry parent. Object metadata worker
получает из PostgreSQL. `messageId` совпадает с outbox ID и Celery `task_id`. Queue:
`snax.import.processing.v1`.

## Delivery semantics

Physical delivery — at-least-once. `acks_late`, reject-on-worker-lost, prefetch 1 and Redis
visibility timeout cover worker crash/redelivery. Duplicate publish is expected between broker
acceptance and `PUBLISHED` commit. Exactly-once effect is bounded to WORK-003 database lifecycle
and is obtained through uniqueness, row locks, atomic claim, lease token, optimistic version,
terminal checks, append-only events and the read-only/idempotent technical processor. It is not
a promise for arbitrary future non-idempotent external side effects.

## Lease, retry и dead-letter

Heartbeat must be positive, lease greater than heartbeat and normally at least three intervals.
Soft limit is less than hard limit; hard limit is less than broker visibility timeout. Processing
retry delay is capped exponential backoff with injectable bounded jitter and `available_at` in
PostgreSQL. Publisher retry is independent and never creates another processing run.
Nonretryable or exhausted processing ends in durable `DEAD_LETTERED` and `Import FAILED`.

## Redis message-loss recovery

`PUBLISHED` only proves broker acceptance. A reconciler finds old unclaimed `QUEUED` runs,
increments `dispatch_generation` and appends a new outbox row with
`process:{run_id}:{generation}`. It re-delivers the same logical run without changing import
status or creating a second run.

## Crash/recovery matrix

| Failure | Durable result/recovery |
|---|---|
| Schedule commit absent | No QUEUED/run/event/outbox |
| Dispatcher absent | PENDING remains |
| Crash before publish | Expired PUBLISHING lock recovered |
| Crash after publish before mark | Duplicate delivery; worker idempotent |
| Redis loses accepted message | Queued-run redispatch generation |
| Duplicate worker delivery | One atomic claim/effect |
| Worker dies after claim | Lease expiry, sweeper, retry run |
| Handler finishes before completion commit | Safe replay; current handler is read-only |
| Stale worker completes | `JOB_LEASE_LOST`, no mutation |
| PostgreSQL outage | No processing effect |
| MinIO outage | Retryable failure |
| Digest mismatch | Nonretryable dead-letter |
| Max attempts | Durable dead-letter, Import FAILED |
| Manual retry | New run, old history unchanged |

## Technology and dependencies

Celery is chosen because SPEC already establishes a Celery-compatible worker with Redis. Celery
and redis-py use bounded compatible ranges supporting Python 3.12 and permissive BSD licenses.
No result backend is configured. A different broker abstraction requires another ADR.

## Consequences

Positive: API and broker failure are decoupled; worker concurrency and crashes are recoverable;
queue state is inspectable without Redis persistence assumptions. Negative: dispatcher,
sweeper and reconciler processes must be operated; physical duplicates are normal; future
non-idempotent handlers must implement an effect-specific idempotency strategy.

## Scope

The only WORK-003 processor validates immutable source existence, size and SHA-256 in local/test.
It performs no workbook parsing, formulas, normalization, business output, 1C integration, OCR
or receipt processing and is rejected in production-like environments.
