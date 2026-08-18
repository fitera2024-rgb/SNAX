from __future__ import annotations

import sys
import time

import requests


def wait_for(url: str, expected_text: str) -> None:
    last_error = "no response"
    for _ in range(30):
        try:
            response = requests.get(url, timeout=3)
            response.raise_for_status()
            if expected_text not in response.text:
                raise RuntimeError(f"expected {expected_text!r} in response")
            print(f"smoke ok: {url} -> {response.status_code}")
            return
        except (requests.RequestException, RuntimeError) as exc:
            last_error = str(exc)
            time.sleep(2)
    raise RuntimeError(f"smoke failed: {url}: {last_error}")


def main() -> int:
    wait_for("http://localhost:8000/health", '"status":"ok"')
    wait_for("http://localhost:8000/version", '"applicationName":"SNAX"')
    wait_for("http://localhost:8080", "SNAX Order Import")
    return 0


if __name__ == "__main__":
    sys.exit(main())
