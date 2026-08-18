export type ImportRecord = { id: string; date: string; time: string; supplier: string; file: string; profile: string; rows: number; errors: number; status: "Готов" | "Требует внимания" | "Обработка" };
export const imports: ImportRecord[] = [
  { id: "15fd7c55-19e1-468d-b4aa-cdc3f327d8e1", date: "18.08.2026", time: "10:15", supplier: "Демо-поставщик Север", file: "demo_price_0818.xlsx", profile: "DEMO_NORTH v1.4", rows: 220, errors: 0, status: "Готов" },
  { id: "d1064521-9977-445e-ad34-8c24086627ed", date: "18.08.2026", time: "09:02", supplier: "Демо-поставщик Восток", file: "demo_catalog.csv", profile: "DEMO_EAST v2.1", rows: 188, errors: 6, status: "Требует внимания" },
  { id: "8d4014ec-36d7-4560-aa6d-c3b32b0717f0", date: "17.08.2026", time: "16:48", supplier: "Автоопределение", file: "demo_input.xlsx", profile: "Определяется", rows: 92, errors: 0, status: "Обработка" },
];
export const profiles = [
  { code: "DEMO_NORTH", name: "Демо-поставщик Север", version: "1.4.0", status: "Активен", last: "18.08.2026, 10:15" },
  { code: "DEMO_EAST", name: "Демо-поставщик Восток", version: "2.1.0", status: "Активен", last: "18.08.2026, 09:02" },
  { code: "DEMO_GENERIC", name: "Универсальный демо-профиль", version: "0.8.0", status: "Черновик", last: "Нет успешных импортов" },
];
