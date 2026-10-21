from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from ..core.config import ROOT


@contextmanager
def job_process_lock(job_id: str) -> Iterator[bool]:
    """Allow only one local process to run a persisted job at a time."""
    lock_dir = ROOT / "data" / "job-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = lock_dir / f"{job_id}.lock"
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError:
                yield False
                return
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                yield False
                return
        yield True
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
