# Prompt для Codex — WORK-002

Ты реализуешь **WORK-002 — Ядро импорта, PostgreSQL и неизменяемое хранение файлов** в проекте SNAX.

## Паспорт

- Репозиторий: `fitera2024-rgb/SNAX`
- База: `main`
- Рабочая ветка: `work/002-import-core-storage`
- Issue: `#6`
- Task card: `tasks/WORK-002-import-core-storage.md`
- Модель: **GPT-5.3-Codex**
- Reasoning: **high**
- Spark: **не использовать**

## Перед изменениями

Полностью прочитай:

1. `AGENTS.md`
2. `tasks/WORK-002-import-core-storage.md`
3. `docs/TZ.md`
4. `docs/SPEC.md`
5. `adr/ADR-001-hybrid-architecture.md`
6. `docs/reviews/WORK-001-review.md`
7. `contracts/openapi.yaml`
8. `tasks/IMPLEMENTATION_BACKLOG.md`
9. `README.md`

Не удаляй и не изменяй `docs/etalon`.

Сначала опубликуй:

- краткий архитектурный план;
- выбранные domain statuses и таблицу переходов;
- предполагаемую структуру каталогов;
- список создаваемых/изменяемых файлов;
- стратегию согласования PostgreSQL и S3 без ложной distributed transaction;
- команды проверок.

После плана начинай реализацию без дополнительных вопросов, если требования не содержат фактического противоречия.

## Выполни

Реализуй task card полностью:

- framework-neutral domain/value objects;
- state machine и domain errors;
- SQLAlchemy 2.x persistence;
- repositories и unit of work;
- Alembic initial migration;
- PostgreSQL integration tests;
- SHA-256 streaming;
- S3 port и MinIO adapter;
- immutable deterministic object naming;
- application service регистрации импорта;
- `POST /imports` multipart upload;
- `GET /imports/{importId}` из PostgreSQL;
- idempotency и exact duplicate handling;
- стабильные problem responses;
- CI и Docker integration gates;
- README с фактически проверенными командами.

## Критические правила

1. Domain не импортирует FastAPI, SQLAlchemy, boto3/minio SDK или Settings.
2. Raw object нельзя перезаписывать.
3. Original filename не участвует в object key.
4. Digest — lowercase SHA-256, вычисляется потоково.
5. Exact duplicate не создаёт второй import или второй blob.
6. Idempotency replay возвращает исходный результат; тот же key с другим digest конфликтует.
7. Не делай вид, что PostgreSQL и S3 образуют одну транзакцию. Опиши и протестируй компенсацию.
8. Не используй SQLite как доказательство PostgreSQL-конкурентности.
9. Не запускай migrations скрыто при production startup.
10. Не меняй OpenAPI без необходимости и contract tests.
11. Не добавляй реальные файлы поставщиков.
12. Не реализуй parsing, queue/outbox, profiles, normalization, 1С, OCR, приёмку или production auth.

## Сохранность результата

После первого вертикального среза, содержащего domain, migration, storage port и хотя бы один рабочий integration test:

1. немедленно опубликуй изменения в текущую ветку;
2. создай/обнови draft PR в `main`;
3. заголовок PR: `[WORK-002] Ядро импорта, PostgreSQL и immutable storage`;
4. тело PR должно содержать `Closes #6`;
5. продолжай работу в том же PR.

Не оставляй весь результат только в локальной object database Codex Cloud.

## Обязательные проверки

Выполни эквивалентный полный gate и приведи фактический результат:

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

cd apps/web
npm ci
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

Если среда не позволяет запустить Docker или registry, код и первый срез всё равно должны быть опубликованы в PR. Полный gate затем выполняется GitHub Actions.

## Перед завершением

- обнови task card до `REVIEW`, не до `DONE`;
- добавь `docs/reviews/WORK-002-review-draft.md` с фактическими доказательствами и рисками;
- приложи migration graph;
- перечисли таблицы, constraints и indexes;
- покажи state transition matrix;
- покажи object key policy;
- укажи, как доказано отсутствие второго blob/import при race;
- перечисли все команды и результаты;
- укажи технический долг;
- не объявляй `READY_TO_MERGE`: это решение принимает GPT-5.6 Pro после независимого ревью.
