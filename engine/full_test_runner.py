# engine/full_test_runner.py
"""
Comprehensive Test Runner for TECTIX ATO Compliance Tests.

This module provides a full-featured test runner that:
- Runs all 175+ tests against a system ID
- Shows full results with pass/fail/concern/na status
- Displays relevant JSON data for each test
- Generates HTML and JSON reports
- Supports filtering by test number, result type, or pattern

Usage (CLI):
    python -m engine.full_test_runner --system-id 101
    python -m engine.full_test_runner --system-id 101 --output html --report results.html
    python -m engine.full_test_runner --system-id 101 --tests 1,2,3,10-20
    python -m engine.full_test_runner --system-id 101 --filter fail

Usage (Programmatic):
    from engine.full_test_runner import run_full_test_suite
    results = run_full_test_suite(system_id=101)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from engine.config import Config
from engine.models import ATOStatus, Result, SystemContext, TestResult
from engine.helpers import test_number_from_name
from engine import test_api
from engine import tests as tests_mod

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=os.getenv("LOGLEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("full_test_runner")


# -----------------------------------------------------------------------------
# Data Classes for Enhanced Results
# -----------------------------------------------------------------------------
@dataclass
class TestExecutionResult:
    """Enhanced test result with execution metadata and context data."""
    test_number: int
    test_name: str
    result: Result
    message: str
    execution_time_ms: float = 0.0
    error: Optional[str] = None
    context_fields_used: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_number": self.test_number,
            "test_name": self.test_name,
            "result": self.result.value,
            "message": self.message,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "error": self.error,
            "context_fields_used": self.context_fields_used,
        }


@dataclass
class FullTestSuiteResult:
    """Complete test suite execution results."""
    system_id: int
    system_name: Optional[str]
    execution_start: datetime
    execution_end: Optional[datetime] = None
    total_tests: int = 0
    pass_count: int = 0
    fail_count: int = 0
    concern_count: int = 0
    na_count: int = 0
    error_count: int = 0
    results: List[TestExecutionResult] = field(default_factory=list)
    context_snapshot: Dict[str, Any] = field(default_factory=dict)
    json_data_sources: Dict[str, Any] = field(default_factory=dict)

    @property
    def execution_time_seconds(self) -> float:
        if self.execution_end:
            return (self.execution_end - self.execution_start).total_seconds()
        return 0.0

    @property
    def pass_rate(self) -> float:
        if self.total_tests == 0:
            return 0.0
        return (self.pass_count / self.total_tests) * 100

    def summary(self) -> str:
        return (
            f"System: {self.system_name or self.system_id} | "
            f"Total: {self.total_tests} | "
            f"PASS: {self.pass_count} | "
            f"FAIL: {self.fail_count} | "
            f"CONCERN: {self.concern_count} | "
            f"N/A: {self.na_count} | "
            f"ERRORS: {self.error_count} | "
            f"Pass Rate: {self.pass_rate:.1f}%"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "system_id": self.system_id,
            "system_name": self.system_name,
            "execution_start": self.execution_start.isoformat(),
            "execution_end": self.execution_end.isoformat() if self.execution_end else None,
            "execution_time_seconds": round(self.execution_time_seconds, 2),
            "summary": {
                "total_tests": self.total_tests,
                "pass_count": self.pass_count,
                "fail_count": self.fail_count,
                "concern_count": self.concern_count,
                "na_count": self.na_count,
                "error_count": self.error_count,
                "pass_rate": round(self.pass_rate, 2),
            },
            "results": [r.to_dict() for r in self.results],
            "context_snapshot": self.context_snapshot,
            "json_data_sources": self.json_data_sources,
        }


# -----------------------------------------------------------------------------
# Test Discovery
# -----------------------------------------------------------------------------
def discover_tests() -> Dict[int, Callable[[SystemContext, ATOStatus], TestResult]]:
    """Discover all test functions from the tests module."""
    table: Dict[int, Callable] = {}
    for name in dir(tests_mod):
        if not name.startswith("test_"):
            continue
        fn = getattr(tests_mod, name)
        if callable(fn):
            n = test_number_from_name(name)
            if n is not None and n != 0:  # Skip test_0
                table[n] = fn
    return dict(sorted(table.items()))


def parse_test_selection(selection: str) -> Set[int]:
    """Parse test selection string like '1,2,3,10-20,50'.

    Args:
        selection: Comma-separated list of test numbers or ranges.

    Returns:
        Set of test numbers to run.
    """
    result: Set[int] = set()
    for part in selection.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            result.update(range(int(start), int(end) + 1))
        else:
            result.add(int(part))
    return result


# -----------------------------------------------------------------------------
# Context Building and JSON Data Extraction
# -----------------------------------------------------------------------------
def build_context(
    cfg: Config,
    system_id: int,
    apms_csv_path: str,
    checklist_path: str,
) -> SystemContext:
    """Build a SystemContext from local JSON fixtures."""
    return test_api.build_system_context_from_emass(
        cfg=cfg,
        system_id=system_id,
        apms_csv_path=apms_csv_path,
        checklist_path=checklist_path,
    )


def extract_context_snapshot(ctx: SystemContext) -> Dict[str, Any]:
    """Extract key fields from SystemContext for reporting."""
    snapshot = {}

    # Core identity
    snapshot["system_id"] = ctx.system_id
    snapshot["system_name"] = ctx.system_name
    snapshot["system_acronym"] = ctx.system_acronym
    snapshot["registration_type"] = ctx.registration_type

    # CIA Triad
    snapshot["confidentiality"] = ctx.confidentiality
    snapshot["integrity"] = ctx.integrity
    snapshot["availability"] = ctx.availability
    snapshot["impact"] = ctx.impact

    # Classification
    snapshot["classification"] = ctx.classification
    snapshot["mission_criticality"] = ctx.mission_criticality

    # Data sensitivity
    snapshot["cui"] = ctx.cui
    snapshot["pii"] = ctx.pii
    snapshot["phi"] = ctx.phi
    snapshot["nss"] = ctx.nss
    snapshot["fms"] = ctx.fms

    # RMF / Workflow
    snapshot["rmf_activity"] = ctx.rmf_activity
    snapshot["workflow_type"] = ctx.workflow_type
    snapshot["workflow_name"] = ctx.workflow_name
    snapshot["workflow_stage"] = ctx.workflow_stage
    snapshot["authorization_status"] = ctx.authorization_status

    # Cloud
    snapshot["cloud_computing"] = ctx.cloud_computing
    snapshot["cloud_type"] = ctx.cloud_type
    snapshot["is_saas"] = ctx.is_saas
    snapshot["is_paas"] = ctx.is_paas
    snapshot["is_iaas"] = ctx.is_iaas

    # Inventory indicators
    snapshot["has_hardware_data"] = ctx.has_hardware_data
    snapshot["has_software_data"] = ctx.has_software_data
    snapshot["artifact_number"] = ctx.artifact_number

    # APMS correlation
    snapshot["apms_item_name"] = ctx.apms_item_name
    snapshot["apms_acronym"] = ctx.apms_acronym

    return {k: v for k, v in snapshot.items() if v is not None}


def extract_json_data_sources(ctx: SystemContext) -> Dict[str, Any]:
    """Extract loaded JSON data sources for detailed inspection."""
    sources = {}

    def safe_extract(obj: Any, max_items: int = 10) -> Any:
        """Safely extract data, limiting large lists."""
        if obj is None:
            return None
        if hasattr(obj, "model_dump"):
            data = obj.model_dump()
        elif hasattr(obj, "dict"):
            data = obj.dict()
        elif isinstance(obj, dict):
            data = obj
        else:
            return str(obj)

        # If there's a 'data' list, summarize it
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
            full_list = data["data"]
            data = dict(data)  # copy
            data["_total_items"] = len(full_list)
            data["data"] = full_list[:max_items]
            if len(full_list) > max_items:
                data["_truncated"] = True
        return data

    # Extract each data source
    if ctx.system_info:
        sources["system_info"] = safe_extract(ctx.system_info)
    if ctx.system_details_dashboard:
        sources["system_details_dashboard"] = safe_extract(ctx.system_details_dashboard)
    if ctx.workflow_dashboard:
        sources["workflow_dashboard"] = safe_extract(ctx.workflow_dashboard)
    if ctx.controls:
        sources["controls"] = safe_extract(ctx.controls)
    if ctx.test_results:
        sources["test_results"] = safe_extract(ctx.test_results)
    if ctx.artifact_details:
        sources["artifact_details"] = safe_extract(ctx.artifact_details)
    if ctx.artifact_summary:
        sources["artifact_summary"] = safe_extract(ctx.artifact_summary)
    if ctx.hardware:
        sources["hardware"] = safe_extract(ctx.hardware)
    if ctx.software:
        sources["software"] = safe_extract(ctx.software)
    if ctx.privacy:
        sources["privacy"] = safe_extract(ctx.privacy)
    if ctx.findings:
        sources["findings"] = safe_extract(ctx.findings)
    if ctx.cac:
        sources["cac"] = safe_extract(ctx.cac)
    if ctx.system_poam_dashboard:
        sources["system_poam_dashboard"] = safe_extract(ctx.system_poam_dashboard)
    if ctx.associations:
        sources["associations"] = safe_extract(ctx.associations)
    if ctx.user_details:
        sources["user_details"] = safe_extract(ctx.user_details)

    # APMS data
    if ctx.apms_first_row_raw:
        sources["apms_first_row"] = ctx.apms_first_row_raw

    return sources


# -----------------------------------------------------------------------------
# Test Execution
# -----------------------------------------------------------------------------
def run_single_test_with_timing(
    test_fn: Callable,
    test_number: int,
    ctx: SystemContext,
) -> TestExecutionResult:
    """Execute a single test and capture timing and result."""
    test_name = getattr(test_fn, "__name__", f"test_{test_number}")
    status = ATOStatus()

    start_time = time.perf_counter()
    error_msg = None
    result = Result.NA
    message = "Test did not produce a result"

    try:
        tr: TestResult = test_fn(ctx, status)
        result = tr.result
        message = tr.message
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        result = Result.FAIL
        message = f"Test raised exception: {error_msg}"
        logger.exception("Test %s raised an exception", test_number)

    end_time = time.perf_counter()
    execution_time_ms = (end_time - start_time) * 1000

    return TestExecutionResult(
        test_number=test_number,
        test_name=test_name,
        result=result,
        message=message,
        execution_time_ms=execution_time_ms,
        error=error_msg,
    )


def run_full_test_suite(
    system_id: int,
    apms_csv_path: Optional[str] = None,
    checklist_path: Optional[str] = None,
    cfg: Optional[Config] = None,
    selected_tests: Optional[Set[int]] = None,
    filter_results: Optional[Set[Result]] = None,
    verbose: bool = False,
    include_json_data: bool = True,
) -> FullTestSuiteResult:
    """Run the full test suite against a system.

    Args:
        system_id: Target system identifier.
        apms_csv_path: Path to APMS CSV (defaults to ELS_system_match_preview.csv).
        checklist_path: Path to checklist Excel (defaults to static/DeepDiveTests.xlsx).
        cfg: Config object (auto-created if None).
        selected_tests: Set of specific test numbers to run (None = all).
        filter_results: Only include results matching these statuses in output.
        verbose: Print progress to stdout.
        include_json_data: Include full JSON data sources in result.

    Returns:
        FullTestSuiteResult with all execution data.
    """
    execution_start = datetime.now()

    # Setup paths
    if apms_csv_path is None:
        # Check common locations for APMS CSV
        default_csv = os.getenv("APMS_CSV", "ELS_system_match_preview.csv")
        module_dir = os.path.dirname(os.path.abspath(__file__))
        found = False
        for candidate in [
            default_csv,
            f"engine/{default_csv}",
            f"../engine/{default_csv}",
            os.path.join(module_dir, default_csv),  # Same dir as this module
        ]:
            if os.path.exists(candidate):
                apms_csv_path = candidate
                found = True
                break
        if not found:
            apms_csv_path = default_csv  # Will fail with clear error
    if checklist_path is None:
        checklist_path = "static/DeepDiveTests.xlsx"

    apms_csv_path = os.path.abspath(os.path.expanduser(apms_csv_path))
    checklist_path = os.path.abspath(os.path.expanduser(checklist_path))

    # Validate paths
    if not os.path.exists(apms_csv_path):
        raise FileNotFoundError(f"APMS CSV not found: {apms_csv_path}")
    if not os.path.exists(checklist_path):
        raise FileNotFoundError(f"Checklist not found: {checklist_path}")

    # Setup config
    if cfg is None:
        cfg = Config()
        cfg.configure_logging()
        cfg.validate_minimums()

    if verbose:
        print(f"\n{'='*60}")
        print(f"TECTIX Full Test Runner - System ID: {system_id}")
        print(f"{'='*60}")
        print(f"APMS CSV: {apms_csv_path}")
        print(f"Checklist: {checklist_path}")
        print(f"\nBuilding SystemContext...")

    # Build context
    ctx = build_context(cfg, system_id, apms_csv_path, checklist_path)
    system_name = ctx.system_name

    if verbose:
        print(f"System Name: {system_name or 'Unknown'}")
        print(f"\nDiscovering tests...")

    # Discover tests
    all_tests = discover_tests()

    # Filter to selected tests if specified
    if selected_tests:
        tests_to_run = {k: v for k, v in all_tests.items() if k in selected_tests}
    else:
        tests_to_run = all_tests

    total_tests = len(tests_to_run)
    if verbose:
        print(f"Found {len(all_tests)} tests, running {total_tests}")
        print(f"\n{'-'*60}")
        print("Running tests...")
        print(f"{'-'*60}\n")

    # Initialize result
    suite_result = FullTestSuiteResult(
        system_id=system_id,
        system_name=system_name,
        execution_start=execution_start,
        total_tests=total_tests,
    )

    # Extract context snapshot
    suite_result.context_snapshot = extract_context_snapshot(ctx)

    # Extract JSON data if requested
    if include_json_data:
        suite_result.json_data_sources = extract_json_data_sources(ctx)

    # Run each test
    for i, (test_num, test_fn) in enumerate(sorted(tests_to_run.items()), 1):
        exec_result = run_single_test_with_timing(test_fn, test_num, ctx)

        # Update counts
        if exec_result.error:
            suite_result.error_count += 1
        if exec_result.result == Result.PASS:
            suite_result.pass_count += 1
        elif exec_result.result == Result.FAIL:
            suite_result.fail_count += 1
        elif exec_result.result == Result.CONCERN:
            suite_result.concern_count += 1
        elif exec_result.result == Result.NA:
            suite_result.na_count += 1

        # Filter results if requested
        if filter_results is None or exec_result.result in filter_results:
            suite_result.results.append(exec_result)

        if verbose:
            status_symbol = {
                Result.PASS: "\033[92m[PASS]\033[0m",
                Result.FAIL: "\033[91m[FAIL]\033[0m",
                Result.CONCERN: "\033[93m[CONCERN]\033[0m",
                Result.NA: "\033[90m[N/A]\033[0m",
            }.get(exec_result.result, "[???]")

            print(f"  {i:3d}/{total_tests} | Test {test_num:3d} | {status_symbol} | {exec_result.message[:60]}")

    suite_result.execution_end = datetime.now()

    if verbose:
        print(f"\n{'-'*60}")
        print(f"SUMMARY: {suite_result.summary()}")
        print(f"Execution time: {suite_result.execution_time_seconds:.2f}s")
        print(f"{'='*60}\n")

    return suite_result


# -----------------------------------------------------------------------------
# Report Generation
# -----------------------------------------------------------------------------
def generate_json_report(result: FullTestSuiteResult, filepath: str) -> None:
    """Generate a JSON report file."""
    with open(filepath, "w") as f:
        json.dump(result.to_dict(), f, indent=2, default=str)
    logger.info("JSON report written to %s", filepath)


def generate_html_report(result: FullTestSuiteResult, filepath: str) -> None:
    """Generate an HTML report file with full details."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TECTIX Test Results - System {result.system_id}</title>
    <style>
        :root {{
            --pass-color: #28a745;
            --fail-color: #dc3545;
            --concern-color: #ffc107;
            --na-color: #6c757d;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
            padding: 20px;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        header {{
            background: linear-gradient(135deg, #1a237e, #3949ab);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 20px;
        }}
        header h1 {{ font-size: 2em; margin-bottom: 10px; }}
        header .meta {{ opacity: 0.9; font-size: 0.9em; }}
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .card {{
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            text-align: center;
        }}
        .card.pass {{ border-left: 4px solid var(--pass-color); }}
        .card.fail {{ border-left: 4px solid var(--fail-color); }}
        .card.concern {{ border-left: 4px solid var(--concern-color); }}
        .card.na {{ border-left: 4px solid var(--na-color); }}
        .card .value {{ font-size: 2.5em; font-weight: bold; }}
        .card .label {{ color: #666; font-size: 0.9em; }}
        .card.pass .value {{ color: var(--pass-color); }}
        .card.fail .value {{ color: var(--fail-color); }}
        .card.concern .value {{ color: var(--concern-color); }}
        .card.na .value {{ color: var(--na-color); }}
        .section {{
            background: white;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            overflow: hidden;
        }}
        .section-header {{
            background: #f8f9fa;
            padding: 15px 20px;
            border-bottom: 1px solid #eee;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .section-header h2 {{ font-size: 1.2em; }}
        .section-header .toggle {{ font-size: 1.5em; color: #666; }}
        .section-content {{ padding: 20px; }}
        .section-content.collapsed {{ display: none; }}
        .results-table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .results-table th, .results-table td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        .results-table th {{
            background: #f8f9fa;
            font-weight: 600;
        }}
        .results-table tr:hover {{ background: #f8f9fa; }}
        .status-badge {{
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: 600;
            text-transform: uppercase;
        }}
        .status-PASS {{ background: #d4edda; color: #155724; }}
        .status-FAIL {{ background: #f8d7da; color: #721c24; }}
        .status-CONCERN {{ background: #fff3cd; color: #856404; }}
        .status-NA {{ background: #e2e3e5; color: #383d41; }}
        .context-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 15px;
        }}
        .context-item {{
            background: #f8f9fa;
            padding: 10px 15px;
            border-radius: 5px;
        }}
        .context-item .key {{ font-weight: 600; color: #555; }}
        .context-item .value {{ color: #333; }}
        .json-viewer {{
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 0.85em;
            max-height: 500px;
            overflow-y: auto;
        }}
        .json-viewer pre {{ margin: 0; white-space: pre-wrap; }}
        .filter-bar {{
            display: flex;
            gap: 10px;
            margin-bottom: 15px;
            flex-wrap: wrap;
        }}
        .filter-btn {{
            padding: 8px 16px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 0.9em;
            transition: all 0.2s;
        }}
        .filter-btn:hover {{ opacity: 0.8; }}
        .filter-btn.active {{ box-shadow: 0 0 0 2px #333; }}
        .filter-btn.all {{ background: #333; color: white; }}
        .filter-btn.pass {{ background: var(--pass-color); color: white; }}
        .filter-btn.fail {{ background: var(--fail-color); color: white; }}
        .filter-btn.concern {{ background: var(--concern-color); color: #333; }}
        .filter-btn.na {{ background: var(--na-color); color: white; }}
        .search-box {{
            padding: 10px 15px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 0.9em;
            width: 250px;
        }}
        .test-detail {{
            margin-top: 10px;
            padding: 10px 15px;
            background: #f8f9fa;
            border-radius: 5px;
            display: none;
        }}
        .test-row.expanded .test-detail {{ display: block; }}
        .expand-btn {{
            background: none;
            border: none;
            cursor: pointer;
            font-size: 1.2em;
            color: #666;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>TECTIX RMF Compliance Test Results</h1>
            <div class="meta">
                <strong>System:</strong> {result.system_name or 'Unknown'} (ID: {result.system_id}) |
                <strong>Executed:</strong> {result.execution_start.strftime('%Y-%m-%d %H:%M:%S')} |
                <strong>Duration:</strong> {result.execution_time_seconds:.2f}s
            </div>
        </header>

        <div class="summary-cards">
            <div class="card">
                <div class="value">{result.total_tests}</div>
                <div class="label">Total Tests</div>
            </div>
            <div class="card pass">
                <div class="value">{result.pass_count}</div>
                <div class="label">Passed</div>
            </div>
            <div class="card fail">
                <div class="value">{result.fail_count}</div>
                <div class="label">Failed</div>
            </div>
            <div class="card concern">
                <div class="value">{result.concern_count}</div>
                <div class="label">Concerns</div>
            </div>
            <div class="card na">
                <div class="value">{result.na_count}</div>
                <div class="label">N/A</div>
            </div>
            <div class="card">
                <div class="value">{result.pass_rate:.1f}%</div>
                <div class="label">Pass Rate</div>
            </div>
        </div>

        <div class="section">
            <div class="section-header" onclick="toggleSection(this)">
                <h2>Test Results ({len(result.results)} tests)</h2>
                <span class="toggle">-</span>
            </div>
            <div class="section-content">
                <div class="filter-bar">
                    <button class="filter-btn all active" onclick="filterResults('all')">All</button>
                    <button class="filter-btn pass" onclick="filterResults('PASS')">Pass ({result.pass_count})</button>
                    <button class="filter-btn fail" onclick="filterResults('FAIL')">Fail ({result.fail_count})</button>
                    <button class="filter-btn concern" onclick="filterResults('CONCERN')">Concern ({result.concern_count})</button>
                    <button class="filter-btn na" onclick="filterResults('NA')">N/A ({result.na_count})</button>
                    <input type="text" class="search-box" placeholder="Search tests..." onkeyup="searchTests(this.value)">
                </div>
                <table class="results-table" id="resultsTable">
                    <thead>
                        <tr>
                            <th style="width: 50px;"></th>
                            <th style="width: 80px;">Test #</th>
                            <th style="width: 120px;">Status</th>
                            <th>Message</th>
                            <th style="width: 100px;">Time (ms)</th>
                        </tr>
                    </thead>
                    <tbody>
"""

    # Add test rows
    for r in result.results:
        html += f"""
                        <tr class="test-row" data-status="{r.result.value}" data-test="{r.test_number}" data-name="{r.test_name}">
                            <td><button class="expand-btn" onclick="toggleTestDetail(this)">+</button></td>
                            <td>{r.test_number}</td>
                            <td><span class="status-badge status-{r.result.value}">{r.result.value}</span></td>
                            <td>{r.message}</td>
                            <td>{r.execution_time_ms:.2f}</td>
                        </tr>
                        <tr class="test-detail-row" style="display:none;">
                            <td colspan="5">
                                <div class="test-detail">
                                    <strong>Test Name:</strong> {r.test_name}<br>
                                    <strong>Full Message:</strong> {r.message}<br>
                                    {f'<strong>Error:</strong> {r.error}<br>' if r.error else ''}
                                </div>
                            </td>
                        </tr>
"""

    html += """
                    </tbody>
                </table>
            </div>
        </div>

        <div class="section">
            <div class="section-header" onclick="toggleSection(this)">
                <h2>System Context Snapshot</h2>
                <span class="toggle">+</span>
            </div>
            <div class="section-content collapsed">
                <div class="context-grid">
"""

    # Add context items
    for key, value in result.context_snapshot.items():
        display_value = str(value) if value is not None else '<em>null</em>'
        html += f"""
                    <div class="context-item">
                        <span class="key">{key}:</span>
                        <span class="value">{display_value}</span>
                    </div>
"""

    html += """
                </div>
            </div>
        </div>

        <div class="section">
            <div class="section-header" onclick="toggleSection(this)">
                <h2>JSON Data Sources</h2>
                <span class="toggle">+</span>
            </div>
            <div class="section-content collapsed">
"""

    # Add JSON data sections
    for source_name, source_data in result.json_data_sources.items():
        json_str = json.dumps(source_data, indent=2, default=str)
        html += f"""
                <h3 style="margin: 15px 0 10px;">{source_name}</h3>
                <div class="json-viewer">
                    <pre>{json_str}</pre>
                </div>
"""

    html += """
            </div>
        </div>
    </div>

    <script>
        function toggleSection(header) {
            const content = header.nextElementSibling;
            const toggle = header.querySelector('.toggle');
            content.classList.toggle('collapsed');
            toggle.textContent = content.classList.contains('collapsed') ? '+' : '-';
        }

        function filterResults(status) {
            document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');

            document.querySelectorAll('.test-row').forEach(row => {
                const rowStatus = row.dataset.status;
                const detailRow = row.nextElementSibling;
                if (status === 'all' || rowStatus === status) {
                    row.style.display = '';
                    // Keep detail row hidden unless expanded
                } else {
                    row.style.display = 'none';
                    if (detailRow) detailRow.style.display = 'none';
                }
            });
        }

        function searchTests(query) {
            query = query.toLowerCase();
            document.querySelectorAll('.test-row').forEach(row => {
                const testNum = row.dataset.test;
                const testName = row.dataset.name.toLowerCase();
                const message = row.querySelector('td:nth-child(4)').textContent.toLowerCase();
                const detailRow = row.nextElementSibling;

                if (testNum.includes(query) || testName.includes(query) || message.includes(query)) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                    if (detailRow) detailRow.style.display = 'none';
                }
            });
        }

        function toggleTestDetail(btn) {
            const row = btn.closest('.test-row');
            const detailRow = row.nextElementSibling;
            if (detailRow.style.display === 'none') {
                detailRow.style.display = '';
                btn.textContent = '-';
            } else {
                detailRow.style.display = 'none';
                btn.textContent = '+';
            }
        }
    </script>
</body>
</html>
"""

    with open(filepath, "w") as f:
        f.write(html)
    logger.info("HTML report written to %s", filepath)


def print_terminal_report(result: FullTestSuiteResult, show_json: bool = False) -> None:
    """Print a detailed terminal report."""
    print(f"\n{'='*80}")
    print(f"TECTIX Full Test Suite Results")
    print(f"{'='*80}")
    print(f"System ID:   {result.system_id}")
    print(f"System Name: {result.system_name or 'Unknown'}")
    print(f"Executed:    {result.execution_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Duration:    {result.execution_time_seconds:.2f}s")
    print(f"\n{'-'*80}")
    print(f"SUMMARY")
    print(f"{'-'*80}")
    print(f"  Total Tests: {result.total_tests}")
    print(f"  \033[92mPASS:    {result.pass_count}\033[0m")
    print(f"  \033[91mFAIL:    {result.fail_count}\033[0m")
    print(f"  \033[93mCONCERN: {result.concern_count}\033[0m")
    print(f"  \033[90mN/A:     {result.na_count}\033[0m")
    print(f"  ERRORS:  {result.error_count}")
    print(f"  Pass Rate: {result.pass_rate:.1f}%")

    print(f"\n{'-'*80}")
    print(f"DETAILED RESULTS")
    print(f"{'-'*80}")

    for r in result.results:
        status_color = {
            Result.PASS: "\033[92m",
            Result.FAIL: "\033[91m",
            Result.CONCERN: "\033[93m",
            Result.NA: "\033[90m",
        }.get(r.result, "")
        reset = "\033[0m"

        print(f"\nTest {r.test_number}: {r.test_name}")
        print(f"  Status:  {status_color}{r.result.value}{reset}")
        print(f"  Message: {r.message}")
        print(f"  Time:    {r.execution_time_ms:.2f}ms")
        if r.error:
            print(f"  Error:   {r.error}")

    if show_json:
        print(f"\n{'-'*80}")
        print(f"SYSTEM CONTEXT SNAPSHOT")
        print(f"{'-'*80}")
        print(json.dumps(result.context_snapshot, indent=2, default=str))

        print(f"\n{'-'*80}")
        print(f"JSON DATA SOURCES")
        print(f"{'-'*80}")
        for name, data in result.json_data_sources.items():
            print(f"\n--- {name} ---")
            print(json.dumps(data, indent=2, default=str)[:2000])
            if len(json.dumps(data, default=str)) > 2000:
                print("... (truncated)")

    print(f"\n{'='*80}\n")


# -----------------------------------------------------------------------------
# CLI Main
# -----------------------------------------------------------------------------
def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="TECTIX Full Test Runner - Run all RMF compliance tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all tests for system 101
  python -m engine.full_test_runner --system-id 101

  # Run specific tests
  python -m engine.full_test_runner --system-id 101 --tests 1,2,3,10-20

  # Generate HTML report
  python -m engine.full_test_runner --system-id 101 --output html --report results.html

  # Show only failures
  python -m engine.full_test_runner --system-id 101 --filter fail

  # Generate JSON report with all data
  python -m engine.full_test_runner --system-id 101 --output json --report results.json
        """
    )

    parser.add_argument(
        "--system-id", "-s",
        type=int,
        required=True,
        help="Target system ID to test"
    )
    parser.add_argument(
        "--apms-csv",
        default=None,
        help="Path to APMS CSV file (auto-detected if not specified)"
    )
    parser.add_argument(
        "--checklist",
        default=None,
        help="Path to checklist Excel file (defaults to static/DeepDiveTests.xlsx)"
    )
    parser.add_argument(
        "--tests", "-t",
        help="Specific tests to run (e.g., '1,2,3,10-20')"
    )
    parser.add_argument(
        "--filter", "-f",
        choices=["pass", "fail", "concern", "na"],
        help="Filter results to show only specific status"
    )
    parser.add_argument(
        "--output", "-o",
        choices=["terminal", "html", "json"],
        default="terminal",
        help="Output format"
    )
    parser.add_argument(
        "--report", "-r",
        help="Output file path for html/json reports"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show progress during execution"
    )
    parser.add_argument(
        "--show-json",
        action="store_true",
        help="Include JSON data in terminal output"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Minimal output (just summary)"
    )

    args = parser.parse_args()

    # Parse test selection
    selected_tests = None
    if args.tests:
        try:
            selected_tests = parse_test_selection(args.tests)
        except ValueError as e:
            print(f"Error parsing test selection: {e}")
            return 2

    # Parse result filter
    filter_results = None
    if args.filter:
        filter_map = {
            "pass": {Result.PASS},
            "fail": {Result.FAIL},
            "concern": {Result.CONCERN},
            "na": {Result.NA},
        }
        filter_results = filter_map[args.filter]

    try:
        result = run_full_test_suite(
            system_id=args.system_id,
            apms_csv_path=args.apms_csv,
            checklist_path=args.checklist,
            selected_tests=selected_tests,
            filter_results=filter_results,
            verbose=args.verbose and args.output == "terminal",
            include_json_data=args.output != "terminal" or args.show_json,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 2
    except Exception as e:
        logger.exception("Test execution failed")
        print(f"Error: {e}")
        return 1

    # Generate output
    if args.output == "html":
        report_path = args.report or f"test_results_{args.system_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        generate_html_report(result, report_path)
        print(f"HTML report generated: {report_path}")
    elif args.output == "json":
        report_path = args.report or f"test_results_{args.system_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        generate_json_report(result, report_path)
        print(f"JSON report generated: {report_path}")
    else:
        if args.quiet:
            print(result.summary())
        else:
            print_terminal_report(result, show_json=args.show_json)

    # Return exit code based on failures
    if result.fail_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
