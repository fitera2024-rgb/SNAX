from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bsl_extension_pack_is_recommended() -> None:
    recommendations = json.loads(
        (ROOT / ".vscode" / "extensions.json").read_text(encoding="utf-8")
    )["recommendations"]
    assert "astrizhachuk.1c-extension-pack" in recommendations
    assert "1c-syntax.language-1c-bsl" in recommendations


def test_unicode_highlight_disabled_for_cyrillic() -> None:
    settings = json.loads((ROOT / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    assert settings["editor.unicodeHighlight.nonBasicASCII"] is False
    assert settings["editor.unicodeHighlight.ambiguousCharacters"] is False


def test_lesson_mcp_servers_use_npx_packages() -> None:
    servers = json.loads((ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert servers["sequential-thinking"] == {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
    }
    assert servers["memory"] == {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
    }
