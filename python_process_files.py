# python_process_files.py
"""
Drop-in generator that now uses the engine's Python runner but still writes the
JSON/CSV/XLSX artifacts callers expect.

Artifacts created in `output_dir`:
  - latest_results.json
  - Checklist_<system_id>.csv
  - Checklist_<system_id>.xlsx  (sheet: Results)

Public functions (compat preserved):
  - generate_checklist(...) -> ChecklistArtifacts
  - run_scan_and_store(...)  -> str | None (unchanged behavior)
Also provided:
  - generate_checklist_status(...) -> ATOStatus
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Union
import os

import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from engine.config import Config
from datetime import datetime
from engine.test_runner_lib import run_all_tests_status as generate_checklist_status, list_available_tests
from models import ATOStatus, DataFramePayload, ChecklistArtifacts
from log_config import setup_logging
from db import store_scan_results
from typing import Callable
import threading

DEFAULT_TESTS_MODULE = "engine.tests"
DEFAULT_CHECKLIST_TEMPLATE = "engine/DeepDiveTests.xlsx" 
DEFAULT_APMS_CSV = "engine/ELS_system_match_preview.csv"


logger = setup_logging()

# ---------- helpers: JSON/CSV/XLSX artifacts --------------------------------

def _status_to_rows(
    status: ATOStatus,
    system_name: Optional[str] = None,
) -> List[Dict[str, Union[int, str]]]:
    """Flatten an ATOStatus into row dictionaries for JSON/CSV/XLSX output.

    This function is the single source of truth for the tabular representation
    of test results. Any column added here will flow through to:

      * latest_results.json
      * Checklist_<system_id>.csv
      * Checklist_<system_id>.xlsx
      * /api/summary/latest → Reporting UI → TestTable

    The intent is to mirror the fields on TestResult while also providing
    human-readable column names that work well in spreadsheets and the UI.

    Args:
        status: Aggregated ATOStatus object produced by the checklist engine.
            Must contain an iterable `results` of TestResult instances.
        system_name: Optional system display name. When provided, it is added
            as a column on each row to simplify downstream display and pivoting.

    Returns:
        A list of dictionaries where each dict represents a single test row.
        Keys are column names and values are restricted to `int` or `str` so
        that the payload is safe for JSON, CSV, and Excel serializers.
    """
    rows: List[Dict[str, Union[int, str]]] = []

    # NOTE:
    # - Keep "test_num" and "Result" stable: the frontend and some reports
    #   already assume these names.
    # - Also emit canonical, lower-case variants ("test_number", "result",
    #   "name", "message") to future-proof API and data processing.
    for test_result in status.results:
        # Normalize Result enum → plain string (e.g., "PASS", "FAIL", "CONCERN", "NA").
        if hasattr(test_result.result, "value"):
            result_str = str(test_result.result.value)
        else:
            result_str = str(test_result.result)

        # Base row: mirror all TestResult fields plus a few friendly aliases.
        row: Dict[str, Union[int, str]] = {
            # Numeric identifier: used by the UI for ordering and display.
            "test_num": int(test_result.test_number),
            "test_number": int(test_result.test_number),
            "Test Number": int(test_result.test_number),

            # Human-readable name of the test.
            "name": test_result.name,
            "Test Name": test_result.name,

            # Machine- and human-friendly result status.
            "result": result_str,
            "Result": result_str,

            # Explanation / context for why the test passed/failed/raised concern.
            "message": test_result.message,
            "Message": test_result.message,
        }

        # Attach system name (if known) so consumers can group/pivot without
        # relying on directory structure or separate metadata.
        if system_name:
            row["system_name"] = system_name
            row["System Name"] = system_name

        rows.append(row)

    return rows


def _write_csv(rows: List[Dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_xlsx_simple(rows: List[Dict], path: Path, sheet: str = "Results") -> None:
    """
    Simple results workbook for anyone who reads a flat sheet.
    We ALSO update the P-ISSM_Checklist template (see the function below).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name=sheet, index=False)


