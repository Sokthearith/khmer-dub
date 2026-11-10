"""Stopping a running job (the app's Stop button).

Long steps report progress often. Once Stop is pressed, the next progress report raises `Stopped`, so the
job ends at a safe point: finished steps stay saved and the step that was running starts over next time.
External programs (ffmpeg) can't check anything, so Stop also ends the ones that are running.

Jobs run one at a time (the app queues them), so one flag is enough.
"""

from __future__ import annotations

import subprocess
import threading


class Stopped(BaseException):
    """Raised at the next safe point after Stop. A BaseException, so `except Exception` blocks let it through."""


_active = threading.Event()  # a job is running
_stop = threading.Event()  # Stop was pressed during it
_procs: set[subprocess.Popen] = set()
_lock = threading.Lock()


def begin() -> None:
    _stop.clear()
    _active.set()


def end() -> None:
    _active.clear()
    _stop.clear()


def requested() -> bool:
    return _stop.is_set()


def check() -> None:
    if _stop.is_set():
        raise Stopped()


def request() -> bool:
    """Stop the running job. False when nothing is running."""
    if not _active.is_set():
        return False
    _stop.set()
    with _lock:
        procs = list(_procs)
    for p in procs:
        try:
            p.kill()
        except OSError:
            pass
    return True


def popen(cmd: list[str], **kwargs) -> subprocess.Popen:
    """Start an external program that Stop can end. Call `done(p)` when it has finished."""
    check()
    p = subprocess.Popen(cmd, **kwargs)
    with _lock:
        _procs.add(p)
    return p


def done(p: subprocess.Popen) -> None:
    with _lock:
        _procs.discard(p)
