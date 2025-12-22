# scan_policy_scheduler.py
"""
Scan Policy Scheduler — single module, merged functionality (DB-agnostic).

This module owns orchestration only:
  • Cross-process leader election via a file lock (no DB usage here)
  • Adaptive polling toward the next scheduled run:
        > 120 minutes out  -> sleep 60 minutes
        20-120 minutes out -> sleep 20 minutes
        <= 20 minutes out  -> sleep 1 minute
  • Due-window sweep (±SCAN_WINDOW_SECS around now) so multiple policies set
    for the same minute all get processed
  • Atomic claim via db.try_claim_policy(...)
  • Per-policy system fan-out with ThreadPoolExecutor
  • Graceful shutdown on signals/Flask teardown
  • ZERO direct SQL/ORM usage — all DB I/O is via db.py helpers

Environment variables:
  POLICY_RUNNER_LOCK_PATH            (default: /tmp/policy_runner.lock)
  POLICY_SCHEDULER_WAKE_FALLBACK_SECS (default: 300)   # when nothing upcoming
  POLICY_SCAN_WINDOW_SECS            (default: 300)    # ±window used for due sweep
  POLICY_RUN_MAX_WORKERS             (default: 4)
  POLICY_RUN_OUTPUT_DIR              (default: /tmp/policy-runs)
  POLICY_JOB_ID_PREFIX               (default: "policy")

Integration (factory OR non-factory):
  • Singleton style with signals:
      from scan_policy_scheduler import start_policy_runner, stop_policy_runner
      start_policy_runner()    # safe to call once at boot
      # stop_policy_runner()   # call on shutdown if you need manual control

  • Flask (no factory), paste in flaskapp.py:
      from scan_policy_scheduler import start_policy_runner
      @app.before_first_request
      def _boot_sched():
          start_policy_runner()

  • If you prefer a manual stop event instead:
      from scan_policy_scheduler import start_scan_policy_scheduler
      STOP_EVENT = start_scan_policy_scheduler()
      # ... later -> STOP_EVENT.set()
"""

from __future__ import annotations

import concurrent.futures as cf
import fcntl
import os
import signal
import threading
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Dict, IO, List, Optional, Sequence, Tuple

from log_config import setup_logging
from db import (
    policies_list,                 # -> List[dict]
    try_claim_policy,              # (policy_id, now_epoch, min_epoch) -> bool
    list_system_ids_by_policy_id,  # (policy_id) -> List[int]
    stamp_policy_last_run_now,
)
from python_process_files import run_scan_and_store

logger = setup_logging()

# ─────────────────────────────────────────────────────────────────────────────
# Tunables
# ─────────────────────────────────────────────────────────────────────────────

LOCK_PATH = os.getenv("POLICY_RUNNER_LOCK_PATH", "/tmp/policy_runner.lock")
FALLBACK_WAKE_SECS = int(os.getenv("POLICY_SCHEDULER_WAKE_FALLBACK_SECS", "300"))
SCAN_WINDOW_SECS = int(os.getenv("POLICY_SCAN_WINDOW_SECS", "300"))
MAX_WORKERS = int(os.getenv("POLICY_RUN_MAX_WORKERS", "4"))
RUN_OUTPUT_DIR = os.getenv("POLICY_RUN_OUTPUT_DIR", "/tmp/policy-runs")
JOB_ID_PREFIX = os.getenv("POLICY_JOB_ID_PREFIX", "policy")

# ─────────────────────────────────────────────────────────────────────────────
# Public APIs
# ─────────────────────────────────────────────────────────────────────────────

def start_scan_policy_scheduler() -> threading.Event:
    """Start the scheduler loop on a daemon thread and return a stop_event.

    Returns:
      threading.Event: Event you can .set() to request shutdown.

    Behavior:
      - Starts one daemon thread in this process.
      - Thread elects a cross-process leader via file lock.
      - Loops adaptively toward the nearest scheduled run and, when close,
        performs a due-window sweep to claim & execute all policies firing now.
    """
    stop_event = threading.Event()
    t = threading.Thread(
        target=_scheduler_loop,
        name="scan-policy-scheduler",
        args=(stop_event,),
        daemon=True,
    )
    t.start()
    logger.info("[SCHED] started daemon thread: %s", t.name)
    return stop_event


# Singleton wrapper + signal integration (optional nicer API)

_runner_lock = threading.Lock()
_runner_singleton_stop: Optional[threading.Event] = None