def _write_latest_json(rows: List[Dict], path: Path) -> None:
    """Atomically write the latest results JSON so readers never see a partial file.

    This is safe under concurrent writers to the *same directory* because each
    writer uses a unique temporary filename (pid + thread id) and then performs
    an atomic `os.replace` into ``path``.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Unique temp name per writer to avoid collisions in shared dirs.
    tmp_name = f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}"
    tmp_path = path.with_name(tmp_name)

    # Write to a temp file first
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())  # ensure contents are on disk

    # Atomic replace on POSIX (and works on modern Windows): never exposes partial file.
    os.replace(tmp_path, path)

def _sanitize_job_id_for_path(job_id: str) -> str:
    """Return a filesystem-safe directory name derived from a job_id.

    This function is intentionally conservative: it replaces common
    separator/unsafe characters with underscores and trims length so
    that a job_id like "policy:1" becomes "policy_1".

    Args:
        job_id: Raw job identifier (for example, "policy:1").

    Returns:
        A short, filesystem-safe string suitable for use as a single
        directory name component.
    """
    s = (job_id or "job").strip()
    if not s:
        s = "job"

    # Replace path separators and a few problematic characters.
    for ch in ("/", "\\", os.path.sep, os.path.altsep or "", ":", ";", " "):
        if ch:
            s = s.replace(ch, "_")

    # Collapse repeated underscores for readability.
    while "__" in s:
        s = s.replace("__", "_")

    # Guard against excessively long directory names.
    return s[:64]

#MOAR HELPERS-------------------
# --- Progress sink (job-scoped, optional) -----------------------------------


_progress_sinks: Dict[str, Callable[[str], None]] = {}

def register_progress_sink(job_id: str, writer: Callable[[str], None]) -> None:
    """
    Register a callback that accepts a single string line to be emitted for a given job_id.
    The callback can push to process_output[job_id], log, etc.
    """
    _progress_sinks[job_id] = writer

def _emit(job_id: str, line: str) -> None:
    """
    Best-effort emit of a progress line for SSE. Safe no-op if no sink registered.
    """
    try:
        cb = _progress_sinks.get(job_id)
        if cb and line:
            cb(line.rstrip("\r\n"))
    except Exception:
        pass

def unregister_progress_sink(job_id: str) -> None:
    """Remove the registered sink for a job_id (no-op if not present)."""
    try:
        _progress_sinks.pop(job_id, None)
    except Exception:
        pass

# ---------- P-ISSM_Checklist updater ----------------------------------------

def update_p_issm_checklist_from_status(
    *,
    checklist_template_path: Union[str, Path],
    output_xlsx_path: Union[str, Path],
    system_id: int,
    status: ATOStatus,
    system_name: Optional[str] = None,
    sheet_name: str = "P-ISSM_Checklist",
) -> Path:
    """
    Update the P-ISSM_Checklist worksheet in the provided template by writing the
    per-test 'Result' values in order (first test at the first data row).

    Behavior:
    - Locates the header row by scanning for both 'Package Review Check' and 'Result'.
    - Identifies the 'Result' column index based on that header row.
    - Writes each `TestResult.result` to the corresponding row below the header,
      one per test in ascending order of `test_num`.
    - Sets:
        B2 = system_id
        C5 = system_name (if provided)
    - Saves to `output_xlsx_path`.

    Notes:
    - This mirrors the old pipeline’s effect without needing cell JSON maps.
    - If the sheet or columns are missing, a clear error is raised.

    Returns:
        Path to the saved workbook.
    """
    checklist_template_path = Path(checklist_template_path)
    output_xlsx_path = Path(output_xlsx_path)
    output_xlsx_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        wb = load_workbook(checklist_template_path)
    except InvalidFileException as e:
        raise RuntimeError(f"Failed to load checklist template: {e}")
    except FileNotFoundError:
        raise FileNotFoundError(f"Checklist template not found: {checklist_template_path}")

    if sheet_name not in wb.sheetnames:
        raise KeyError(
            f"Worksheet '{sheet_name}' does not exist in template. "
            f"Available sheets: {', '.join(wb.sheetnames)}"
        )

    ws = wb[sheet_name]

    # Set ID/name “like before”
    ws["B2"] = system_id
    if system_name:
        ws["C5"] = system_name

    # Read the sheet with pandas to discover header and column indices robustly
    try:
        xls = pd.ExcelFile(checklist_template_path)
        if sheet_name not in xls.sheet_names:
            raise KeyError(f"Worksheet '{sheet_name}' missing in template file.")
        raw = pd.read_excel(checklist_template_path, sheet_name=sheet_name, header=None)
    except Exception as e:
        raise RuntimeError(f"Failed to read checklist sheet for structure detection: {e}")

    # Find header row: must include “Package Review Check” and “Result”
    header_row_idx = None
    for i in range(min(20, len(raw))):  # scan first 20 rows; adjust if needed
        row = raw.iloc[i].astype(str).str.strip()
        if row.str.contains("Package Review Check", case=False).any() and \
           row.str.contains("Result", case=False).any():
            header_row_idx = i
            break
    if header_row_idx is None:
        raise RuntimeError("Could not locate header row with 'Package Review Check' and 'Result' columns.")

    # Find the exact column for “Result”
    header_series = raw.iloc[header_row_idx].astype(str).str.strip()
    try:
        result_col_idx = int(header_series[header_series.str.lower() == "result"].index[0])
    except Exception:
        # Try case-insensitive contains if exact match fails
        matches = header_series[header_series.str.contains("^result$", case=False, regex=True)]
        if matches.empty:
            raise RuntimeError("Could not find 'Result' column on header row.")
        result_col_idx = int(matches.index[0])

    # First data row is header_row_idx + 1 (0-based -> Excel +1 later)
    first_data_row = header_row_idx + 2  # +1 for next row, +1 for Excel 1-based

    # Write results in ascending test_num order
    ordered = sorted(status.results, key=lambda r: int(getattr(r, "test_number", 0)))
    for offset, tr in enumerate(ordered):
        excel_row = first_data_row + offset
        excel_col = result_col_idx + 1  # openpyxl is 1-based columns
        ws.cell(row=excel_row, column=excel_col, value=str(tr.result))

    # Persist the updated workbook
    wb.save(output_xlsx_path)
    return output_xlsx_path


# ---------- public API: run + artifacts (drop-in) ---------------------------

# --- Back-compat shim for the Flask worker thread ---------------------------
# Old signature (positional) expected by /process route:
#   generate_checklist(job_id, system_id, data_path, json_path, job_dir, checklist_template)
#
# We adapt it to the new engine-backed implementation and still write json_path.
def generate_checklist(
    *,
    job_id: str,
    system_id: int,
    output_dir: Union[str, Path],
    cfg: Optional["Config"] = None,
    apms_csv_path: Union[str, Path] = DEFAULT_APMS_CSV,
    checklist_path: Union[str, Path] = DEFAULT_CHECKLIST_TEMPLATE,
    tests_module: str = DEFAULT_TESTS_MODULE,
    system_name: Optional[str] = None,
) -> Optional[ChecklistArtifacts]:
    """Run tests and emit JSON/CSV/XLSX artifacts; return artifact descriptor.

    This function remains backward-compatible: callers still receive a
    `ChecklistArtifacts` instance. The returned object now also contains
    `artifacts.status` (an `ATOStatus`) for consumers that want to persist
    directly without rebuilding status.

    Artifacts created in `output_dir`:
      * `latest_results.json`
      * `Checklist_<system_id>.csv`
      * `Checklist_<system_id>.xlsx`
      * `Checklist_<system_id>_PISSM.xlsx`

    Args:
      job_id: Job identifier used for grouping and traceability.
      system_id: Numeric system identifier under evaluation.
      output_dir: Directory where artifacts will be written.
      cfg: Optional engine configuration.
      apms_csv_path: Path to APMS CSV used for correlation.
      checklist_path: Path to the P-ISSM workbook template.
      tests_module: Dotted module path that exposes test functions.
      system_name: Optional display name override.

    Returns:
      ChecklistArtifacts | None: Artifact descriptor; None on engine failure.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    status = generate_checklist_status(
        system_id=system_id,
        cfg=cfg,
        apms_csv_path=str(apms_csv_path),
        checklist_path=str(checklist_path),
        tests_module=tests_module
    )
    if status is None:
        return None

    effective_system_name = getattr(status, "system_name", None) or system_name

    # Build rows once and write all artifacts.
    rows = _status_to_rows(status, system_name=effective_system_name)

    latest_json_path = output_dir / "latest_results.json"
    csv_path = output_dir / f"Checklist_{system_id}.csv"
    xlsx_simple_path = output_dir / f"Checklist_{system_id}.xlsx"
    xlsx_pissm_path = output_dir / f"Checklist_{system_id}_PISSM.xlsx"

    _write_latest_json(rows, latest_json_path)
    _write_csv(rows, csv_path)
    _write_xlsx_simple(rows, xlsx_simple_path)

    update_p_issm_checklist_from_status(
        checklist_template_path=checklist_path,
        output_xlsx_path=xlsx_pissm_path,
        system_id=system_id,
        status=status,
        system_name=effective_system_name,
    )

    # Payloads
    results_df = pd.DataFrame(rows)
    csv_payload = DataFramePayload.from_dataframe(
        pd.read_csv(csv_path), system_id=system_id, source=str(csv_path)
    )
    results_payload = DataFramePayload.from_dataframe(
        results_df, system_id=system_id, source=str(latest_json_path)
    )

    # (NEW) attach status for new callers; old callers ignore the extra field
    return ChecklistArtifacts(
        job_id=job_id,
        system_id=system_id,
        excel_path=str(xlsx_pissm_path),
        csv_payload=csv_payload,
        results_payload=results_payload,
        status=status,  # <--- important bit
    )




