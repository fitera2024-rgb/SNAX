# Executable prompt — WORK-003

Выполни `tasks/WORK-003-queue-outbox-worker.md` целиком в репозитории
`fitera2024-rgb/SNAX`, в точной ветке `work/003-queue-outbox-worker`, base `main`.

До кода полностью прочитай `AGENTS.md`, `docs/TZ.md`, `docs/SPEC.md`, ADR-001, backlog,
WORK-002 task/review, OpenAPI, README, project configuration, migration 0001, domain,
application, DB/storage/API adapters и все tests. Приоритет требований: AGENTS, принятые ADR,
исходная постановка WORK-003, task card, SPEC, TZ, OpenAPI, implementation, README.

Сначала опубликуй архитектурный план, topology, три state matrices, message V1, delivery и
exactly-once strategies, crash matrix, retry/lease/dead-letter/recovery/redispatch policies,
schema constraints/indexes, module/file plan, checks и scope confirmation. Затем сразу
реализуй без дополнительного подтверждения, если нет фактического противоречия.

Task card является полным исполняемым acceptance checklist и не может быть сокращена или
заменена mock-only доказательством. После первого вертикального среза (docs/ADR, migration,
outbox model/repository, queue port/Celery skeleton, worker claim, PostgreSQL и duplicate
delivery tests) немедленно commit/publish в эту же ветку и создай/обнови единственный Draft PR
`[WORK-003] Queue, transactional outbox and worker`. Не создавай альтернативную ветку/PR.

Выполни все unit, live PostgreSQL, live Redis/Celery/MinIO, API/E2E, migration, Docker,
contract/manifest, dependency и frontend gates. Не считать skipped live tests успехом. В
конце создай review draft, переведи task card в `REVIEW`, сохрани PR Draft и передай на
независимое GPT-5.6 Pro review без merge и без заявления `READY_TO_MERGE`.
