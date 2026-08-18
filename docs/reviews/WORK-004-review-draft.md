# Архитектурное ревью WORK-004 — Raw Workbook Model и Reader Protocol

## Паспорт

| Поле | Значение |
|---|---|
| Работа | `WORK-004` |
| Ветка | `work/004-raw-workbook-model` |
| База | `main` |
| Статус | `REVIEW` |
| Scope | raw model, reader port, test support reader, tests, schema |
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
`ports/workbook_reader.py`. Production reader adapters в WORK-004 отсутствуют:
line-oriented reader находится только в `tests/_synthetic_workbook_reader.py` и
проверяет protocol/contract fixtures.

## Модель данных

- `Workbook`: UUID, source file ID, filename metadata, format, UTC timestamp, sheets и
  string-only workbook metadata.
- `Sheet`: name, zero-based sheet index, visibility, dimensions, merged ranges и
  replayable read-only `Sequence[Row]`; sequence может быть lazy/disk-backed.
- `Row`: 1-based index, cells, hidden flag и optional Decimal row height.
- `Cell`: coordinate/row/column, `ValueType`, raw/display values, formula metadata,
  cached value и error code.
- `CellCoordinate`: 1-based row/column плюс derived A1 representation.
- `Formula`: formula text и cached result; вычисление не выполняется.
- `MergedRange`: start/end coordinates с проверкой порядка и границ листа.

Строковые значения не приводятся к числам: код `001234` остаётся `STRING` с
ведущими нулями. Модель и JSON Schema отклоняют несогласованные пары
`valueType/rawValue`; formula metadata и cached value допустимы только для `FORMULA`.
Денежной или товарной бизнес-логики в raw model нет.

## Reader Protocol

`WorkbookReader` содержит:

```python
supports(media_type, extension) -> bool
read(source: BinaryIO, options: ReaderOptions) -> ReaderResult
```

`ReaderOptions` конфигурирует max file size, sheets, rows, columns, cells, timeout и
memory budget. Опций отбрасывания hidden sheets или formulas нет: raw reader обязан
сохранить их. `ReaderResult` содержит workbook, issues, statistics, warnings и errors;
`warnings/errors` вычисляются из typed issue severity, а не из текстового сообщения.

Стабильные коды включают `FILE_TOO_LARGE`, `WORKBOOK_TOO_MANY_SHEETS`,
`WORKBOOK_TOO_MANY_ROWS`, `WORKBOOK_TOO_MANY_COLUMNS`, `CELL_LIMIT_EXCEEDED`,
`UNSUPPORTED_FORMAT`, `FORMULA_PRESENT`, `FORMULA_ERROR`, `CELL_ERROR`,
`MERGED_RANGE_INVALID`, `SHEET_READ_FAILED`, `ROW_READ_FAILED` и другие технические
коды лимитов/структуры.

## Test support reader и безопасность

Test-only `SyntheticWorkbookReader` принимает UTF-8 NDJSON и обрабатывает поток
построчно. Это проверяет раннюю остановку по лимитам и не требует полноценного XLSX
parser. Reader:

- не выполняет формулы и сохраняет их как data;
- не вызывает Excel/LibreOffice/COM и не запускает макросы;
- сохраняет hidden sheets вместе с visibility и всеми raw rows/cells;
- прекращает чтение при size, sheets, rows, columns, cells, timeout или memory limit;
- возвращает typed issue и частичный raw workbook только с явно учтёнными прочитанными
  данными.

Он не экспортируется из `src/` и не является production adapter. Полноценная проверка
ZIP signature/decompression ratio, read-only XLSX, isolated XLS worker и process-level
RSS enforcement являются обязательными входами следующей reader работы и здесь не
имитируются.

## Тесты

- unit: coordinates, A1, value types, leading zeroes, formulas/cached values, merged
  ranges, validation rules;
- property-style: 500 случайных строковых кодов проходят JSON round-trip без изменения
  типа/значения; 500 случайных scalar-cell значений сохраняются без conversion;
- synthetic integration: empty workbook, multiple/hidden sheets, merged cells, formula
  and error cells, malformed JSON, row/column/cell limits;
- contract: два valid и пять invalid raw-workbook fixtures через
  `python scripts/validate_contracts.py`.

Регрессии WORK-001/WORK-002/WORK-003 остаются в общем `pytest` suite; docs/etalon и
OpenAPI business endpoints не изменены.

## Команды и результаты

Финальный локальный прогон выполнен на Python 3.12.13:

```bash
ruff check .
ruff format --check .
mypy src
pytest -q -m "not integration"
pytest -q tests/test_raw_workbook.py tests/test_raw_workbook_properties.py \
  tests/test_synthetic_workbook_reader.py tests/test_raw_workbook_contract.py
python scripts/validate_contracts.py
python scripts/validate_manifest.py
```

Результаты: Ruff/format/mypy — passed; non-integration suite — 77 passed, 9 deselected;
raw-workbook suite — 34 passed; contract validation — 2 valid и 5 invalid raw fixtures
processed as expected; manifest validation — passed. Docker локально не запускался,
поскольку Docker CLI отсутствует. GitHub Actions CI #122 на исходном review HEAD
`f1bc0bb` прошёл jobs backend, frontend, migration, outbox-postgres, queue-worker и
docker; любой follow-up commit должен повторно пройти те же jobs до Ready for review.

## Технический долг

1. Реальные XLSX/XLS/CSV readers не входят в WORK-004.
2. ZIP-bomb/decompression ratio и изоляция legacy XLS требуют отдельной реализации.
3. `Sheet.rows` допускает replayable lazy/disk-backed `Sequence`; вызов `to_dict()`
   намеренно материализует JSON payload. Production reader должен реализовать sequence
   через batches/cursor и не собирать весь workbook в RAM до сериализации.
4. Memory limit synthetic reader — консервативный input budget, а не измерение RSS
   процесса; production worker должен иметь OS/container memory guard.
5. Реляционная persistence raw sheets/rows и reader application service остаются
   следующими задачами.