def run_scan_and_store(
    system_id: int,
    *,
    job_id: str,
    output_dir: Union[str, Path],
    cfg: Optional["Config"] = None,
    apms_csv_path: Union[str, Path] = DEFAULT_APMS_CSV,
    checklist_path: Union[str, Path] = DEFAULT_CHECKLIST_TEMPLATE,
    tests_module: str = DEFAULT_TESTS_MODULE,
    system_name: Optional[str] = None,
) -> Optional[str]:
    """Run the engine, write artifacts, and persist one scan run.

    This orchestrates the full pipeline:
      1) Execute the engine-backed checklist generator (JSON/CSV/XLSX).
      2) Retrieve the in-memory ``ATOStatus`` from artifacts (or rebuild once
         if missing).
      3) Persist a ``TestRun`` plus ``TestOutcome`` rows using the DB layer.

    Concurrency / filesystem layout:
      * ``output_dir`` is treated as a **base directory**.
      * Artifacts for a given (job_id, system_id) are written into:
            <output_dir>/<sanitized_job_id>/system_<system_id>/
        This avoids collisions when multiple workers share the same base and
        run different systems or policies concurrently.

    Behavior intentionally mirrors the previous implementation for argument
    shapes (stringified paths, same tests module), with added timing metadata
    and a defensive class-identity check so Pydantic v2 validation cannot fail.

    Args:
        system_id: Primary key of the system under test (SUT).
        job_id: External job identifier used for grouping/traceability.
        output_dir: Base directory where artifacts will be written. A per-run
            subdirectory is created under this path.
        cfg: Optional engine configuration object.
        apms_csv_path: Path to the APMS CSV used during checklist generation.
        checklist_path: Path to the P-ISSM workbook template used for output.
        tests_module: Dotted module path that exposes test functions.
        system_name: Optional friendly name stored with run metadata (not
            passed into the engine builder).

    Returns:
        The persisted ``run_id`` (UUID string) on success; otherwise ``None``.

    Side Effects:
        Writes artifacts into a derived per-run directory under ``output_dir``
        and inserts rows into the database.

    Logging:
        Exceptions are logged with context at ERROR and the function returns
        ``None``.

    Example:
        >>> run_scan_and_store(
        ...     system_id=101,
        ...     job_id="policy:1",
        ...     output_dir="/tmp/policy-runs",
        ...     apms_csv_path="/data/APMS.csv",
        ...     checklist_path="/templates/P-ISSM.xlsx",
        ...     tests_module="engine.tests",
        ...     system_name="Payments API (Prod)",
        ... )
        '8a1e7b34-4f5a-11ef-9c9d-0242ac120002'
    """

    # Derive a per-run working directory so concurrent workers do not collide.
    base_dir = Path(output_dir)
    job_dir_name = _sanitize_job_id_for_path(job_id)
    out_dir = base_dir / job_dir_name / f"system_{int(system_id)}"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Starting scan run (system_id=%s, job_id=%s, out_dir=%s)",
        system_id,
        job_id,
        out_dir,
    )

    started_at = datetime.utcnow()

    # 1) Generate artifacts using the same calling convention as compat.
    try:
        artifacts = generate_checklist(
            job_id=job_id,
            system_id=int(system_id),
            output_dir=out_dir,  # <-- per-run directory
            cfg=cfg,
            apms_csv_path=str(apms_csv_path),
            checklist_path=str(checklist_path),
            tests_module=tests_module,
        )
    except Exception as exc:
        logger.exception(
            "Checklist generation failed (system_id=%s, job_id=%s): %s",
            system_id,
            job_id,
            exc,
        )
        return None

    if artifacts is None:
        logger.error(
            "Checklist generation returned None (system_id=%s, job_id=%s)",
            system_id,
            job_id,
        )
        return None

    # 2) Obtain (or rebuild once) the in-memory ATOStatus the engine returns.
    status: Optional[ATOStatus] = getattr(artifacts, "status", None)
    if status is None:
        logger.warning(
            "Artifacts.status missing; rebuilding ATOStatus (system_id=%s, job_id=%s)",
            system_id,
            job_id,
        )
        try:
            status = generate_checklist_status(
                system_id=system_id,
                cfg=cfg,
                apms_csv_path=str(apms_csv_path),
                checklist_path=str(checklist_path),
                tests_module=tests_module,
            )
        except Exception as exc:
            logger.exception(
                "Failed to build ATOStatus (system_id=%s, job_id=%s): %s",
                system_id,
                job_id,
                exc,
            )
            return None

    if status is None:
        logger.error(
            "ATOStatus unavailable after generation (system_id=%s, job_id=%s)",
            system_id,
            job_id,
        )
        return None

    # Ensure Pydantic v2 model identity is the canonical models.ATOStatus.
    if not isinstance(status, ATOStatus):
        try:
            status = ATOStatus.model_validate(status.model_dump())  # type: ignore[attr-defined]
        except AttributeError:
            status = ATOStatus.model_validate(status)

    finished_at = datetime.utcnow()
    duration_seconds = max(0, int((finished_at - started_at).total_seconds()))

    # 3) Persist results. Keep run_meta focused; unknown keys land in metadata_json.
    run_meta: Dict[str, Any] = {
        "job_id": job_id,
        "scan_label": job_id,
        "system_name": system_name,
        "data_path": (
            str(getattr(getattr(artifacts, "results_payload", None), "source", "")) or None
        )
        or str(apms_csv_path),
        "excel_path": str(getattr(artifacts, "excel_path", "") or "") or None,
        "csv_path": (
            str(getattr(getattr(artifacts, "csv_payload", None), "source", "") or "") or None
        ),
        "started_at": started_at.isoformat() + "Z",
        "finished_at": finished_at.isoformat() + "Z",
        "duration_seconds": duration_seconds,
        # Optional breadcrumbs (db layer will tuck unknown keys into metadata_json).
        "environment": os.getenv("APP_ENV", "prod"),
        "script_version": os.getenv("TECTIX_VERSION"),
        "commit_hash": os.getenv("GIT_COMMIT_SHA"),
        # Optionally expose the working directory used, for debugging.
        "output_dir": str(out_dir),
    }

    try:
        run_id = store_scan_results(
            system_id=system_id,
            run_meta=run_meta,
            status=status,
        )
        logger.info(
            "Persisted scan results (system_id=%s, job_id=%s, run_id=%s, duration=%ss)",
            system_id,
            job_id,
            run_id,
            duration_seconds,
        )
        return run_id
    except Exception as exc:
        logger.exception(
            "Persisting scan results failed (system_id=%s, job_id=%s): %s",
            system_id,
            job_id,
            exc,
        )
        return None


