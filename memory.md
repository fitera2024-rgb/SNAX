# Memory

This file is the working project memory for AI agents.

Eligibility, routing between this file and `1c-templates-mcp` (`remember` / `recall`),
fallback when the MCP server is unavailable — see `AGENTS.md → Project memory`.
There are no permanent entries yet.

Entry format (one entry = one self-contained rule). Use English for narrative,
preserve original 1C identifiers (objects, modules, attributes) as-is:

## 2026-08-25 — Canonical 1C MCP documentation

- **Scope:** Docker MCP servers for 1C (`comol/*` images) and Cursor `.cursor/mcp.json`.
- **Rule:** Treat https://docs.onerpa.ru/mcp-servery-1c as the operational documentation for ports, images, LICENSE_KEY, volumes, and embeddings. Keep project server ids from the 1c-rules catalog (`1C-docs-mcp`, `1c-code-check-mcp`, …); do not rename them to older OneRPA example aliases (`1c-docs-mcp`, `1c-code-checker-mcp`). `1c-data-mcp` is OneMCP (IB HTTP service), not a Docker container.
- **Why:** A renamed id breaks `mcp-1c-tools` routing. Starting images without LICENSE_KEY fails. Mixing OneMCP with Docker search servers confuses install/debug.
- **Source:** user pointed at https://docs.onerpa.ru/mcp-servery-1c after 1c-rules install.

<!--
## YYYY-MM-DD — <short rule title>

- **Scope:** module / subsystem / object where the rule applies (e.g. `Документ.РеализацияТоваровУслуг`).
- **Rule:** what must / must not be done.
- **Why:** consequence of violation (production breakage / data loss / regulatory / data leak).
- **Source:** user request, incident, or external document that established the rule.
-->
