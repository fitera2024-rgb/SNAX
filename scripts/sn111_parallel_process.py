from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import time
import traceback
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel
from PIL import Image, ImageDraw, ImageFont, ImageOps

PUBLIC_KEY = os.environ.get("PUBLIC_KEY", "https://disk.yandex.ru/d/-yUlF0K-Ot1ZoA")
GROUP = int(os.environ.get("GROUP", "0"))
GROUPS = int(os.environ.get("GROUPS", "6"))
META_API = "https://cloud-api.yandex.net/v1/disk/public/resources"
DOWNLOAD_API = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
ROOT = Path(os.environ.get("OUTPUT_ROOT", f"sn111_parallel/group_{GROUP}"))
TRANSCRIPTS = ROOT / "transcripts"
FRAMES = ROOT / "frames"
CONTACTS = ROOT / "contact_sheets"
AUDIO = ROOT / "audio"
WORK = ROOT / "work"
LOGS = ROOT / "logs"
for path in [TRANSCRIPTS, FRAMES, CONTACTS, AUDIO, WORK, LOGS]:
    path.mkdir(parents=True, exist_ok=True)


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"[{stamp}] {message}"
    print(line, flush=True)
    with (LOGS / "processing.log").open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def request_json(base_url: str, params: dict[str, Any], retries: int = 6) -> dict[str, Any]:
    url = base_url + "?" + urllib.parse.urlencode(params)
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "SN111-parallel-processor/1.0"})
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response)
        except Exception as exc:
            last = exc
            delay = min(60, 2**attempt)
            log(f"API retry {attempt + 1}/{retries}: {exc}; sleep {delay}s")
            time.sleep(delay)
    raise RuntimeError(f"Yandex API request failed: {last}")


def normalize_path(path: str | None) -> str:
    if not path:
        return "/"
    if path.startswith("disk:"):
        path = path[5:]
    if not path.startswith("/"):
        path = "/" + path
    return path


def list_all() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def walk(path: str = "/") -> None:
        path = normalize_path(path)
        if path in seen:
            return
        seen.add(path)
        offset = 0
        while True:
            data = request_json(
                META_API,
                {"public_key": PUBLIC_KEY, "path": path, "limit": 1000, "offset": offset, "sort": "name"},
            )
            embedded = data.get("_embedded") or {}
            batch = embedded.get("items") or []
            for raw in batch:
                item = dict(raw)
                item["path"] = normalize_path(
                    raw.get("path") or (path.rstrip("/") + "/" + (raw.get("name") or ""))
                )
                items.append(item)
                if item.get("type") == "dir":
                    walk(item["path"])
            offset += len(batch)
            if not batch or offset >= embedded.get("total", len(batch)):
                break

    walk()
    return items


def download(resource_path: str, destination: Path, expected_size: int | None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    last: Exception | None = None
    for attempt in range(6):
        try:
            partial.unlink(missing_ok=True)
            href = request_json(DOWNLOAD_API, {"public_key": PUBLIC_KEY, "path": resource_path})["href"]
            request = urllib.request.Request(href, headers={"User-Agent": "SN111-parallel-processor/1.0"})
            with urllib.request.urlopen(request, timeout=180) as response, partial.open("wb") as stream:
                shutil.copyfileobj(response, stream, length=1024 * 1024)
            if expected_size and partial.stat().st_size != expected_size:
                raise OSError(f"size mismatch: expected {expected_size}, got {partial.stat().st_size}")
            partial.replace(destination)
            return
        except Exception as exc:
            last = exc
            delay = min(90, 3 * 2**attempt)
            log(f"Download retry {attempt + 1}/6 for {resource_path}: {exc}; sleep {delay}s")
            time.sleep(delay)
    raise RuntimeError(f"Download failed for {resource_path}: {last}")


def safe(value: str, limit: int = 100) -> str:
    value = unicodedata.normalize("NFC", value)
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value)
    value = re.sub(r"\s+", " ", value).strip(" ._")
    return (value or "file")[:limit]


def chronological_key(item: dict[str, Any]) -> tuple[str, str]:
    name = item.get("name") or ""
    match = re.search(r"(20\d{6})[_-]?(\d{6})", name)
    if match:
        return match.group(1) + match.group(2), name.casefold()
    return "99999999999999", name.casefold()


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    log("RUN " + " ".join(command))
    return subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def probe(path: Path) -> dict[str, Any]:
    result = run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    )
    return json.loads(result.stdout)


