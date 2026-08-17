# Implementation backlog v2.0

Каждая задача выполняется отдельным PR либо небольшой связанной серией. Общие правила — `AGENTS.md`. Критерий готовности — раздел 17 SPEC.

## TASK-000 — Bootstrap репозитория

**Цель:** воспроизводимый локальный запуск и CI.

**Результат:** Python project, FastAPI health/version, Docker Compose PostgreSQL/Redis/MinIO, quality tools, contract validation, CI, `.env.example`.

**Не входит:** domain model, readers, UI, 1С.

**Acceptance:** команды README работают; CI зелёный; secrets scan не находит секретов.

## TASK-001 — Контракты

**Цель:** сделать схемы исполняемым контрактом.

**Результат:** загрузка OpenAPI; validation JSON Schema examples; semantic checks digest/decimal/string codes; contract tests.

**Acceptance:** valid examples проходят; invalid fixtures падают с ожидаемым code/path.

## TASK-002 — Domain model

**Результат:** entity/value objects для file, batch, run, issue, transformation, package; state machines; domain errors; no framework dependencies.

**Acceptance:** переходы состояний и запрещённые переходы полностью протестированы.

## TASK-003 — Persistence

**Результат:** SQLAlchemy models, repositories, Alembic initial migration, transactional unit of work, unique constraints.

**Acceptance:** migration up/down; concurrent duplicate insert безопасен.

## TASK-004 — Object storage

**Результат:** S3 port/adapter, immutable object naming, streaming upload/download, metadata, signed URL policy.

**Acceptance:** digest проверяется; path traversal невозможен; повтор не создаёт второй blob.

## TASK-005 — Queue и outbox

**Результат:** idempotent jobs, retry/dead-letter, heartbeat, transactional outbox dispatcher.

**Acceptance:** повторная доставка события создаёт один эффект; зависшая задача обнаруживается.

## TASK-006 — Raw workbook model

**Результат:** framework-neutral model sheets/rows/cells/formula/cached/display/coordinates/merged ranges и Reader Protocol.

**Acceptance:** model сериализуется и поддерживает большие книги без обязательной загрузки всего content в память.

## TASK-007 — XLSX reader

**Результат:** безопасное чтение XLSX, limits, hidden sheets, merged cells, formulas/cached values, error cells.

**Acceptance:** malicious/large synthetic fixtures; ни одна строка не теряется без issue.

## TASK-008 — CSV reader

**Результат:** encoding/dialect detection с override, raw coordinates, limits.

**Acceptance:** UTF-8/Windows-1251, delimiters, quoted newlines, malformed row issues.

## TASK-009 — Legacy XLS reader

**Результат:** isolated worker/container, BIFF reader, no network, resource limits, common raw model.

**Acceptance:** timeout/crash изолирован; два legacy golden profiles читаются либо получают объяснимую blocking issue.

## TASK-010 — Profile schema и registry

**Результат:** Pydantic models, JSON Schema validation, immutable version storage, activation/rollback, allowed operations registry.

**Acceptance:** arbitrary code cannot be expressed; invalid profiles fail before processing.

## TASK-011 — Profile detection

**Результат:** structural fingerprint, candidate ranking, ambiguity/drift statuses, explain log.

**Acceptance:** golden files выбирают ожидаемый профиль; changed header → `TEMPLATE_CHANGED`/review.

## TASK-012 — Row classification

**Результат:** rules PRODUCT/CATEGORY/HEADER/TOTAL/COMMENT/BLANK/DERIVED/ERROR, repeated header detection.

**Acceptance:** classified count reconciles with raw rows.

## TASK-013 — Normalization pipeline

**Результат:** pure functions text/GTIN/decimal/date/unit/availability/packaging/external key, transformation events.

**Acceptance:** property tests; no silent coercion to zero/empty.

## TASK-014 — Data quality engine

**Результат:** checks, severity, blocking policy, duplicate row detection, formula issues, package summary.

**Acceptance:** critical blocks publish; noncritical travels with row.

## TASK-015 — Package builder

**Результат:** canonical package, JSON Schema validation, digest, manifest/chunks, immutable publish, XLSX pilot export.

**Acceptance:** deterministic payload for same run; chunk reconstruction equals payload.

## TASK-016 — Пилотные профили

**Результат:** 3–5 утверждённых profiles, sanitized golden fixtures, expected rows/issues/summary.

**Acceptance:** AC-004…AC-009 для выбранных профилей; review expected snapshots.

## TASK-017 — Operator UI

**Результат:** upload, progress, profile review, summary, rows/issues, publish, protocol export.

**Acceptance:** role-based actions, large list pagination, Playwright happy/error flows.

## TASK-018 — API для polling 1С

**Результат:** next package, manifest/chunks/issues, ACK, service auth, rate limit, audit.

