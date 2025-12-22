# scan_executor.py
from __future__ import annotations

import atexit
import logging
import threading
from typing import Optional

# Reuse  already-implemented scheduler (no duplicate logic here).
from scan_policy_scheduler import start_scan_policy_scheduler

logger = logging.getLogger(__name__)

# Single, process-wide handle to the background scheduler.
_STOP_EVENT: Optional[threading.Event] = None


def start_background_scan_executor() -> threading.Event:
    """
    Start the background scan-policy executor (daemonized) exactly once.

    This function is an idempotent, FAANG-style wrapper around 
    `start_scan_policy_scheduler()` implementation. It spawns the scheduler's
    daemon thread that continuously:
      * computes the nearest due `ScanPolicy`,
      * dispatches scans using `run_scan_for_systems(...)`,
      * stamps policy `last_run_epoch` the same way  scheduler already does.

    Returns:
        threading.Event: A stop-event we can `.set()` during graceful shutdown.

    Notes:
        - The underlying scheduler thread is a daemon; it won’t block process exit.
        - We register an atexit hook to set the stop-event on interpreter shutdown.
        - Safe to call multiple times; the same event is returned after the first call.
    """
    global _STOP_EVENT
    if _STOP_EVENT is not None and not _STOP_EVENT.is_set():
        logger.info("[EXEC] background scan executor already running")
        return _STOP_EVENT

    _STOP_EVENT = start_scan_policy_scheduler()
    atexit.register(_shutdown_on_exit)
    logger.info("[EXEC] background scan executor started")
    return _STOP_EVENT


def stop_background_scan_executor() -> bool:
    """
    Signal the background executor to stop polling.

    Returns:
        bool: True if a running executor was signaled, False if it wasn’t running.
    """
    global _STOP_EVENT
    if _STOP_EVENT is None:
        return False
    if not _STOP_EVENT.is_set():
        _STOP_EVENT.set()
        logger.info("[EXEC] background scan executor stop signal sent")
        return True
    return False


def is_background_scan_executor_running() -> bool:
    """
    Quick health check for callers that need to assert executor state.

    Returns:
        bool: True if the executor has been started and not yet stopped.
    """
    return _STOP_EVENT is not None and not _STOP_EVENT.is_set()


def _shutdown_on_exit() -> None:
    """Atexit hook: ensure we signal the scheduler to stop on interpreter shutdown."""
    try:
        stop_background_scan_executor()
    except Exception:  # best-effort; never raise from atexit
        pass
