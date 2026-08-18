import { NavLink, Route, Routes } from "react-router-dom";

const routes = [
  ["/", "Дашборд"],
  ["/imports", "Импорты"],
  ["/imports/new", "Новая загрузка"],
  ["/profiles", "Профили"],
  ["/settings", "Настройки"],
] as const;

function Placeholder({ title }: { title: string }) {
  return (
    <section className="panel">
      <p className="eyebrow">SNAX ORDER IMPORT</p>
      <h1>{title}</h1>
      <p>Рабочая область внешнего сервиса импорта заказов.</p>
    </section>
  );
}

export function App() {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">SNAX</div>
        <nav aria-label="Основная навигация">
          {routes.map(([path, label]) => (
            <NavLink key={path} to={path} end={path === "/"}>
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main>
        <Routes>
          {routes.map(([path, label]) => (
            <Route key={path} path={path} element={<Placeholder title={label} />} />
          ))}
          <Route path="/imports/:id" element={<Placeholder title="Карточка импорта" />} />
        </Routes>
      </main>
    </div>
  );
}
