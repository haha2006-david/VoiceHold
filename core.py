"""Small, dependency-free state machine for hold-to-talk input."""

from __future__ import annotations

from enum import Enum
import threading
from typing import Callable


class ReleaseResult(str, Enum):
    IGNORED = "ignored"
    TAP = "tap"
    RECORDING_FINISHED = "recording_finished"


class HoldToTalk:
    """Turn a button hold into start/stop callbacks without blocking the hook."""

    def __init__(
        self,
        hold_seconds: float,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
    ) -> None:
        if hold_seconds <= 0:
            raise ValueError("hold_seconds must be positive")
        self._hold_seconds = hold_seconds
        self._on_start = on_start
        self._on_stop = on_stop
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._pressed = False
        self._recording = False

    def press(self) -> bool:
        """Register a press. Returns false if a press is already in progress."""
        with self._lock:
            if self._pressed:
                return False
            self._pressed = True
            self._recording = False
            self._timer = threading.Timer(self._hold_seconds, self._start_if_held)
            self._timer.daemon = True
            self._timer.start()
            return True

    def release(self) -> ReleaseResult:
        """Register a release and report whether it was a normal click or dictation."""
        with self._lock:
            if not self._pressed:
                return ReleaseResult.IGNORED
            self._pressed = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            was_recording = self._recording
            self._recording = False

        if was_recording:
            self._on_stop()
            return ReleaseResult.RECORDING_FINISHED
        return ReleaseResult.TAP

    def _start_if_held(self) -> None:
        # Starting while the lock is held prevents a release from stopping a
        # recorder that has not finished starting yet.
        with self._lock:
            self._timer = None
            if not self._pressed or self._recording:
                return
            try:
                self._on_start()
            except Exception:
                # A failed microphone start should fall back to an ordinary
                # click on release rather than swallowing it permanently.
                self._recording = False
                raise
            self._recording = True

