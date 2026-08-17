# Начальный prompt для Codex

Ты работаешь в репозитории проекта **SNAX Order Import**.

Цель проекта: построить внешний сервис нормализации файлов поставщиков и расширение 1С:УТ для staging, сопоставления номенклатуры и передачи данных в типовой процесс расчёта потребности. Внешний сервис не рассчитывает заказ и не создаёт документ заказа.

## Сначала

1. Прочитай `AGENTS.md` полностью.
2. Прочитай `docs/TZ.md`, `docs/SPEC.md` и `adr/ADR-001-hybrid-architecture.md`.
3. Открой `tasks/IMPLEMENTATION_BACKLOG.md` и выполняй только `TASK-000`.
4. Проверь существующие файлы и не удаляй контрактные артефакты.

## TASK-000 — ожидаемый результат

Создай воспроизводимый bootstrap репозитория:

- Python 3.12 project с `pyproject.toml`;
- базовую package structure из SPEC;
- FastAPI endpoint `/health/live`, `/health/ready`, `/version`;
- PostgreSQL/Redis/MinIO в `docker-compose.yml`;
- `.env.example` без секретов;
- Ruff, mypy, pytest и pre-commit;
- скрипт `scripts/validate_contracts.py`, валидирующий JSON Schema examples и OpenAPI YAML;
- минимальный GitHub Actions workflow для lint/typecheck/tests/contracts;
- README-команды, которые реально работают;
- unit/contract tests для bootstrap.

Не реализуй readers, profile engine, business entities или 1С-интеграцию в этой задаче.

## Ограничения

- Не меняй публичные схемы без явной ошибки; при необходимости сначала объясни проблему.
- Не добавляй production credentials и реальные файлы поставщиков.
- Не используй float для денежных/количественных контрактов.
- Не создавай код, обращающийся напрямую к БД 1С.
- Не отключай проверки ради зелёного CI.

## Формат результата

Перед изменениями сообщи короткий план. После изменений перечисли:

1. изменённые файлы;
2. принятые решения;
3. выполненные команды и фактический результат;
4. оставшиеся ограничения;
5. готовность `TASK-000` по каждому критерию.


Дополнение по приемке: `docs/TZ_ADDENDUM_RECEIVING.md`. Задачи `TASK-026…036` не выполнять до завершения предшествующих зависимостей и утверждения решений из `DECISIONS_REQUIRED.md`.
