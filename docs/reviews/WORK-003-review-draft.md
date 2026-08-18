# WORK-003 — review draft

## 1. Паспорт работы

| Поле | Значение |
|---|---|
| Работа | WORK-003 — Очередь обработки, transactional outbox и worker |
| Репозиторий | `fitera2024-rgb/SNAX` |
| Base | `main` (`2e93c03`) |
| Branch | `work/003-queue-outbox-worker` |
| Draft PR | `#8` — `[WORK-003] Queue, transactional outbox and worker` |
| Task card | `REVIEW` |
| Независимое ревью | GPT-5.6 Pro, ещё не выполнено |
| Merge | не выполнялся |

## 2. Final branch/head

Branch: `work/003-queue-outbox-worker`. Ранний опубликованный vertical-slice commit:
`38b127f0e5006b17f5c16f792990cb6e179caa08`. Основной implementation head:
`b90e8b0073dcfcc18da801cf3eb292468271a5a5`. CI-stabilization changes опубликованы через
GitHub API как `4d58b7b54824ada2b0da23ca51bea9d06e8c0665` и
`8df693c23884802af9a97f9fbc9d767d93002e8b`.

## 3. Process topology

```text
FastAPI / operator CLI
  → application services
  → PostgreSQL transaction (Import + event + ProcessingRun + OutboxMessage)
  → outbox dispatcher (short claim transaction, publish outside transaction)
  → Redis broker / Celery JSON delivery
  → thin Celery task
  → processing application service + MinIO source integrity check
  → PostgreSQL lifecycle completion/failure

recovery sweeper → expired lease retry/dead-letter
recovery sweeper → old unclaimed QUEUED run redispatch generation
```

PostgreSQL — source of truth. Redis — только at-least-once transport. Celery result backend
отключён.

## 4. Import state matrix

| From | To | Причина/атомарные записи |
|---|---|---|
| `RECEIVED` | `STORED` | immutable source сохранён |
| `STORED` | `QUEUED` | новый run + event + outbox |
| `QUEUED` | `PROCESSING` | atomic worker claim + lease + event |
| `PROCESSING` | `READY_FOR_REVIEW` | run `SUCCEEDED` + event |
| `PROCESSING` | `FAILED` | failed/timed-out/dead-letter run + event |
| `FAILED` | `QUEUED` | новый retry run + event + outbox |
| `RECEIVED/STORED/QUEUED` | `CANCELLED` | существующая state machine |

## 5. ProcessingRun state matrix

| From | To | Guard |
|---|---|---|
| — | `QUEUED` | positive run number, unique per import |
| `QUEUED` | `PROCESSING` | import/run/message match, row lock, server lease token |
| `PROCESSING` | `SUCCEEDED` | matching worker/token and unexpired lease |
| `PROCESSING` | `FAILED` | matching lease, retryable attempt remains |
| `PROCESSING` | `TIMED_OUT` | lease expired under row lock |
| `PROCESSING/FAILED/TIMED_OUT/QUEUED` | `DEAD_LETTERED` | nonretryable or exhausted budget |
| `QUEUED` | `CANCELLED` | import already cancelled |

`SUCCEEDED`, `DEAD_LETTERED`, `CANCELLED` терминальны. Retry создаёт новый immutable run.

## 6. Outbox state matrix

| From | To | Причина |
|---|---|---|
| — | `PENDING` | создан атомарно с lifecycle command |
| `PENDING` | `PUBLISHING` | `SKIP LOCKED`, due time, dispatcher lock |
| `PUBLISHING` | `PUBLISHED` | broker принял JSON task |
| `PUBLISHING` | `PENDING` | retryable publish failure/backoff |
| `PUBLISHING` | `PENDING` | expired dispatcher lock recovery |
| `PUBLISHING/PENDING` | `DEAD` | invalid message или exhausted publisher budget |

## 7. Message contract V1

`ProcessingJobMessageV1` содержит `schemaVersion=1`, `messageId`, фиксированный `eventType`,
`importId`, `processingRunId`, `runNumber`, `dispatchGeneration`, `correlationId`, UTC
`requestedAt` и nullable `retryOfRunId`. `additionalProperties=false`; размер ограничен
`QUEUE_MESSAGE_MAX_BYTES`. В сообщении отсутствуют bytes, filename, object key, credentials и
commercial payload. Schema/example/negative fixture находятся в `contracts/`.

## 8. Migration graph

```text
base → 20260818_0001 (WORK-002) → 20260818_0002 (WORK-003/head)
```

Revision `20260818_0002` имеет downgrade к `20260818_0001`, расширяет существующую таблицу
`processing_runs`, выполняет безопасный backfill и создаёт `outbox_messages`.

