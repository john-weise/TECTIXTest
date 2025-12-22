# helpers.py
from __future__ import annotations

"""
Cross-cutting helpers used by tests and runners.

Includes:
- String normalization and loose boolean parsing
- Epoch-to-date conversion + current UTC epoch
- Test discovery and safe execution primitives
- SystemContext builders (config- and session-based)

Notes:
- We treat system_id as an INT throughout, only stringifying at HTTP/CSV boundaries
  inside emass_api.build_system_context_from_emass.
"""

import importlib
import inspect
from engine.config import Config 
import logging
import time
from typing import Any, Callable, Optional
from engine.emass_api import init_emass_session_from_config, build_system_context_from_emass
from engine.models import ATOStatus, Result, TestResult, SystemContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API exposure for this helpers module
# ---------------------------------------------------------------------------
# `__all__` explicitly defines the *public surface area* of this module:
#   - Tools like `from helpers import *` will only import these names.
#   - It also serves as a "table of contents" for other developers, showing
#     which functions/types are intended to be stable entry points.
#
# Why we do this:
#   - Keeps our module clean and intentional, no leaking private functions.
#   - Helps juniors/new devs know which functions are "safe to rely on"
#     versus which are internal helpers that may change.
#   - Provides a single place to review/extend when we add new functionality.
#
# How to extend:
#   1. Write your new helper function or class in this file.
#   2. Decide if it’s meant to be public (i.e., consumed by tests or runners).
#   3. If yes, add its name (as a string) to the list below.
#   4. Keep names sorted/grouped logically (normalization, discovery, context).
#   5. Make sure the function/class has a clear docstring.
#
# Example:
#   def say_hello(): ...
#   __all__.append("say_hello")
#
# Think of __all__ as the "public menu" of this file:
# if a function’s name is listed here, other parts of the
# project can use it. If it’s not, it stays private — like
# items not printed on the menu.
#
# By convention, we avoid exporting names starting with "_"
# unless there’s a very strong reason; those are considered
# private implementation details.
# ---------------------------------------------------------------------------

__all__ = [
    # normalization / parsing
    "normalize",
    "to_bool_loose",
    "epoch_to_ymd",
    "utc_now_epoch",
    # discovery / execution
    "is_test_function",
    "test_number_from_name",
    "safe_run_test",
    "run_discovered_tests",
    # context builders
    "build_context_from_config",
    "build_context_from_emass_session",
]

# -----------------------------
# Normalization / parsing
# -----------------------------
def normalize(value: Optional[str]) -> str:
    """
    Normalize a string for robust comparisons.

    Returns:
        Lowercased, trimmed string; empty string when input is None.
    """
    return (value or "").strip().lower()

#new tool written by John to convert true or false to yes or no for data matching.
def bool_to_yesno(value: Optional[str]) -> Optional[str]:
    """
    Loosely parse user-facing true/false values and return yes or no.

    Accepts: yes/true/y/1 and no/false/n/0 (case-insensitive).
    Returns None for anything ambiguous or missing.
    """
    if value is None:
        return None
    s = normalize(value)
    if s in {"yes", "true", "y", "1"}:
        return "Yes"
    if s in {"no", "false", "n", "0"}:
        return "No"
    return None


def to_bool_loose(value: Optional[str]) -> Optional[bool]:
    """
    Loosely parse user-facing yes/no values.

    Accepts: yes/true/y/1 and no/false/n/0 (case-insensitive).
    Returns None for anything ambiguous or missing.
    """
    if value is None:
        return None
    s = normalize(value)
    if s in {"yes", "true", "y", "1"}:
        return True
    if s in {"no", "false", "n", "0"}:
        return False
    return None


def epoch_to_ymd(epoch_seconds: int) -> Optional[str]:
    """
    Convert epoch seconds (UTC) to 'YYYY-MM-DD'.

    Args:
        epoch_seconds: Seconds since Unix epoch (UTC).

    Returns:
        Date string or None if conversion fails.
    """
    try:
        import datetime as dt
        return dt.datetime.utcfromtimestamp(int(epoch_seconds)).strftime("%Y-%m-%d")
    except Exception:
        return None