def start_policy_runner() -> None:
    """Idempotently start the singleton scheduler with signal handlers.

    Safe to call multiple times; only the first call starts the background
    thread. Installs SIGTERM/SIGINT handlers to stop gracefully.
    """
    global _runner_singleton_stop
    if _runner_singleton_stop is not None:
        return
    with _runner_lock:
        if _runner_singleton_stop is None:
            _runner_singleton_stop = start_scan_policy_scheduler()
            _install_signal_handlers()

def stop_policy_runner() -> None:
    """Stop the singleton scheduler if running."""
    global _runner_singleton_stop
    with _runner_lock:
        if _runner_singleton_stop is not None:
            try:
                _runner_singleton_stop.set()
            except Exception:
                pass
            _runner_singleton_stop = None

def _install_signal_handlers() -> None:
    """Install SIGTERM/SIGINT handlers that stop the singleton runner."""
    def _handler(signum, _frame):
        logger.info("[SCHED] stop signal %s", signum)
        stop_policy_runner()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handler)
        except Exception:
            # Some embedding environments disallow signal handlers.
            pass

# ─────────────────────────────────────────────────────────────────────────────
# Core loop (adaptive polling + due-window sweep) 
# ─────────────────────────────────────────────────────────────────────────────

def _scheduler_loop(stop_event: threading.Event) -> None:
    """Main loop: elect leader, aim for nearest schedule, sweep window when close.

    Strategy:
      1) Elect a leader via non-blocking file lock (best-effort).
      2) Pull all policy dicts via db.policies_list().
      3) Compute nearest upcoming run time across policies.
      4) Sleep adaptively toward that time (hourly / 20m / 1m).
      5) When inside ±SCAN_WINDOW_SECS of now, sweep all policies whose next fire
         lands inside the window; atomically claim & run each.
    """
    lock_file: Optional[IO] = None
    is_leader = False

    try:
        while not stop_event.is_set():
            # Leader election: only the leader does work; everyone else polls lightly.
            if not is_leader:
                is_leader, lock_file = _try_become_leader(lock_file)
                if not is_leader:
                    _sleep_with_stop(stop_event, seconds=min(60, FALLBACK_WAKE_SECS))
                    continue

            now = datetime.now(timezone.utc)

            # Fetch lightweight policy dicts (DB access abstracted via db.py).
            try:
                pols: List[Dict] = policies_list()
            except Exception:
                logger.exception("[SCHED] failed to list policies; backing off")
                _sleep_with_stop(stop_event, seconds=60)
                continue

            nearest = _compute_nearest_upcoming_run(pols, now)
            if nearest is None:
                # Nothing scheduled → sleep fallback cadence.
                _sleep_with_stop(stop_event, seconds=FALLBACK_WAKE_SECS)
                continue

            _, next_at = nearest
            seconds_until = max(0, int((next_at - now).total_seconds()))

            # Adaptive cadence toward the nearest event.
            if seconds_until > 2 * 3600:
                cadence = 3600
            elif seconds_until > 20 * 60:
                cadence = 20 * 60
            else:
                cadence = 60

            # When close to the firing time, sweep the ±window and run everything due.
            if seconds_until <= SCAN_WINDOW_SECS:
                _sweep_and_execute_due_window(pols, now)
                # Avoid hammering: after a sweep, wait a short, fixed interval.
                _sleep_with_stop(stop_event, seconds=60)
            else:
                _sleep_with_stop(stop_event, seconds=min(cadence, seconds_until))
    finally:
        _release_leader_lock(lock_file)

# ─────────────────────────────────────────────────────────────────────────────
# Leader election (file lock)
# ─────────────────────────────────────────────────────────────────────────────

def _try_become_leader(lock_file: Optional[IO]) -> Tuple[bool, Optional[IO]]:
    """Attempt to acquire a non-blocking exclusive file lock.

    Args:
      lock_file: Existing open handle to the lock file, if any.

    Returns:
      Tuple[bool, Optional[IO]]: (is_leader, lock_file_handle)
    """
    try:
        if lock_file is None:
            lock_file = open(LOCK_PATH, "a+")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        # Best-effort: stamp PID for observability.
        try:
            lock_file.seek(0)
            lock_file.truncate()
            lock_file.write(f"leader_pid={os.getpid()}\n")
            lock_file.flush()
            os.fsync(lock_file.fileno())
        except Exception:
            pass

        logger.info("[SCHED] acquired leader lock at %s", LOCK_PATH)
        return True, lock_file
    except BlockingIOError:
        return False, lock_file
    except Exception:
        logger.exception("[SCHED] leader lock attempt failed; running as non-leader")
        return False, lock_file