## 9. Таблицы

- `imports` и append-only `import_status_events` — существующий lifecycle;
- `source_files` — immutable source metadata;
- `processing_runs` — attempt, lineage, lease, heartbeat, failure и dispatch generation;
- `outbox_messages` — durable broker command/publisher state.

## 10. Constraints

- unique `(import_id, run_number)` и partial unique active run per import;
- run number/version/dispatch generation positive, delivery count nonnegative;
- retry parent FK и self-reference prohibition;
- UTC/timestamp ordering, lease/completion/dead-letter consistency;
- unique outbox `deduplication_key`, payload JSONB object;
- schema/version positive, attempts nonnegative, lock/published consistency;
- FKs `processing_runs.import_id`, retry parent и outbox processing run.

## 11. Indexes

Run: import, status, `(status, lease_expires_at)`, `(status, queued_at)`, retry parent и partial
unique active import. Outbox: `(status, available_at)`, `(status, lock_expires_at)`, aggregate,
processing run, correlation, created and published timestamps.

## 12. Queue configuration

Полный набор documented env: broker URL, versioned queue, visibility/message-size limits,
outbox batch/poll/lock/retry, worker ID/concurrency/prefetch/time limits, lease/heartbeat,
processing attempts/backoff/jitter, autostart/mode, recovery interval и redelivery threshold.
Validation запрещает nonpositive values, invalid timing, partial storage/runtime fallback и
test processor/autostart в production-like mode.

## 13. Celery delivery settings

JSON-only serializers/accept list, explicit `snax.import.processing.v1`, allowlisted task,
`acks_late`, reject-on-worker-lost, prefetch 1, UTC, bounded soft/hard limits, visibility
timeout выше hard limit, connection retry at startup, no result backend.

## 14. Outbox algorithm

Dispatcher восстанавливает expired locks и claim-ит due batch короткой transaction через
`FOR UPDATE SKIP LOCKED`. Commit происходит до network publish. Затем отдельная короткая
transaction фиксирует `PUBLISHED`, retry/backoff или durable `DEAD`. Crash после publish до
mark допускает duplicate delivery и не теряет logical command.

## 15. Worker claim algorithm

Worker строго валидирует bounded message, блокирует run/import, сверяет IDs/run/generation и
`QUEUED` states, создаёт server UUID lease token, worker ID/timestamps, увеличивает delivery
count, переводит run/import в `PROCESSING`, добавляет event и коммитит одной transaction.
Повторная delivery terminal/non-queued run — deterministic no-op.

## 16. Lease/heartbeat algorithm

Heartbeat имеет отдельную короткую transaction и требует worker/token/current unexpired lease.
Background runner продлевает lease с интервалом меньше lease. Completion/failure повторно
проверяют token; stale worker получает `JOB_LEASE_LOST`. Sweeper проверяет expiry повторно под
row lock, поэтому heartbeat и recovery не создают два active runs.

## 17. Retry formula

```text
raw = min(max, base * multiplier ** (attempt_number - 1))
delay = clamp(raw + raw * jitter_ratio * (2 * random - 1), 0, max)
```

Publisher retry не меняет run number. Processing retry закрывает старый run и атомарно создаёт
новый run/outbox с `retry_of_run_id`. Manual retry идемпотентен по
`manual-retry:{import}:{correlation}` и также продолжает lineage.

## 18. Dead-letter policy

Durable DLQ — `processing_runs`, не Redis. Nonretryable failure или exhausted budget сохраняет
`DEAD_LETTERED`, timestamps, stable code/reason/retryable flag, import/correlation/run lineage и
оставляет `Import FAILED`. Operator query: `python -m snax_import.cli.queue_status --dead-letter`.

## 19. Redis message-loss recovery

Reconciler блокирует old unclaimed `QUEUED` run, увеличивает `dispatch_generation` и создаёт
новый outbox `process:{runId}:{generation}`. Import и logical run не меняются; duplicate broker
messages снова сходятся к одному atomic claim/effect.

## 20. Crash/recovery matrix

| Сценарий | Результат |
|---|---|
| A. schedule DB commit отсутствует | нет QUEUED/run/event/outbox |
| B. dispatcher не работает | durable `PENDING` остаётся |
| C. crash до publish | expired outbox lock → `PENDING` |
| D. crash после publish до mark | duplicate delivery, один claim/effect |
| E. Redis потерял accepted task | queued-run redispatch generation |
| F. duplicate delivery | deterministic no-op после первого claim |
| G. worker умер после claim | lease expiry → timeout + retry/dead-letter |
| H. handler закончил до completion commit | read-only effect безопасно повторяется |
| I. stale worker завершает | lease token guard отклоняет |
| J. PostgreSQL недоступен | lifecycle effect не фиксируется |
| K. MinIO временно недоступен | retryable stable failure |
| L. digest mismatch | immediate nonretryable dead-letter |
| M. max attempts | durable dead-letter, import FAILED |
| N. manual retry | новый linked run, старая история неизменна |

