# Исследовательский intake 27.08.2026

Публичная папка Яндекс.Диска заказчика. Канонический URL:

**https://disk.yandex.ru/d/dfKzWDC27vtTFg**

Имя папки на Диске: `SNAX`. Это не новый продукт и не замена ТЗ: это передача материалов, в том числе выгрузок 1С.

## Что принято в Git

| Артефакт | Назначение |
|---|---|
| [dump-intake-YANDEX-2026-08-27.md](dump-intake-YANDEX-2026-08-27.md) | Разбор дампов Розницы и УТ |
| [config-dump-manifest.yandex-share.sanitized.json](config-dump-manifest.yandex-share.sanitized.json) | Манифест без payload |
| [retail-config-index.json](retail-config-index.json) | Публичный индекс полной XML Розницы |
| [ut-config-index.json](ut-config-index.json) | Публичный индекс полной XML УТ |
| [extension-index.json](extension-index.json) | Сводка 6 XML-расширений |
| [indexes/](indexes/) | Пообъектный индекс расширений (без имён процедур BSL) |
| [extension-passport.draft.sanitized.json](extension-passport.draft.sanitized.json) | Черновик паспортов, все `UNDECIDED` / `UNVERIFIED` |
| [share-inventory.json](share-inventory.json) | Имена и размеры файлов шары; SHA только у дампов и реестра v1.2 |
| [ACTION_PLAN.md](ACTION_PLAN.md) | Что делать дальше |
| [ibases-display-names.md](ibases-display-names.md) | Только отображаемые имена из list-file |

SHA-256 реестра интервью v1.2 на шаре совпал с [2026-08-26](../2026-08-26/README.md): `f3306f79184c9d6706b4578ee20d383ff0850a040aa7ba3be0e130a98a70a122`.

Набор справочников полной Розницы совпал с частичным ZIP 26.08 (735 имён). Индекс каталогов 26.08 не заменяется.

## Что сознательно не в Git

- zip/xml/cf/cfe/dt payload, в том числе внутренние `Ext/ParentConfigurations/*.cf`;
- `ibases_SNAX (1).v8i` (строки подключения);
- исходные DOCX/PPTX заказчика с коммерческим оформлением;
- прайсы поставщиков, выписки, видео интервью.

Карантин на машине агента: `.local/dumps/incoming/yandex-2026-08-27/` (каталог в `.gitignore`).
