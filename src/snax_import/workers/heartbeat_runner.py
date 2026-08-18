from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Event, Thread


class HeartbeatRunner:
    def __init__(self, *, interval_seconds: float, heartbeat: Callable[[], object]) -> None:
        self.interval_seconds = interval_seconds
        self.heartbeat = heartbeat
        self._stop = Event()
        self._thread: Thread | None = None
        self.error: BaseException | None = None

    def __enter__(self) -> HeartbeatRunner:
        self._thread = Thread(target=self._run, name="snax-job-heartbeat", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds * 2))
            if self._thread.is_alive():
                logging.getLogger(__name__).error("JOB_HEARTBEAT_RUNNER_STOP_TIMEOUT")

    def raise_if_failed(self) -> None:
        if self.error is not None:
            raise self.error

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.heartbeat()
            except BaseException as exc:
                self.error = exc
                logging.getLogger(__name__).exception("JOB_HEARTBEAT_FAILED", exc_info=exc)
                self._stop.set()