## 21. Exactly-once-effect evidence

Unique run/dedup constraints, partial unique active run, row locks, lease token, optimistic
version, terminal checks, append-only events и idempotent read-only test handler. Гарантия
ограничена WORK-003 technical effect; future non-idempotent integrations потребуют собственного
effect key/idempotency ledger.

## 22. Duplicate-delivery evidence

Unit test повторно claim-ит один message и получает один `PROCESSING` event. Dispatcher test
проверяет один durable publish. `queue_smoke_test.py` отправляет тот же payload повторно и
проверяет один run и один completion event. Live выполнение ожидает CI `queue-worker`.

## 23. Stale-job recovery evidence

Unit tests покрывают timeout→retry и сохранение одного active run. PostgreSQL integration test
гоняет heartbeat и sweeper параллельно. `queue_resilience_test.py` проверяет heartbeat,
stale retry и последующий worker success на live stack. Live выполнение ожидает CI.

## 24–25. Выполненные команды и фактические результаты

| Команда | Результат на текущем checkout |
|---|---|
| `ruff check .` | passed |
| `ruff format --check .` | passed локально и в CI |
| `mypy src` | passed, 60 source files |
| `pytest -q -m "not integration"` | 40 passed |
| `pytest -q` | 40 passed, 9 service tests skipped локально; это не CI evidence |
| `python scripts/validate_contracts.py` | schemas/examples/negative fixture/OpenAPI passed |
| `python scripts/validate_manifest.py` | passed; validator canonicalizes text LF on Windows |
| `pip check` | no broken requirements |
| `pip-audit --skip-editable` | no known third-party vulnerabilities; first-party editable skipped |
| dependency licenses | Celery BSD-3-Clause; redis-py MIT |
| `npm ci` | 246 packages, 0 vulnerabilities |
| `npm run lint` | passed |
| `npm run typecheck` | passed |
| `npm test -- --run` | 1 file, 9 tests passed |
| `npm run build` | passed, Vite production bundle built |
| `docker compose ...` / migrations / live services | Docker CLI отсутствует локально; CI run 79 прошёл все live gates |

## 26. CI run ID

`32116712353` (run 79): `backend`, `frontend`, `migration`, `outbox-postgres`,
`queue-worker` и `docker` — success. Run URL:
https://github.com/fitera2024-rgb/SNAX/actions/runs/32116712353.
Этот head зелёный; review остаётся Draft до независимого GPT-5.6 Pro review.

## 27. Изменённые файлы

Изменения сгруппированы в task/ADR/contracts/migration; domain queue entities/policies/ports;
SQLAlchemy models/repositories/UoW; scheduling/processing/outbox services; Celery adapter/worker;
dispatcher/sweeper/CLI; runtime/readiness/logging; Compose/CI/env/dependencies; smoke scripts;
unit/PostgreSQL/live tests; README и этот review draft. Точный список фиксируется Git diff PR #8.

## 28. Остаточные риски

- live Docker/service evidence подтверждён CI run 79 на head `8df693c`;
- broker delivery физически остаётся at-least-once;
- будущий processor с external side effects обязан реализовать effect-specific idempotency;
- production operator authorization отсутствует и manual retry остаётся CLI-only.

## 29. Technical debt

- заменить test-only source-integrity handler реальным reader pipeline в следующей работе;
- при появлении нескольких worker pools вынести стабильный deployment-level worker identity;
- добавить production observability/alerts и authorized operator surface отдельной задачей;
- возможный unreferenced immutable object GC остаётся scope последующей retention work.

## 30. Подтверждение границ

WORK-003 не реализует parsing XLS/XLSX/CSV, formulas, normalization/DQ, profiles, matching,
package builder, расчёт заказа, 1С, OCR/PDF, receipt, barcode, production auth или operator UI.

## 31. `docs/etalon`

`git diff` не содержит файлов под `docs/etalon`; эталонные материалы не изменялись.

## 32. Commercial files/secrets

Добавлены только короткие synthetic byte payloads, создаваемые в памяти. Supplier/commercial
files, personal data и реальные credentials не добавлены. `.env.example`/Compose содержат
только явно локальные test credentials. PR остаётся Draft и не является `READY_TO_MERGE`.
