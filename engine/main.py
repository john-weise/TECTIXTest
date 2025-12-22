# main.py
from __future__ import annotations

"""
Entry point for the TECTIX ATO script.

Responsibilities:
  - Parse command-line arguments
  - Load configuration (config.ini) and initialize logging
  - Build the SystemContext exactly once
  - Execute all tests and print a concise summary
  - Return a useful process exit code for CI/CD

Exit codes:
  0  -> All tests PASS or are N/A
  1  -> One or more tests FAIL
  2  -> A fatal error occurred (configuration, network, etc.)
"""

import argparse
import logging
import os
import sys
import time
from typing import Optional

from engine.config import Config
from engine.context import init_context, get_context
from engine.models import ATOStatus, SystemContext
from engine.tests import run_all_tests, build_context_from_emass_env


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """
    Parse command-line arguments for the ATO Deep Dive runner.

    This function centralizes all CLI input handling to keep `main()` focused
    on orchestration. Each argument is clearly defined with defaults pulled
    from environment variables when available.

    Args:
        argv (Optional[list[str]]): Explicit argument list to parse. 
            Defaults to None, which causes argparse to use sys.argv[1:].
            This parameter exists primarily to support unit testing.

    Returns:
        argparse.Namespace: Parsed and validated arguments, including:
            - config (str): Path to configuration INI file.
            - system_id (int): Integer system identifier used in eMASS APIs.
            - apms_csv (str): Path to the APMS CSV file for this execution.
            - checklist (str): Path to the checklist file.
    """
    parser = argparse.ArgumentParser(
        description="ATO Deep Dive Runner — compliance test harness for eMASS systems.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Config file path (defaults to CONFIG_FILE env var or 'config.ini')
    parser.add_argument(
        "--config",
        default=os.getenv("CONFIG_FILE", "config.ini"),
        help="Path to configuration INI file (overrides CONFIG_FILE env var).",
    )

    # System ID is always numeric; enforce as int to avoid string/int mismatches.
    parser.add_argument(
        "--system-id",
        type=int,
        default=os.getenv("EMASS_SYSTEM_ID"),
        help="Numeric eMASS system ID. Overrides config.ini if provided.",
    )

    # APMS CSV is dynamic each run (no useful default).
    parser.add_argument(
        "--apms-csv",
        required=True,
        help="Path to the APMS CSV report for this run (dynamic per execution).",
    )

    # Checklist file can come from env or config.ini as fallback.
    parser.add_argument(
        "--checklist",
        default=os.getenv("CHECKLIST_PATH"),
        help="Path to checklist file. Overrides config.ini if provided.",
    )

    return parser.parse_args(argv)


def resolve_runtime_config(args: argparse.Namespace) -> Config:
    """
    Load configuration and initialize logging.

    Args:
        args: Parsed CLI args including --config.

    Returns:
        Config: Loaded configuration object.
    """
    cfg = Config(file_path=args.config)
    cfg.configure_logging()
    cfg.validate_minimums()
    return cfg


def build_context_once(
    system_id: str,
    apms_csv_path: str,
    checklist_path: str,
) -> SystemContext:
    """
    Build the SystemContext exactly once and store it in the singleton.

    Args:
        system_id: eMASS system identifier.
        apms_csv_path: Path to the APMS CSV (dynamic each run).
        checklist_path: Path to the checklist file.

    Returns:
        SystemContext: The initialized and cached context instance.
    """
    context = build_context_from_emass_env(
        system_id=system_id,
        apms_csv_path=apms_csv_path,
        checklist_path=checklist_path,
    )
    init_context(context)
    return context


def main(argv: Optional[list[str]] = None) -> int:
    """
    Program entry. Orchestrates configuration, context construction, and test execution.
    NOTE: During integration, we may make this return an object used by rest of program. ALSO, main may become ATO_Script (or something) later during integration

    Args:
        argv: Optional argument list (for testing).

    Returns:
        int: Process exit code (see module docstring).
    """
    start_time = time.time()
    try:
        args = parse_args(argv)
        cfg = resolve_runtime_config(args)
        logger = logging.getLogger("main")

        # Determine effective inputs
        effective_system_id = args.system_id or cfg.emass_system_id
        if not effective_system_id:
            logger.error("--system-id is required (CLI arg or EMASS_SYSTEM_ID env or config.ini emass.system_id)")
            return 2

        effective_checklist_path = args.checklist or cfg.checklist_path

        logger.info("Starting ATO Deep Dive for system_id=%s", effective_system_id)
        logger.debug("Using checklist_path=%s", effective_checklist_path)
        logger.debug("Using APMS CSV=%s", args.apms_csv)

        # Build (and cache) SystemContext once
        build_context_once(
            system_id=effective_system_id,
            apms_csv_path=args.apms_csv,
            checklist_path=effective_checklist_path,
        )

        # Execute tests
        final_status: ATOStatus = run_all_tests(get_context())
        runtime_sec = time.time() - start_time

        # Report summary
        logger.info(final_status.summary())
        logger.info("Completed in %.2fs", runtime_sec)

        # Exit code policy: non-zero if any FAIL
        if final_status.fail_count > 0:
            return 1
        return 0

    except KeyboardInterrupt:
        logging.getLogger("main").warning("Interrupted by user.")
        return 2
    except SystemExit as se:
        # Allow explicit sys.exit() or raise SystemExit to propagate code
        return int(se.code) if se.code is not None else 2
    except Exception as exc:  # noqa: BLE001 (we want a top-level safety net)
        logging.getLogger("main").exception("Fatal error: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
