# log_config.py
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import List, Dict, Optional, Any

from flask import has_request_context, request


# ---- Configuration ----
# All logs must live under this directory. Adjust as needed.
BASE_LOG_DIR = Path(os.getenv("TECTIX_LOG_DIR", "./logs")).resolve()
BASE_LOG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_LOGFILE_NAME = "server.log"


class RequestFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if has_request_context():
            # If you run behind a proxy, consider reading X-Forwarded-For safely here.
            record.ip = request.remote_addr or "N/A"
        else:
            record.ip = "N/A"
        return True


def setup_logging(logfile: str = DEFAULT_LOGFILE_NAME) -> logging.Logger:
    """
    Configure and return the 'TECTIX' logger.
    Ensures logs write under BASE_LOG_DIR and installs a FileHandler if none exists.
    """
    logger = logging.getLogger("TECTIX")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        # Normalize logfile path to BASE_LOG_DIR
        log_path = Path(logfile)
        if not log_path.is_absolute():
            log_path = BASE_LOG_DIR / log_path
        log_path = log_path.resolve()

        # Safety: force logs to live under BASE_LOG_DIR
        if BASE_LOG_DIR not in [log_path] + list(log_path.parents):
            raise ValueError(f"Log path {log_path} is outside {BASE_LOG_DIR}")

        log_path.parent.mkdir(parents=True, exist_ok=True)

        handler = logging.FileHandler(log_path)
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s from %(ip)s: %(message)s"
        )
        handler.setFormatter(formatter)
        handler.addFilter(RequestFilter())
        logger.addHandler(handler)

    return logger


# ---------- Utilities ----------

def get_logfile_path(logger: Optional[logging.Logger] = None) -> Path:
    """
    Return the absolute path to the current logfile used by the 'TECTIX' logger.
    Falls back to BASE_LOG_DIR/DEFAULT_LOGFILE_NAME if a FileHandler is not present.
    """
    logger = logger or logging.getLogger("TECTIX")
    for h in logger.handlers:
        if isinstance(h, logging.FileHandler):
            # FileHandler.baseFilename is absolute
            return Path(getattr(h, "baseFilename"))
    return (BASE_LOG_DIR / DEFAULT_LOGFILE_NAME).resolve()


def _resolve_logfile_strict(p: Path) -> Path:
    """
    Resolve a caller-supplied logfile path and ensure it is under BASE_LOG_DIR.
    """
    rp = p.resolve()
    if BASE_LOG_DIR not in [rp] + list(rp.parents):
        raise ValueError("Access to this path is not allowed.")
    return rp


def _compile_glob(pattern: str, case_sensitive: bool) -> re.Pattern:
    """
    Safe 'regex-like' compiler: supports only '*' and '?' wildcards.
      - '*' => matches up to 128 chars, non-greedy
      - '?' => matches exactly one char
    Everything else is treated literally.

    This avoids catastrophic backtracking while still being flexible.
    """
    if len(pattern) > 256:
        raise ValueError("Pattern too long (max 256).")

    # Escape everything, then re-enable our wildcards.
    pat = re.escape(pattern)
    pat = pat.replace(r"\*", r".{0,128}?").replace(r"\?", r".")

    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(pat, flags)


def search_log(
    pattern: str,
    *,
    use_glob: bool = True,           # default to safe glob-like search
    case_sensitive: bool = False,
    max_bytes: int = 2_000_000,      # read last N bytes of the log
    max_matches: int = 200,          # cap match count
    context: int = 0,                # lines of context before/after
    per_line_limit: int = 20_000,    # avoid pathological single-line scans
    timeout_s: float = 1.0,          # overall time budget
    logfile: Optional[Path] = None,
    logger: Optional[logging.Logger] = None,
) -> List[Dict[str, Any]]:
    """
    Search the tail of the log file for a pattern.

    Returns a list of dicts: {
      "line_no": int,        # line index within the scanned tail
      "line": str,           # full (uncut) line as in the file
      "match": [start, end], # match span within the (possibly truncated) scan segment
      "before": [..],        # if context>0
      "after":  [..],        # if context>0
    }

    Safety:
      - Defaults to a glob-like matcher (use_glob=True) to avoid ReDoS.
      - Reads only the last `max_bytes` bytes.
      - Caps matches, line length, and enforces a global timeout.
      - Restricts logfile access to BASE_LOG_DIR.
    """
    log_path = (logfile and _resolve_logfile_strict(Path(logfile))) or get_logfile_path(logger)
    if not log_path.exists():
        return []

    start_time = time.time()

    # Read only the tail of the file
    with open(log_path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes), os.SEEK_SET)
        tail = f.read()

    text = tail.decode("utf-8", errors="replace")
    lines = text.splitlines()

    # Compile matcher (glob-like by default)
    rx = _compile_glob(pattern, case_sensitive) if use_glob else None
    if not use_glob:
        # If we *must* allow raw regex, put a very strict validator here.
        # It's disabled by default due to ReDoS risk.
        raise ValueError("Raw regex disabled. Enable only if you accept ReDoS risk.")

    results: List[Dict[str, Any]] = []

    for idx, raw_line in enumerate(lines, start=1):
        # Timeout check
        if time.time() - start_time > timeout_s:
            break

        # Cap per-line processing while preserving the original for return
        scan_segment = raw_line[:per_line_limit]

        m = rx.search(scan_segment)
        if not m:
            continue

        rec: Dict[str, Any] = {
            "line_no": idx,
            "line": raw_line,
            "match": [m.start(), m.end()],
        }
        if context:
            before_start = max(0, idx - 1 - context)
            after_end = min(len(lines), idx - 1 + 1 + context)
            rec["before"] = lines[before_start: idx - 1]
            rec["after"] = lines[idx: after_end]
        results.append(rec)
        if len(results) >= max_matches:
            break

    return results
