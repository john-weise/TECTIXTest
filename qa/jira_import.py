#!/usr/bin/env python3
"""
Tectix QA Test Case Importer for JIRA
======================================
Reads qa/test_cases.csv and creates JIRA issues via the REST API.

Works with:
  - Jira Cloud (atlassian.net)
  - Jira Server / Data Center (self-hosted)
  - Any project using Task issue types

Setup:
  pip install jira requests

Configuration:
  Edit the CONFIG section below or set environment variables:
    JIRA_URL        Your Jira instance URL
    JIRA_EMAIL      Your Jira account email (Cloud only)
    JIRA_TOKEN      API token (Cloud) or Personal Access Token (Server)
    JIRA_PROJECT    Project key (e.g. TECTIX or QA)

Usage:
  # Dry run - shows what would be created, creates nothing
  python qa/jira_import.py --dry-run

  # Import all test cases
  python qa/jira_import.py

  # Import specific category only
  python qa/jira_import.py --category AUTH

  # Import P0 tests only
  python qa/jira_import.py --priority P0

  # Import with custom CSV
  python qa/jira_import.py --csv qa/test_cases.csv
"""

import csv
import os
import sys
import time
import argparse
import textwrap
from pathlib import Path

# ─── CONFIGURATION ───────────────────────────────────────────────────────────
# Edit these OR set the corresponding environment variables.

CONFIG = {
    # Jira instance URL
    # Cloud example:  "https://yourcompany.atlassian.net"
    # Server example: "https://jira.yourcompany.com"
    "jira_url": os.environ.get("JIRA_URL", "https://yourcompany.atlassian.net"),

    # Cloud: your Atlassian account email
    # Server: leave empty (use token only)
    "jira_email": os.environ.get("JIRA_EMAIL", "you@company.com"),

    # Cloud: API token from https://id.atlassian.com/manage-profile/security/api-tokens
    # Server: Personal Access Token from Jira Profile > Personal Access Tokens
    "jira_token": os.environ.get("JIRA_TOKEN", ""),

    # Jira project key where test cases will be created (e.g. "QA", "TECTIX")
    "project_key": os.environ.get("JIRA_PROJECT", "TECTIX"),

    # Issue type to use for test cases.
    # "Task" works in any Jira project with no plugins required.
    # "Test" requires Xray or Zephyr plugins.
    "issue_type": os.environ.get("JIRA_ISSUE_TYPE", "Task"),

    # Label to tag all test cases with (makes them easy to find/filter)
    "base_label": "tectix-qa",

    # Delay between API calls in seconds (avoids rate limiting)
    "request_delay": 0.3,
}

# ─── PRIORITY MAPPING ────────────────────────────────────────────────────────
# Maps test case priorities (P0-P3) to Jira priority names.
# Adjust if your Jira instance uses different names.
PRIORITY_MAP = {
    "P0": "Highest",
    "P1": "High",
    "P2": "Medium",
    "P3": "Low",
}

# ─── HELPER FUNCTIONS ────────────────────────────────────────────────────────

def connect_to_jira(config: dict):
    """Connect to Jira and return a JIRA client instance."""
    try:
        from jira import JIRA
    except ImportError:
        print("Error: 'jira' package not installed.")
        print("Run: pip install jira")
        sys.exit(1)

    url = config["jira_url"]
    email = config["jira_email"]
    token = config["jira_token"]

    if not token:
        print("Error: JIRA_TOKEN not set. Create one at:")
        print("  Cloud: https://id.atlassian.com/manage-profile/security/api-tokens")
        print("  Server: Jira > Profile > Personal Access Tokens")
        sys.exit(1)

    try:
        # Cloud uses basic_auth=(email, token)
        # Server uses token_auth=token
        if "atlassian.net" in url:
            jira = JIRA(server=url, basic_auth=(email, token))
        else:
            jira = JIRA(server=url, token_auth=token)

        # Validate connection
        myself = jira.myself()
        print(f"Connected to Jira as: {myself['displayName']} ({myself.get('emailAddress', 'N/A')})")
        return jira

    except Exception as e:
        print(f"Error connecting to Jira: {e}")
        print(f"URL: {url}")
        sys.exit(1)


