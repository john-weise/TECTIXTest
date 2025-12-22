# process_files.py
import io
import os
import json
import subprocess
from pathlib import Path
import pandas as pd
from openpyxl import load_workbook
from typing import List, Dict, Union, Optional
import re
from log_config import setup_logging
from openpyxl.utils.exceptions import InvalidFileException
import time
import math
import traceback
import numpy as np
# New: models for returning DataFrame payloads & artifacts
from models import DataFramePayload, ChecklistArtifacts
import csv
from db import store_scan_results

from datetime import datetime
import uuid
# setup logger
logger = setup_logging()


def _psq(v: Union[Path, str]) -> str:
    """PowerShell-safe single-quoted literal (escape single quotes by doubling)."""
    s = str(v)
    return s.replace("'", "''")


# ─── Shared state ─────────────────────────────────────
process_output: Dict[str, List[str]] = {}  # single source of truth


# Shared paths and state
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
WORKING_DIR = BASE_DIR / "working"
BUILD_DIR = BASE_DIR / "react_build"
WORKING_DIR.mkdir(exist_ok=True)
SCRIPTS_DIR = Path("/app/scripts")  # adjust if script lives elsewhere

def update_excel(checklist_path, data_path, system_id, output_dir, test_json_data):
    """
    Update the 'P-ISSM_Checklist' sheet with:
      - B2 = system_id
      - C5 = first value from the uploaded CSV (df.iloc[0, 0]) if present
      - All A1-style writes from test_json_data (list of {"Cell": "A1", "Value": ...})
        * Non-A1 entries (e.g., META_* or invalid addresses) are safely ignored.

    Returns the saved workbook path: output_dir / f"Checklist_{system_id}.xlsx"
    """
    # --- helpers ---
    import numpy as _np
    import pandas as _pd
    import re as _re

    def _to_plain(v):
        """Convert numpy/pandas scalars to plain Python types; leave other values as-is."""
        # Handle pandas NA / NaN
        try:
            # pd.isna works for numpy and pandas
            if _pd.isna(v):
                return None
        except Exception:
            pass

        # numpy scalar -> Python
        if isinstance(v, (_np.generic,)):
            return v.item()

        return v

    # Simple A1 matcher (A..ZZZ + 1..1048576); good enough for our use
    _A1_RE = _re.compile(r"^[A-Za-z]{1,3}\d{1,7}$")

    # --- load workbook ---
    try:
        wb = load_workbook(checklist_path)
    except InvalidFileException as e:
        raise RuntimeError(f"Failed to load workbook: {e}")

    sheet_name = "P-ISSM_Checklist"
    if sheet_name not in wb.sheetnames:
        available = ", ".join(wb.sheetnames)
        raise KeyError(f"Worksheet '{sheet_name}' does not exist. Available sheets: {available}")

    ws = wb[sheet_name]

    # B2 = system_id
    ws["B2"] = system_id

    # --- CSV read (with friendlier failure) ---
    try:
        df = pd.read_csv(data_path)
    except Exception as e:
        raise RuntimeError(f"Failed to read data CSV '{data_path}': {e}")

    if not df.empty:
        # use iloc with explicit row/col to avoid the FutureWarning on Series.__getitem__
        try:
            ws["C5"] = _to_plain(df.iloc[0, 0])
        except Exception as e:
            # don't fail the whole run over this; surface a clearer error instead
            raise RuntimeError(f"Failed to write first CSV value to C5: {e}")

    # --- Apply writes from test_json_data (only real A1 cells) ---
    # test_json_data is expected to be a list of dicts with keys 'Cell' and 'Value'
    for item in test_json_data or []:
        cell = item.get("Cell")
        value = item.get("Value")

        if cell is None or value is None:
            continue
        if not isinstance(cell, str):
            continue

        # Skip metadata and non-A1 coordinates (prevents META_* from crashing openpyxl)
        if cell.startswith("META_"):
            continue
        if not _A1_RE.match(cell):
            continue

        try:
            ws[cell] = _to_plain(value)
        except Exception as e:
            # match original behavior: raise with the offending cell address
            raise RuntimeError(f"Failed writing to cell {cell}: {e}")

    # --- Save output workbook ---
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"Checklist_{system_id}.xlsx"
    try:
        wb.save(output_path)
    except Exception as e:
        raise RuntimeError(f"Failed to save workbook: {e}")

    return output_path



def _json_like_to_df(obj):
    """
    Best-effort conversion of JSON-ish structures into a pandas DataFrame.
    Supports:
      - list[dict]
      - dict with 'rows' (and optional 'columns')
    Returns None if no tabular shape inferred.
    """
    import pandas as pd

    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return pd.DataFrame(obj)
    if isinstance(obj, dict) and "rows" in obj and isinstance(obj["rows"], list):
        if isinstance(obj.get("columns"), list):
            return pd.DataFrame(obj["rows"], columns=obj["columns"])
        return pd.DataFrame(obj["rows"])
    return None

def _parse_timespan_seconds(s: Optional[str]) -> Optional[float]:
    """
    Parse strings like 'HH:MM:SS' or 'HH:MM:SS.mmmmmm' (e.g., '00:00:41.6403817')
    into total seconds (float). Returns None if unparsable.
    """
    if not s:
        return None
    try:
        t = s.strip()
        if not t:
            return None
        hh, mm, ss = t.split(":")
        sec = float(ss)
        return int(hh) * 3600 + int(mm) * 60 + sec
    except Exception:
        return None

# --- Excel → JSON helpers ---------------------------------------------
def _find_header_row(df: pd.DataFrame, search_rows: int = 12) -> Optional[int]:
    """
    Locate the header row in P-ISSM_Checklist by scanning the first few rows
    for both 'Package Review Check' and 'Result'.
    """
    for i in range(min(search_rows, len(df))):
        row = df.iloc[i].astype(str).str.strip()
        if row.str.contains("Package Review Check", case=False).any() and \
           row.str.contains("Result", case=False).any():
            return i
    return None


