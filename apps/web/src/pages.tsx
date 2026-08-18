import { type FormEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { imports, profiles, type ImportRecord } from "./data";

function StatusBadge({ status }: { status: ImportRecord["status"] | "Активен" | "Черновик" }) {
  const tone = status === "Готов" || status === "Активен" ? "success" : status === "Обработка" ? "progress" : "warning";
  return <span className={`badge ${tone}`}><span />{status}</span>;
}

function ImportTable({ records = imports }: { records?: ImportRecord[] }) {
  return <div className="table-wrap"><table><thead><tr><th>Дата и время</th><th>Поставщик</th><th>Файл</th><th>Профиль</th><th>Строк</th><th>Ошибок</th><th>Статус</th><th /></tr></thead><tbody>{records.map((item) => <tr key={item.id}><td><strong>{item.date}</strong><small>{item.time}</small></td><td>{item.supplier}</td><td className="file-cell">{item.file}</td><td>{item.profile}</td><td>{item.rows}</td><td className={item.errors ? "error-number" : ""}>{item.errors}</td><td><StatusBadge status={item.status} /></td><td><Link className="table-link" to={`/imports/${item.id}`}>Открыть</Link></td></tr>)}</tbody></table></div>;
}

export function Dashboard() {
  const kpis = [["Файлов сегодня", "12", "+3 к вчера"], ["Успешно обработано", "9", "75% потока"], ["Требуют внимания", "2", "6 ошибок"], ["Несопоставленных позиций", "18", "Нужна проверка"]];
  return <><section className="hero-row"><div><p>Оперативная сводка за 18 августа</p><h2>Контроль входящих файлов</h2></div><Link className="button primary" to="/imports/new">＋ Загрузить файл</Link></section><section className="kpi-grid">{kpis.map(([label, value, note], index) => <article className="kpi-card" key={label}><div className={`kpi-icon tone-${index}`}>{["Ф", "✓", "!", "≠"][index]}</div><div><p>{label}</p><strong>{value}</strong><small>{note}</small></div></article>)}</section><section className="card"><div className="card-head"><div><h2>Последние загрузки</h2><p>Синтетические данные демонстрационного контура</p></div><Link className="text-link" to="/imports">Все импорты →</Link></div><ImportTable records={imports.slice(0, 3)} /></section><section className="notice"><strong>Демо-режим</strong><span>Файлы не загружаются и не обрабатываются. Интерфейс показывает только mock-сценарии WORK-001.</span></section></>;
}

export function Imports() {
  const [query, setQuery] = useState("");
  const filtered = imports.filter((item) => `${item.supplier} ${item.file} ${item.profile}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="card registry"><div className="card-head"><div><h2>Все импорты</h2><p>{filtered.length} записи в демонстрационном журнале</p></div><Link className="button primary" to="/imports/new">＋ Новая загрузка</Link></div><div className="toolbar"><label className="search"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Поставщик, файл или профиль" /></label><button className="button secondary" type="button">Фильтры</button></div>{filtered.length ? <ImportTable records={filtered} /> : <EmptyState message="Импорты по этому запросу не найдены" />}</section>;
}

export function NewImport() {
  const [confirmed, setConfirmed] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const submit = (event: FormEvent) => { event.preventDefault(); if (confirmed) setSubmitted(true); };
  return <div className="form-layout"><form className="card upload-card" onSubmit={submit}><div className="card-head"><div><h2>Исходный файл поставщика</h2><p>Только демонстрация интерфейса, содержимое не читается</p></div><span className="step-label">Шаг 1 из 1</span></div>{submitted ? <div className="success-panel"><span>✓</span><h3>Mock-загрузка зарегистрирована</h3><p>Файл не передавался на сервер. Можно вернуться в журнал импортов.</p><Link className="button primary" to="/imports">Открыть журнал</Link></div> : <><label className="dropzone"><input type="file" accept=".xlsx,.xls,.csv" /><span className="upload-symbol">↑</span><strong>Перетащите файл сюда</strong><small>или нажмите, чтобы выбрать на компьютере</small><em>XLSX, XLS или CSV · до 100 МБ</em></label><label className="field"><span>Поставщик</span><select defaultValue="auto"><option value="auto">Определить автоматически</option><option>Демо-поставщик Север</option><option>Демо-поставщик Восток</option></select><small>Выбор влияет только на mock-сценарий.</small></label><label className="check"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>Подтверждаю, что файл не содержит персональных данных и коммерческой информации.</span></label><div className="form-actions"><Link className="button secondary" to="/imports">Отмена</Link><button className="button primary" disabled={!confirmed}>Зарегистрировать mock-загрузку</button></div></>}</form><aside className="card help-card"><h3>Перед загрузкой</h3><ol><li>Удалите персональные данные.</li><li>Убедитесь, что файл обезличен.</li><li>Не используйте реальные прайсы в демо-контуре.</li></ol><div className="format-note"><strong>Допустимые форматы</strong><p>.xlsx · .xls · .csv</p></div></aside></div>;
}

type DataState = "ready" | "loading" | "empty" | "error";
export function ImportDataState({ state }: { state: DataState }) {
  if (state === "loading") return <div className="state-panel" role="status"><span className="spinner" />Загружаем данные импорта…</div>;
  if (state === "empty") return <EmptyState message="В этом разделе пока нет данных" />;
  if (state === "error") return <div className="state-panel error-state" role="alert"><strong>Не удалось получить данные</strong><span>Повторите попытку позднее. Код: MOCK_UNAVAILABLE</span></div>;
  return <div className="detail-table"><div><span>1</span><strong>SUP-A-1001</strong><p>Напиток фруктовый, 1 л</p><em className="ok-text">Проверено</em></div><div><span>2</span><strong>SUP-A-1002</strong><p>Молочный продукт, 900 мл</p><em className="warn-text">Требует внимания</em></div></div>;
}

export function ImportDetail() {
  const { id } = useParams();
  const record = imports.find((item) => item.id === id) ?? imports[0];
  const [tab, setTab] = useState<"rows" | "errors" | "log">("rows");
  return <><div className="detail-heading"><Link to="/imports" className="back-link">← К журналу</Link><div><h2>{record.file}</h2><StatusBadge status={record.status} /></div><p>ID {record.id}</p></div><section className="summary-grid"><article className="card file-info"><h3>Реквизиты файла</h3><dl><div><dt>Поставщик</dt><dd>{record.supplier}</dd></div><div><dt>Профиль</dt><dd>{record.profile}</dd></div><div><dt>Получен</dt><dd>{record.date}, {record.time}</dd></div><div><dt>Формат</dt><dd>XLSX · 184 КБ</dd></div></dl></article><article className="card pipeline"><h3>Этапы обработки</h3><div className="steps"><span className="done">✓<small>Получен</small></span><i /><span className="done">✓<small>Профиль</small></span><i /><span className="done">✓<small>Проверка</small></span><i /><span className={record.status === "Готов" ? "done" : "attention"}>{record.status === "Готов" ? "✓" : "!"}<small>Результат</small></span></div></article><article className="card mini-summary"><h3>Резюме</h3><strong>{record.rows}<small> строк</small></strong><p><span>{record.errors}</span> ошибок · <span>18</span> предупреждений</p></article></section><section className="card tabs-card"><div className="tabs" role="tablist"><button className={tab === "rows" ? "active" : ""} onClick={() => setTab("rows")}>Строки <span>{record.rows}</span></button><button className={tab === "errors" ? "active" : ""} onClick={() => setTab("errors")}>Ошибки <span>{record.errors}</span></button><button className={tab === "log" ? "active" : ""} onClick={() => setTab("log")}>Протокол</button></div>{tab === "rows" ? <ImportDataState state="ready" /> : tab === "errors" ? (record.errors ? <ImportDataState state="error" /> : <ImportDataState state="empty" />) : <div className="protocol"><time>10:15:03</time> RAW_LOADED · mock-файл зарегистрирован<br /><time>10:15:04</time> PROFILE_SELECTED · {record.profile}<br /><time>10:15:05</time> VALIDATED · проверка завершена</div>}</section></>;
}

function EmptyState({ message }: { message: string }) { return <div className="empty-state"><span>□</span><strong>{message}</strong><small>Измените фильтр или вернитесь позднее.</small></div>; }

export function Profiles() {
  return <><section className="hero-row"><div><p>Декларативные настройки демонстрационного контура</p><h2>Профили поставщиков</h2></div><button className="button secondary" type="button" disabled>＋ Новый профиль</button></section><section className="profile-grid">{profiles.map((profile) => <article className="card profile-card" key={profile.code}><div className="profile-top"><span>{profile.code.slice(5, 7)}</span><StatusBadge status={profile.status as "Активен" | "Черновик"} /></div><h3>{profile.name}</h3><p>{profile.code}</p><dl><div><dt>Версия</dt><dd>{profile.version}</dd></div><div><dt>Последний успешный импорт</dt><dd>{profile.last}</dd></div></dl><button className="button secondary full" type="button">Просмотреть</button></article>)}</section><div className="notice"><strong>Только просмотр</strong><span>Реальное создание и исполнение профилей не входит в WORK-001.</span></div></>;
}

export function Settings() {
  const connections = [["PostgreSQL", "Хранилище метаданных"], ["Redis", "Очередь и кэш"], ["MinIO", "Объектное хранилище"], ["1С:УТ", "Отключено в WORK-001"]];
  return <div className="settings-grid"><section className="card settings-card"><h2>Параметры приложения</h2><p>Без production-секретов и действующих подключений</p><label className="field"><span>Публичный адрес API</span><input value="http://localhost:8000" readOnly /></label><label className="field"><span>Часовой пояс интерфейса</span><select defaultValue="vladivostok"><option value="vladivostok">Asia/Vladivostok (UTC+10)</option></select></label><label className="field"><span>Максимальный размер файла</span><input value="100 МБ" readOnly /></label><button className="button primary" type="button" disabled>Сохранить настройки</button></section><section className="card connection-card"><h2>Подключения</h2><p>Статусы локального scaffold</p>{connections.map(([name, note], index) => <div className="connection" key={name}><span className={index === 3 ? "off" : "on"} /><div><strong>{name}</strong><small>{note}</small></div><em>{index === 3 ? "Не настроено" : "Локально"}</em></div>)}</section><section className="card auth-placeholder"><span>i</span><div><h3>Авторизация</h3><p>Production authorization не реализована. Демо-контур не содержит пользователей, ролей или токенов.</p></div></section></div>;
}
