import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { App } from "./App";
import { ImportDataState } from "./pages";

function renderAt(path: string) { return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>); }
test.each([["/", "Контроль входящих файлов"], ["/imports", "Все импорты"], ["/imports/new", "Исходный файл поставщика"], ["/profiles", "Профили поставщиков"], ["/settings", "Параметры приложения"]])("route %s renders its screen", (path, heading) => { renderAt(path); expect(screen.getByRole("heading", { name: heading, level: 2 })).toBeInTheDocument(); });
test("mock upload requires the data confirmation", async () => { const user = userEvent.setup(); renderAt("/imports/new"); const submit = screen.getByRole("button", { name: "Зарегистрировать mock-загрузку" }); expect(submit).toBeDisabled(); await user.click(screen.getByRole("checkbox")); expect(submit).toBeEnabled(); await user.click(submit); expect(screen.getByText("Mock-загрузка зарегистрирована")).toBeInTheDocument(); });
test.each(["loading", "empty", "error"] as const)("import detail supports %s state", (state) => { render(<ImportDataState state={state} />); expect(screen.getByText(state === "loading" ? /Загружаем/ : state === "empty" ? /пока нет данных/ : /Не удалось/)).toBeInTheDocument(); });
