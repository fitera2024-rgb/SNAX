# WORK-009 — Supplier Profile Detection review draft

Status: `REVIEW`

Branch: `work/009-supplier-profile-detection`

Base: `work/008-supplier-profile-schema`

Merge: не выполнялся.

## 1. Цель и границы

WORK-009 добавляет техническое определение Supplier Profile для уже прочитанного
`RawWorkbook`:

```text
Reader -> RawWorkbook -> SupplierProfileDetector -> DetectionResult
```

Detector рассматривает только активную текущую версию профиля. В работу входят
filename pattern, extension, sheet names, declared column names и media type.

В работу не входят product matching, номенклатура, 1С, normalization, order
calculation, AI matching, fuzzy matching и чтение файлов.

## 2. Архитектура

`src/snax_import/domain/profile_detection.py` содержит framework-neutral immutable
модели `ProfileMatchCandidate` и `DetectionResult`, а также enum confidence.
`src/snax_import/application/profile_detector.py` содержит orchestration и сравнение
`RawWorkbook` с декларативными правилами `SupplierProfileVersion`.

Reader остаётся ответственным только за построение raw-модели. Detector не открывает
файлы, не меняет raw cells и не импортирует reader adapters.

## 3. Detection strategy

Для каждой active profile version detector оценивает каждое `SupplierFileRule` как
отдельный технический вариант и оставляет лучший вариант профиля.

- Filename использует case-insensitive glob (`price*`); для совместимости с уже
  существующим `fileNameRegex` поддерживается безопасный regex fallback.
- Extension сравнивается с суффиксом имени файла без доверия к регистру.
- Media type сравнивается без параметров после `;` (`text/csv; charset=utf-8`
  совпадает с `text/csv`).
- Sheet names сравниваются после trim/casefold/схлопывания пробелов. Оцениваются
  expected sheets file rule или required sheet mappings.
- Column names ищутся среди текстовых raw/display значений строк workbook; лучшая
  строка заголовка получает долю совпавших объявленных source columns.

Пустой технический признак не штрафует профиль: его вес исключается из знаменателя.
Таким образом, вариант с filename и columns не получает искусственный штраф за
отсутствующий sheet rule.

## 4. Scoring

Компонентный score каждого признака находится в диапазоне `0..1`. Итог:

```text
score = sum(component_score * active_weight) / sum(active_weight)
```

Весы задаются через `ProfileDetectionWeights`. Значения по умолчанию:

| Признак | Вес |
|---|---:|
| filename | 0.20 |
| sheet | 0.30 |
| columns | 0.40 |
| extension | 0.10 |
| media type | 0.00 |

Последний вес оставлен нулевым по умолчанию, чтобы сохранить запрошенную базовую
модель 20/30/40/10; media type включается конфигурацией без изменения detector.

## 5. Confidence и выбор

По умолчанию confidence классифицируется так:

| Score | Confidence |
|---:|---|
| `>= 0.80` | `HIGH` |
| `>= 0.50` | `MEDIUM` |
| `< 0.50` | `LOW` |

Автоматический выбор требует score не ниже `selection_threshold` (`0.50`). При двух
и более кандидатах выбор запрещён, если разница между первым и вторым score меньше
`ambiguity_margin` (`0.05`). Поэтому кандидаты `0.82` и `0.80` дают
`AMBIGUOUS_PROFILE` и `selected_profile = None`.

При отсутствии положительного кандидата или при отсутствии кандидата выше порога
возвращается `ReaderIssueCode.PROFILE_NOT_FOUND`. При близких сильных кандидатах
возвращается `ReaderIssueCode.AMBIGUOUS_PROFILE`. В обоих случаях selected profile
не выбирается автоматически, а ranked candidates сохраняются в результате. Для любого
результата без selected profile итоговый confidence принудительно ограничен `MEDIUM`;
`HIGH` допустим только вместе с выбранным профилем.

## 6. Примеры

Для `price_alfa.xlsx` с листом `Прайс` и колонками `Артикул`, `Цена`, `Остаток`
профиль с соответствующими правилами получает score `1.0`, confidence `HIGH` и
возвращается как `selected_profile`.

Для файла `price_common.xlsx`, когда два профиля получают `0.82` и `0.80`, результат
содержит оба `ProfileMatchCandidate`, `MEDIUM` confidence и issue
`AMBIGUOUS_PROFILE`; ни один профиль не selected.

## 7. Tests and fixtures

Добавлены unit/integration-like tests в `tests/test_profile_detection.py`:

- filename glob match;
- sheet match с безопасной нормализацией;
- column header match;
- extra columns без штрафа;
- extra sheets без штрафа;
- partial sheet match;
- media type weighting;
- changed template / no automatic selection;
- configurable weighted scoring;
- HIGH/MEDIUM/LOW confidence;
- simple match `RawWorkbook -> Detector -> SupplierProfile`;
- multiple candidates;
- no match / `PROFILE_NOT_FOUND`;
- ambiguous match `0.82/0.80` с `MEDIUM` confidence без selection;
- independent CSV supplier profile.

Synthetic fixtures находятся в `tests/fixtures/profile_detection/` и не содержат
коммерческих данных.

## 8. Contract

Добавлены `contracts/profile-detection.schema.json` и synthetic example
`contracts/examples/profile-detection.example.json`. Schema проверяет candidates,
 confidence, selected profile shape, запрет `HIGH` без selected profile и
 `PROFILE_NOT_FOUND`/`AMBIGUOUS_PROFILE` issues. `scripts/validate_contracts.py`
 подключает валидный example и negative fixture к общему contract gate.

## 9. Limitations and follow-up

1. Structural fingerprint, ranges, header aliases, row classification и profile drift
   checks остаются отдельной последующей задачей.
2. Detector использует только active current profile version; draft/archived profiles
   не участвуют в автоматическом выборе.
3. Header detection ищет совпадение среди raw rows и не выполняет normalization или
   product interpretation.
4. Media type по умолчанию выключен в score и должен быть включён в deployment-specific
   configuration, если он является различающим признаком.

## 10. Verification

Финальный локальный quality gate:

```text
ruff check .                 PASS
ruff format --check .        PASS
mypy src                     PASS
pytest -q                    PASS (9 existing integration tests skipped)
python scripts/validate_contracts.py PASS
python scripts/validate_manifest.py  PASS
git diff --check             PASS
```
