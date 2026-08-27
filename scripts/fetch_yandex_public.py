"""Скачать публичную папку Яндекс.Диска в карантин .local (payload не в Git)."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PUBLIC = "https://disk.yandex.ru/d/dfKzWDC27vtTFg"
API = "https://cloud-api.yandex.net/v1/disk/public/resources"
DOWNLOAD_API = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / ".local" / "dumps" / "incoming" / "yandex-2026-08-27"


def remote_path_to_local(remote: str) -> Path:
    relative = remote.lstrip("/")
    return DEST / relative


def download_href(remote_path: str) -> str:
    query = urllib.parse.urlencode({"public_key": PUBLIC, "path": remote_path})
    with urllib.request.urlopen(DOWNLOAD_API + "?" + query, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    href = payload.get("href")
    if not href:
        raise RuntimeError(f"no download href for {remote_path}")
    return str(href)


def fetch_file(remote_path: str, size: int | None) -> Path:
    target = remote_path_to_local(remote_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and size is not None and target.stat().st_size == size:
        print(f"skip exists {remote_path}", flush=True)
        return target
    href = download_href(remote_path)
    tmp = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(href, headers={"User-Agent": "snax-dump-intake/1.0"})
    with urllib.request.urlopen(request, timeout=600) as response, tmp.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    tmp.replace(target)
    print(f"saved {target.stat().st_size} {remote_path}", flush=True)
    return target


def collect_files(node: object) -> list[dict]:
    found: list[dict] = []
    if isinstance(node, list):
        for child in node:
            found.extend(collect_files(child))
        return found
    if not isinstance(node, dict):
        return found
    if node.get("type") == "file":
        found.append(node)
    nested = node.get("children") or node.get("items") or []
    if isinstance(nested, list):
        for child in nested:
            found.extend(collect_files(child))
    return found


def main() -> None:
    tree_path = DEST / "tree.json"
    if not tree_path.is_file():
        raise SystemExit(f"missing {tree_path}; list the folder first")
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    files = collect_files(tree)
    priority = (
        "/Розница/",
        "/УТ Новая/",
        "/ibases_SNAX",
        "/SNAX_Анализ_конфигурации",
    )

    def rank(item: dict) -> tuple[int, int]:
        path = item.get("path") or ""
        group = 1
        if any(path.startswith(prefix) or path == prefix.rstrip("/") for prefix in priority):
            group = 0
        return (group, -(item.get("size") or 0) if group == 0 else (item.get("size") or 0))

    files.sort(key=rank)
    only_prefix = sys.argv[1] if len(sys.argv) > 1 else None
    if only_prefix:
        files = [item for item in files if (item.get("path") or "").startswith(only_prefix)]
    failures: list[str] = []
    for item in files:
        path = item["path"]
        try:
            fetch_file(path, item.get("size"))
        except (
            OSError,
            TimeoutError,
            urllib.error.URLError,
            json.JSONDecodeError,
            RuntimeError,
            KeyError,
        ) as exc:
            failures.append(f"{path}: {type(exc).__name__}: {exc}")
            print(f"FAIL {path}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    if failures:
        raise SystemExit(f"failed {len(failures)}/{len(files)}")
    print(f"downloaded {len(files)} files -> {DEST}")


if __name__ == "__main__":
    main()
