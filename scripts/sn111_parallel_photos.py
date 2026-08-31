from __future__ import annotations

import json
import os
import re
import shutil
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

PUBLIC_KEY = os.environ.get("PUBLIC_KEY", "https://disk.yandex.ru/d/-yUlF0K-Ot1ZoA")
GROUP = int(os.environ.get("GROUP", "0"))
GROUPS = int(os.environ.get("GROUPS", "4"))
META_API = "https://cloud-api.yandex.net/v1/disk/public/resources"
DOWNLOAD_API = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
ROOT = Path(f"sn111_photo_groups/group_{GROUP}")
OUT = ROOT / "photos"
WORK = ROOT / "work"
OUT.mkdir(parents=True, exist_ok=True)
WORK.mkdir(parents=True, exist_ok=True)


def request_json(base: str, params: dict[str, Any]) -> dict[str, Any]:
    url = base + "?" + urllib.parse.urlencode(params)
    last: Exception | None = None
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SN111-photo-groups/1.0"})
            with urllib.request.urlopen(req, timeout=90) as response:
                return json.load(response)
        except Exception as exc:
            last = exc
            time.sleep(min(60, 2**attempt))
    raise RuntimeError(last)


def normalize(path: str | None) -> str:
    if not path:
        return "/"
    if path.startswith("disk:"):
        path = path[5:]
    return path if path.startswith("/") else "/" + path


def list_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def walk(path: str = "/") -> None:
        path = normalize(path)
        if path in seen:
            return
        seen.add(path)
        offset = 0
        while True:
            data = request_json(META_API, {"public_key": PUBLIC_KEY, "path": path, "limit": 1000, "offset": offset, "sort": "name"})
            embedded = data.get("_embedded") or {}
            batch = embedded.get("items") or []
            for raw in batch:
                item = dict(raw)
                item["path"] = normalize(raw.get("path") or path.rstrip("/") + "/" + (raw.get("name") or ""))
                items.append(item)
                if item.get("type") == "dir":
                    walk(item["path"])
            offset += len(batch)
            if not batch or offset >= embedded.get("total", len(batch)):
                break

    walk()
    return items


def safe(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    value = re.sub(r'[\\/:*?"<>|]+', "_", value)
    return re.sub(r"\s+", " ", value).strip(" ._")[:105] or "photo"


def download(item: dict[str, Any], destination: Path) -> None:
    partial = destination.with_suffix(destination.suffix + ".part")
    last: Exception | None = None
    for attempt in range(6):
        try:
            partial.unlink(missing_ok=True)
            href = request_json(DOWNLOAD_API, {"public_key": PUBLIC_KEY, "path": item["path"]})["href"]
            req = urllib.request.Request(href, headers={"User-Agent": "SN111-photo-groups/1.0"})
            with urllib.request.urlopen(req, timeout=180) as response, partial.open("wb") as stream:
                shutil.copyfileobj(response, stream, length=1024 * 1024)
            expected = int(item.get("size") or 0)
            if expected and partial.stat().st_size != expected:
                raise OSError(f"size mismatch {partial.stat().st_size} != {expected}")
            partial.replace(destination)
            return
        except Exception as exc:
            last = exc
            time.sleep(min(90, 3 * 2**attempt))
    raise RuntimeError(last)


def main() -> None:
    items = list_items()
    images = sorted(
        [item for item in items if item.get("type") == "file" and (item.get("mime_type") or "").startswith("image/")],
        key=lambda item: (item.get("name") or "").casefold(),
    )
    selected = [(index + 1, item) for index, item in enumerate(images) if index % GROUPS == GROUP]
    index_rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    print(f"Group {GROUP}: {len(selected)} of {len(images)} photos", flush=True)
    for number, item in selected:
        name = item.get("name") or Path(item["path"]).name
        source = WORK / f"P{number:03d}{Path(name).suffix or '.jpg'}"
        destination = OUT / f"P{number:03d}_{safe(Path(name).stem)}.jpg"
        try:
            print(f"PHOTO {number}/{len(images)} {item['path']}", flush=True)
            download(item, source)
            with Image.open(source) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((2200, 2200), Image.Resampling.LANCZOS)
                image.save(destination, "JPEG", quality=90, optimize=True, progressive=True)
                width, height = image.size
            index_rows.append({
                "id": f"P{number:03d}",
                "source_path": item["path"],
                "source_name": name,
                "output_name": destination.name,
                "width": width,
                "height": height,
                "source_size": item.get("size"),
            })
        except Exception as exc:
            failures.append({"path": item["path"], "error": repr(exc)})
        finally:
            source.unlink(missing_ok=True)
    (ROOT / "photo_index.json").write_text(json.dumps(index_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"DONE group {GROUP}: {len(index_rows)} ok, {len(failures)} failed", flush=True)


if __name__ == "__main__":
    main()
