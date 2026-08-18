# Архитектурное ревью WORK-004 — Raw Workbook Model и Reader Protocol

## Паспорт

| Поле | Значение |
|---|---|
| Работа | `WORK-004` |
| Ветка | `work/004-raw-workbook-model` |
| База | `main` |
| Статус | `REVIEW` |
| Scope | raw model, reader port, synthetic adapter, tests, schema |
| Merge | не выполняется в рамках WORK-004 |

## Архитектура

Поток WORK-004:

```text
immutable source stream
    -> WorkbookReader port
    -> RawWorkbookResult
    -> Raw Workbook Model
    -> будущие profile/normalization этапы
```

Модель находится в `domain/raw_workbook.py` и не импортирует FastAPI, SQLAlchemy,
openpyxl, pandas, S3 SDK, Celery или Redis. Контракт reader находится в
`ports/workbook_reader.py`. Synthetic adapter находится в
`adapters/workbook/synthetic.py` и нужен только для contract/integration fixtures
до WORK-005.

## Модель данных

- `Workbook`: UUID, source file ID, filename metadata, format, UTC timestamp, sheets и
  string-only workbook metadata.
- `Sheet`: name, zero-based sheet index, visibility, dimensions, merged ranges и rows.
- `Row`: 1-based index, cells, hidden flag и optional Decimal row height.
- `Cell`: coordinate/row/column, `ValueType`, raw/display values, formula metadata,
  cached value и error code.
- `CellCoordinate`: 1-based row/column плюс derived A1 representation.
- `Formula`: formula text и cached result; вычисление не выполняется.
- `MergedRange`: start/end coordinates с проверкой порядка и границ листа.

Строковые значения не приводятся к числам: код `00123` остаётся `STRING` с
ведущими нулями. Денежной или товарной бизнес-логики в raw model нет.

## Reader Protocol

`WorkbookReader` содержит:

```python
supports(media_type, extension) -> bool
read(source: BinaryIO, options: ReaderOptions) -> RawWorkbookResult
```

`ReaderOptions` конфигурирует max file size, sheets, rows, columns, cells, timeout,
memory budget, hidden sheets и сохранение formulas. `ReaderResult` содержит workbook,
issues, statistics, warnings и errors; `warnings/errors` вычисляются из typed issue
severity, а не из текстового сообщения.

Стабильные коды включают `FILE_TOO_LARGE`, `WORKBOOK_TOO_MANY_SHEETS`,
`WORKBOOK_TOO_MANY_ROWS`, `WORKBOOK_TOO_MANY_COLUMNS`, `CELL_LIMIT_EXCEEDED`,
`UNSUPPORTED_FORMAT`, `FORMULA_PRESENT`, `FORMULA_ERROR`, `CELL_ERROR`,
`MERGED_RANGE_INVALID`, `SHEET_READ_FAILED`, `ROW_READ_FAILED` и другие технические
коды лимитов/структуры.

## Synthetic adapter и безопасность

`SyntheticWorkbookReader` принимает UTF-8 NDJSON и обрабатывает поток построчно. Это
проверяет раннюю остановку по лимитам и не требует полноценного XLSX parser. Adapter:

- не выполняет формулы и сохраняет их как data;
- не вызывает Excel/LibreOffice/COM и не запускает макросы;
- исключает hidden sheets по умолчанию с `HIDDEN_SHEET_SKIPPED`;
- прекращает чтение при size, sheets, rows, columns, cells, timeout или memory limit;
- возвращает typed issue и частичный raw workbook только с явно учтёнными прочитанными
  данными.

Полноценная проверка ZIP signature/decompression ratio, read-only XLSX, isolated XLS
worker и process-level RSS enforcement являются обязательными входами следующей reader
работы и не имитируются этим synthetic adapter.

## Тесты

- unit: coordinates, A1, value types, leading zeroes, formulas/cached values, merged
  ranges, validation rules;
- property-style: 500 случайных строковых кодов и 500 случайных scalar-cell значений
  без изменения типа/значения;
- synthetic integration: empty workbook, multiple/hidden sheets, merged cells, formula
  and error cells, malformed JSON, row/column/cell limits;
- contract: valid example и два invalid examples через `python scripts/validate_contracts.py`.

Регрессии WORK-001/WORK-002/WORK-003 остаются в общем `pytest` suite; docs/etalon и
OpenAPI business endpoints не изменены.

## Команды и результаты

Ожидаемые команды ревью:

```bash
ruff check .
ruff format --check .
mypy src
pytest -q -m "not integration"
python scripts/validate_contracts.py
python scripts/validate_manifest.py
```

Результаты и commit SHA заполняются после финального прогона и commit. GitHub Actions
должен выполнить backend, frontend, migration, queue-worker, outbox-postgres и docker
jobs на опубликованном branch.

## Технический долг

1. Реальные XLSX/XLS/CSV readers не входят в WORK-004.
2. ZIP-bomb/decompression ratio и изоляция legacy XLS требуют отдельной реализации.
3. Raw model сейчас материализует возвращённый workbook; production reader должен
   записывать строки пачками/через cursor, не собирая большой payload целиком.
4. Memory limit synthetic reader — консервативный input budget, а не измерение RSS
   процесса; production worker должен иметь OS/container memory guard.
5. Реляционная persistence raw sheets/rows и reader application service остаются
   следующими задачами.
