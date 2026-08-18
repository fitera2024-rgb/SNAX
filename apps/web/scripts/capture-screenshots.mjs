import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
const routes = [["dashboard", "/"], ["imports", "/imports"], ["new-import", "/imports/new"], ["import-detail", "/imports/15fd7c55-19e1-468d-b4aa-cdc3f327d8e1"], ["profiles", "/profiles"], ["settings", "/settings"]];
const viewports = [["1366", 1366, 900], ["390", 390, 844]];
const output = resolve(process.cwd(), "../../docs/screenshots/work-001");
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
for (const [size, width, height] of viewports) { const page = await browser.newPage({ viewport: { width, height } }); for (const [name, path] of routes) { await page.goto(`http://localhost:5173${path}`, { waitUntil: "networkidle" }); await page.screenshot({ path: resolve(output, `${name}-${size}.png`), fullPage: true }); } await page.close(); }
await browser.close();
