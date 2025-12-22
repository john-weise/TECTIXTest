"""
This script is an entry point to run individual tests
for testing and evaluation.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Callable, Dict

from engine.config import Config
from engine.models import SystemContext, ATOStatus, TestResult
from engine.helpers import test_number_from_name  # for numbering logic
from engine import test_api  # JSON-simulated API pulls
from engine import tests as tests_mod  # tests.py inside engine/

# -----------------------
# Logging (simple default)
# -----------------------
logging.basicConfig(
    level=os.getenv("LOGLEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_runner")

CHECKLIST_PATH = "static/DeepDiveTests.xlsx"


# -----------------------
# Pretty-print utilities
# -----------------------
def dump_pydantic(obj: Any) -> str:
    """Return a JSON string representation for Pydantic models (v1 or v2).

    Handles both Pydantic v1 and v2 APIs and falls back to best-effort JSON
    serialization if the object is not a Pydantic model.

    Args:
        obj: Object to serialize.

    Returns:
        JSON-formatted string representation.
    """
    # Pydantic v2
    if hasattr(obj, "model_dump_json"):
        try:
            return obj.model_dump_json(indent=2)
        except TypeError:
            # Some versions don't accept indent kwarg
            return obj.model_dump_json()
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(), indent=2, default=str)

    # Pydantic v1
    if hasattr(obj, "json"):
        try:
            return obj.json(indent=2)
        except TypeError:
            return obj.json()
    if hasattr(obj, "dict"):
        return json.dumps(obj.dict(), indent=2, default=str)

    # Fallback
    try:
        return json.dumps(obj, indent=2, default=str)
    except Exception:
        return str(obj)


# -----------------------
# Test discovery helpers
# -----------------------
def index_tests_by_number(
    mod: Any,
) -> Dict[int, Callable[[SystemContext, ATOStatus], TestResult]]:
    """Index test functions by their numeric test id.

    Scans the given module for callables whose names start with ``test_`` and
    uses ``test_number_from_name`` to extract the numeric id.

    Args:
        mod: Imported module object to inspect.

    Returns:
        Mapping of test number → test function.
    """
    table: Dict[int, Callable[[SystemContext, ATOStatus], TestResult]] = {}
    for name in dir(mod):
        if not name.startswith("test_"):
            continue
        fn = getattr(mod, name)
        if callable(fn):
            n = test_number_from_name(name)  # e.g., "test_10" -> 10
            if n is not None:
                table[n] = fn
    return dict(sorted(table.items()))


# -----------------------
# Context builder wrapper
# -----------------------
def build_context_from_json(
    cfg: Config,
    system_id: int,
    apms_csv_path: str,
    checklist_path: str,
) -> SystemContext:
    """Build a SystemContext from local JSON/CSV fixtures.

    Delegates to ``engine.test_api.build_system_context_from_emass``, which
    simulates API pulls using local JSON-backed data.

    Args:
        cfg: Application configuration object.
        system_id: eMASS system identifier.
        apms_csv_path: Absolute path to the APMS CSV file.
        checklist_path: Absolute path to the deep-dive checklist workbook.

    Returns:
        Fully-populated SystemContext snapshot for the target system.
    """
    return test_api.build_system_context_from_emass(
        cfg=cfg,
        system_id=system_id,
        apms_csv_path=apms_csv_path,
        checklist_path=checklist_path,
    )


def main() -> int:
    """CLI entry point for running individual ATO tests."""
    print("=== ATO Test Runner ===")

    # Config + logging
    cfg = Config()
    cfg.configure_logging()
    cfg.validate_minimums()

    # Prompt only for system_id and APMS CSV
    default_sys = cfg.emass_system_id or 101
    system_id_str = input(f"Enter system_id (int) [{default_sys}]: ").strip() or str(default_sys)
    try:
        system_id = int(system_id_str)
    except ValueError:
        print("system_id must be an integer.")
        return 2

    default_apms = os.getenv("APMS_CSV", "ELS_system_match_preview.csv")
    apms_csv_path_input = input(f"APMS CSV path [{default_apms}]: ").strip() or default_apms

    # Normalize to absolute paths for clearer error messages
    apms_csv_path_abs = os.path.abspath(os.path.expanduser(apms_csv_path_input))
    checklist_path_abs = os.path.abspath(os.path.expanduser(CHECKLIST_PATH))

    # Validate paths (print full absolute paths)
    if not os.path.exists(apms_csv_path_abs):
        print(f"APMS CSV not found: {apms_csv_path_abs}")
        return 2

    if not os.path.exists(checklist_path_abs):
        print(f"Checklist not found: {checklist_path_abs}")
        return 2

    # Build context from local JSONs
    print("\nBuilding SystemContext from Notionalassets/*.json ...")
    ctx = build_context_from_json(cfg, system_id, apms_csv_path_abs, checklist_path_abs)
    print("SystemContext ready.")

    # Discover tests from engine.tests
    test_table = index_tests_by_number(tests_mod)
    if not test_table:
        print("No tests found in engine/tests.py (functions named test_*).")
        return 1

    # Show available tests, but hide test 0
    print("\nAvailable tests:", ", ".join(str(n) for n in test_table if n != 0))
    choice_raw = input("Which test number do you want to run? ").strip()
    try:
        choice = int(choice_raw)
    except ValueError:
        print("Please enter a valid integer test number.")
        return 2

    if choice not in test_table:
        print(f"Test {choice} not found.")
        return 3

    test_fn = test_table[choice]
    status = ATOStatus()

    # Show a friendly name if present
    test_name = getattr(test_fn, "__name__", f"test_{choice}")
    print(f"\nRunning {test_name} ...")

    try:
        tr: TestResult = test_fn(ctx, status)  # type: ignore[arg-type]
    except Exception as exc:
        logger.exception("Test %s raised an exception", choice)
        print(
            json.dumps(
                {"error": f"Test {choice} crashed", "exception": repr(exc)},
                indent=2,
            )
        )
        return 4

    print("\n=== TestResult (Pydantic) ===")
    print(dump_pydantic(tr))

    if input("\nShow aggregated ATOStatus as well? [y/N]: ").strip().lower() == "y":
        print("\n=== ATOStatus (Pydantic) ===")
        print(dump_pydantic(status))

    print("\nDone.\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(2)
