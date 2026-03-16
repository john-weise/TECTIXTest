#!/usr/bin/env python3
"""
Generate JIRA-compatible CSV files from test_cases.csv

Produces:
  qa/test_cases_jira_import.csv  - For Jira built-in CSV importer (no plugins needed)
  qa/test_cases_xray.csv         - For Xray plugin CSV importer
  qa/test_cases_zephyr.csv       - For Zephyr Scale CSV importer

Usage:
  python qa/generate_jira_csvs.py
"""

import csv
import re
from pathlib import Path

SRC = Path("qa/test_cases.csv")
OUT_DIR = Path("qa")

PRIORITY_MAP = {
    "P0": "Highest",
    "P1": "High",
    "P2": "Medium",
    "P3": "Low",
}


def read_source() -> list:
    with open(SRC, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def clean(text: str) -> str:
    """Collapse whitespace and strip."""
    return re.sub(r"\s+", " ", (text or "").strip())


# ─── 1. JIRA BUILT-IN CSV IMPORTER ──────────────────────────────────────────
# Jira's built-in importer (Settings > System > Import Issues from CSV).
# Maps to standard Jira fields, no plugins required.
# Issue type: Task. Priority from Jira priority list.
# Column names must match Jira field names exactly for auto-mapping.
#
# Required mapping when importing:
#   Summary           → Summary
#   Description       → Description
#   Priority          → Priority
#   Labels            → Labels
#   Issue Type        → Issue Type
#   Test ID           → (custom field or label)
#   Preconditions     → can be mapped to Environment or a custom field

def generate_jira_builtin(rows: list):
    out = OUT_DIR / "test_cases_jira_import.csv"
    fieldnames = [
        "Summary",
        "Issue Type",
        "Priority",
        "Labels",
        "Description",
        "Environment",      # Repurposed for Preconditions
        "Comment",          # Repurposed for Notes
    ]

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            test_id  = row["Test ID"].strip()
            name     = row["Test Name"].strip()
            priority = PRIORITY_MAP.get(row["Priority"].strip(), "Medium")
            category = row["Category"].strip()
            sub_cat  = row["Sub-Category"].strip()
            automatable = row["Automatable"].strip().lower()

            # Labels: category, sub-category, priority tag, automatable flag
            label_cat = f"category-{category.lower().replace(' ', '-')}"
            label_sub = f"type-{sub_cat.lower().replace(' ', '-').replace('/', '-')}"
            label_auto = "automatable" if automatable == "yes" else "manual-only"
            label_prio = f"priority-{row['Priority'].strip().lower()}"
            labels = f"tectix-qa {label_cat} {label_sub} {label_auto} {label_prio}"

            # Summary: [TEST-ID] Test Name
            summary = f"[{test_id}] {name}"

            # Description: structured text
            parts = []
            parts.append(f"Test ID: {test_id}")
            parts.append(f"Category: {category} > {sub_cat}")
            if row.get("Test Steps"):
                parts.append(f"\nTEST STEPS:\n{row['Test Steps']}")
            if row.get("Test Data"):
                parts.append(f"\nTEST DATA:\n{row['Test Data']}")
            if row.get("Expected Result"):
                parts.append(f"\nEXPECTED RESULT:\n{row['Expected Result']}")
            if row.get("Automatable"):
                parts.append(f"\nAutomatable: {row['Automatable']}")
            description = "\n".join(parts)

            writer.writerow({
                "Summary":      summary,
                "Issue Type":   "Task",
                "Priority":     priority,
                "Labels":       labels,
                "Description":  description,
                "Environment":  clean(row.get("Preconditions", "")),
                "Comment":      clean(row.get("Notes", "")),
            })

    print(f"Generated: {out} ({len(rows)} rows)")
    return out


# ─── 2. XRAY PLUGIN CSV FORMAT ───────────────────────────────────────────────
# For Xray's dedicated Test Case Importer (Test > Import Tests from CSV).
# Creates "Test" issue type with structured steps.
# Requires Xray plugin installed in Jira.
#
# Each test step is a separate row sharing the same Issue Id.
# Columns: Issue Id, Test Type, Summary, Precondition, Action, Data, Result

def split_steps(steps_text: str) -> list:
    """Split numbered steps into a list of (action, data, result) tuples."""
    if not steps_text:
        return [("Execute test", "", "")]

    # Try to split on numbered steps like "1. step\n2. step"
    parts = re.split(r"\n?\d+\.\s+", steps_text.strip())
    parts = [p.strip() for p in parts if p.strip()]

    if not parts:
        return [(steps_text.strip(), "", "")]

    return [(p, "", "") for p in parts]


def generate_xray(rows: list):
    out = OUT_DIR / "test_cases_xray.csv"
    fieldnames = [
        "Issue Id",
        "Test Type",
        "Summary",
        "Precondition",
        "Action",
        "Data",
        "Result",
        "Labels",
        "Priority",
    ]

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            test_id     = row["Test ID"].strip()
            name        = row["Test Name"].strip()
            precond     = clean(row.get("Preconditions", ""))
            steps_text  = row.get("Test Steps", "")
            test_data   = row.get("Test Data", "")
            expected    = clean(row.get("Expected Result", ""))
            priority    = PRIORITY_MAP.get(row["Priority"].strip(), "Medium")
            automatable = row["Automatable"].strip().lower()
            category    = row["Category"].strip()
            sub_cat     = row["Sub-Category"].strip()

            # Xray test type: Manual or Generic (for automated)
            test_type = "Generic" if automatable == "yes" else "Manual"

            # Labels
            labels = f"tectix-qa category-{category.lower().replace(' ', '-')} priority-{row['Priority'].strip().lower()}"

            # Split steps - each step = one row, same Issue Id
            steps = split_steps(steps_text)

            # First row carries the summary and precondition
            first = True
            for i, (action, data, result) in enumerate(steps):
                # Last step: attach expected result
                if i == len(steps) - 1:
                    result = expected or result

                # Test data on first step only
                step_data = test_data if first else ""

                writer.writerow({
                    "Issue Id":    test_id,
                    "Test Type":   test_type if first else "",
                    "Summary":     f"[{test_id}] {name}" if first else "",
                    "Precondition": precond if first else "",
                    "Action":      action,
                    "Data":        clean(step_data),
                    "Result":      result,
                    "Labels":      labels if first else "",
                    "Priority":    priority if first else "",
                })
                first = False

    print(f"Generated: {out} ({len(rows)} tests, multi-row format)")
    return out


# ─── 3. ZEPHYR SCALE CSV FORMAT ──────────────────────────────────────────────
# For Zephyr Scale's CSV importer.
# Supports folder hierarchy using "/" in the Folder column.
# Test steps use separate "Step" and "Expected Result" columns per row.
# Ref: https://support.smartbear.com/zephyr-scale-cloud/docs/en/test-cases/import-test-cases.html

def generate_zephyr(rows: list):
    out = OUT_DIR / "test_cases_zephyr.csv"
    fieldnames = [
        "Name",
        "Objective",
        "Precondition",
        "Folder",
        "Status",
        "Priority",
        "Labels",
        "Step",
        "Expected Result",
        "Test Data",
    ]

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            test_id     = row["Test ID"].strip()
            name        = row["Test Name"].strip()
            precond     = clean(row.get("Preconditions", ""))
            steps_text  = row.get("Test Steps", "")
            test_data   = row.get("Test Data", "")
            expected    = clean(row.get("Expected Result", ""))
            priority    = PRIORITY_MAP.get(row["Priority"].strip(), "Medium")
            automatable = row["Automatable"].strip().lower()
            category    = row["Category"].strip()
            sub_cat     = row["Sub-Category"].strip()
            notes       = clean(row.get("Notes", ""))

            # Folder hierarchy: Tectix QA / Category / Sub-Category
            folder = f"Tectix QA/{category}/{sub_cat}"

            # Labels: automatable flag + priority tag
            label_auto = "Automatable" if automatable == "yes" else "Manual-Only"
            labels = f"tectix-qa, {label_auto}, {row['Priority'].strip()}"

            # Objective = test name with ID and any notes
            objective = f"[{test_id}] {name}"
            if notes:
                objective += f"\n\nNotes: {notes}"

            # Zephyr status: "Draft" for new imports
            status = "Draft"

            # Split steps - each step = one row
            steps = split_steps(steps_text)

            first = True
            for i, (action, _, _) in enumerate(steps):
                step_expected = expected if i == len(steps) - 1 else ""
                step_data = test_data if first else ""

                writer.writerow({
                    "Name":            f"[{test_id}] {name}" if first else "",
                    "Objective":       objective if first else "",
                    "Precondition":    precond if first else "",
                    "Folder":          folder if first else "",
                    "Status":          status if first else "",
                    "Priority":        priority if first else "",
                    "Labels":          labels if first else "",
                    "Step":            action,
                    "Expected Result": step_expected,
                    "Test Data":       clean(step_data),
                })
                first = False

    print(f"Generated: {out} ({len(rows)} tests, multi-row format)")
    return out


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    if not SRC.exists():
        print(f"Error: Source file not found: {SRC}")
        print("Run from the repository root: python qa/generate_jira_csvs.py")
        return

    rows = read_source()
    print(f"Read {len(rows)} test cases from {SRC}\n")

    jira_file  = generate_jira_builtin(rows)
    xray_file  = generate_xray(rows)
    zephyr_file = generate_zephyr(rows)

    print(f"""
Generated 3 JIRA-ready CSV files:

1. {jira_file}
   → Use with: Jira > Settings > System > Import Issues from CSV
   → No plugins required. Creates Task issues.

2. {xray_file}
   → Use with: Xray plugin > Test > Import Tests from CSV
   → Requires Xray plugin. Creates Test issues with structured steps.

3. {zephyr_file}
   → Use with: Zephyr Scale > Test Cases > Import from CSV
   → Requires Zephyr Scale plugin. Creates Test Cases with folder hierarchy.

See qa/JIRA_INTEGRATION.md for full instructions on each approach.
""")


if __name__ == "__main__":
    main()