**Acceptance:** repeated calls/ACK idempotent; retries and correlation work.

## TASK-019 — Mapping sync/cache

**Результат:** mapping delta schema, checkpoint, optimistic version conflicts, cached hints.

**Acceptance:** newer 1С version always wins; deleted/blocked mappings propagate.

## TASK-020 — 1С staging importer

**Результат:** extension metadata, package registry, chunk loader, digest/schema check, idempotency, ACK.

**Acceptance:** repeated package creates one document; interrupted chunk load resumes.

## TASK-021 — 1С matching workspace

**Результат:** deterministic steps, statuses, candidates/explanations, mass actions, audit, `DO_NOT_BUY` persistence.

**Acceptance:** ambiguity never writes typical data; saved mapping reuses automatically.

## TASK-022 — 1С apply

**Результат:** apply approved rows to partner nomenclature/prices/extension registers; availability separate; per-row result; mapping delta.

**Acceptance:** transaction/partial policy approved; rollback/error transparent.

## TASK-023 — Пилот типового расчёта УТ

**Результат:** настроенные способы обеспечения в test base, контрольные SKU, comparison report, order draft.

**Acceptance:** бизнес утверждает параметры; trace package → mapping → recommendation → order.

## TASK-024 — Production hardening

**Результат:** auth, secrets, metrics, dashboards, alerts, retention, backup/restore, load/security tests, incident runbooks.

**Acceptance:** operational readiness checklist signed.

## TASK-025 — Release и передача

**Результат:** release artifacts, deployment docs, compatibility matrix, operator/KM/admin guides, UAT protocol, known limitations.

**Acceptance:** UAT завершён; rollback and restore demonstrated; handover signed.


# Дополнение v2.1 — приемка поставок

## TASK-026 — Receipt domain и контракт

**Результат:** domain entities/value objects для receipt document, package, acceptance session, scan event, discrepancy; state machines; `receipt-package.schema.json`; valid/invalid contract fixtures.

**Acceptance:** запрещенные переходы протестированы; decimal/GTIN semantics валидируются; OCR confidence не превращается в подтвержденный бизнес-факт.

## TASK-027 — Ingestion документов поставки

**Результат:** безопасный прием PDF/XLSX/XML/EDI, immutable original, SHA-256, MIME/signature, duplicate detection, limits и audit.

**Acceptance:** повторный digest не создает второй import; неподдерживаемый скан сохраняется как attachment-only с объяснимым статусом.

## TASK-028 — Профили документов поставки

**Результат:** извлечение шапки, строк, сумм, VAT, coordinates/confidence; 2–3 утвержденных профиля; обезличенные golden fixtures.

**Acceptance:** строки и итоги сверяются; ни одна строка не теряется; реальный УПД не коммитится.

## TASK-029 — API обмена receipt-package

**Результат:** receipt import/publish, polling/ACK/status endpoints, authentication, rate limit и contract tests.

**Acceptance:** повторные запросы идемпотентны; package/status correlation прослеживается.

## TASK-030 — Staging приемки в 1С

**Результат:** объект приемки, связь с заказом поставщику, idempotent import, attachment link, order/document/fact columns.

**Acceptance:** повтор package ID создает один staging; mismatch поставщика/организации/склада блокирует применение.

## TASK-031 — Рабочее место магазина

**Результат:** список ожидаемых поставок, barcode scanning, actual quantity, damage/comment/photo, submit/return, role restrictions.

**Acceptance:** известный код подставляет номенклатуру; неизвестный сохраняется как `MAPPING_REQUIRED`; магазин не проводит типовой документ.

## TASK-032 — Движок сопоставления приемки

**Результат:** saved mapping → order line → GTIN+packaging → supplier SKU → manual; discrepancy classification and explanations.

**Acceptance:** ambiguity never auto-links; each physical scan has final line/status.

## TASK-033 — Проверка и создание документов 1С

**Результат:** reviewer workspace, exception-only view, idempotent creation of standard receipt and optional transfer by configured route.

**Acceptance:** lines without discrepancies are not retyped; repeated create command makes one document.

## TASK-034 — Аудит и синхронизация статусов

**Результат:** scan/status/user/device history, correlation IDs, service status callback, trace links order → source → session → 1С docs.

**Acceptance:** audit is append-only; ACK/status sent only after transaction commit.

## TASK-035 — Golden/UAT приемки

**Результат:** anonymized 32-line receipt fixture, shortage/overage/unplanned/mapping/packaging/price/damage tests and UAT protocol.

**Acceptance:** AC-RCV-001…015 verified in test base.

## TASK-036 — OCR/EDI (опциональная волна)

**Результат:** выполняется только после ADR: OCR hints, structured UПД XML/EDI and confidence/review flow.

**Acceptance:** OCR cannot auto-post or overwrite physical fact; human review and source coordinates are mandatory.
