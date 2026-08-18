# Архитектурное ревью WORK-001

## Паспорт

| Поле | Значение |
|---|---|
| Работа | `WORK-001` |
| Репозиторий | `fitera2024-rgb/SNAX` |
| Pull request | `#5` |
| Ветка | `work/001-web-bootstrap-impl` |
| Основная модель | `GPT-5.3-Codex`, reasoning `high` |
| Ревью | GPT-5.6 Pro |
| Решение | `READY_TO_MERGE` при зелёном финальном CI |

## Проверенный результат

- создан FastAPI baseline с health/version endpoint'ами, environment-конфигурацией, correlation ID, JSON-логированием и единым форматом ошибок;
- создан React + TypeScript + Vite web shell со всеми маршрутами WORK-001;
- добавлены синтетические mock-данные без коммерческих файлов;
- добавлены backend API tests и frontend component tests;
- добавлен воспроизводимый `package-lock.json`;
- настроены PostgreSQL, Redis, MinIO, API и web в Docker Compose;
- добавлены contract validation, smoke test и GitHub Actions CI;
- сохранены 12 скриншотов обязательных экранов для ширины 1366 px и 390 px;
- `docs/etalon` не изменён;
- parsing, сопоставление, расчёт заказа, интеграция с 1С, OCR и production authorization не реализовывались.

## Доказательства проверок

Финальный CI должен повторно подтвердить:

- Ruff lint и format check;
- mypy;
- pytest;
- OpenAPI/JSON Schema validation;
- npm ci, lint, typecheck, Vitest и production build;
- Docker Compose config/build/up;
- API и web smoke test;
- корректное завершение Docker Compose.

## Исправления по результатам ревью

- статус task card приведён к `DONE`;
- MinIO закреплён на конкретной версии образа вместо `latest`;
- API и консоль MinIO опубликованы на локальных портах `9000` и `9001` в соответствии с README;
- актуализированы SHA-256 для изменённых файлов baseline-пакета в `MANIFEST.sha256`.

## Неблокирующий технический долг

Следующие пункты не входят в WORK-001 и должны быть учтены в последующих работах:

1. заменить `latest` в декларации frontend-зависимостей на согласованные semver-диапазоны; lockfile уже обеспечивает воспроизводимость текущего релиза;
2. отказаться от внешнего Google Fonts `@import` в пользу системного или локально поставляемого шрифтового стека для автономного развёртывания;
3. заменить scaffold-статусы зависимостей в readiness response на реальные проверки PostgreSQL, Redis и S3 после появления адаптеров;
4. обновить GitHub Actions при выпуске версий без предупреждения о Node 20;
5. перейти со Starlette TestClient/httpx на поддерживаемую связку после стабилизации `httpx2`;
6. добавить production hardening контейнеров, secrets management и non-root runtime отдельной работой.

## Итог

WORK-001 соответствует утверждённым границам. После зелёного CI pull request может быть переведён из draft и слит в `main` методом squash.
