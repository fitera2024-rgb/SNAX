# WORK-008-CLEANUP report

Статус: cleanup completed, merge not performed.

## Что найдено

В рабочем дереве находилась вторая незакоммиченная часть реализации WORK-008:

- application/supplier_profiles.py с facade-сервисами создания версии и архивации;
- расширенные exports в domain/__init__.py и application/__init__.py;
- infrastructure adapter, ошибочно экспортированный через ports/__init__.py;
- compatibility aliases SupplierProfileStatus, SupplierTargetField,
  SupplierDataType и SupplierValidationRuleType;
- дополнительный framework-neutral SupplierProfileValidator в domain.

Git history не содержит supplier_profiles.py или SupplierDataType. Эти элементы
появились в незакоммиченном рабочем дереве 19 августа 2026 года и не происходят
из base-ветки WORK-007. SupplierDataType является прямым alias для DataType,
добавленным для совместимости словаря имён двух параллельных черновиков WORK-008.

## Соответствие архитектуре

Найденные SupplierProfile, SupplierProfileVersion, SupplierSheetMapping,
SupplierColumnMapping и SupplierValidationRule соответствуют domain scope WORK-008.
Они framework-neutral и не импортируют HTTP, БД, readers, matching,
normalization, 1С или order logic.

CreateSupplierProfile, GetSupplierProfile и UpdateSupplierProfileVersion используют
repository port. CreateSupplierProfileVersion и ArchiveSupplierProfile являются
тонкими facade-сервисами над теми же application contracts.

SupplierProfileRepository содержит требуемые save, get, list и archive. In-memory
реализация остаётся отдельным adapter для тестов.

## Какие зависимости были сломаны

- domain/__init__.py импортировал SupplierDataType и другие имена до согласования
  канонических exports; SupplierDataType не является отдельным enum.
- ports/__init__.py импортировал InMemorySupplierProfileRepository, создавая
  обратную зависимость ports на infrastructure adapter.
- UpdateSupplierProfileVersion существовал, но не экспортировался публичным
  application API.
- archive изменял effectiveTo у всех версий, нарушая требование о неизменности
  истории при архивации.
- ValidationSeverity.CRITICAL существовал в domain, но отсутствовал в JSON Schema.

## Что сохранено

- все domain entities, enums, versioning и serialization;
- compatibility aliases, включая SupplierDataType;
- оба application module: core contracts и plural facade;
- domain и application validators;
- repository port и in-memory adapter;
- дополнительные проверки уникальности mappings и validation rules.

Application ProfileValidator остаётся основным валидатором use cases со стабильными
machine-readable codes. SupplierProfileValidator сохранён как framework-neutral
compatibility API и не используется application services.

## Что удалено

Файлы и полезные сущности не удалялись. Удалены только:

- импорт InMemorySupplierProfileRepository из ports package;
- изменение version snapshots внутри SupplierProfile.archive.

## Какие файлы изменены и почему

- domain/supplier_profile.py: archive теперь меняет только статус и updatedAt.
- domain/__init__.py: добавлены канонические enum exports при сохранении aliases.
- ports/__init__.py: восстановлено направление зависимости к port, без adapter.
- application/supplier_profiles.py: публично экспортирован core Update service.
- application/__init__.py: опубликованы Create/Get/Update/Profile services и validator.
- contracts/supplier-profile.schema.json: severity синхронизирована с domain.
- tests/test_supplier_profile.py: facade и неизменность history покрыты тестом.

Ни 1С, ни matching, ни normalization, ни order logic не добавлялись. Merge не
выполнялся.