def read_test_cases(csv_path: str, category_filter: str = None, priority_filter: str = None) -> list:
    """Read test cases from CSV, optionally filtered by category or priority."""
    cases = []
    csv_file = Path(csv_path)

    if not csv_file.exists():
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)

    with open(csv_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Apply filters
            if category_filter and row.get("Category", "").upper() != category_filter.upper():
                continue
            if priority_filter and row.get("Priority", "") != priority_filter.upper():
                continue

            cases.append(row)

    return cases


def build_issue_fields(row: dict, config: dict) -> dict:
    """Convert a CSV row into a Jira issue fields dict."""
    test_id    = row.get("Test ID", "").strip()
    category   = row.get("Category", "").strip()
    sub_cat    = row.get("Sub-Category", "").strip()
    priority   = row.get("Priority", "P2").strip()
    name       = row.get("Test Name", "").strip()
    precond    = row.get("Preconditions", "").strip()
    steps      = row.get("Test Steps", "").strip()
    test_data  = row.get("Test Data", "").strip()
    expected   = row.get("Expected Result", "").strip()
    automatable = row.get("Automatable", "").strip()
    notes      = row.get("Notes", "").strip()

    # Build summary: "[TEST-ID] Test Name"
    summary = f"[{test_id}] {name}" if test_id else name

    # Build description in Jira wiki markup
    desc_parts = []

    if precond:
        desc_parts.append(f"*Preconditions:*\n{precond}")

    if steps:
        desc_parts.append(f"*Test Steps:*\n{steps}")

    if test_data:
        desc_parts.append(f"*Test Data:*\n{{noformat}}{test_data}{{noformat}}")

    if expected:
        desc_parts.append(f"*Expected Result:*\n{expected}")

    if automatable:
        desc_parts.append(f"*Automatable:* {automatable}")

    if notes:
        desc_parts.append(f"*Notes:* {notes}")

    description = "\n\n".join(desc_parts)

    # Build labels
    labels = [config["base_label"]]
    if category:
        labels.append(f"category-{category.lower().replace(' ', '-')}")
    if sub_cat:
        labels.append(f"type-{sub_cat.lower().replace(' ', '-')}")
    if automatable.lower() == "yes":
        labels.append("automatable")
    if automatable.lower() == "no":
        labels.append("manual-only")

    # Map priority
    jira_priority = PRIORITY_MAP.get(priority, "Medium")

    fields = {
        "project":     {"key": config["project_key"]},
        "summary":     summary,
        "description": description,
        "issuetype":   {"name": config["issue_type"]},
        "priority":    {"name": jira_priority},
        "labels":      labels,
    }

    return fields


def check_project_exists(jira, project_key: str) -> bool:
    """Verify that the target Jira project exists."""
    try:
        jira.project(project_key)
        return True
    except Exception:
        return False


def check_issue_type_exists(jira, project_key: str, issue_type: str) -> bool:
    """Verify that the issue type is available in the project."""
    try:
        meta = jira.createmeta(projectKeys=project_key, expand="projects.issuetypes")
        for project in meta.get("projects", []):
            for it in project.get("issuetypes", []):
                if it["name"].lower() == issue_type.lower():
                    return True
        return False
    except Exception:
        return False


def create_epic(jira, config: dict, category: str) -> str:
    """Create an epic for a test category. Returns the epic key."""
    try:
        # Try to create epic (requires Epic issue type and Epic Name field)
        fields = {
            "project":     {"key": config["project_key"]},
            "summary":     f"[QA] {category} Tests",
            "issuetype":   {"name": "Epic"},
            "labels":      [config["base_label"], "qa-epic"],
        }

        # Epic Name field (customfield_10011 is common but varies by instance)
        # Attempt to set it; if it fails, we still create the epic without it
        try:
            fields["customfield_10011"] = f"[QA] {category}"
        except Exception:
            pass

        epic = jira.create_issue(fields=fields)
        return epic.key

    except Exception as e:
        print(f"  Warning: Could not create epic for {category}: {e}")
        return None


# ─── MAIN IMPORT FUNCTION ────────────────────────────────────────────────────

def run_import(args):
    """Main import logic."""
    config = CONFIG.copy()

    # Override config from command line args
    if args.url:
        config["jira_url"] = args.url
    if args.email:
        config["jira_email"] = args.email
    if args.token:
        config["jira_token"] = args.token
    if args.project:
        config["project_key"] = args.project
    if args.issue_type:
        config["issue_type"] = args.issue_type

    # Read test cases
    cases = read_test_cases(
        csv_path=args.csv,
        category_filter=args.category,
        priority_filter=args.priority,
    )

    if not cases:
        print("No test cases found matching the filters.")
        return

    print(f"\nFound {len(cases)} test case(s) to import.")

    # Summary by category and priority
    from collections import Counter
    cat_counts = Counter(r.get("Category", "Unknown") for r in cases)
    pri_counts = Counter(r.get("Priority", "?") for r in cases)
    print("\nBreakdown by category:")
    for cat, count in sorted(cat_counts.items()):
        print(f"  {cat:<30} {count} tests")
    print("\nBreakdown by priority:")
    for pri, count in sorted(pri_counts.items()):
        print(f"  {pri}  {count} tests")

    if args.dry_run:
        print(f"\n{'='*60}")
        print("DRY RUN MODE - No issues will be created")
        print(f"{'='*60}")
        print("\nSample of what would be created:\n")
        for i, row in enumerate(cases[:3]):
            fields = build_issue_fields(row, config)
            print(f"  Issue {i+1}: {fields['summary']}")
            print(f"  Priority: {fields['priority']['name']}")
            print(f"  Labels:   {', '.join(fields['labels'])}")
            print()
        if len(cases) > 3:
            print(f"  ... and {len(cases) - 3} more")
        print("\nRun without --dry-run to actually import.")
        return

    # Connect to Jira
    print(f"\nConnecting to Jira: {config['jira_url']}")
    jira = connect_to_jira(config)

    # Validate project
    if not check_project_exists(jira, config["project_key"]):
        print(f"Error: Project '{config['project_key']}' not found.")
        print("Check your JIRA_PROJECT setting.")
        sys.exit(1)
    print(f"Project '{config['project_key']}' found.")

    # Validate issue type
    if not check_issue_type_exists(jira, config["project_key"], config["issue_type"]):
        print(f"Warning: Issue type '{config['issue_type']}' may not be available.")
        print("Will attempt anyway. Change --issue-type if it fails.")

    # Create epics per category (optional, skipped if Epic type unavailable)
    epic_keys = {}
    if args.create_epics:
        print("\nCreating category epics...")
        for cat in cat_counts.keys():
            print(f"  Creating epic for: {cat}")
            key = create_epic(jira, config, cat)
            if key:
                epic_keys[cat] = key
                print(f"    → {key}")
            time.sleep(config["request_delay"])

    # Import test cases
    print(f"\nImporting {len(cases)} test cases...")
    print("-" * 60)

    created = []
    failed  = []

    for i, row in enumerate(cases, start=1):
        test_id = row.get("Test ID", f"#{i}")
        name    = row.get("Test Name", "Untitled")
        category = row.get("Category", "")

        try:
            fields = build_issue_fields(row, config)

            # Link to epic if created
            if category in epic_keys:
                # customfield_10014 is the Epic Link field in most Jira instances
                fields["customfield_10014"] = epic_keys[category]

            issue = jira.create_issue(fields=fields)
            created.append((test_id, issue.key))
            print(f"  [{i:>3}/{len(cases)}] {test_id:<12} → {issue.key}  {name[:45]}")

            time.sleep(config["request_delay"])

        except Exception as e:
            failed.append((test_id, str(e)))
            print(f"  [{i:>3}/{len(cases)}] {test_id:<12} → FAILED: {e}")

    # Results summary
    print(f"\n{'='*60}")
    print(f"Import Complete")
    print(f"{'='*60}")
    print(f"  Created:  {len(created)}")
    print(f"  Failed:   {len(failed)}")

    if created:
        print(f"\nView imported tests:")
        print(f"  {config['jira_url']}/issues/?jql=labels={config['base_label']}+ORDER+BY+created+DESC")

    if failed:
        print("\nFailed imports:")
        for test_id, error in failed:
            print(f"  {test_id}: {error}")

    # Write mapping file (test_id → jira_key)
    if created:
        mapping_path = Path(args.csv).parent / "jira_mapping.csv"
        with open(mapping_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Test ID", "Jira Key", "Jira URL"])
            for test_id, jira_key in created:
                url = f"{config['jira_url']}/browse/{jira_key}"
                writer.writerow([test_id, jira_key, url])
        print(f"\nTest ID → Jira Key mapping saved to: {mapping_path}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Import Tectix QA test cases into Jira",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          # See what would be imported without creating anything
          python qa/jira_import.py --dry-run

          # Import all test cases
          python qa/jira_import.py

          # Import only authentication tests
          python qa/jira_import.py --category Authentication

          # Import only P0 critical tests
          python qa/jira_import.py --priority P0

          # Import to a specific project with custom issue type
          python qa/jira_import.py --project QA --issue-type Test

          # Import and create category epics
          python qa/jira_import.py --create-epics

        Environment variables:
          JIRA_URL      Jira instance URL
          JIRA_EMAIL    Jira account email (Cloud)
          JIRA_TOKEN    API token or Personal Access Token
          JIRA_PROJECT  Target project key
        """),
    )

    parser.add_argument("--csv",         default="qa/test_cases.csv", help="Path to test cases CSV")
    parser.add_argument("--dry-run",     action="store_true",          help="Preview without creating issues")
    parser.add_argument("--category",    default=None,                 help="Filter: import only this category (e.g. Authentication)")
    parser.add_argument("--priority",    default=None,                 help="Filter: import only this priority (P0, P1, P2, P3)")
    parser.add_argument("--create-epics",action="store_true",          help="Create a Jira Epic per test category")
    parser.add_argument("--url",         default=None,                 help="Override JIRA_URL")
    parser.add_argument("--email",       default=None,                 help="Override JIRA_EMAIL")
    parser.add_argument("--token",       default=None,                 help="Override JIRA_TOKEN")
    parser.add_argument("--project",     default=None,                 help="Override JIRA_PROJECT")
    parser.add_argument("--issue-type",  default=None,                 help="Override issue type (default: Task)")

    args = parser.parse_args()
    run_import(args)


if __name__ == "__main__":
    main()
