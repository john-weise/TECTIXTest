# engine/test_runner_lib.py
"""
Importable ATO test runner utilities.

This module exposes programmatic entry points used by background workers or
CLIs—no interactive prompts or prints. Callers pass explicit inputs (Config,
system_id, file paths), and we return structured results.

Public API
----------
- list_available_tests(...) -> Mapping[int, str]
    Discover `test_*` callables and return { test_number: function_name }.

- run_single_test(...) -> Tuple[TestResult, ATOStatus]
    Build a SystemContext, execute one test by number, and return both the
    TestResult and the aggregate ATOStatus after that test.

- run_all_tests_status(...) -> ATOStatus
    Discover and run all (or selected) tests, returning ONLY the aggregated
    ATOStatus.

Design choices
--------------
- If `cfg` is None, we *automatically* construct a default Config() which reads
  the hard-coded default path (see engine.config.DEFAULT_CONFIG_PATH). This makes
  the runner work out-of-the-box without requiring CONFIG_FILE env or explicit
  wiring in callers (e.g., background threads).
- We validate required file paths before building the context.
- We never call input() or print(); logging is via the module logger.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple, Union

from engine.config import Config, DEFAULT_CONFIG_PATH  # default config file path
from engine.models import SystemContext, ATOStatus, TestResult
from engine.helpers import run_discovered_tests, test_number_from_name  # noqa: F401
import engine.test_api  # JSON-backed builders; no HTTP required

# -----------------------------------------------------------------------------
# Module logging (caller may reconfigure handlers/levels)
# -----------------------------------------------------------------------------
logger = logging.getLogger(__name__)
if not logger.handlers:
    # If caller didn't attach handlers, at least set a level; handlers are
    # typically configured by the host app (flask/gunicorn or CLI).
    logger.setLevel(logging.INFO)


# -----------------------------------------------------------------------------
# JSON helpers (safe pretty printing for pydantic v1/v2 or plain objects)
# -----------------------------------------------------------------------------
def dump_pydantic(obj: Any) -> str:
    """
    Serialize Pydantic v2/v1 models or plain dataclasses/objects to JSON.

    Order of attempts:
      - Pydantic v2: model_dump_json(indent=2) or model_dump()
      - Pydantic v1: .json(indent=2) or .dict()
      - Fallback: json.dumps(..., default=str)
    """
    # Pydantic v2
    if hasattr(obj, "model_dump_json"):
        try:
            return obj.model_dump_json(indent=2)  # type: ignore[call-arg]
        except TypeError:
            return obj.model_dump_json()  # type: ignore[call-arg]
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(), indent=2, default=str)  # type: ignore[attr-defined]

    # Pydantic v1
    if hasattr(obj, "json"):
        try:
            return obj.json(indent=2)  # type: ignore[attr-defined]
        except TypeError:
            return obj.json()  # type: ignore[attr-defined]
    if hasattr(obj, "dict"):
        return json.dumps(obj.dict(), indent=2, default=str)  # type: ignore[attr-defined]

    # Fallback
    try:
        return json.dumps(obj, indent=2, default=str)
    except Exception:
        return str(obj)


# -----------------------------------------------------------------------------
# Test discovery
# -----------------------------------------------------------------------------
def _load_tests_module(tests_module: Union[str, ModuleType] = "tests") -> ModuleType:
    """
    Import and return the tests module.

    Args:
        tests_module: Module object or importable module name.

    Returns:
        The imported ModuleType.

    Raises:
        ModuleNotFoundError: If a string name cannot be imported.
        TypeError: If `tests_module` is neither str nor ModuleType.
    """
    if isinstance(tests_module, ModuleType):
        return tests_module
    if isinstance(tests_module, str):
        return importlib.import_module(tests_module)
    raise TypeError("tests_module must be a module object or importable module name (str).")


def _index_tests_by_number(mod: ModuleType) -> Dict[int, Callable[[SystemContext, ATOStatus], TestResult]]:
    """
    Scan `mod` for callables named `test_*` and map them to numeric IDs.

    The numeric ID is derived from the function name via `test_number_from_name`
    (robust to patterns like `test_10` or `test_10_control_ac`).

    Returns:
        Sorted mapping: { test_number: test_function }
    """
    table: Dict[int, Callable[[SystemContext, ATOStatus], TestResult]] = {}
    for attr_name in dir(mod):
        if not attr_name.startswith("test_"):
            continue
        test_fn = getattr(mod, attr_name, None)
        if callable(test_fn):
            test_num = test_number_from_name(attr_name)  # e.g., "test_10" -> 10
            if test_num is not None:
                table[test_num] = test_fn  # type: ignore[assignment]
    # Ensure deterministic ordering by test number
    return dict(sorted(table.items()))


def list_available_tests(
    tests_module: Union[str, ModuleType] = "tests",
    hide_zero: bool = True,
) -> Mapping[int, str]:
    """
    Discover available tests and return their numeric IDs and function names.

    Args:
        tests_module: Module containing `test_*` callables.
        hide_zero: Exclude test number 0 if present.

    Returns:
        Mapping of test number → function name.
    """
    mod = _load_tests_module(tests_module)
    discovered = _index_tests_by_number(mod)
    if hide_zero:
        discovered = {k: v for k, v in discovered.items() if k != 0}
    return {k: getattr(v, "__name__", f"test_{k}") for k, v in discovered.items()}


# -----------------------------------------------------------------------------
# Config handling
# -----------------------------------------------------------------------------
def _ensure_config(cfg: Optional[Config], caller_name: str) -> Config:
    """
    Ensure we have a Config instance.

    If `cfg` is None, construct a default `Config()` which uses the *hard-coded*
    default config path (see engine.config.DEFAULT_CONFIG_PATH), not environment
    variables. This mirrors CLI behavior and avoids surprising dependency on
    CONFIG_FILE when background threads forget to pass a config.

    Raises:
        RuntimeError: with clear diagnostics if we cannot construct a Config.
    """
    if isinstance(cfg, Config):
        return cfg

    try:
        auto_cfg = Config()  # Uses DEFAULT_CONFIG_PATH ("config.ini") in current working directory
        logger.debug(
            "Auto-constructed Config() in %s using DEFAULT_CONFIG_PATH=%s (cwd=%s)",
            caller_name, DEFAULT_CONFIG_PATH, os.getcwd(),
        )
        return auto_cfg
    except Exception as exc:
        message = (
            f"Could not construct Config() in {caller_name}.\n"
            f"- CWD: {os.getcwd()}\n"
            f"- Tried hard-coded DEFAULT_CONFIG_PATH: {DEFAULT_CONFIG_PATH}\n"
            f"- ERROR: {exc!r}\n"
            "Hint: ensure a config.ini exists at the process CWD or pass cfg=Config(<path>)"
        )
        logger.error(message)
        raise RuntimeError(message) from exc

def _extract_system_name_from_context(ctx: SystemContext) -> Optional[str]:
    """Best-effort system display name resolver.

    Tries common attributes and dict-style fields on the provided SystemContext
    to produce a human-readable system name. Returns the first non-empty match.

    Args:
        ctx: Fully-populated SystemContext for the target system.

    Returns:
        A string system name suitable for UI/reporting, or None if no name
        could be inferred.
    """
    # Direct attributes first.
    for attr in ("system_name", "name", "systemName", "SystemName"):
        val = getattr(ctx, attr, None)
        if val:
            s = str(val).strip()
            if s:
                return s

    # Then look inside known dict-like members.
    for container in (
        getattr(ctx, "system_info", None),
        getattr(ctx, "meta", None),
        getattr(ctx, "__dict__", None),
    ):
        if isinstance(container, dict):
            for key in (
                "system_name",
                "systemName",
                "System Name",
                "SystemName",
                "Name",
                "Item Name",
            ):
                val = container.get(key)
                if val:
                    s = str(val).strip()
                    if s:
                        return s

    return None



# -----------------------------------------------------------------------------
# Context builder wrapper
# -----------------------------------------------------------------------------
def build_context_from_json(
    *,
    cfg: Optional[Config],
    system_id: int,
    apms_csv_path: str,
    checklist_path: str,
) -> SystemContext:
    """
    Build a SystemContext using local JSON-backed fixtures (via engine.test_api).

    Args:
        cfg: Config instance (if None, we auto-create Config()).
        system_id: Target system identifier.
        apms_csv_path: Path to APMS CSV used for correlation.
        checklist_path: Path to the Deep Dive checklist Excel.

    Returns:
        Fully populated SystemContext.

    Raises:
        FileNotFoundError: If input paths do not exist.
        Exception: Any error propagated by test_api builder.
    """
    cfg = _ensure_config(cfg, "build_context_from_json")

    # Validate required inputs early with explicit errors
    if not os.path.exists(apms_csv_path):
        raise FileNotFoundError(f"APMS CSV not found: {apms_csv_path}")
    if not os.path.exists(checklist_path):
        raise FileNotFoundError(f"Checklist not found: {checklist_path}")

    # Delegate to the engine's JSON-backed builder (no external HTTP)
    return engine.test_api.build_system_context_from_emass(
        cfg=cfg,
        system_id=system_id,
        apms_csv_path=apms_csv_path,
        checklist_path=checklist_path,
    )


# -----------------------------------------------------------------------------
# Main programmatic API
# -----------------------------------------------------------------------------
def run_single_test(
    test_number: int,
    *,
    cfg: Optional[Config],
    system_id: int,
    apms_csv_path: str,
    checklist_path: str = "DeepDiveTests.xlsx",
    tests_module: Union[str, ModuleType] = "tests",
    logger_: Optional[logging.Logger] = None,
) -> Tuple[TestResult, ATOStatus]:
    """
    Execute one test by number and return (TestResult, ATOStatus).

    Behavior:
      - Ensures a Config (auto-creates if None), configures logging, validates minimums.
      - Builds SystemContext from fixture JSON + APMS CSV.
      - Resolves the requested test from `tests_module`.
      - Executes it and returns the structured result and the aggregate status.

    Raises:
      FileNotFoundError: if paths are invalid.
      KeyError: if the requested test number does not exist.
      Exception: any exception raised by the test function (re-raised).
    """
    log = logger_ or logger

    # Ensure a config and let it initialize logging/minimums if supported.
    cfg = _ensure_config(cfg, "run_single_test")
    try:
        if hasattr(cfg, "configure_logging"):
            cfg.configure_logging()
        if hasattr(cfg, "validate_minimums"):
            cfg.validate_minimums()
    except Exception:
        log.exception("Config initialization failed.")
        raise

    # Build context
    context = build_context_from_json(
        cfg=cfg,
        system_id=system_id,
        apms_csv_path=apms_csv_path,
        checklist_path=checklist_path,
    )

    # Resolve the test function
    mod = _load_tests_module(tests_module)
    dispatch = _index_tests_by_number(mod)
    if test_number not in dispatch:
        raise KeyError(f"Test {test_number} not found in {getattr(mod, '__name__', mod)}.")

    test_fn = dispatch[test_number]
    test_name = getattr(test_fn, "__name__", f"test_{test_number}")
    log.info("Running %s on system_id=%s", test_name, system_id)

    # Execute one test
    status = ATOStatus()
    try:
        result: TestResult = test_fn(context, status)  # type: ignore[arg-type]
        # If the test didn't add itself to status, ensure aggregation:
        if not any(r.test_number == result.test_number for r in status.results):
            status.add(result)
    except Exception:
        log.exception("Test %s raised an exception.", test_number)
        raise

    log.info("Test %s completed.", test_name)
    return result, status




def run_all_tests_status(
    *,
    cfg: Optional[Config],
    system_id: int,
    apms_csv_path: str,
    checklist_path: str = "DeepDiveTests.xlsx",
    tests_module: Union[str, ModuleType] = "tests",
    include_zero: bool = False,
    selected: Optional[Iterable[int]] = None,
    fail_fast: bool = False,
    logger_: Optional[logging.Logger] = None,
) -> ATOStatus:
    """Run the full compliance test suite and return an aggregated ATOStatus.

    This is the main programmatic runner used by the background job pipeline.
    It builds a SystemContext for the requested `system_id`, discovers all
    `test_*` callables in `tests_module`, executes them in numeric order, and
    aggregates each test's `TestResult` into a single ATOStatus.

    The returned ATOStatus is also annotated with `system_name`, inferred from
    the SystemContext, so downstream reporting code can label the system
    without having to rebuild context.

    Args:
        cfg: Optional Config. If None, a default Config() is constructed using
            DEFAULT_CONFIG_PATH. Logging/validation hooks on Config are called.
        system_id: Target system identifier to evaluate.
        apms_csv_path: Path to the APMS CSV used for correlation and metadata.
        checklist_path: Path to the Deep Dive workbook (Excel) used to seed
            checklist data. Defaults to "DeepDiveTests.xlsx".
        tests_module: Module (or module name) containing `test_*` functions.
            Defaults to "tests". Callables are expected to have the signature
            (SystemContext, ATOStatus) -> TestResult.
        include_zero: If True, include any `test_0*` functions. By default
            test number 0 is skipped.
        selected: Optional iterable of specific test numbers to run instead of
            running everything discovered.
        fail_fast: If True, re-raise immediately on the first test exception.
            If False, log and continue running remaining tests.
        logger_: Optional logger. If not provided, module-level `logger` is used.

    Returns:
        ATOStatus:
            - `results`: List[TestResult] for all executed tests.
            - `{pass,fail,concern,na}_count`: Aggregated counts.
            - `system_name`: Best-effort friendly name for the system, derived
              from SystemContext for downstream reporting/export.
    """
    log = logger_ or logger

    # Ensure config and initialize logging / validation.
    cfg = _ensure_config(cfg, "run_all_tests_status")
    if hasattr(cfg, "configure_logging"):
        cfg.configure_logging()
    if hasattr(cfg, "validate_minimums"):
        cfg.validate_minimums()

    # Snapshot effective config (redacted by Config.as_dict()).
    try:
        log.info("Runner using Config: %s", cfg.as_dict())
    except Exception:
        pass

    # Build the execution context for this system.
    context = build_context_from_json(
        cfg=cfg,
        system_id=system_id,
        apms_csv_path=apms_csv_path,
        checklist_path=checklist_path,
    )

    # Pre-resolve a display name so downstream callers don't have to.
    sys_name = _extract_system_name_from_context(context)

    # Discover available tests in the provided tests module.
    mod = _load_tests_module(tests_module)
    dispatch = _index_tests_by_number(mod)
    if not include_zero:
        dispatch = {k: v for k, v in dispatch.items() if k != 0}
    if selected is not None:
        requested = {int(n) for n in selected}
        dispatch = {k: v for k, v in dispatch.items() if k in requested}

    # Execute tests in numeric order and aggregate into ATOStatus.
    status = ATOStatus(system_name=sys_name)
    for test_number in sorted(dispatch.keys()):
        test_fn = dispatch[test_number]
        test_name = getattr(test_fn, "__name__", f"test_{test_number}")
        log.info("→ Running %s", test_name)
        try:
            tr: TestResult = test_fn(context, status)  # type: ignore[arg-type]
            if not any(r.test_number == tr.test_number for r in status.results):
                status.add(tr)
        except Exception:
            log.exception("✗ %s raised an exception", test_name)
            if fail_fast:
                raise
            # continue with remaining tests

    return status


__all__ = [
    "dump_pydantic",
    "list_available_tests",
    "build_context_from_json",
    "run_single_test",
    "run_all_tests_status",
]