def _release_leader_lock(lock_file: Optional[IO]) -> None:
    """Release file lock if held (best effort)."""
    if lock_file is None:
        return
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        lock_file.close()
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# Due-window sweep + execution
# ─────────────────────────────────────────────────────────────────────────────

def _sweep_and_execute_due_window(policies: Sequence[Dict], now_utc: datetime) -> None:
    """Find all policies due within ±SCAN_WINDOW_SECS around now and execute them.

    Steps:
      - Compute window [now - window, now + window].
      - For each policy whose _next_ fire falls inside and whose last_run_epoch
        is older than the window start, attempt an atomic claim.
      - If claimed, fan out scans for its enrolled systems.
    """
    window_start = now_utc - timedelta(seconds=SCAN_WINDOW_SECS)
    window_end = now_utc + timedelta(seconds=SCAN_WINDOW_SECS)
    window_start_epoch = int(window_start.timestamp())
    now_epoch = int(now_utc.timestamp())

    # Filter candidates locally (no DB reads beyond the initial list).
    candidates: List[Dict] = []
    for pol in policies:
        nxt = _next_fire_time_from_dict(pol, now_utc)
        if nxt is None:
            continue
        if not (window_start <= nxt <= window_end):
            continue
        last_run_epoch = int(pol.get("last_run_epoch") or 0)
        if last_run_epoch >= window_start_epoch:
            continue
        candidates.append(pol)

    if not candidates:
        logger.debug("[SCHED] window sweep found no due policies (%s..%s)", window_start, window_end)
        return

    # Claim & execute each due policy.
    for pol in candidates:
        pid = int(pol["id"])
        name = str(pol.get("name") or pid)

        try:
            if not try_claim_policy(policy_id=pid, now_epoch=now_epoch, min_epoch=window_start_epoch):
                # Another worker/process already claimed it for this window.
                continue
        except Exception:
            logger.exception("[SCHED] claim failed (policy_id=%s)", pid)
            continue

        # Claimed → run its systems
        try:
            _run_policy(pid, name)
        except Exception:
            logger.exception("[SCHED] execution crashed (policy_id=%s)", pid)

# ─────────────────────────────────────────────────────────────────────────────
# Execution helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run_policy(policy_id: int, policy_name: str) -> None:
    """Execute all systems enrolled in a policy in a bounded thread pool.

    Args:
      policy_id: Primary key of the policy being executed.
      policy_name: Policy name (for logging only).
    """
    try:
        system_ids = list_system_ids_by_policy_id(policy_id)
    except Exception:
        logger.exception("[SCHED] failed to list systems (policy_id=%s)", policy_id)
        return

    if not system_ids:
        logger.info("[SCHED] policy %s (%s) has no systems; skipping", policy_id, policy_name)
        return

    logger.info("[SCHED] running %s systems for policy %s (%s)", len(system_ids), policy_id, policy_name)

    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix=f"policy-{policy_id}") as pool:
        futs: List[cf.Future[Tuple[int, str]]] = [
            pool.submit(_run_one_system, policy_id, sid) for sid in system_ids
        ]
        for fut in cf.as_completed(futs):
            try:
                sid, run_id = fut.result()
                logger.info("[SCHED] system %s completed run_id=%s (policy=%s)", sid, run_id, policy_id)
            except Exception:
                logger.exception("[SCHED] a system task failed (policy=%s)", policy_id)

def _run_one_system(policy_id: int, system_id: int) -> Tuple[int, str]:
    """Execute a single system scan and return (system_id, run_id).

    Args:
      policy_id: ID of the policy dispatching this scan (for job tagging).
      system_id: ID of the system to scan.

    Returns:
      Tuple[int, str]: (system_id, persisted run_id as string).

    Raises:
      Propagates exceptions thrown by run_scan_and_store.
    """
    job_id = f"{JOB_ID_PREFIX}:{policy_id}"
    run_id = run_scan_and_store(
        system_id=system_id,
        job_id=job_id,
        output_dir=RUN_OUTPUT_DIR,
        cfg=None,
    )
    return system_id, str(run_id)

# ─────────────────────────────────────────────────────────────────────────────
# Schedule math (pure runner-side logic)
# ─────────────────────────────────────────────────────────────────────────────