def _parse_p_issm_checklist(xlsx_path: Path) -> pd.DataFrame:
    try:
        xls = pd.ExcelFile(xlsx_path)
        if "P-ISSM_Checklist" not in xls.sheet_names:
            return pd.DataFrame()

        raw = pd.read_excel(xlsx_path, sheet_name="P-ISSM_Checklist", header=None)
        hdr = _find_header_row(raw)
        if hdr is None:
            return pd.DataFrame()

        df = pd.read_excel(xlsx_path, sheet_name="P-ISSM_Checklist", header=hdr)

        rename_map = {
            "Tabs": "tabs",
            "Requirement": "requirement",
            "Package Type": "package_type",
            "Package Review Check": "test_description",
            "Result": "result",
            "Returnable for Rework?": "returnable",
            "ISSM Comment": "issm_comment",
            "ISSM Recommendation": "issm_recommendation",
            "Status": "status",
            "ISO/PM Evidence & Comments": "evidence",
        }
        df = df.rename(columns={str(c).strip(): rename_map.get(str(c).strip(), str(c).strip())
                                for c in df.columns})

        # Trim only strings – keep NaN as NaN
        for c in df.columns:
            df[c] = df[c].apply(lambda v: v.strip() if isinstance(v, str) else v)

        # Normalize common “empty” tokens to NaN
        df = df.replace({
            "": np.nan, "nan": np.nan, "NaN": np.nan,
            "NONE": np.nan, "None": np.nan,
            "NULL": np.nan, "Null": np.nan
})
        # Keep the useful columns that usually exist
        cols_keep = [c for c in [
            "tabs","requirement","package_type","test_description","result",
            "returnable","issm_comment","issm_recommendation","status","evidence"
        ] if c in df.columns]
        if not cols_keep:
            return pd.DataFrame()
        df = df[cols_keep]

        # Drop spacer/header rows: require some test signal
        mask_real = df["test_description"].notna() if "test_description" in df.columns else False
        if "result" in df.columns:
            mask_real = mask_real | df["result"].notna()
        df = df[mask_real]

        # Forward fill section columns so each row carries its section
        for c in ("tabs", "requirement"):
            if c in df.columns:
                df[c] = df[c].ffill()

        # Number tests in visible order
        df.insert(0, "test_num", range(1, len(df) + 1))
        return df.reset_index(drop=True)
    except Exception:
        return pd.DataFrame()




def _json_safe_records(df: pd.DataFrame) -> list:
    """
    Convert a DataFrame to list[dict] with JSON-safe values:
    - np.nan/NaN/NaT/Inf -> None
    """
    def safe(v):
        # leave strings as-is
        if isinstance(v, str):
            return v
        # pandas/np missing
        try:
            if pd.isna(v):
                return None
        except Exception:
            pass
        # floats: map infs
        if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
            return None
        return v

    out = []
    for rec in df.to_dict(orient="records"):
        out.append({k: safe(v) for k, v in rec.items()})
    return out
# --- NEW/UPDATED imports (top of file) ---
from dataclasses import dataclass, field
from typing import Any, Tuple

# --- Shared regexes at module scope ---
ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
ROW_RE  = re.compile(r"^([A-Z]+)(\d+)$")  # e.g., "G140" -> ("G", 140)


# --- Logging & preview utilities --------------------------------------------

def _strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)

@dataclass
class PSLogger:
    job_id: str
    output_dir: Path
    max_lines: int = 800
    out_lines: List[str] = field(default_factory=list)
    session_log: List[str] = field(default_factory=list)

    def __post_init__(self):
        # hook into global stream used by UI
        existing = process_output.get(self.job_id, [])
        self.out_lines = existing
        process_output[self.job_id] = existing

    def push(self, line: str) -> None:
        line = (line or "").rstrip("\r\n")
        if not line:
            return
        line = _strip_ansi(line)
        formatted = f"[PS] {line}"
        print(formatted, flush=True)
        self.out_lines.append(formatted)
        self.session_log.append(formatted)
        if len(self.out_lines) > self.max_lines:
            del self.out_lines[: len(self.out_lines) - self.max_lines]
        process_output[self.job_id] = self.out_lines.copy()

    def final(self, msg: Optional[str] = None) -> None:
        if msg:
            print(msg, flush=True)
            self.out_lines.append(msg)
            self.session_log.append(msg)
        process_output[self.job_id] = self.out_lines.copy()

    def write_failure_log(self) -> None:
        try:
            log_file = self.output_dir / f"{self.job_id}_powershell_failure.log"
            with open(log_file, "w", encoding="utf-8") as f:
                f.write("\n".join(self.session_log))
            logger.error(f"PowerShell run failed. Full log saved to: {log_file}")
        except Exception as e:
            logger.error(f"Failed to save PowerShell failure log: {e}")

    def df_preview(self, df: Optional[pd.DataFrame], rows: int = 5) -> str:
        try:
            if df is None:
                return "(df is None)"
            return json.dumps({
                "shape": [int(df.shape[0]), int(df.shape[1])],
                "columns": [str(c) for c in list(df.columns)[:50]],
                "head": df.head(rows).to_dict(orient="records"),
            }, ensure_ascii=False)
        except Exception as e:
            return f"<df_preview error: {e}>"

    def log_json_block(
        self,
        title: str,
        obj: Any,
        file_name: Optional[str] = None,
        max_items: int = 150,
        max_chars: int = 30000,
    ) -> None:
        """Pretty-print a safe preview of JSON into the live log."""
        try:
            meta = ""
            view = obj
            if isinstance(obj, list):
                meta = f"items={len(obj)}"
                if len(obj) > max_items:
                    view = obj[:max_items]
                    meta += f" (showing first {max_items})"
            elif isinstance(obj, dict):
                meta = f"keys={len(obj.keys())}"

            pretty = json.dumps(view, ensure_ascii=False, indent=2)
            truncated = False
            if len(pretty) > max_chars:
                pretty = pretty[:max_chars] + "\n... <truncated>"
                truncated = True

            header = f"[JSON] {title}"
            if meta:
                header += f" [{meta}]"
            if file_name:
                header += f" (file: {file_name})"
            self.push(header)
            for line in pretty.splitlines():
                self.push(line)
            if truncated:
                self.push(f"[JSON] (preview truncated to {max_chars} chars; open file for full contents)")
        except Exception as e:
            self.push(f"[WARN] Failed to pretty-print {title}: {e}")


