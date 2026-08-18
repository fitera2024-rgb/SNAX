# WORK-002 review draft

## Scope and current status

This document is a review handoff for WORK-002. The task card is `REVIEW`; the PR remains Draft and this document does not claim `READY_TO_MERGE`.

Repository: `fitera2024-rgb/SNAX`  
Branch: `work/002-import-core-storage`  
Issue: `#6`  
Draft PR: `#7`

Implemented scope:

- framework-neutral value objects/entities/errors and import lifecycle;
- SQLAlchemy 2.x models, repository/UoW ports and PostgreSQL adapter;
- Alembic initial migration;
- streaming SHA-256 to a private temporary file;
- deterministic immutable S3/MinIO adapter and local deterministic test adapter;
- idempotency/exact duplicate registration service;
- real `POST /imports` and PostgreSQL-backed `GET /imports/{importId}` path;
- API contract extension for the mandatory lifecycle states;
- unit, API, race, PostgreSQL, MinIO and migration-oriented integration tests.

Parsing, queue/worker/outbox, profiles, normalization, package building, 1C, OCR, receiving, authorization and production hardening remain out of scope.

The contract's idempotency parameter is aligned with the WORK-002 requirement as `X-Idempotency-Key`; the implementation also accepts the previous `Idempotency-Key` spelling for compatibility.

## State transition matrix

| From \\ To | RECEIVED | STORED | QUEUED | PROCESSING | READY_FOR_REVIEW | FAILED | CANCELLED |
|---|---:|---:|---:|---:|---:|---:|---:|
| RECEIVED | — | Y | — | — | — | — | Y |
| STORED | — | — | Y | — | — | — | Y |
| QUEUED | — | — | — | Y | — | — | Y |
| PROCESSING | — | — | — | — | Y | Y | — |
| READY_FOR_REVIEW | — | — | — | — | — | — | — |
| FAILED | — | — | Y* | — | — | — | — |
| CANCELLED | — | — | — | — | — | — | — |

`Y*` is only `Import.retry()`. All forbidden transitions raise typed domain errors; terminal states have terminal-state errors. Initial `RECEIVED` and `RECEIVED -> STORED` events are append-only and sequence ordered.

## Migration graph and database inventory

```text
<base> -> 20260818_0001_initial_import_core (head)
```

Tables:

- `source_files`: UUID, lowercase SHA-256, deterministic object key, filename/media metadata, size, storage status, UTC creation time;
- `imports`: UUID, source FK, lifecycle status, optimistic version, correlation/idempotency keys, optional supplier/profile codes and UTC timestamps;
- `processing_runs`: UUID, import FK, run number/status/timestamps/failure details;
- `import_status_events`: UUID, import FK, append-only sequence, previous/new status, reason, correlation, actor and UTC timestamp.

Unique constraints: `source_files.sha256`, `source_files.object_key`, `imports.idempotency_key`, `imports.source_file_id`, `(processing_runs.import_id, run_number)`, `(import_status_events.import_id, sequence)`.  
Checks: lowercase 64-character digest, non-negative size, positive import version, positive event sequence.  
Indexes: source created time; import status, created time and source FK; processing import FK and status; event import FK and occurred time.  
Foreign keys: imports → source files; processing runs/events → imports.

Downgrade removes event, processing, import and source tables in reverse dependency order.

## Object key and storage policy

`raw/sha256/{digest[0:2]}/{digest[2:4]}/{digest}`. The key is derived only from a validated lowercase digest; original filename, supplier input, absolute paths, traversal segments, control characters and OS separators cannot influence it. A repeated put performs HEAD/conditional no-overwrite and validates size/metadata/digest. Reads can stream and re-hash the object.

## PostgreSQL/S3 compensation

The application does not model PostgreSQL and S3 as one transaction. It streams the upload to a private temporary file, computes digest/size, checks idempotency and digest duplicates, performs an idempotent object put, then registers source/import/events in one PostgreSQL transaction. On DB failure, only `created_by_attempt=true` is eligible for deletion. A pre-existing object is never deleted. Timeout/uncertain put is resolved through HEAD and digest verification; retry never overwrites the raw object.

## Duplicate race evidence

The local deterministic race test in `tests/test_import_registration.py` runs two concurrent registrations of identical bytes with different idempotency keys and asserts one import, one source file and one object; the losing request receives `DuplicateFile`. PostgreSQL/MinIO race evidence is provided by the `tests/integration` suite when `TEST_DATABASE_URL` and `TEST_S3_*` are configured; those tests are intentionally skipped locally when the services are unavailable and must be confirmed by CI.

## Commands and observed results

Observed locally on 2026-08-18:

- `python -m ruff check .` — PASS;
- `python -m mypy src` — PASS;
- `python -m pytest -q -rA` — PASS, 17 passed and 3 integration tests skipped without service variables;
- `python scripts/validate_contracts.py` — PASS, OpenAPI and three JSON examples validated;
- `docker compose config` — NOT RUN: Docker CLI is not installed in this environment;
- PostgreSQL Alembic up/down/up — NOT RUN locally for the same Docker/service limitation;
- MinIO integration — NOT RUN locally for the same service limitation;
- frontend `npm run lint`, `npm run typecheck`, `npm test -- --run` and `npm run build` — PASS locally; the first `npm ci` attempt hit a Windows file-lock `EPERM`, after which a dependency install retry completed and the lockfile was restored unchanged.
- GitHub Actions CI run `32091537475` / run `#26` — PASS: backend, frontend, Docker smoke, and `database-storage-api`; the latter completed PostgreSQL `upgrade -> downgrade -> upgrade`, MinIO bucket preparation, and the integration suite against live PostgreSQL/MinIO services.

The GitHub Actions integration job was independently checked after completion. The PR remains Draft because WORK-002 requires an independent architecture review before any readiness or merge decision.

## Remaining risks and technical debt

1. No queue/worker exists yet, so the registration endpoint intentionally stops at `STORED`.
2. The local fallback adapter is limited to local/test environments; production requires complete PostgreSQL and S3 configuration.
3. PostgreSQL/MinIO checks cannot be claimed from local unit tests; CI/service evidence is still required.
4. API authentication, retention, backup/restore, signed URLs and production container hardening are out of scope.
5. A future worker must use the optimistic transition method and preserve append-only event ordering.

## Boundary confirmations

- `docs/etalon` was not changed by WORK-002.
- No real supplier or commercial files were added.
- No secrets or production credentials were added.
- No merge, readiness or release approval is claimed.
