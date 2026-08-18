from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from .models import ImportRow, ImportStatusDetail, ImportStatusSummary

FIRST_IMPORT_ID = UUID("15fd7c55-19e1-468d-b4aa-cdc3f327d8e1")
SECOND_IMPORT_ID = UUID("d1064521-9977-445e-ad34-8c24086627ed")

_IMPORTS: dict[str, tuple[ImportStatusSummary, list[ImportRow], ImportStatusDetail]] = {}


def _seed() -> None:
    records: list[tuple[ImportStatusSummary, list[ImportRow], ImportStatusDetail]] = [
        (
            ImportStatusSummary(
                id=FIRST_IMPORT_ID,
                supplier="Демо-поставщик Север",
                fileName="price_vendor_a_20260818.xlsx",
                profile="VENDOR_A_V1",
                rows=220,
                errors=2,
                status="READY_FOR_1C",
                createdAt=datetime(2026, 8, 18, 10, 15, tzinfo=UTC),
            ),
            [
                ImportRow(
                    row=1,
                    sku="SKU-1001",
                    supplierSku="SUP-A-1001",
                    name="Фруктовый сок 1л",
                    status="ok",
                    amount=120,
                ),
                ImportRow(
                    row=2,
                    sku="SKU-1002",
                    supplierSku="SUP-A-1002",
                    name="Молоко ультрапастеризованное 0.9%",
                    status="warning",
                    amount=60,
                ),
            ],
            ImportStatusDetail(
                id=FIRST_IMPORT_ID,
                supplier="Демо-поставщик Север",
                fileName="price_vendor_a_20260818.xlsx",
                profile="VENDOR_A_V1",
                rows=220,
                errors=2,
                status="READY_FOR_1C",
                createdAt=datetime(2026, 8, 18, 10, 15, tzinfo=UTC),
                steps=["raw_loaded", "profile_selected", "normalized", "validated", "ready_for_1C"],
            ),
        ),
        (
            ImportStatusSummary(
                id=SECOND_IMPORT_ID,
                supplier="Демо-поставщик Восток",
                fileName="supplier_b.csv",
                profile="SUPPLIER_B_V2",
                rows=188,
                errors=6,
                status="PROFILE_REVIEW",
                createdAt=datetime(2026, 8, 18, 9, 2, tzinfo=UTC),
            ),
            [
                ImportRow(
                    row=1,
                    sku="L-5001",
                    supplierSku="LB-5001",
                    name="Туалетная бумага 4 шт.",
                    status="error",
                    amount=200,
                ),
            ],
            ImportStatusDetail(
                id=SECOND_IMPORT_ID,
                supplier="Демо-поставщик Восток",
                fileName="supplier_b.csv",
                profile="SUPPLIER_B_V2",
                rows=188,
                errors=6,
                status="PROFILE_REVIEW",
                createdAt=datetime(2026, 8, 18, 9, 2, tzinfo=UTC),
                steps=["raw_loaded", "profile_review", "blocked_by_template"],
            ),
        ),
    ]

    for summary, rows, detail in records:
        _IMPORTS[str(summary.id)] = (summary, rows, detail)


def list_imports() -> list[ImportStatusSummary]:
    return [value[0] for value in _IMPORTS.values()]


def get_import_summary(import_id: UUID) -> ImportStatusSummary | None:
    value = _IMPORTS.get(str(import_id))
    return value[0] if value is not None else None


def get_import_rows(import_id: UUID) -> list[ImportRow]:
    value = _IMPORTS.get(str(import_id))
    return value[1] if value is not None else []


def get_import_detail(import_id: UUID) -> ImportStatusDetail | None:
    value = _IMPORTS.get(str(import_id))
    return value[2] if value is not None else None


_seed()