_DAY_OF_WEEK_INDEX = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
}

def _compute_nearest_upcoming_run(policies: Sequence[Dict], now_utc: datetime) -> Optional[Tuple[int, datetime]]:
    """Return the nearest upcoming (policy_id, run_at_utc) >= now among policies.

    Args:
      policies: Iterable of policy dicts from db.policies_list().
      now_utc: Reference UTC time.

    Returns:
      Optional[Tuple[int, datetime]]: The nearest (policy_id, run_at) or None.
    """
    nearest: Optional[Tuple[int, datetime]] = None
    for pol in policies:
        nxt = _next_fire_time_from_dict(pol, now_utc)
        if nxt is None or nxt < now_utc:
            continue
        cand = (int(pol["id"]), nxt)
        if nearest is None or cand[1] < nearest[1]:
            nearest = cand
    return nearest

def _next_fire_time_from_dict(pol: Dict, ref: datetime) -> Optional[datetime]:
    """Compute the next UTC fire time for a policy dict from db.policies_list().

    Expected keys:
      - frequency: "daily" | "weekly" | "biweekly" | "monthly"
      - time_of_day: "HH:MM[:SS]"
      - day_of_week: Optional[str] (weekly/biweekly/monthly)
      - week_of_month: Optional[int] (monthly; 1..5 with 5 meaning 'last')
      - anchor_epoch: Optional[int] (biweekly cadence anchor)
      - last_run_epoch: Optional[int] (timestamp of last execution)

    Returns:
      datetime | None: Next scheduled UTC time, or None if insufficient info.
    """
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)

    tod_str = (pol.get("time_of_day") or "00:00:00").strip()
    parts = [int(p) for p in tod_str.split(":")]
    h, mi, s = (parts + [0, 0, 0])[:3]
    base_today = ref.replace(hour=h, minute=mi, second=s, microsecond=0)

    freq = (pol.get("frequency") or "").lower()

    if freq == "daily":
        return base_today if base_today >= ref else base_today + timedelta(days=1)

    if freq == "weekly":
        dow_name = pol.get("day_of_week")
        if not dow_name:
            return None
        dow = _DAY_OF_WEEK_INDEX.get(dow_name, 0)
        delta = (dow - base_today.weekday()) % 7
        cand = base_today + timedelta(days=delta)
        return cand if cand >= ref else cand + timedelta(days=7)

    if freq == "biweekly":
        anchor_epoch = pol.get("anchor_epoch")
        last_run_epoch = pol.get("last_run_epoch")
        if anchor_epoch:
            anchor = datetime.fromtimestamp(int(anchor_epoch), tz=timezone.utc)
        elif last_run_epoch:
            anchor = datetime.fromtimestamp(int(last_run_epoch), tz=timezone.utc)
        else:
            dow_name = pol.get("day_of_week")
            if dow_name:
                dow = _DAY_OF_WEEK_INDEX.get(dow_name, 0)
                delta = (dow - base_today.weekday()) % 7
                anchor = base_today + timedelta(days=delta)
            else:
                anchor = base_today
        anchor = anchor.replace(hour=h, minute=mi, second=s, microsecond=0)
        if anchor >= ref:
            return anchor
        period = timedelta(days=14)
        elapsed = ref - anchor
        steps = int((elapsed.total_seconds() + period.total_seconds() - 1) // period.total_seconds())
        return anchor + steps * period

    if freq == "monthly":
        week = pol.get("week_of_month")
        dow_name = pol.get("day_of_week")
        if not week or not dow_name:
            return None
        week = int(week)
        dow = _DAY_OF_WEEK_INDEX.get(dow_name, 0)
        y, mth = ref.year, ref.month
        cand = _nth_weekday_of_month_utc(y, mth, dow, week, h, mi, s)
        if cand < ref:
            y2, m2 = (y + 1, 1) if mth == 12 else (y, mth + 1)
            cand = _nth_weekday_of_month_utc(y2, m2, dow, week, h, mi, s)
        return cand

    return None

def _nth_weekday_of_month_utc(y: int, m: int, dow: int, week: int, h: int, mi: int, s: int) -> datetime:
    """Return the UTC datetime for the nth weekday of a given month.

    Args:
      y: Year
      m: Month (1..12)
      dow: Day-of-week index (0=Mon..6=Sun)
      week: Nth occurrence (1..4), or 5 for 'last'
      h: Hour
      mi: Minute
      s: Second

    Returns:
      datetime: Computed UTC datetime.
    """
    first = datetime(y, m, 1, h, mi, s, tzinfo=timezone.utc)
    offset = (dow - first.weekday()) % 7
    first_target = first + timedelta(days=offset)
    if week in (1, 2, 3, 4):
        return first_target + timedelta(weeks=week - 1)
    # week == 5 -> last occurrence in month
    if m == 12:
        next_first = datetime(y + 1, 1, 1, h, mi, s, tzinfo=timezone.utc)
    else:
        next_first = datetime(y, m + 1, 1, h, mi, s, tzinfo=timezone.utc)
    days_back = (next_first.weekday() - dow) % 7 or 7
    return next_first - timedelta(days=days_back)



# ─────────────────────────────────────────────────────────────────────────────
# Sleep helper
# ─────────────────────────────────────────────────────────────────────────────

def _sleep_with_stop(stop_event: threading.Event, *, seconds: int) -> None:
    """Sleep in short slices so we react quickly to stop_event."""
    deadline = _time.time() + max(0, seconds)
    while not stop_event.is_set():
        now = _time.time()
        if now >= deadline:
            break
        _time.sleep(min(1.0, deadline - now))


# ─────────────────────────────────────────────────────────────────────────────
# Ad-hoc execution API (manual/HTTP triggers)
# ─────────────────────────────────────────────────────────────────────────────

def scan_now(
    *,
    system_ids: Optional[Sequence[int]] = None,
    policy_id: Optional[int] = None,
    blocking: Optional[bool] = None,
) -> bool:
    """Dispatch immediate scans either by policy or explicit system list.

    Modes:
      • policy_id provided → Run all systems enrolled to that policy now (ignores schedule).
        Uses ``execute_scan_policy(..., force=True)`` for consistent stamping/behavior.
      • system_ids provided → Run those systems directly via the same dispatcher the
        scheduler uses (``run_scan_for_systems``). De-dupes IDs and preserves order.

    Args:
      system_ids: Explicit system IDs to scan (ignored if ``policy_id`` is provided).
      policy_id:  Policy to execute now (schedule is ignored).
      blocking:   Optional override for env ``SCAN_BLOCKING`` just for this call.
                  True waits for completion; False fire-and-forgets; None leaves env as-is.

    Returns:
      True if scans were dispatched (and, in blocking mode, all succeeded for the
      selected set). False if nothing was run (e.g., no IDs and no policy).

    Notes:
      - Uses ``_override_env`` to scope any temporary ``SCAN_BLOCKING`` override.
      - For ad-hoc system lists, uses ``policy_id=0`` in job tags for neutrality.
    """
    # Prefer policy-based execution (keeps stamping uniform with scheduler).
    if policy_id is not None:
        return execute_scan_policy(policy_id, force=True, blocking=blocking)

    # Otherwise, run an explicit system list.
    unique_ids = list(dict.fromkeys(system_ids or ()))  # de-dupe, preserve order
    if not unique_ids:
        logger.warning("[SCAN] scan_now called with neither policy_id nor system_ids")
        return False

    # Temporary override of SCAN_BLOCKING, if requested by caller.
    with _override_env("SCAN_BLOCKING", blocking):
        return run_scan_for_systems(policy_id=0, system_ids=unique_ids)


def execute_scan_policy(
    policy_id: int,
    *,
    force: bool = True,
    blocking: Optional[bool] = None,
) -> bool:
    """Execute all systems for a policy immediately (schedule ignored by default).

    This keeps behavior aligned with the background scheduler:
      1) Resolve enrolled system IDs via `db.list_system_ids_by_policy_id`.
      2) Dispatch work via `run_scan_for_systems(...)`.
      3) Stamp `last_run_epoch` using `db.stamp_policy_last_run_now(...)`.

    Args:
        policy_id: The target scan policy ID.
        force:     Present for API parity; schedule is ignored in this DB-agnostic runner.
        blocking:  Optional override for env `SCAN_BLOCKING` just for this call.

    Returns:
        True if a dispatch occurred (and in blocking mode, that all succeeded),
        False if the policy has no enrolled systems.
    """
    try:
        sys_ids = list_system_ids_by_policy_id(policy_id)
    except Exception:
        logger.exception("[EXEC] failed to list systems for policy_id=%s", policy_id)
        return False

    if not sys_ids:
        logger.info("[EXEC] policy_id=%s has no systems; stamping and skipping", policy_id)
        try:
            stamp_policy_last_run_now(policy_id)
        except Exception:
            logger.exception("[EXEC] failed to stamp last_run_epoch for empty policy_id=%s", policy_id)
        return True  # consistent with scheduler: no-op but stamped

    with _override_env("SCAN_BLOCKING", blocking):
        ok = run_scan_for_systems(policy_id=policy_id, system_ids=sys_ids)

    # Stamp last_run_epoch regardless of outcome (matches window-claim semantics).
    try:
        stamp_policy_last_run_now(policy_id)
    except Exception:
        logger.exception("[EXEC] failed to stamp last_run_epoch for policy_id=%s", policy_id)

    return ok




def run_scan_for_systems(policy_id: int, system_ids: Sequence[int]) -> bool:
    """Dispatch scans for the provided systems via a bounded thread pool.

    Pure orchestration: we do not touch SQL/ORM here; each scan is performed by
    `run_scan_and_store(...)` which persists its own results.

    Env:
        SCAN_WORKERS   (default: 2) — thread pool size
        SCAN_BLOCKING  (default: 0) — if truthy, block until all scans complete

    Args:
        policy_id:  Owning policy for logging/job tagging (0 for ad-hoc batches).
        system_ids: Systems to scan.

    Returns:
        bool: If blocking mode → True iff all scans completed successfully.
              If async mode   → True when jobs were scheduled; False if none.
    """
    systems = [int(s) for s in system_ids if isinstance(s, (int,))]

    if not systems:
        logger.info("[SCAN] policy=%s no systems to run; nothing scheduled", policy_id)
        return False

    max_workers = max(1, int(os.getenv("SCAN_WORKERS", "2")))
    blocking_env = os.getenv("SCAN_BLOCKING", "0").strip().lower() in {"1", "true", "yes"}

    logger.info(
        "[SCAN] policy=%s scheduling %d system(s) (workers=%d, blocking=%s)",
        policy_id, len(systems), max_workers, blocking_env,
    )

    def _run_all(ids: Sequence[int]) -> tuple[int, int]:
        ok = fail = 0
        with cf.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"policy-{policy_id}") as pool:
            fut_by_sid = {
                pool.submit(
                    run_scan_and_store,
                    system_id=sid,
                    job_id=f"{JOB_ID_PREFIX}:{policy_id}",
                    output_dir=RUN_OUTPUT_DIR,
                    cfg=None,
                ): sid
                for sid in ids
            }
            for fut in cf.as_completed(fut_by_sid):
                sid = fut_by_sid[fut]
                try:
                    run_id = fut.result()
                    if run_id:
                        ok += 1
                        logger.info("[SCAN] system_id=%s completed run_id=%s (policy=%s)", sid, run_id, policy_id)
                    else:
                        fail += 1
                        logger.error("[SCAN] system_id=%s returned no run_id (policy=%s)", sid, policy_id)
                except Exception:
                    fail += 1
                    logger.exception("[SCAN] system_id=%s raised during scan (policy=%s)", sid, policy_id)
        return ok, fail

    if blocking_env:
        ok_count, fail_count = _run_all(systems)
        logger.info("[SCAN] policy=%s finished: ok=%d fail=%d", policy_id, ok_count, fail_count)
        return ok_count == len(systems)

    # Fire-and-forget in a daemon thread
    def _bg():
        ok_count, fail_count = _run_all(systems)
        logger.info("[SCAN] (async) policy=%s finished: ok=%d fail=%d", policy_id, ok_count, fail_count)

    threading.Thread(target=_bg, name=f"policy-{policy_id}-runner", daemon=True).start()
    return True



# ─────────────────────────────────────────────────────────────────────────────
# Env override utility (scoped)
# ─────────────────────────────────────────────────────────────────────────────

class _override_env:
    """Context manager to temporarily set a boolean-ish env var to '1' or '0'."""

    def __init__(self, var_name: str, value: Optional[bool]) -> None:
        self.var_name = var_name
        self.value = value
        self.original: Optional[str] = None

    def __enter__(self):
        if self.value is None:
            return
        self.original = os.getenv(self.var_name)
        os.environ[self.var_name] = "1" if self.value else "0"

    def __exit__(self, exc_type, exc, tb):
        if self.value is None:
            return
        if self.original is None:
            os.environ.pop(self.var_name, None)
        else:
            os.environ[self.var_name] = self.original