def timestamp(seconds: float, srt: bool = False) -> str:
    if not math.isfinite(seconds):
        seconds = 0
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    separator = "," if srt else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def contact_sheets(frame_directory: Path, destination: Path, interval: float) -> int:
    frames = sorted(frame_directory.glob("frame_*.jpg"))
    if not frames:
        return 0
    destination.mkdir(parents=True, exist_ok=True)
    columns, rows = 4, 4
    cell_w, cell_h, label_h = 400, 250, 28
    font = ImageFont.load_default()
    count = 0
    for start in range(0, len(frames), columns * rows):
        selected = frames[start : start + columns * rows]
        canvas = Image.new("RGB", (columns * cell_w, rows * (cell_h + label_h)), "white")
        draw = ImageDraw.Draw(canvas)
        for local, frame_path in enumerate(selected):
            global_index = start + local
            with Image.open(frame_path) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((cell_w, cell_h), Image.Resampling.LANCZOS)
                x = local % columns * cell_w + (cell_w - image.width) // 2
                y = local // columns * (cell_h + label_h) + (cell_h - image.height) // 2
                canvas.paste(image, (x, y))
            draw.text(
                (local % columns * cell_w + 8, local // columns * (cell_h + label_h) + cell_h + 5),
                f"{global_index + 1:04d}  {timestamp(global_index * interval)}",
                fill="black",
                font=font,
            )
        count += 1
        canvas.save(destination / f"sheet_{count:03d}.jpg", "JPEG", quality=84, optimize=True)
    return count


def main() -> None:
    all_items = list_all()
    videos = sorted(
        [item for item in all_items if item.get("type") == "file" and (item.get("mime_type") or "").startswith("video/")],
        key=chronological_key,
    )
    selected = [(index + 1, item) for index, item in enumerate(videos) if index % GROUPS == GROUP]
    log(f"Group {GROUP}/{GROUPS}: selected {len(selected)} of {len(videos)} videos")
    (ROOT / "selection.json").write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")

    model = WhisperModel(
        os.environ.get("WHISPER_MODEL", "small"),
        device="cpu",
        compute_type="int8",
        cpu_threads=max(2, os.cpu_count() or 4),
        num_workers=1,
    )
    prompt = (
        "Инструкция по установке торговой точки SNAX Снекс. Форус, Фронтол, 1С, УТ, Розница, ККТ, "
        "онлайн-касса, фискальный накопитель, ФН, ОФД, КСО, касса самообслуживания, термопринтер, "
        "этикетка, штрих-код, QR-код, DataMatrix, Честный знак, сканер, роутер, Wi-Fi, ИБП, RJ-45, "
        "денежный ящик, первый чек."
    )
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for chronological_number, item in selected:
        name = item.get("name") or Path(item["path"]).name
        media_id = f"V{chronological_number:03d}"
        base = f"{media_id}_{safe(Path(name).stem)}"
        local_video = WORK / f"{media_id}.mp4"
        local_audio = AUDIO / f"{base}.mp3"
        frame_directory = FRAMES / base
        contact_directory = CONTACTS / base
        try:
            log(f"VIDEO {media_id}: {item['path']}")
            download(item["path"], local_video, int(item.get("size") or 0) or None)
            metadata = probe(local_video)
            duration = float((metadata.get("format") or {}).get("duration") or 0)
            streams = metadata.get("streams") or []
            video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
            important = any(
                token in name.casefold()
                for token in ["форус", "настр", "штрих", "qr", "сканирован", "молоч", "первому покупателю", "кассир"]
            )
            interval = 2.0 if important else 4.0
            run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(local_video),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    "48k",
                    str(local_audio),
                ]
            )
            frame_directory.mkdir(parents=True, exist_ok=True)
            run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(local_video),
                    "-vf",
                    f"fps=1/{interval:g},scale='if(gt(iw,1600),1600,iw)':-2",
                    "-q:v",
                    "4",
                    str(frame_directory / "frame_%05d.jpg"),
                ]
            )
            sheets = contact_sheets(frame_directory, contact_directory, interval)
            log(f"TRANSCRIBE {media_id}, {duration:.1f}s")
            segments_iterator, info = model.transcribe(
                str(local_audio),
                language="ru",
                beam_size=5,
                best_of=5,
                vad_filter=True,
                word_timestamps=True,
                initial_prompt=prompt,
                condition_on_previous_text=True,
            )
            segments: list[dict[str, Any]] = []
            for segment in segments_iterator:
                segments.append(
                    {
                        "id": segment.id,
                        "start": segment.start,
                        "end": segment.end,
                        "text": segment.text.strip(),
                        "avg_logprob": segment.avg_logprob,
                        "no_speech_prob": segment.no_speech_prob,
                        "words": [
                            {
                                "start": word.start,
                                "end": word.end,
                                "word": word.word,
                                "probability": word.probability,
                            }
                            for word in (segment.words or [])
                        ],
                    }
                )
            (TRANSCRIPTS / f"{base}.txt").write_text(
                "\n".join(f"[{timestamp(segment['start'])} --> {timestamp(segment['end'])}] {segment['text']}" for segment in segments)
                + "\n",
                encoding="utf-8",
            )
            with (TRANSCRIPTS / f"{base}.srt").open("w", encoding="utf-8") as stream:
                for number, segment in enumerate(segments, 1):
                    stream.write(
                        f"{number}\n{timestamp(segment['start'], True)} --> {timestamp(segment['end'], True)}\n{segment['text']}\n\n"
                    )
            (TRANSCRIPTS / f"{base}.json").write_text(
                json.dumps(
                    {
                        "chronological_number": chronological_number,
                        "source_path": item["path"],
                        "source_name": name,
                        "duration_seconds": duration,
                        "detected_language": info.language,
                        "language_probability": info.language_probability,
                        "frame_interval_seconds": interval,
                        "segments": segments,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            results.append(
                {
                    "id": media_id,
                    "source_path": item["path"],
                    "source_name": name,
                    "source_size": item.get("size"),
                    "duration_seconds": duration,
                    "width": video_stream.get("width"),
                    "height": video_stream.get("height"),
                    "frame_interval_seconds": interval,
                    "frame_count": len(list(frame_directory.glob("frame_*.jpg"))),
                    "contact_sheet_count": sheets,
                    "status": "ok",
                }
            )
        except Exception as exc:
            failures.append({"path": item["path"], "error": repr(exc), "traceback": traceback.format_exc()})
            log(f"FAILED {item['path']}: {exc}")
        finally:
            local_video.unlink(missing_ok=True)

    (ROOT / "index.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"DONE group {GROUP}: {len(results)} ok, {len(failures)} failed")


if __name__ == "__main__":
    main()
