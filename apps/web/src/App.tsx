import { NavLink, Route, Routes, useLocation } from "react-router-dom";

import { Dashboard, ImportDetail, Imports, NewImport, Profiles, Settings } from "./pages";

const navigation = [
  { path: "/", label: "Дашборд", mark: "Д" },
  { path: "/imports", label: "Импорты", mark: "И" },
  { path: "/profiles", label: "Профили", mark: "П" },
  { path: "/settings", label: "Настройки", mark: "Н" },
] as const;
const pageNames: Record<string, string> = { "/": "Дашборд", "/imports": "Журнал импортов", "/imports/new": "Новая загрузка", "/profiles": "Профили поставщиков", "/settings": "Настройки" };

function Layout() {
  const { pathname } = useLocation();
  const title = pathname.startsWith("/imports/") && pathname !== "/imports/new" ? "Карточка импорта" : (pageNames[pathname] ?? "SNAX");
  return <div className="shell"><aside className="sidebar"><div className="brand"><span className="brand-mark">S</span><span>SNAX</span></div><p className="brand-caption">ORDER IMPORT</p><nav aria-label="Основная навигация">{navigation.map(({ path, label, mark }) => <NavLink key={path} to={path} end={path === "/" || path === "/imports"}><span className="nav-mark" aria-hidden="true">{mark}</span>{label}</NavLink>)}</nav><div className="sidebar-foot"><span className="status-dot" />Система доступна<p>Контур: локальный</p></div></aside><div className="workspace"><header className="topbar"><div><p className="breadcrumb">Внешний сервис / {title}</p><h1>{title}</h1></div><div className="operator"><span>ДК</span><div><strong>Демо-контур</strong><small>Без реальных данных</small></div></div></header><main><Routes><Route path="/" element={<Dashboard />} /><Route path="/imports" element={<Imports />} /><Route path="/imports/new" element={<NewImport />} /><Route path="/imports/:id" element={<ImportDetail />} /><Route path="/profiles" element={<Profiles />} /><Route path="/settings" element={<Settings />} /></Routes></main></div></div>;
}

export function App() { return <Layout />; }