def utc_now_epoch() -> int:
    """Return current UTC time as epoch seconds (int)."""
    return int(time.time())


# -----------------------------
# Test discovery / execution
# -----------------------------
def is_test_function(candidate: Any) -> bool:
    """
    Determine if a callable is a valid test function.

    A valid test function must:
      - Be a function named with the prefix 'test_'.
      - Accept exactly two parameters: (ctx, status).

    This signature enforces a uniform interface across tests.
    """
    if not inspect.isfunction(candidate):
        return False
    if not candidate.__name__.startswith("test_"):
        return False
    sig = inspect.signature(candidate)
    return len(sig.parameters) == 2


def test_number_from_name(function_name: str) -> int:
    """
    Extract the numeric identifier from a test function name.

    Examples:
        'test_12_extra' -> 12
        'test_3'        -> 3
    """
    try:
        suffix = function_name.split("test_", 1)[1]
        digits = "".join(ch for ch in suffix if ch.isdigit())
        return int(digits) if digits else 0
    except Exception:
        return 0


def safe_run_test(
    test_fn: Callable[[SystemContext, ATOStatus], TestResult],
    context: SystemContext,
    aggregate_status: ATOStatus,
) -> None:
    """
    Execute a single test; convert uncaught exceptions into a CONCERN
    record so one failing test cannot abort the entire run.
    """
    try:
        logger.debug("Executing %s", test_fn.__name__)
        test_fn(context, aggregate_status)
    except Exception as exc:
        logger.exception("Unhandled exception in %s: %s", test_fn.__name__, exc)
        tr = TestResult(
            test_number=test_number_from_name(test_fn.__name__),
            name=test_fn.__name__.replace("_", " ").title(),
            result=Result.CONCERN,
            message=f"Test raised exception: {exc!r}",
        )
        aggregate_status.add(tr)


def run_discovered_tests(module_name: str, context: SystemContext) -> ATOStatus:
    """
    Discover and execute all 'test_*' functions from a given module.

    Steps:
      - Import the module by name.
      - Collect functions named 'test_*' that accept (ctx, status).
      - Sort by numeric suffix (test_1, test_2, ...).
      - Execute each with exception safety.
      - Return aggregated ATOStatus.
    """
    logger.info("Discovering tests in module '%s'", module_name)
    module = importlib.import_module(module_name)

    tests: list[Callable[[SystemContext, ATOStatus], TestResult]] = [
        fn for _, fn in inspect.getmembers(module, inspect.isfunction)
        if is_test_function(fn)
    ]
    tests.sort(key=lambda fn: test_number_from_name(fn.__name__))
    logger.info("Discovered %d test(s): %s", len(tests), [f.__name__ for f in tests])

    status = ATOStatus()
    for test_fn in tests:
        safe_run_test(test_fn, context, status)

    logger.info("All tests complete.")
    return status


