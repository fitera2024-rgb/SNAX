# Контракты интеграции

- `openapi.yaml` — HTTP API сервиса.
- `schemas/import-package.schema.json` — канонический пакет прайс-листа для 1С.
- `schemas/mapping-sync.schema.json` — дельта подтверждённых связей из 1С.
- `schemas/receipt-package.schema.json` — канонический пакет документа поставки для staging приемки.
- `raw-workbook.schema.json` — framework-neutral raw workbook result для reader protocol.
- `supplier-profile.schema.json` — declarative supplier profile and immutable version snapshots.
- `examples/` — валидные примеры для contract tests.
- `invalid/` — примеры, которые обязаны быть отклонены схемой.

Raw workbook использует 1-based индексы строк/колонок и хранит A1-представление
координаты рядом с числовыми индексами. `FORMULA` — только metadata (`formulaText`
и cached result); схема и reader не исполняют формулы. Для `ERROR` исходный Excel
token (`#REF!`, `#DIV/0!`, `#VALUE!`) сохраняется в `rawValue`, а `errorCode`
содержит стабильный machine code, например `FORMULA_ERROR_REF`.
Schema связывает `valueType` с JSON-типом `rawValue`, поэтому `STRING: "001234"`
не может пройти contract validation после молчаливого преобразования в число.

Правила изменения:

1. обратимо совместимые дополнения выпускаются в рамках той же major-версии;
2. breaking changes требуют новой версии endpoint/schema и ADR;
3. денежные и количественные значения передаются строками decimal;
4. идентификаторы и GTIN передаются строками;
5. примеры должны валидироваться Draft 2020-12 и OpenAPI parser в CI.