# --- PowerShell helpers ------------------------------------------------------

def sanity_check_pwsh(log: PSLogger) -> bool:
    """Quick pwsh availability check."""
    try:
        t = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", "Write-Host 'hello-from-pwsh'"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", timeout=5,
        )
        log.push(f"(sanity) {t.stdout.strip()}")
        return True
    except Exception as e:
        log.final(f"[ERROR] pwsh sanity check failed: {e}")
        return False


def run_pwsh_and_capture(
    pwsh_cmd: List[str],
    log: PSLogger,
    startup_timeout: int = 30,
    inactivity_timeout: int = 240,
) -> Tuple[int, float]:
    """
    Spawn a pwsh process attached to a PTY, stream output to `log.push`,
    enforce startup/inactivity timeouts, and return (returncode, elapsed_seconds).
    """
    import select, errno, pty

    log.push("PowerShell launch initiated…")
    master_fd, slave_fd = pty.openpty()
    start_time = time.time()
    try:
        env = os.environ.copy()
        env["TERM"] = "xterm"
        env["PYTHONUNBUFFERED"] = "1"
        time.sleep(0.3)  # small breath to settle TTY

        proc = subprocess.Popen(
            pwsh_cmd,
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            text=False, env=env, close_fds=True,
        )
    except Exception as e:
        try:
            os.close(master_fd); os.close(slave_fd)
        except Exception:
            pass
        log.final(f"[ERROR] Failed to start PowerShell: {e}")
        return (255, 0.0)
    finally:
        try:
            os.close(slave_fd)
        except Exception:
            pass

    buf = b""
    last_output_time = start_time

    try:
        while True:
            r, _, _ = select.select([master_fd], [], [], 0.2)

            if master_fd in r:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError as oe:
                    if oe.errno in (errno.EIO, 5):
                        break  # PTY closed
                    raise
                if not chunk:
                    break
                buf += chunk
                buf = buf.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        decoded = line.decode("utf-8", errors="replace")
                    except Exception:
                        decoded = line.decode("latin-1", errors="replace")
                    log.push(decoded)
                    last_output_time = time.time()

            now = time.time()
            if now - start_time > startup_timeout and len(log.session_log) == 0:
                log.push("[ERROR] Script produced no output after startup timeout.")
                proc.terminate(); proc.wait()
                return (254, now - start_time)
            if len(log.session_log) > 0 and now - last_output_time > inactivity_timeout:
                log.push("[ERROR] Script hung after producing output (heartbeat timeout).")
                proc.terminate(); proc.wait()
                return (253, now - start_time)

            if proc.poll() is not None and not r:
                # drain any remaining bytes
                try:
                    while True:
                        chunk = os.read(master_fd, 4096)
                        if not chunk:
                            break
                        buf += chunk
                except OSError:
                    pass
                break
    finally:
        if buf:
            try:
                decoded = buf.decode("utf-8", errors="replace")
            except Exception:
                decoded = buf.decode("latin-1", errors="replace")
            if decoded:
                for line in decoded.splitlines():
                    log.push(line)
        try:
            os.close(master_fd)
        except Exception:
            pass
        proc.wait()

    rc = int(proc.returncode or 0)
    elapsed = time.time() - start_time
    log.push(f"PowerShell exited with code {rc}")
    return (rc, elapsed)


# --- Result/status derivation helpers ---------------------------------------

