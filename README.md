# SNAX Order Import

Гибридная система автоматизации заказов поставщикам:

1. внешний сервис безопасно читает XLS/XLSX/CSV поставщиков;
2. приводит строки к канонической модели и формирует пакет;
3. расширение 1С:УТ принимает пакет в staging;
4. категорийный менеджер подтверждает связи с номенклатурой;
5. 1С применяет цены/условия, рассчитывает потребность типовым механизмом и создаёт черновик заказа;
6. при поставке магазин фиксирует фактический товар сканером, а уполномоченный пользователь проводит подготовленный документ без повторного ввода.

## Эталонные материалы

- [Категорийный менеджер и склад — эталонный комплект от 12.08.2026](docs/etalon/category-manager-warehouse/2026-08-12/README.md)
- [Финансовый директор — эталонный комплект v1.1 от 13.08.2026](docs/etalon/financial-director/2026-08-13/README.md)
- [Финансовый директор — объединённый отчёт v1.2 по видео и транскрибации от 13.08.2026](docs/etalon/financial-director/2026-08-13-v1.2/README.md)

В каталогах эталонов сохраняются утверждённые структуры документов, уровни доказательности, контрольные суммы исходных материалов и ссылки на неизменённые редакции. Новые версии не перезаписывают предыдущие.

## Главные документы

- [Техническое задание](docs/TZ.md)
- [Функционально-техническая спецификация](docs/SPEC.md)
- [Дополнение 2.1: автоматизация приемки](docs/TZ_ADDENDUM_RECEIVING.md)
- [Архитектурное решение](adr/ADR-001-hybrid-architecture.md)
- [ADR-002: приемка поставки](adr/ADR-002-receiving-workflow.md)
- [Программный backlog](tasks/IMPLEMENTATION_BACKLOG.md)
- [Процесс выполнения работ](docs/WORK_PROCESS.md)
- [WORK-001: bootstrap web-сервиса](tasks/WORK-001-web-bootstrap.md)
- [Prompt Codex Cloud для WORK-001](CODEX_WORK_001_PROMPT.md)
- [Начальный prompt для Codex](CODEX_INITIAL_PROMPT.md)
- [OpenAPI](contracts/openapi.yaml)
- [JSON Schema пакета](contracts/schemas/import-package.schema.json)
- [JSON Schema синхронизации связей](contracts/schemas/mapping-sync.schema.json)
- [JSON Schema профиля](profiles/schema/profile.schema.json)

## Статус

Этот пакет — baseline v2.1. В WORK-001 добавлен запускаемый внешний scaffold: FastAPI API, React web shell, локальная инфраструктура Docker Compose и проверки качества. Это не production-код и он не читает файлы поставщиков.

Разработка ведётся двумя связанными уровнями:

- `TASK-000…` — программный backlog из спецификации;
- `WORK-001…` — управляемые работы с номером, моделью Codex, task card, проверками и отдельным PR.

**WORK-001 включает весь bootstrap из `TASK-000` и добавляет обязательный web shell.** Для прямого запуска в Codex Cloud используется `CODEX_WORK_001_PROMPT.md`.

## Codex Cloud

В изолированном checkout Codex Cloud локальная ветка может называться `work`, remote может отсутствовать, а GitHub CLI может быть не авторизован. Это нормальный режим. Реализация выполняется в текущем checkout, а публикация — встроенным действием Codex Cloud.

Желаемая ветка публикации WORK-001:

```text
work/001-web-bootstrap-impl
```

Желаемый PR:

```text
[WORK-001] Bootstrap внешнего web-сервиса SNAX
```

## Инварианты

- 1С — master номенклатуры и связей.
- Сервис не рассчитывает потребность и не создаёт заказы.
- Raw-данные неизменяемы.
- Нет молчаливой потери строк.
- GTIN — строка, не глобальный уникальный ключ.
- Все операции идемпотентны и прослеживаемы.
- Физический факт приёмки хранится в 1С и не заменяется результатом OCR.
- Сервис не проводит поступление и не изменяет складской остаток.

Полный набор правил находится в `AGENTS.md`.

## Локальный запуск WORK-001

Требования: Python 3.12+, Node.js 22+, Docker Compose v2.

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/uvicorn snax_import.main:app --reload
```

Web запускается из `apps/web`:

```bash
npm ci
npm run dev
```

API доступен на `http://localhost:8000`, web — на `http://localhost:5173`.

Полный локальный стек:

```bash
docker compose up -d --build
```

После запуска Compose API доступен на `http://localhost:8000`, web — на `http://localhost:8080`, консоль MinIO — на `http://localhost:9001`.

## Проверки WORK-001

Backend и контракты, из корня репозитория:

```bash
ruff check .
ruff format --check .
mypy src
pytest -q
python scripts/validate_contracts.py
```

Frontend, из `apps/web`:

```bash
npm ci
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

Docker smoke, из корня репозитория:

```bash
docker compose config
docker compose up -d --build
python scripts/smoke_test.py
docker compose down -v
```

## WORK-002: ядро импорта

WORK-002 добавляет реальную регистрацию исходного файла: потоковый SHA-256, immutable raw object в S3/MinIO, PostgreSQL lifecycle и `POST/GET /imports`. Разбор XLS/XLSX/CSV и очередь намеренно не входят в эту работу.

Локальный стек с миграциями и bucket preparation:

```bash
python -m pip install -e ".[dev]"
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose exec api python scripts/prepare_storage.py
python scripts/smoke_test.py
python -m pytest -q -m integration
docker compose down -v
```

Миграция проверяется отдельно в PostgreSQL:

```bash
alembic upgrade head
alembic downgrade base
alembic upgrade head
```

Поток регистрации требует `X-Idempotency-Key` (16–200 символов) и принимает multipart-поле `file`; поддерживается также прежнее имя `Idempotency-Key`. Новый файл возвращает `202` со статусом `STORED`, повтор того же ключа и digest — `200`, другой digest с тем же ключом — `409 IDEMPOTENCY_CONFLICT`, точный duplicate с другим ключом — `409 DUPLICATE_FILE`, превышение `MAX_UPLOAD_BYTES` — `413 FILE_TOO_LARGE`.

Объект хранится по детерминированному ключу `raw/sha256/{digest[0:2]}/{digest[2:4]}/{digest}`. Имя файла — только metadata. PostgreSQL и S3 не считаются одной distributed transaction: после DB rollback удаляется только объект, созданный текущей попыткой; уже существующий object не удаляется и не перезаписывается.

## Структура первой волны

- сервисный каркас и контракты;
- web shell;
- raw workbook model;
- XLSX/CSV/XLS readers;
- profile DSL;
- normalization и DQ;
- package builder;
- 3–5 golden profiles;
- API для polling 1С;
- staging и рабочее место сопоставления в расширении УТ.

## Данные

Реальные прайс-листы поставщиков не должны храниться в публичном/общем Git. Для тестов используются обезличенные golden fixtures или синтетические файлы, сохраняющие структуру и аномалии.
