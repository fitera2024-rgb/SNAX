# ADR-006: Legacy XLS reader adapter

## Status

Accepted for WORK-006.

## Decision

Use `xlrd` 2.x as the isolated reader for BIFF `.xls` workbooks. `xlrd` is a specialized parser for the legacy BIFF format and does not accept OOXML `.xlsx` files.

Formula records are captured from BIFF and decompiled to text using `xlrd`'s formula parser. The adapter never evaluates formulas; the BIFF cached result is mapped to `Formula.cached_result` when present.

## Rejected alternatives

LibreOffice, Excel automation, COM, and external conversion are prohibited by WORK-006. General-purpose spreadsheet libraries that do not read BIFF directly were not selected.

## Consequences

The adapter owns all `xlrd` imports and translates parser values into `RawWorkbook`. The domain and business logic remain format-independent. Password-protected and malformed files are rejected with controlled reader issues. BIFF formatting is used only to decode dates and does not alter source text, so text such as `001234` remains text.

## Risks

BIFF formula tokens can include features that `xlrd` cannot decompile. Such formulas remain protected by the parse error boundary and are never executed; the limitation is documented for review and covered by the synthetic formula fixture.
