#!/usr/bin/env python3
"""
TECTIX Test Runner - Interactive and Batch Mode

This is a convenience wrapper for running all RMF compliance tests.

Usage:
    # Interactive mode (prompts for inputs)
    python run_tests.py

    # Quick run with system ID
    python run_tests.py 101

    # Full options via CLI
    python run_tests.py 101 --html --verbose

    # Generate both HTML and JSON reports
    python run_tests.py 101 --html --json

For full CLI options:
    python -m engine.full_test_runner --help
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.full_test_runner import (
    run_full_test_suite,
    generate_html_report,
    generate_json_report,
    print_terminal_report,
    discover_tests,
    parse_test_selection,
)
from engine.models import Result
from datetime import datetime


def interactive_mode():
    """Run in interactive mode with prompts."""
    print("\n" + "=" * 60)
    print("TECTIX RMF Compliance Test Runner")
    print("=" * 60)

    # Get system ID
    default_id = 101
    system_id_input = input(f"\nEnter System ID [{default_id}]: ").strip()
    try:
        system_id = int(system_id_input) if system_id_input else default_id
    except ValueError:
        print("Invalid system ID. Using default.")
        system_id = default_id

    # Show available tests
    all_tests = discover_tests()
    print(f"\nFound {len(all_tests)} tests available.")

    # Ask about test selection
    run_all = input("\nRun all tests? [Y/n]: ").strip().lower()
    selected_tests = None
    if run_all == 'n':
        tests_input = input("Enter test numbers (e.g., 1,2,3,10-20): ").strip()
        if tests_input:
            try:
                selected_tests = parse_test_selection(tests_input)
                print(f"Selected {len(selected_tests)} tests.")
            except ValueError as e:
                print(f"Invalid selection: {e}. Running all tests.")

    # Ask about output format
    print("\nOutput options:")
    print("  1. Terminal only (default)")
    print("  2. Terminal + HTML report")
    print("  3. Terminal + JSON report")
    print("  4. Terminal + HTML + JSON")
    output_choice = input("Choose output [1-4]: ").strip() or "1"

    generate_html = output_choice in ("2", "4")
    generate_json = output_choice in ("3", "4")

    # Ask about verbosity
    verbose = input("\nShow progress during execution? [Y/n]: ").strip().lower() != 'n'
    show_json_data = input("Show JSON data in terminal output? [y/N]: ").strip().lower() == 'y'

    # APMS and checklist paths
    default_csv = os.getenv("APMS_CSV", "ELS_system_match_preview.csv")
    apms_path = None
    for candidate in [default_csv, f"engine/{default_csv}", f"../engine/{default_csv}"]:
        if os.path.exists(candidate):
            apms_path = candidate
            break
    if apms_path is None:
        apms_path = default_csv
    checklist_path = "static/DeepDiveTests.xlsx"

    print(f"\nUsing APMS CSV: {apms_path}")
    print(f"Using Checklist: {checklist_path}")

    # Run tests
    print("\n" + "-" * 60)
    print("Running tests...")
    print("-" * 60)

    try:
        result = run_full_test_suite(
            system_id=system_id,
            apms_csv_path=apms_path,
            checklist_path=checklist_path,
            selected_tests=selected_tests,
            verbose=verbose,
            include_json_data=generate_html or generate_json or show_json_data,
        )
    except FileNotFoundError as e:
        print(f"\nError: {e}")
        return 2
    except Exception as e:
        print(f"\nError running tests: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Display results
    print_terminal_report(result, show_json=show_json_data)

    # Generate reports
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    if generate_html:
        html_path = f"test_results_{system_id}_{timestamp}.html"
        generate_html_report(result, html_path)
        print(f"\nHTML report: {html_path}")

    if generate_json:
        json_path = f"test_results_{system_id}_{timestamp}.json"
        generate_json_report(result, json_path)
        print(f"JSON report: {json_path}")

    return 0 if result.fail_count == 0 else 1


def quick_mode(system_id: int, args: list):
    """Run with command line arguments."""
    import argparse

    parser = argparse.ArgumentParser(description="Quick test runner")
    parser.add_argument("system_id", type=int, nargs="?", default=system_id)
    parser.add_argument("--html", action="store_true", help="Generate HTML report")
    parser.add_argument("--json", action="store_true", help="Generate JSON report")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show progress")
    parser.add_argument("--tests", "-t", help="Specific tests (e.g., 1,2,3,10-20)")
    parser.add_argument("--filter", "-f", choices=["pass", "fail", "concern", "na"])
    parser.add_argument("--show-json", action="store_true", help="Show JSON in terminal")
    parser.add_argument("--quiet", "-q", action="store_true", help="Summary only")

    parsed = parser.parse_args([str(system_id)] + args)

    selected_tests = None
    if parsed.tests:
        selected_tests = parse_test_selection(parsed.tests)

    filter_results = None
    if parsed.filter:
        filter_map = {
            "pass": {Result.PASS},
            "fail": {Result.FAIL},
            "concern": {Result.CONCERN},
            "na": {Result.NA},
        }
        filter_results = filter_map[parsed.filter]

    try:
        result = run_full_test_suite(
            system_id=parsed.system_id,
            selected_tests=selected_tests,
            filter_results=filter_results,
            verbose=parsed.verbose,
            include_json_data=parsed.html or parsed.json or parsed.show_json,
        )
    except Exception as e:
        print(f"Error: {e}")
        return 1

    if not parsed.quiet:
        print_terminal_report(result, show_json=parsed.show_json)
    else:
        print(result.summary())

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    if parsed.html:
        html_path = f"test_results_{parsed.system_id}_{timestamp}.html"
        generate_html_report(result, html_path)
        print(f"HTML report: {html_path}")

    if parsed.json:
        json_path = f"test_results_{parsed.system_id}_{timestamp}.json"
        generate_json_report(result, json_path)
        print(f"JSON report: {json_path}")

    return 0 if result.fail_count == 0 else 1


def main():
    if len(sys.argv) == 1:
        # No arguments - interactive mode
        return interactive_mode()
    else:
        # Arguments provided - quick mode
        try:
            system_id = int(sys.argv[1])
            return quick_mode(system_id, sys.argv[2:])
        except ValueError:
            # First arg is not a number, might be --help
            if sys.argv[1] in ("--help", "-h"):
                print(__doc__)
                return 0
            print(f"Invalid system ID: {sys.argv[1]}")
            return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
