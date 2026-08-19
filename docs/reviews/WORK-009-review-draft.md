# WORK-009 — Supplier Profile Detection review draft

Status: `READY_TO_MERGE`

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

Для каждого file rule строится отдельный `ProfileFingerprint`: filename pattern,
extensions, media types, нормализованные sheet names и column names. Этот объект
используется всеми компонентами сравнения и сохраняется в explain result кандидата.

В работу не входят product matching, номенклатура, 1С, normalization, order
calculation, AI matching, fuzzy matching и чтение файлов.

## 2. Архитектура

`src/snax_import/domain/profile_detection.py` содержит framework-neutral immutable
модели `ProfileFingerprint`, `ScoreComponent`, `ProfileMatchCandidate` и
`DetectionResult`, а также enum confidence и domain status.
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

Внутренний компонентный ratio каждого признака находится в диапазоне `0..1`. Итог:

```text
score = sum(component_score * active_weight) / sum(active_weight)
```

В контракте результат представлен как `totalScore` в диапазоне `0..100` и
`scoreComponents`. Каждый компонент содержит начисленный `score` и максимальный
`weight`; domain model проверяет, что сумма начисленных баллов равна `totalScore`.

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

Domain status принимает `MATCHED`, `PROFILE_NOT_FOUND`, `AMBIGUOUS_PROFILE` или
`TEMPLATE_CHANGED` и согласован с наличием selected profile.

## 6. TEMPLATE_CHANGED

Если filename pattern распознаёт поставщика, совпадает хотя бы один объявленный
форматный признак (extension/media type), но weighted structural compatibility листов
и колонок ниже `structural_compatibility_threshold` (`0.50`), detector возвращает
`TEMPLATE_CHANGED`, `selectedProfile = null` и одноимённый blocking issue.

Так `price_alfa.xlsx` с ожидаемыми листом `Прайс` и колонками
`Артикул / Цена / Остаток`, пришедший с листом `Новый шаблон` и колонками
`SKU / Unit price / Available`, не маскируется как неизвестный поставщик.

## 7. Примеры

Для `price_alfa.xlsx` с листом `Прайс` и колонками `Артикул`, `Цена`, `Остаток`
профиль с соответствующими правилами получает score `1.0`, confidence `HIGH` и
возвращается как `selected_profile`.

Для файла `price_common.xlsx`, когда два профиля получают `0.82` и `0.80`, результат
содержит оба `ProfileMatchCandidate`, `MEDIUM` confidence и issue
`AMBIGUOUS_PROFILE`; ни один профиль не selected.

Success contract example содержит `totalScore = 98` и component points
`filename=20/20`, `extension=10/10`, `sheets=30/30`, `columns=38/40`.

## 8. Tests and fixtures

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

Матрица `docs/qa/detection-test-matrix.md` связывает DET-001…DET-009 с automated
tests, включая invalid metadata, workbook 5 001 rows, UI serialization contract и
manager approval hand-off без автоматического выбора.

## 9. Contract

Schema проверяет status, candidates, fingerprint, weighted score explanation,
confidence, selected profile shape, запрет `HIGH` без selected profile и все три
blocking issues. Contract gate включает четыре positive examples: success, ambiguous,
template changed и unknown, а также negative fixture для `HIGH` без selection.

## 10. Limitations and follow-up

1. Ranges, header aliases, row classification и semantic validation остаются
   последующими задачами; fingerprint TASK-011 покрывает технические признаки.
2. Detector использует только active current profile version; draft/archived profiles
   не участвуют в автоматическом выборе.
3. Header detection ищет совпадение среди raw rows и не выполняет normalization или
   product interpretation.
4. Media type по умолчанию выключен в score и должен быть включён в deployment-specific
   configuration, если он является различающим признаком.

## 11. Verification

Финальный локальный quality gate:

```text
ruff check .                 PASS
ruff format --check .        PASS
mypy src                     PASS
pytest -q                    PASS (141 passed, 9 integration tests skipped)
python scripts/validate_contracts.py PASS
python scripts/validate_manifest.py  PASS
git diff --check             PASS
```
