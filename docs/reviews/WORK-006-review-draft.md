# WORK-006 review draft: Legacy XLS Reader Adapter

## Chosen library

`xlrd` 2.x is selected because it is a focused BIFF/XLS reader and no longer parses OOXML. It is declared as a runtime dependency and is isolated in `src/snax_import/adapters/workbook/xls_reader.py`.

## Architecture

`XlsWorkbookReader` implements `WorkbookReader`, reads untrusted bytes, opens BIFF through `xlrd`, and maps the result to the existing `Workbook`/`RawWorkbook` model. No business rules, column matching, supplier profiles, product matching, GTIN, pricing, ordering, OCR, or 1C behavior is included.

## Limits and controlled errors

The adapter enforces `max_file_size`, `max_sheets`, `max_rows`, `max_columns`, `max_cells`, and `timeout_seconds`. It reports `XLS_TOO_LARGE`, `XLS_CORRUPTED`, `XLS_UNSUPPORTED`, `XLS_PASSWORD_PROTECTED`, `CELL_LIMIT_EXCEEDED`, `ROW_LIMIT_EXCEEDED`, and `SHEET_LIMIT_EXCEEDED` through `ReaderResult.issues`, preserving a partial workbook only when it is safe to do so.

## Security

Input is treated as untrusted. The reader does not start Excel, invoke COM, call LibreOffice, convert files externally, or execute formulas. Formula text is retained as `Formula.formula_text`; the BIFF cached result is retained separately. The adapter bounds input and traversal before constructing domain rows and cells.

## Mapping

BIFF sheets map to `Sheet` with stable index, name, and visible/hidden/very-hidden state. Rows retain their source index. Cells map BIFF text, numeric, date, boolean, error, and formula values to `ValueType`, `raw_value`, `display_value`, `formula`, `cached_value`, and `error_code`. Text is not numerically coerced, preserving leading zero strings.

## Tests and fixtures

Synthetic fixtures cover simple workbooks, multiple sheets, formulas, cell errors, hidden sheets, leading-zero text, corruption, and password protection. Unit tests cover type mapping, coordinates, formulas, errors, and limits. Integration tests cover XLS to reader to `RawWorkbook` flow, including multi-sheet and bounded-input scenarios.

## Risks

BIFF contains historical formula and formatting variants. Formula decompilation is intentionally read-only and is bounded by the same parse timeout. Unsupported formula tokens must never trigger evaluation; they are treated as adapter/parser failures and surfaced as controlled reader issues.
