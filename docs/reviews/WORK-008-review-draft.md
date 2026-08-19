# WORK-008 — Supplier Profile Schema review draft

Status: `REVIEW`

Branch: `work/008-supplier-profile-schema`

Merge: не выполнялся.

## 1. Цель

WORK-008 добавляет декларативную доменную модель Supplier Profile. Профиль описывает,
как понимать уже прочитанный `RawWorkbook`: ожидаемые file formats, листы, технические
назначения листов, mappings колонок и validation rules. Detection, matching, normalization,
номенклатура, 1С и расчёт заказа в работу не входят.

## 2. Архитектура

Профиль расположен между reader raw-layer и будущим mapping engine:

```text
XLSX / XLS / CSV -> RawWorkbook -> Supplier Profile -> Future Processing
```

`src/snax_import/domain/supplier_profile.py` не импортирует FastAPI, SQLAlchemy,
PostgreSQL, pandas или reader libraries. Application contracts зависят только от domain
и repository port. In-memory adapter находится в `adapters/memory` и не экспортируется
через ports package.

## 3. Domain model

`SupplierProfile` хранит supplier id, name/description, lifecycle status, current version,
UTC timestamps и ordered immutable version history. `SupplierProfileVersion` хранит schema
version, effective interval, author и декларативное содержимое профиля. Enum vocabulary
ограничивает status, sheet purpose, target field, data type, rule type и severity.

## 4. Versioning

Номер версии начинается с 1 и монотонно увеличивается. При создании профиля автоматически
создаётся первая версия `version_number=1`; поэтому DRAFT-профиль не бывает без истории.
Draft profile может получить следующую версию; activation переводит профиль в `ACTIVE`.
Создание следующей версии у active profile закрывает предыдущую через `effective_to` и
оставляет новый snapshot открытым. Frozen dataclasses, deep-frozen rule values и in-memory
repository запрещают прямое редактирование active profile. Archive меняет aggregate status и
`updated_at`, не переписывая version snapshots, поэтому история сохраняется byte-for-byte на
уровне domain objects.

## 5. File rules

`SupplierFileRule` описывает extensions, media types, optional filename pattern и expected
sheet names. Это декларативные признаки; автоматическое detection намеренно оставлено
для WORK-009.

## 6. Sheet mappings

`SupplierSheetMapping` связывает имя листа с `PRODUCT_PRICE`, `STOCK`, `CATALOG`,
`REFERENCE` или `UNKNOWN`, а также хранит required и priority. Duplicate sheet names
отклоняются.

## 7. Column mappings

`SupplierColumnMapping` связывает source column с техническим target field и declared data
type. Поддерживаются `SUPPLIER_CODE`, `NAME`, `DESCRIPTION`, `PRICE`, `STOCK`, `BARCODE`,
`UNIT`, `CATEGORY`, `UNKNOWN` и `STRING`, `INTEGER`, `DECIMAL`, `DATE`, `BOOLEAN`,
`UNKNOWN`. Значения raw workbook не преобразуются; например, leading-zero code остаётся
строкой. Duplicate source columns и duplicate target fields отклоняются.

## 8. Validation

`SupplierValidationRule` поддерживает `REQUIRED`, `MAX_LENGTH`, `REGEX` и `VALUE_RANGE`.
Domain guards проверяют enum values, positive limits, regex compilation и mapping
duplicates. `ProfileValidator` добавляет application-level machine-readable issues, а
framework-neutral `SupplierProfileValidator` проверяет aggregate invariants до repository
save.

## 9. Schema

`contracts/supplier-profile.schema.json` использует JSON Schema Draft 2020-12, закрытые
objects (`additionalProperties: false`) и явные enum values. В contract validation добавлены
valid examples `simple_supplier_profile`, `multi_sheet_profile`, `versioned_profile` и
invalid examples для missing `supplierId`, invalid status, invalid target field и invalid
version.

## 10. Tests

Добавлены unit tests для lifecycle, append-only versioning, archive history, mapping/rule
failures, repository immutability и application contracts. Property-style tests генерируют
1–30 последовательных versions и проверяют positive version numbers и history preservation.
Contract tests валидируют все three valid examples и отклоняют six invalid fixtures, включая
некорректные UUID и date-time. Format checks выполняются с явным `FormatChecker`.
Fixtures synthetic; реальные прайсы и коммерческие данные не добавлялись.

## 11. Results

Локальные проверки:

```text
ruff check .                 PASS
ruff format --check .       PASS
mypy src                     PASS
pytest -q                   PASS
python scripts/validate_contracts.py PASS
python scripts/validate_manifest.py   PASS after manifest update
git diff --check             PASS
```

Во время разработки исправлен только формат `scripts/validate_contracts.py`; reader
adapters и `RawWorkbook` не изменялись.

## 12. Risks

1. Profile JSON schema пока не содержит detection/fingerprint DSL — это намеренная граница
   WORK-008 и следующий этап.
2. Repository — in-memory test adapter; PostgreSQL persistence не реализуется в этой работе.
3. Application contract использует existing project command style; HTTP and SQL adapters
   отсутствуют.
4. JSON Schema проверяет formats через явный `FormatChecker`; domain tests отдельно проверяют
   timezone-aware UTC timestamps и temporal invariants. Persistent repository и transaction
   boundary остаются отдельной задачей.

## 13. Technical debt

- Добавить persistent repository и transaction boundary в отдельной persistence work.
- Добавить loader/from-dict с безопасным error path для profile files.
- Добавить structural fingerprint, profile matching и explain log в WORK-009.
- Согласовать окончательный profile semver policy с contract compatibility matrix.
- После независимого review обновить этот draft фактическим commit/CI/PR результатом.

## 14. WORK-008-FIX — lifecycle hardening

Финальное ревью выявило три блокера: schema не представляла поддерживаемый DRAFT без версии,
`SupplierValidationRule.value` позволял менять snapshot через исходный mapping, а repository
принимал forged archive с изменённым aggregate. Дополнительно были усилены temporal и format
проверки.

Исправления:

- `SupplierProfile.create()` атомарно создаёт DRAFT с первой версией `1`, а schema требует
  непустую историю и `currentVersion`;
- rule values deep-freeze вложенные mappings/lists, а `to_dict()` возвращает безопасную копию;
- repository принимает только канонические archive/activation transitions и append-only
  version updates без переписывания старой истории;
- domain запрещает `effectiveTo` без `effectiveFrom`, пересечения и несколько открытых версий;
- contract tests и validator используют `FormatChecker`, добавлены invalid UUID/datetime
  fixtures и rule-specific schema guards.

Merge не выполнялся. Статус review остаётся `REVIEW` до независимого подтверждения фикса.
