# Контракты интеграции

- `openapi.yaml` — HTTP API сервиса.
- `schemas/import-package.schema.json` — канонический пакет прайс-листа для 1С.
- `schemas/mapping-sync.schema.json` — дельта подтверждённых связей из 1С.
- `schemas/receipt-package.schema.json` — канонический пакет документа поставки для staging приемки.
- `examples/` — валидные примеры для contract tests.

Правила изменения:

1. обратимо совместимые дополнения выпускаются в рамках той же major-версии;
2. breaking changes требуют новой версии endpoint/schema и ADR;
3. денежные и количественные значения передаются строками decimal;
4. идентификаторы и GTIN передаются строками;
5. примеры должны валидироваться Draft 2020-12 и OpenAPI parser в CI.
