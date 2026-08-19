# WORK-005 — XLSX Reader Adapter final review

Code status: **READY_TO_MERGE**

CI status: **EXTERNAL_BLOCKER**

PR: `#10`

Branch: `work/005-xlsx-reader`

Base: `main`

Reviewed implementation HEAD: `d37b540`

Merge не выполнялся.

## Architecture

`XlsxWorkbookReader` расположен в adapter layer и реализует framework-neutral
`WorkbookReader` port. Adapter зависит только от `openpyxl`, raw workbook domain model
и reader port; профили поставщиков и бизнес-сервисы не используются.

Файл сначала ограниченно копируется в seekable temporary file. Перед parsing выполняется
ZIP preflight по суммарному uncompressed size. Workbook открывается двумя read-only
представлениями: formula view (`data_only=False`) и cached-value view (`data_only=True`).
Формулы не вычисляются и не исполняются.

## Data preservation

- Строка `001234` остаётся `ValueType.STRING` с `rawValue="001234"`.
- Формула сохраняется как raw formula text вместе с доступным cached result.
- Excel error tokens сохраняются со стабильным machine-readable error code.
- Hidden/very-hidden state, merged ranges, row coordinates и blank rows сохраняются.
- Streaming worksheets без dimension metadata читаются до конца с динамическими limits.
- Числовые значения преобразуются только из числовых Excel cell types; строковый текст
  автоматически в число не преобразуется.

## Error handling

Invalid ZIP, truncated/corrupted XLSX, valid non-XLSX ZIP и unsupported cell structures
преобразуются в `ReaderIssue`. Необработанный parser traceback не выходит из adapter.

## Limits

- `max_file_size` проверяется во время chunked copy.
- Суммарный uncompressed ZIP size ограничивается `memory_limit` до `openpyxl` parsing.
- `max_rows` применяется глобально ко всем листам и всегда создаёт blocking issue при
  truncation последнего листа.
- `max_columns` и `max_cells` проверяются до добавления превышающей ячейки.
- `timeout_seconds` проверяется во время copy, ZIP preflight и между sheets/rows.
- Частично прочитанные данные возвращаются только вместе с соответствующим issue.

## Findings resolved

1. PR имел merge conflict с актуальным `main`, поскольку HEAD был основан на pre-merge
   WORK-004. `main` объединён в branch с сохранением WORK-005-only delta.
2. Global `max_rows` мог молча усечь последний sheet без issue. Условие исправлено и
   покрыто multi-sheet test.
3. Valid streaming XLSX без worksheet dimensions возвращал `0 rows`. Добавлена
   unbounded streaming iteration с динамическими limits и observed dimensions.
4. Blank rows исключались из RawWorkbook. Теперь logical row и coordinate sequence
   сохраняются.
5. ZIP expansion не проверялся до чтения worksheet XML. Добавлен uncompressed-size
   preflight по `memory_limit`.
6. Противоречивые media type и extension могли быть приняты по правилу OR. Reader теперь
   требует согласованности всех переданных format hints.
7. Добавлены отсутствовавшие boundary/failure tests.

## Tests and results

Runtime: Python `3.12.13`.

```text
python -m ruff check .
All checks passed!

python -m ruff format --check .
126 files already formatted

python -m mypy src
Success: no issues found in 65 source files

python -m pytest tests/test_xlsx_workbook_reader.py
9 passed, 1 warning

python -m pytest -m "not integration"
86 passed, 9 deselected, 1 warning in 3.19s

python scripts/validate_contracts.py
passed

python scripts/validate_manifest.py
passed
```

Targeted tests покрывают formulas/cached values, stable error codes, hidden sheets,
merged cells, leading-zero strings, blank rows, streaming large workbook (`500` rows,
`5000` cells), corrupted/invalid/unsupported ZIP, `max_file_size`, global `max_rows`,
`max_columns`, `max_cells`, decompression budget и timeout.

Pytest warning — существующий `StarletteDeprecationWarning` из `fastapi.testclient`; к
XLSX adapter не относится.

## CI

GitHub Actions run `32203240357` завершил все jobs до выполнения первого step. Annotation:

```text
The job was not started because recent account payments have failed or your spending
limit needs to be increased.
```

Классификация: **EXTERNAL_BLOCKER**. Workflow не изменялся. После исправления GitHub
Billing/Spending limit требуется rerun CI.

## Scope

Изменения ограничены WORK-005 XLSX reader, его tests, необходимой совместимостью raw
workbook dataclass и этим review summary. Supplier profiles, normalization, matching,
GTIN, order calculation, 1C, OCR и receipt processing отсутствуют.

## Residual risks

1. Timeout кооперативный и не может принудительно прервать один зависший вызов
   `source.read()`, `ZipFile` или `openpyxl.load_workbook()`.
2. `memory_limit` ограничивает compressed source и declared uncompressed ZIP payload,
   но не измеряет фактический RSS двух read-only workbook views.
3. Cached formula result зависит от значения, сохранённого создавшим XLSX приложением;
   reader формулы намеренно не вычисляет.
4. Девять integration tests требуют отдельного integration environment и локально не
   запускались.
