# WORK-007 CSV Reader Adapter — review draft

Статус: **REVIEW**

Ветка: `work/007-csv-reader`

Base: `work/006-xls-reader` (`5f51bf3`)

## Архитектура

`CsvWorkbookReader` реализует общий `WorkbookReader` contract без зависимостей от
профилей поставщиков и бизнес-правил. Источник читается как `BinaryIO`, ограниченно
копируется во временный файл, после чего стандартный модуль Python `csv` формирует
один лист `CSV` общей модели `RawWorkbook`.

Форматные overrides передаются через `ReaderOptions`: `csv_encoding`, `csv_dialect`,
`csv_delimiter` и `csv_quotechar`. Адаптер экспортируется из пакета workbook adapters.

## Encoding policy

Приоритет определения кодировки:

1. Явный `csv_encoding` override через registry Python codecs и полная strict-проверка.
2. BOM для UTF-8 или UTF-16.
3. Полная strict-проверка UTF-8.
4. Полная strict-проверка Windows-1251 (`cp1251`).

Неизвестная кодировка или несовместимые с override байты возвращают
`ReaderIssueCode.UNSUPPORTED_FORMAT`. Ошибка декодирования не выходит traceback наружу.

## Dialect policy

Явный `csv_dialect` выбирает зарегистрированный Python dialect. `csv_delimiter` и
`csv_quotechar` могут переопределить его separator и quote character. Без override
`csv.Sniffer` анализирует не более 128 KiB текста и ищет delimiters `,`, `;`, tab и `|`.
При невозможности detection применяется безопасный `excel` fallback.

`skipinitialspace` всегда выключен: пробелы после delimiter считаются исходными данными
и не удаляются эвристикой. Parser работает с `strict=True`, поддерживает escaped quotes
и multiline quoted values.

## Mapping CSV → RawWorkbook

- CSV представлен одним видимым листом `CSV` с индексом `0`.
- Каждая логическая CSV record становится `Row` с последовательным индексом от `1`.
- Каждое поле становится `Cell` с raw coordinate `(row, column)` и A1 coordinate.
- Все поля, включая `001234` и числовой текст, остаются `ValueType.STRING`.
- `raw_value` и `display_value` содержат одно и то же декодированное строковое значение.
- Начальные и конечные пробелы сохраняются.
- Quoted newline остаётся частью одной ячейки и не создаёт лишнюю raw row.
- Encoding, delimiter, quote character и parser записываются в workbook metadata.

## Limits

- `max_file_size` проверяется во время chunked copy до parsing.
- `max_rows`, `max_columns` и `max_cells` проверяются при построении raw rows/cells.
- `timeout_seconds` проверяется во время copy и между логическими records.
- `memory_limit` применяется к консервативной оценке materialized rows/cells.
- CSV всегда создаёт не более одного листа, поэтому `max_sheets >= 1` выполняется.

При срабатывании limit возвращается blocking `ReaderIssue`. Если parsing уже начался,
доступная безопасная часть workbook сохраняется; усечённые данные всегда сопровождаются
issue и не считаются успешным результатом.

## Security

- Используется стандартный parser Python без выполнения формул, макросов или кода.
- Reader не выполняет network calls и не обращается к business services.
- Исходные байты обрабатываются strict decoder и strict CSV parser.
- Временный файл не требует materialization всего source в RAM.
- Resource limits применяются до и во время построения доменной модели.
- Broken quotes, malformed rows, invalid encoding и I/O errors преобразуются в
  `ReaderIssue`, а не в необработанный traceback.

## Tests

Targeted suite содержит 11 тестов и покрывает:

- UTF-8 и Windows-1251;
- comma, semicolon, tab/dialect override;
- quoted fields, escaped quotes и multiline quoted values;
- сохранение `001234`, пробелов, строкового типа и количества logical rows;
- broken quotes, invalid/unknown encoding, unknown dialect, empty file;
- inconsistent column counts и malformed rows;
- `max_file_size`, `max_rows`, `max_columns`, `max_cells`, `memory_limit`, timeout;
- media type и extension detection.

## Results

Runtime: Python `3.12.13` в локальной `.venv`.

```text
python -m ruff check .
All checks passed!

python -m ruff format --check .
133 files already formatted

python -m mypy src
Success: no issues found in 67 source files

python -m pytest tests/test_csv_workbook_reader.py
11 passed, 1 warning in 0.06s

python -m pytest -m "not integration"
104 passed, 9 deselected, 1 warning in 0.75s

python scripts/validate_contracts.py
6 valid examples accepted, 6 invalid fixtures rejected, OpenAPI validated

python scripts/validate_manifest.py
MANIFEST.sha256 validated
```

Warning в pytest — существующий `StarletteDeprecationWarning` из
`fastapi.testclient`; он не связан с CSV reader. Перед финальным прогоном были
автоматически исправлены две унаследованные format-only ошибки WORK-006 в XLS reader
и его тесте, без изменения поведения.

## Scope

Изменения ограничены workbook reader layer, общими reader options, тестами и этим
review draft. В diff отсутствуют supplier profiles, normalization, matching, GTIN,
order calculation, 1C, OCR и receipt processing. Бизнес-логика не добавлена.

## Risks

1. Timeout кооперативный: он не может прервать зависший внешний `source.read()` или
   один длительный вызов C parser внутри отдельной CSV record.
2. Автоопределение кодировки намеренно ограничено UTF-8/UTF-16/Windows-1251; другие
   кодировки требуют явного override и доступного Python codec.
3. Dialect detection ограничен sample 128 KiB и четырьмя delimiters; необычные форматы
   должны использовать override.
4. Rows materialized в памяти, хотя source spooled на диск; `memory_limit` является
   консервативной оценкой, а не OS-level RSS isolation.
5. Integration tests (`9`) не запускались локально, поскольку требуют отдельного
   integration environment; полный non-integration suite пройден.
