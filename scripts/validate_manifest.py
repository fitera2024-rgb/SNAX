from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "MANIFEST.sha256"


def sha256_file(path: Path) -> str:
    # Git normalizes tracked text to LF. Validate that canonical representation so
    # the same manifest works on Windows checkouts with core.autocrlf enabled.
    data = path.read_bytes()
    if path.suffix.lower() != ".png":
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    failures: list[str] = []
    for line_number, raw_line in enumerate(MANIFEST.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            expected, relative_path = raw_line.split("  ", 1)
        except ValueError:
            failures.append(f"line {line_number}: invalid manifest entry")
            continue
        path = ROOT / relative_path
        if not path.is_file():
            failures.append(f"{relative_path}: missing")
            continue
        actual = sha256_file(path)
        if actual != expected:
            failures.append(f"{relative_path}: expected {expected}, actual {actual}")

    if failures:
        raise SystemExit("manifest validation failed:\n" + "\n".join(failures))
    print(f"validated {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