def _norm_status_from_text(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    t = str(s).strip().lower()
    if "pass" in t:
        return "PASS"
    if "fail" in t:
        return "FAIL"
    if "concern" in t or "manual" in t or "verify" in t or "warning" in t:
        return "CONCERN"
    if "not applicable" in t or "n/a" in t or t == "na":
        return "N/A"
    return None

def _cells_colG_to_row_status(cell_items: List[dict]) -> pd.DataFrame:
    """
    [{Cell:'G141', Value:'TEST RESULT: PASS ...'}, ...] -> DataFrame
    indexed by excel_row with columns: ['Result','Note'].
    """
    rows = {}
    for it in cell_items or []:
        cell = str(it.get("Cell") or "")
        m = ROW_RE.match(cell)
        if not m:
            continue
        col, row = m.group(1), int(m.group(2))
        if col != "G":
            continue
        val = it.get("Value")
        rows[row] = {
            "Result": _norm_status_from_text(val),
            "Note": None if val is None else str(val)
        }
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "excel_row"
    return df

def _add_excel_row_numbers_to_template(xlsx_path: Path) -> Tuple[pd.DataFrame, int]:
    """
    Parse P-ISSM_Checklist and add a 1-based 'excel_row' that matches real sheet rows.
    Returns (df, data_start_row).
    """
    raw = pd.read_excel(xlsx_path, sheet_name="P-ISSM_Checklist", header=None)
    hdr = _find_header_row(raw)
    if hdr is None:
        return pd.DataFrame(), 0
    df = _parse_p_issm_checklist(xlsx_path)
    if df.empty:
        return df, 0
    excel_header_row = hdr + 1       # Excel rows are 1-based
    data_start_row  = excel_header_row + 1
    df.insert(0, "excel_row", range(data_start_row, data_start_row + len(df)))
    return df, data_start_row


# --- JSON & results utilities ----------------------------------------------

def load_json_and_log(
    path: Path,
    title: str,
    log: PSLogger,
    *,
    optional: bool,
    preview_items: int = 150,
    preview_chars: int = 30000,
) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        log.log_json_block(title, obj, file_name=path.name,
                           max_items=preview_items, max_chars=preview_chars)
        return obj
    except Exception as e:
        if optional:
            log.push(f"[WARN] Optional JSON '{path.name}' missing/unreadable: {e}")
            return None
        log.final(f"[ERROR] Failed to load JSON '{path}': {traceback.format_exc()}")
        raise


def build_results_df(
    checklist_path: Path,
    cell_json: List[dict],
    log: PSLogger,
    *,
    log_each_drop: bool = True,                  # kept for signature compatibility
    max_drop_logs: Optional[int] = None,         # kept for signature compatibility
    elapsed_raw: Optional[str] = None,           # timing (string form, e.g., "00:00:41.64")
    elapsed_seconds: Optional[float] = None,     # timing (seconds as float)
    system_name: Optional[str] = None,           # <-- NEW: allow caller to pass item/system name
    **_ignored,                                     # <-- NEW: future-proof for any extra kwargs
) -> pd.DataFrame:
    """
    Build authoritative results_df = template ⨝ col-G results.

    RULES:
    - Do NOT drop or normalize rows based on NaN/NULL/empties.
    - Do NOT drop rows matching the explicit skip list (we only log them).
    - When the test description is empty, mark it with the literal
      'HELP I SHOULD BE DROPPPED' (for JSON/UI inspection).
    """
    SKIP_EXCEL_ROWS: set[int] = {
        46, 60, 62, 64, 66, 71, 74, 77, 89, 97,
        106, 109, 112, 117, 120, 122, 124, 130,
        157, 172, 175, 187, 197,
    }
    EXPECTED_FIRST_TEST_ROW = 5

    def _find_first_real_excel_row(xlsx: Path) -> Optional[int]:
        try:
            raw = pd.read_excel(xlsx, sheet_name="P-ISSM_Checklist", header=None)
        except Exception as e:
            log.push(f"[WARN] Unable to read raw sheet for calibration: {e}")
            return None

        hdr = _find_header_row(raw)
        if hdr is None:
            log.push("[WARN] Could not locate header row for calibration")
            return None

        header_row = raw.iloc[hdr].astype(str).str.strip()
        prc_matches = header_row[header_row.str.contains("Package Review Check", case=False, na=False)]
        if prc_matches.empty:
            log.push("[WARN] Could not find 'Package Review Check' column on header row for calibration")
            return None
        prc_idx = int(prc_matches.index[0])

        for i in range(hdr + 1, len(raw)):
            val = raw.iat[i, prc_idx]
            if pd.isna(val):
                continue
            if isinstance(val, str) and val.strip().lower() in {"", "nan"}:
                continue
            return i + 1  # Excel is 1-based
        return None

    try:
        # 1) Template with 'excel_row'
        try:
            template_df, data_start_row = _add_excel_row_numbers_to_template(checklist_path)
            log.push(f"[DF] template rows={len(template_df)} data_start_row={data_start_row} -> {log.df_preview(template_df)}")
        except Exception:
            log.push("[DF] ERROR parsing template_df")
            log.push(traceback.format_exc())
            template_df = pd.DataFrame()

        # 2) Col-G results from OutputJson
        try:
            colg_df = _cells_colG_to_row_status(cell_json)
            log.push(f"[DF] colG results rows={len(colg_df)} -> {log.df_preview(colg_df)}")
        except Exception:
            log.push("[DF] ERROR deriving colG status")
            log.push(traceback.format_exc())
            colg_df = pd.DataFrame()

        if template_df.empty:
            return pd.DataFrame()

        # 3) Merge on excel_row
        merged = template_df.merge(colg_df, how="left", left_on="excel_row", right_index=True)

        # Prefer normalized 'Result'; fallback to any existing 'result'
        if "Result" not in merged.columns and "result" in merged.columns:
            merged["Result"] = merged["result"]

        # 4) Calibrate line numbers
        first_real_excel = _find_first_real_excel_row(checklist_path)
        shift = (int(first_real_excel) - int(data_start_row)) if first_real_excel is not None \
                else (int(EXPECTED_FIRST_TEST_ROW) - int(data_start_row))
        merged["excel_row_cal"] = merged["excel_row"] + shift
        log.push(f"[ALIGN] data_start_row={data_start_row}, first_real_excel={first_real_excel}, applied shift={shift}")
        try:
            preview_map = (merged[["excel_row", "excel_row_cal", "test_description"]]
                           .head(10)
                           .rename(columns={"test_description": "Package Review Check"}))
            log.push(f"[ALIGN] preview map -> {json.dumps(preview_map.to_dict(orient='records'), ensure_ascii=False)}")
        except Exception:
            pass

        # 5) Build results payload (no dropping)
        picks: List[Tuple[str, str]] = []
        if "tabs" in merged.columns:
            picks.append(("Tabs", "tabs"))
        picks.append(("Package Review Check", "test_description"))
        picks.append(("Result", "Result"))  # PASS/FAIL/CONCERN/N/A

        results_df = pd.DataFrame({dst: merged[src] for (dst, src) in picks})

        # 6) Mark empty descriptions
        def _is_empty_desc(v) -> bool:
            if v is None:
                return True
            try:
                if pd.isna(v):
                    return True
            except Exception:
                pass
            return isinstance(v, str) and v.strip() in {"", "nan", "NaN", "NULL", "None"}

        empty_idx = [i for i, v in merged["test_description"].items() if _is_empty_desc(v)]
        if empty_idx:
            log.push(f"[NOTE] Found {len(empty_idx)} row(s) with empty Test Description (marked with 'HELP I SHOULD BE DROPPPED').")
            for j, i in enumerate(empty_idx[:20]):
                payload = {
                    "excel_row_uncal": int(merged.at[i, "excel_row"]) if "excel_row" in merged.columns else None,
                    "excel_row_cal": int(merged.at[i, "excel_row_cal"]) if "excel_row_cal" in merged.columns else None,
                    "requirement": merged.get("requirement", pd.Series([None])).iloc[i] if "requirement" in merged.columns else None,
                    "colG_Note": merged.get("Note", pd.Series([None])).iloc[i] if "Note" in merged.columns else None,
                }
                log.log_json_block(f"EMPTY description row idx={i}", payload, max_items=50, max_chars=4000)
            if len(empty_idx) > 20:
                log.push(f"[NOTE] ... {len(empty_idx) - 20} more empty-description rows not listed")
            results_df.loc[empty_idx, "Package Review Check"] = "HELP I SHOULD BE DROPPPED"

        # 7) Awareness-only: explicit skip list (retained)
        if "excel_row_cal" in merged.columns:
            in_skip = int(merged["excel_row_cal"].isin(SKIP_EXCEL_ROWS).sum())
            log.push(f"[NOTE] {in_skip} row(s) match the explicit skip list (retained as requested).")

        # 8) Attach meta (elapsed + system_name) to every row
        if elapsed_raw is not None or elapsed_seconds is not None:
            results_df["elapsed_seconds"] = elapsed_seconds
            results_df["elapsed_raw"] = elapsed_raw
            log.push(f"[META] Attached elapsed to results_df: raw='{elapsed_raw}', seconds={elapsed_seconds}")
        if system_name is not None:
            results_df["system_name"] = str(system_name)
            log.push(f"[META] Attached system_name='{system_name}' to results_df")

        # 9) Final preview
        log.push(f"[DF] results_df preview -> {log.df_preview(results_df)}")
        return results_df

    except Exception:
        log.push("[DF] ERROR building authoritative results_df")
        log.push(traceback.format_exc())
        return pd.DataFrame()




def write_results_ui_json(results_df: pd.DataFrame, output_dir: Path, log: PSLogger) -> Optional[Path]:
    """Persist latest_results.json (JSON-safe) and log a short preview."""
    try:
        results_ui_path = output_dir / "latest_results.json"
        if results_df is not None and not results_df.empty:
            # --- Patch: normalize "Result" for JSON display ---
            results_display = results_df.copy()
            if "Result" in results_display.columns:
                def _disp(v):
                    import math, pandas as pd
                    if v is None:
                        return "N/A"
                    try:
                        if isinstance(v, float) and (math.isnan(v)):
                            return "N/A"
                    except Exception:
                        pass
                    if isinstance(v, str) and not v.strip():
                        return "N/A"
                    return v
                results_display["Result"] = results_display["Result"].apply(_disp)

            safe_records = _json_safe_records(results_display)  # uses module-level helper
            with open(results_ui_path, "w", encoding="utf-8") as outf:
                json.dump(safe_records, outf, ensure_ascii=False, indent=2)
            log.push(f"[INFO] Reporting JSON written to: {results_ui_path}")
            log.log_json_block("latest_results.json (preview)", safe_records, file_name=results_ui_path.name,
                               max_items=50, max_chars=12000)
            return results_ui_path
        else:
            log.push("[WARN] No rows to publish to latest_results.json (results_df empty).")
            return None
    except Exception:
        log.push("[DF] ERROR writing latest_results.json")
        log.push(traceback.format_exc())
        return None


def loud_json_keys(title: str, obj: Any, log: PSLogger, *, sample_items: int = 3, max_chars: int = 1200) -> None:
    """VERY LOUD structure introspection: type, top-level keys/length, and sample nested keys."""
    def _short(s: str) -> str: return s if len(s) <= max_chars else s[:max_chars] + " …<truncated>"
    try:
        log.push(f"[BOZO] ===== HEY BOZO LOOK AT ME: {title} =====")
        if obj is None:
            log.push("[BOZO] (object is None)")
            return
        if isinstance(obj, dict):
            keys = list(obj.keys())
            keys_preview = ", ".join(map(str, keys[:40])) + (" …" if len(keys) > 40 else "")
            log.push(f"[BOZO] type=dict  keys={len(keys)}  -> {keys_preview}")
            for k in keys[:20]:
                v = obj[k]
                if isinstance(v, list):
                    log.push(f"[BOZO]   {k}: list(len={len(v)})")
                    if v and isinstance(v[0], dict):
                        sample_union = set()
                        for it in v[:sample_items]:
                            if isinstance(it, dict):
                                sample_union.update(it.keys())
                        preview = ", ".join(sorted(map(str, sample_union)))[:300]
                        log.push(f"[BOZO]     sample item keys: {preview}")
                elif isinstance(v, dict):
                    vk = list(v.keys())
                    preview = ", ".join(map(str, vk[:25])) + (" …" if len(vk) > 25 else "")
                    log.push(f"[BOZO]   {k}: dict(keys={len(vk)}) -> {preview}")
                else:
                    log.push(f"[BOZO]   {k}: {type(v).__name__} -> {_short(repr(v))}")
        elif isinstance(obj, list):
            log.push(f"[BOZO] type=list  len={len(obj)}")
            head = obj[:sample_items]
            for i, it in enumerate(head):
                if isinstance(it, dict):
                    k = list(it.keys())
                    preview = ", ".join(map(str, k[:40])) + (" …" if len(k) > 40 else "")
                    log.push(f"[BOZO]   item[{i}] dict(keys={len(k)}) -> {preview}")
                else:
                    log.push(f"[BOZO]   item[{i}] {type(it).__name__} -> {_short(repr(it))}")
        else:
            log.push(f"[BOZO] type={type(obj).__name__} -> {_short(repr(obj))}")
        # small pretty preview
        try:
            pretty = json.dumps(obj if not isinstance(obj, list) else obj[:sample_items], ensure_ascii=False, indent=2)
            log.push("[BOZO] preview:")
            for line in _short(pretty).splitlines():
                log.push(line)
        except Exception as e:
            log.push(f"[BOZO] (failed to pretty-print preview: {e})")
        log.push(f"[BOZO] ===== END {title} =====")
    except Exception as e:
        log.push(f"[BOZO] (introspection error: {e})")


def save_debug_json(obj: Any, path: Path, log: PSLogger, *, label: str) -> None:
    """Write a pretty JSON snapshot for eyeballing."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        log.push(f"[DEBUG] Saved {label} to: {path}")
    except Exception as e:
        log.push(f"[WARN] Could not save {label} ({path}): {e}")





HEADER_NAME_RE = re.compile(r"^(item\s*name|system\s*name|name)$", re.I)

def _clean_cell(v) -> str:
    if v is None:
        return ""
    s = str(v).strip().strip('"').strip("'")
    # squash repeated whitespace
    s = re.sub(r"\s+", " ", s)
    return s

def extract_item_name_from_csv(csv_path: Path, log=None) -> Optional[str]:
    """
    Return the first non-empty 'Item Name' from the CSV.
    Prefers a header that looks like Item Name/System Name/Name; else uses column C.
    """
    # --- Try pandas first (fast/flexible) ---
    try:
        df = pd.read_csv(
            csv_path,
            dtype=str,
            keep_default_na=False,  # don't turn empty strings into NaN
            na_values=[],           # be conservative about NA parsing
            engine="python",
        )

        # 1) Find a header we know
        col_hit = None
        for c in df.columns:
            if HEADER_NAME_RE.match(str(c).strip()):
                col_hit = c
                break

        series = None
        if col_hit is not None:
            series = df[col_hit]
            src = f"header '{col_hit}'"
        else:
            # 2) Fall back to column C (index 2) if present
            if df.shape[1] >= 3:
                series = df.iloc[:, 2]  # third column
                src = "column C"
            else:
                series = None
                src = None

        if series is not None:
            for raw in series.tolist():
                s = _clean_cell(raw)
                if s:
                    if log:
                        log.push(f"[META] Item Name detected from {src}: {s}")
                    return s

        if log:
            log.push("[WARN] Item Name not found via pandas scan; will try csv module fallback.")
    except Exception as e:
        if log:
            log.push(f"[WARN] pandas could not read CSV: {e}; trying csv module fallback.")

    # --- Fallback: stdlib csv reader ---
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        if not rows:
            if log:
                log.push("[WARN] CSV is empty.")
            return None

        # Detect header row (simple heuristic): if any cell matches our header regex
        header = rows[0]
        header_idx = None
        for i, h in enumerate(header):
            if HEADER_NAME_RE.match(_clean_cell(h)):
                header_idx = i
                break

        if header_idx is not None:
            # scan beneath header for first non-empty
            for r in rows[1:]:
                if header_idx < len(r):
                    s = _clean_cell(r[header_idx])
                    if s:
                        if log:
                            log.push(f"[META] Item Name detected from header '{header[header_idx]}': {s}")
                        return s
        else:
            # No recognizable header → use column C (index 2)
            for r in rows:
                if len(r) >= 3:
                    s = _clean_cell(r[2])
                    if s:
                        if log:
                            log.push(f"[META] Item Name detected from column C: {s}")
                        return s

        if log:
            log.push("[WARN] Could not find a non-empty Item Name in the CSV.")
        return None
    except Exception as e:
        if log:
            log.push(f"[ERROR] csv module failed to read CSV: {e}")
        return None

# --- Main orchestration -----------------------------------------------------

def generate_checklist(
    job_id: str,
    system_id: int,
    data_path: Path,
    json_output_path: Path,
    output_dir: Path,
    checklist_path: Path,
) -> Optional[ChecklistArtifacts]:
    """
    Orchestrates:
      1) Execute ATOaas.ps1 and capture logs.
      2) Load & pretty-print OutputJson/ResultsJson from script.
      3) Build authoritative results_df (template ⨝ col-G), attaching meta (elapsed time, system name).
      4) Save latest_results.json (UI payload).
      5) Update Excel and produce artifacts (CSV/Results DataFramePayloads).
    """
    log = PSLogger(job_id=job_id, output_dir=output_dir)

    try:
        # --- validation ---
        output_dir.mkdir(parents=True, exist_ok=True)
        json_output_path.parent.mkdir(parents=True, exist_ok=True)

        script = SCRIPTS_DIR / "ATOaas.ps1"
        if not script.exists():
            log.final(f"[ERROR] PowerShell script not found: {script}")
            return None
        if not data_path.exists():
            log.final(f"[ERROR] data CSV not found: {data_path}")
            return None
        if not checklist_path.exists():
            log.final(f"[ERROR] Checklist template not found: {checklist_path}")
            return None

        results_json_path = output_dir / f"{job_id}_results.json"

        # --- Extract Item/System Name from the uploaded CSV (for logging + later use) ---
        try:
            item_name = extract_item_name_from_csv(data_path, log=log)
        except Exception as e:
            item_name = None
            log.push(f"[WARN] extract_item_name_from_csv failed: {e}")

        # --- run PowerShell ---
        if not sanity_check_pwsh(log):
            return None

        pwsh_cmd = [
            "pwsh","-NoLogo","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass",
            "-File", str(script),
            "-SystemID", str(system_id),
            "-dataPath", str(data_path),
            "-OutputJson", str(json_output_path),
            "-ResultsJson", str(results_json_path),
            "-ChecklistPath", str(checklist_path),
            "-Verbose","-InformationAction","Continue",
        ]
        rc, elapsed = run_pwsh_and_capture(pwsh_cmd, log)
        if rc != 0:
            log.write_failure_log()
            log.final(f"[ERROR] PowerShell exited with code {rc}")
            return None

        # --- load script JSONs (log previews) ---
        try:
            cell_json = load_json_and_log(json_output_path, "OutputJson (cell map)", log, optional=False)
        except Exception:
            return None  # error already logged via load_json_and_log

        script_results = load_json_and_log(results_json_path, "ResultsJson (script table)", log, optional=True)

        # --- pull elapsedSeconds from ResultsJson and put it everywhere we need ---
        elapsed_raw = None
        elapsed_seconds = None
        if isinstance(script_results, dict):
            elapsed_raw = script_results.get("elapsedSeconds") or None
            try:
                elapsed_seconds = _parse_timespan_seconds(elapsed_raw)
            except Exception:
                elapsed_seconds = None
            if elapsed_raw:
                log.push(f"[META] ResultsJson.elapsedSeconds = '{elapsed_raw}' -> {elapsed_seconds}s")
                # make it part of the cell_json (won't affect col-G merge)
                try:
                    cell_json.append({"Cell": "META_ELAPSED", "Value": elapsed_raw})
                except Exception:
                    pass

        # --- also inject the system/item name into the cell_json for traceability ---
        if item_name:
            try:
                cell_json.append({"Cell": "META_SYSTEM_NAME", "Value": item_name})
            except Exception:
                pass

        # --- build results df & UI json (attach elapsed_* + system_name on each row) ---
        results_df = build_results_df(
            checklist_path,
            cell_json,
            log,
            elapsed_raw=elapsed_raw,
            elapsed_seconds=elapsed_seconds,
            system_name=item_name,       # <-- ensure build_results_df accepts this kwarg
        )
        results_ui_path = write_results_ui_json(results_df, output_dir, log)

        # --- update/save the run XLSX ---
        artifacts: Optional[ChecklistArtifacts] = None
        try:
            result_path = update_excel(checklist_path, data_path, system_id, output_dir, cell_json)
            log.push(f"[SUCCESS] File ready at: {result_path}")

            # CSV payload
            try:
                csv_df = pd.read_csv(data_path)
            except Exception as e:
                log.push(f"[WARN] Could not re-read CSV for DataFrame payload: {e}")
                csv_df = pd.DataFrame()
            csv_payload = DataFramePayload.from_dataframe(csv_df, system_id=system_id, source=str(data_path))

            results_payload = None
            if results_df is not None and not results_df.empty and results_ui_path:
                try:
                    results_payload = DataFramePayload.from_dataframe(
                        results_df, system_id=system_id, source=str(results_ui_path)
                    )
                except Exception:
                    log.push("[DF] ERROR creating DataFramePayload for results_df")
                    log.push(traceback.format_exc())

            artifacts = ChecklistArtifacts(
                job_id=job_id,
                system_id=system_id,
                excel_path=str(result_path),
                csv_payload=csv_payload,
                results_payload=results_payload,
            )
        except Exception:
            log.push(f"[ERROR] Excel update failed: {traceback.format_exc()}")
            artifacts = None
        finally:
            log.push(f"Elapsed time (pwsh run): {elapsed:.2f} seconds")
            log.final()
            return artifacts

    except Exception:
        log.final(f"[ERROR] Unhandled exception: {traceback.format_exc()}")
        return None




def df_keys_summary(
    df: Optional[pd.DataFrame],
    *,
    include_nested: bool = True,
    scan_rows: int = 5000,   # cap how many rows we scan for nested keys
) -> Dict[str, Any]:
    """
    Return a concise schema-like summary of a DataFrame's "keys".

    Returns:
      {
        "shape": [rows, cols],
        "columns": ["colA", "colB", ...],
        "dtypes": {"colA": "int64", "colB": "object", ...},
        "nested": {
            "col_with_dicts": ["inner_key1", "inner_key2", ...],
            ...
        }
      }

    Notes:
      - "columns" are the top-level DataFrame keys.
      - If include_nested=True, we scan up to `scan_rows` rows and build a
        union of dict-keys for any column whose cells contain dict-like values.
      - Safe for None/empty frames.
    """
    out: Dict[str, Any] = {
        "shape": [0, 0],
        "columns": [],
        "dtypes": {},
        "nested": {},
    }

    if df is None or getattr(df, "empty", True):
        return out

    try:
        out["shape"] = [int(df.shape[0]), int(df.shape[1])]
        cols = [str(c) for c in df.columns]
        out["columns"] = cols
        out["dtypes"] = {str(c): str(df[c].dtype) for c in df.columns}
    except Exception:
        # Be defensive—still return *something* even if df is weird
        try:
            out["columns"] = [str(c) for c in getattr(df, "columns", [])]
        except Exception:
            out["columns"] = []
        try:
            out["shape"] = [int(getattr(df, "shape", [0, 0])[0]), int(getattr(df, "shape", [0, 0])[1])]
        except Exception:
            out["shape"] = [0, 0]
        out["dtypes"] = {}
        # Don't attempt nested if basic metadata failed hard
        return out

    if include_nested:
        # For each column, if we see dict-like cells, union their keys
        max_rows = min(scan_rows, len(df))
        for col in df.columns:
            nested_keys: set = set()
            series = df[col].head(max_rows)
            for val in series:
                # Only harvest keys from mapping-like cells
                if isinstance(val, dict):
                    nested_keys.update(map(str, val.keys()))
                # Some pipelines may stash JSON strings—try a cheap parse
                elif isinstance(val, str) and val and (val.strip().startswith("{") and val.strip().endswith("}")):
                    try:
                        parsed = json.loads(val)
                        if isinstance(parsed, dict):
                            nested_keys.update(map(str, parsed.keys()))
                    except Exception:
                        pass
            if nested_keys:
                out["nested"][str(col)] = sorted(nested_keys)

    return out


def log_df_keys(df: Optional[pd.DataFrame], log: Optional[PSLogger] = None, *, title: str = "DataFrame keys") -> Dict[str, Any]:
    """
    Convenience wrapper: compute df_keys_summary and push a readable dump to PSLogger.
    Returns the same dict so caller can also use the data programmatically.
    """
    summary = df_keys_summary(df, include_nested=True)
    if log:
        try:
            log.push(f"[SCHEMA] {title}")
            log.push(f"[SCHEMA] shape = {summary['shape']}")
            log.push(f"[SCHEMA] columns ({len(summary['columns'])}): {', '.join(summary['columns'])}")
            if summary["dtypes"]:
                # show first ~30 entries, then ellipsis
                items = list(summary["dtypes"].items())
                preview = items[:30]
                rest = len(items) - len(preview)
                dtype_str = ", ".join(f"{k}:{v}" for k, v in preview)
                if rest > 0:
                    dtype_str += f", … (+{rest} more)"
                log.push(f"[SCHEMA] dtypes: {dtype_str}")
            if summary["nested"]:
                log.push("[SCHEMA] nested dict-keys by column:")
                for k in sorted(summary["nested"].keys()):
                    keys_list = summary["nested"][k]
                    head = ", ".join(keys_list[:30])
                    suffix = "" if len(keys_list) <= 30 else f", … (+{len(keys_list)-30} more)"
                    log.push(f"[SCHEMA]   {k}: {head}{suffix}")
        except Exception:
            # don't let logging derail caller
            pass
    return summary


def run_scan_and_store(system_id: int, apms_csv: Union[str, Path]) -> Optional[str]:
    """
    Run an APMS-driven scan for a specific system and persist its results.

    This is a thin orchestration layer that *reuses existing pipeline pieces*:
      1) Chooses a checklist template (env override via CHECKLIST_TEMPLATE_PATH, else defaults in ./static).
      2) Invokes the established PowerShell + Excel pipeline via `generate_checklist(...)`.
      3) Consumes the normalized payload that pipeline already writes to
         `<working>/<job_id>/latest_results.json`.
      4) Performs minimal normalization (status only) using `_norm_status_from_text`.
      5) Persists to the database with `store_scan_results(system_id, run_meta, results)`.

    Design notes / invariants:
      - Single source of truth: we only read the pipeline-produced JSON; we do not reparse CSV/XLSX here.
      - Idempotence-ish: `run_id` is a fresh UUID; callers must enforce higher-level idempotency if needed.
      - Logging: all errors are logged with the `[SCAN]` prefix.
      - Timekeeping: timestamps are UTC ISO8601 with trailing 'Z'.

    Parameters
    ----------
    system_id : int
        Primary key of the system under test.
    apms_csv : Union[str, Path]
        Path to the APMS CSV input consumed by the PowerShell pipeline.

    Returns
    -------
    Optional[str]
        The persisted `run_id` (UUID string) on success; `None` if any step fails.

    Side Effects
    ------------
    - Reads: `<working>/<job_id>/latest_results.json` produced by `generate_checklist(...)`.
    - Writes: Files under `<working>/<job_id>/` are created by the pipeline (not by this function).
    - DB write via `store_scan_results(...)`.

    Raises
    ------
    None explicitly; all exceptions are handled and logged, returning `None`.
    """
    # --- Stable timing & identity metadata (captured early for accurate durations) ---
    started_at_utc: datetime = datetime.utcnow()
    run_id: str = str(uuid.uuid4())
    job_id: str = f"scan-{system_id}-{int(time.time())}"

    # --- Input validation: ensure the CSV exists before invoking the heavy pipeline ---
    csv_path: Path = Path(apms_csv)
    if not csv_path.exists():
        logger.error(f"[SCAN] CSV not found: {csv_path}")
        return None

    # --- Resolve checklist template path (env override first, then sensible defaults) ---
    env_tpl = os.getenv("CHECKLIST_TEMPLATE_PATH")
    candidate_templates: List[Path] = [Path(env_tpl)] if env_tpl else []
    candidate_templates += [
        STATIC_DIR / "Checklist_101.xlsx",
        STATIC_DIR / "Checklist.xlsx",
        STATIC_DIR / "P-ISSM_Checklist.xlsx",
    ]
    checklist_path: Optional[Path] = next((p for p in candidate_templates if p and p.exists()), None)
    if checklist_path is None:
        logger.error("[SCAN] No checklist template found (set CHECKLIST_TEMPLATE_PATH or place one in ./static).")
        return None

    # --- Layout working directory for this job (pipeline writes artifacts here) ---
    output_dir: Path = WORKING_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    json_output_path: Path = output_dir / f"{job_id}_cells.json"  # consumed by pipeline; we don't read it here

    # --- Optional: derive a human-readable system/item name from the CSV (for metadata only) ---
    try:
        system_name: Optional[str] = extract_item_name_from_csv(csv_path, log=None)
    except Exception:
        system_name = None

    # --- Execute the established pipeline. This produces latest_results.json on success. ---
    artifacts = generate_checklist(
        job_id=job_id,
        system_id=system_id,
        data_path=csv_path,
        json_output_path=json_output_path,
        output_dir=output_dir,
        checklist_path=checklist_path,
    )
    if artifacts is None:
        logger.error("[SCAN] generate_checklist failed; nothing to store.")
        return None

    # --- Consume the normalized output produced by the pipeline ---
    latest_results_path: Path = output_dir / "latest_results.json"
    if not latest_results_path.exists():
        logger.error(f"[SCAN] Expected results JSON missing: {latest_results_path}")
        return None

    try:
        with open(latest_results_path, "r", encoding="utf-8") as f:
            rows_json = json.load(f)
    except Exception as e:
        logger.error(f"[SCAN] Could not read results JSON: {e}")
        return None

    # --- Minimal normalization for DB: preserve test order, normalize 'Result' only ---
    results_records: List[Dict[str, Optional[str]]] = []
    for idx, row in enumerate(rows_json):
        if not isinstance(row, dict):
            continue  # defensive: ignore junk/stray values
        raw_result = row.get("Result")
        normalized_result = _norm_status_from_text(raw_result) or (
            raw_result.strip() if isinstance(raw_result, str) else raw_result
        )
        results_records.append(
            {
                "test_num": idx + 1,
                "category": row.get("Tabs") or row.get("tabs") or None,
                "test_description": row.get("Package Review Check") or row.get("test_description") or None,
                "result": normalized_result,
                "result_raw": raw_result,
            }
        )

    # --- Duration: prefer pipeline-attached per-row elapsed, else wall-clock ---
    elapsed_seconds: Optional[float] = None
    try:
        for row in rows_json:
            if isinstance(row, dict) and row.get("elapsed_seconds") is not None:
                elapsed_seconds = float(row["elapsed_seconds"])
                break
    except Exception:
        elapsed_seconds = None

    finished_at_utc: datetime = datetime.utcnow()
    duration_seconds: int = (
        int(elapsed_seconds)
        if isinstance(elapsed_seconds, (int, float))
        else int((finished_at_utc - started_at_utc).total_seconds())
    )

    # --- Run-level metadata persisted alongside results for traceability/auditing ---
    run_meta: Dict[str, Union[str, int, None]] = {
        "run_id": run_id,
        "job_id": job_id,
        "started_at": started_at_utc.isoformat() + "Z",
        "finished_at": finished_at_utc.isoformat() + "Z",
        "duration_seconds": duration_seconds,
        "source_csv": str(csv_path),
        "system_name": system_name,
        "output_dir": str(output_dir),
        "latest_results_json": str(latest_results_path),
        "pipeline": "generate_checklist",  # explicitly document the execution path
    }

    # --- Persist to the database via the existing DAL hook ---
    try:
        stored_id = store_scan_results(system_id=system_id, run_meta=run_meta, results=results_records)
        if isinstance(stored_id, str) and stored_id:
            logger.info(f"[SCAN] Stored {len(results_records)} rows for system {system_id} (run_id={stored_id})")
            return stored_id
        # If the DAL doesn't return an id, fall back to the locally generated one.
        logger.info(f"[SCAN] Stored {len(results_records)} rows for system {system_id} (run_id={run_id})")
        return run_id
    except Exception as e:
        logger.error(f"[SCAN] store_scan_results failed: {e}")
        return None