# -----------------------------
# SystemContext builders
# -----------------------------
def build_context_from_config(
    cfg: Config,
    system_id: int,
    apms_csv_path: str,
    checklist_path: str,
) -> SystemContext:
    """
    Construct a fully-populated `SystemContext` using a project `Config`.

    This is the canonical entry point for CLI runners and orchestration code
    where a full configuration object has already been loaded and validated.
    It encapsulates the entire workflow of:

      1. Creating an `EmassSession` with TLS, certificate, and API key details
         pulled from `cfg`.
      2. Querying the eMASS API for authoritative system metadata.
      3. Correlating eMASS fields against APMS CSV data and checklist references.
      4. Producing a structured `SystemContext` suitable for compliance testing.

    Why:
        By centralizing session initialization and context construction,
        runners and test suites can consume a single high-level function
        without worrying about transport details or repeated boilerplate.

    Parameters
    ----------
    cfg : Config
        Validated project configuration (logging should already be set up).
    system_id : int
        Integer eMASS system identifier (e.g., 101, 200).
    apms_csv_path : str
        Filesystem path to the APMS CSV for this run.
    checklist_path : str
        Filesystem path to the checklist workbook.

    Returns
    -------
    SystemContext
        A complete, validated context object ready for test execution.

    Raises
    ------
    RuntimeError
        If client certificates or API details are not present in `cfg`.
    requests.RequestException
        If API calls fail even after retry/backoff logic.
    """
    

    logger.info("Building SystemContext via Config for system_id=%d", system_id)
    emass_session = init_emass_session_from_config(cfg)
    context = build_system_context_from_emass(
        cfg=cfg,
        sess=emass_session,
        system_id=system_id,  # remain int; stringified only at HTTP/CSV boundaries
        apms_csv_path=apms_csv_path,
        checklist_path=checklist_path,
    )

    try:
        logger.debug("SystemContext constructed: %s", context.model_dump(exclude_none=True))  # type: ignore[attr-defined]
    except Exception:
        logger.debug("SystemContext constructed: %r", context)

    return context


def build_context_from_emass_session(
    session: Any,
    cfg: Config,
    system_id: int,
    apms_csv_path: str,
    checklist_path: str,
) -> SystemContext:
    """
    Construct a `SystemContext` using a pre-initialized eMASS session.

    This variant is useful in test harnesses, integration environments,
    or advanced runners where the caller already controls the lifecycle
    of the `EmassSession` (for example, to reuse a session across many
    systems or inject a mocked transport for testing).

    Why:
        Avoids redundant session creation and makes it easy to swap in
        alternate session implementations (e.g., fake API for unit tests).

    Parameters
    ----------
    session : EmassSession
        A live, pre-configured eMASS API session.
    cfg : Config
        Loaded project configuration (for org_id and paths).
    system_id : int
        Integer eMASS system identifier (e.g., 101, 200).
    apms_csv_path : str
        Filesystem path to the APMS CSV for this run.
    checklist_path : str
        Filesystem path to the checklist workbook.

    Returns
    -------
    SystemContext
        A complete context object enriched with eMASS and APMS data.

    Notes
    -----
    - `system_id` remains an int throughout the codebase.
      The underlying API layer handles conversion to string where necessary.
    """
    

    logger.info("Building SystemContext from pre-initialized session for system_id=%d", system_id)
    context = build_system_context_from_emass(
        cfg=cfg,
        sess=session,
        system_id=system_id,
        apms_csv_path=apms_csv_path,
        checklist_path=checklist_path,
    )

    try:
        logger.debug("SystemContext constructed: %s", context.model_dump(exclude_none=True))  # type: ignore[attr-defined]
    except Exception:
        logger.debug("SystemContext constructed: %r", context)

    return context


# -----------------------------
# helpers for raw payloads
# -----------------------------
def sys_row(ctx: SystemContext) -> dict:
    """Return the eMASS `system_info_raw` inner row (usually under 'data')."""
    src = ctx.system_info_raw or {}
    return (src.get("data") if isinstance(src, dict) else src) or {}

def apms_row(ctx: SystemContext) -> dict:
    """Return the APMS CSV first-row snapshot carried on the context."""
    return ctx.apms_first_row_raw or {}

def row_sys_id(row: dict) -> str:
    for k in ("System ID", "SystemID", "systemId", "system_id", "sysId", "id"):
        if k in row and row[k] is not None:
            return str(row[k])
    return ""

def to_bool_loose(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"true", "yes", "y", "1"}:
        return True
    if s in {"false", "no", "n", "0"}:
        return False
    return None

def apms_get_ci(ctx: SystemContext, *keys: str) -> str | None:
    """Case-insensitive get from APMS first row (string out)."""
    row = _apms_row(ctx)
    if not row:
        return None
    lowered = {str(k).lower(): v for k, v in row.items()}
    for k in keys:
        v = lowered.get(k.lower())
        if v is not None:
            return str(v).strip()
    return None