def generate_checklist_compat(
    job_id: str,
    system_id: int,
    data_path: Union[str, Path],
    json_path: Union[str, Path],
    job_dir: Union[str, Path],
    checklist_template: Union[str, Path],
) -> Optional["ChecklistArtifacts"]:
    """
    Backward-compatible worker entry point for the `/process` route.

    This function bridges the legacy Flask workflow (which expects status lines
    in a global SSE buffer and artifacts written to a per-job directory) with
    the new engine-backed Python implementation. It emits the same progress
    strings the frontend already parses (e.g., "Test N: ...", "[SUCCESS] ...",
    "[DONE]"), runs the full test suite via `generate_checklist(...)`, and
    mirrors `latest_results.json` to the legacy path if required.

    Parameters
    ----------
    job_id : str
        Opaque job identifier used as the key for emitting progress lines and
        for locating the job's output directory.
    system_id : int
        Numeric system identifier used by the test engine and artifact file names.
    data_path : str | pathlib.Path
        Path to the uploaded APMS CSV used by the test engine.
    json_path : str | pathlib.Path
        Legacy JSON path; if different from `job_dir/latest_results.json`,
        the file is mirrored here for compatibility with older callers.
    job_dir : str | pathlib.Path
        Directory where all artifacts are written (JSON/CSV/XLSX).
    checklist_template : str | pathlib.Path
        Path to the P-ISSM checklist template workbook used to write results.

    Returns
    -------
    ChecklistArtifacts | None
        Structured artifact bundle on success; `None` if generation fails.

    Side Effects
    ------------
    - Emits progress lines via `_emit(job_id, ...)` for SSE consumers.
    - Writes `latest_results.json`, `Checklist_<system_id>.csv`, and
      `Checklist_<system_id>_PISSM.xlsx` into `job_dir`.
    - Optionally mirrors `latest_results.json` to `json_path` if they differ.
    - Always unregisters the job's progress sink in a `finally` block.

    Thread-safety & Concurrency
    ---------------------------
    - Designed to be run in a background thread per job.
    - Avoids mutable global state except the registered progress sink (which is
      cleaned up reliably in `finally`).

    Notes
    -----
    - Frontend contract preserved: exact messages and completion markers
      (`[SUCCESS] File ready at: ...` and `[DONE]`) are emitted.
    """
    # Normalize common path-like inputs
    data_path = Path(data_path)
    json_path = Path(json_path)
    job_dir = Path(job_dir)
    checklist_template = Path(checklist_template)

    # Announce start and basic context for the SSE stream.
    _emit(job_id, f"[INFO] Starting processing for system {system_id}...")
    _emit(job_id, "Deep Dive Testing: initializing engine context")

    try:
        # Optional: announce the discovered tests so /stream_summary can show progress.
        try:
            discovered = list_available_tests("engine.tests", hide_zero=True)
            for test_num, test_name in discovered.items():
                # The summary stream looks for "Test <num>: <desc>"
                _emit(job_id, f"Test {test_num}: {test_name}")
        except Exception:
            # Discovery failures should not fail the run; just continue silently.
            pass

        # Execute the engine-backed generation, which writes all artifacts to job_dir.
        artifacts = generate_checklist(
            job_id=job_id,
            system_id=int(system_id),
            output_dir=job_dir,
            apms_csv_path=str(data_path),
            checklist_path=str(checklist_template),
            tests_module="engine.tests",
        )

        if artifacts is None:
            _emit(job_id, "[ERROR] Checklist generation failed.")
            _emit(job_id, "[DONE]")
            return None

        # Mirror the reporting JSON to the legacy path if the caller expects it there.
        try:
            latest_json = job_dir / "latest_results.json"
            if latest_json.exists() and latest_json.resolve() != json_path.resolve():
                json_path.write_text(latest_json.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            # Mirroring is best-effort; do not fail the run on errors here.
            pass

        # Emit the exact success + completion markers that the SSE client expects.
        _emit(job_id, f"[SUCCESS] File ready at: {artifacts.excel_path}")
        _emit(job_id, "[DONE]")
        return artifacts

    finally:
        # Ensure the progress sink is always cleaned up (prevents memory growth).
        unregister_progress_sink(job_id)
