# tests.py
from __future__ import annotations

import csv
import datetime
import fnmatch
import inspect
import time
import logging
import os
import time as _time
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Iterable, TYPE_CHECKING
import re


from engine.helpers import (
    sys_row,
    apms_row,
    row_sys_id,
    apms_get_ci,
    normalize,
    epoch_to_ymd,
    to_bool_loose,
    is_test_function,
    test_number_from_name,
    run_discovered_tests,
    bool_to_yesno,
)

from engine.models import (
    ATOStatus,
    Result,
    TestResult,
    SystemContext,
)




# Module-scoped logger configured by config.configure_logging() at program start.
logger = logging.getLogger(__name__)


#------------------------------
#   Helpers
#------------------------------
def _to_bool_loose(v: object) -> Optional[bool]:
    """
    Best-effort boolean coercion for dirty source data.

    Accepts common truthy/falsy encodings from eMASS/APMS exports:
    - True / False
    - "Yes"/"No", "Y"/"N"
    - "1"/"0"
    - "true"/"false"
    Returns:
        True, False, or None if unknown/ambiguous.
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in {"true", "yes", "y", "1"}:
        return True
    if s in {"false", "no", "n", "0"}:
        return False
    return None


def _ci_get(row: dict, *keys: str) -> Any:
    """
    Case-insensitive getter across multiple candidate keys in a dict.

    Args:
        row: source dict (e.g. a row from a CSV or JSON dump).
        *keys: possible spellings / variants of the field.

    Returns:
        First non-None match if found, else None.
    """
    if not isinstance(row, dict):
        return None
    lowered = {str(k).lower(): v for k, v in row.items()}
    for k in keys:
        if k is None:
            continue
        v = lowered.get(k.lower())
        if v is not None:
            return v
    return None


def _apms_get_ci(ctx: SystemContext, *keys: str) -> Any:
    """
    Convenience: case-insensitive lookup into the APMS CSV first row
    that we stashed on the context as ctx.apms_first_row_raw.

    APMS CSV is authoritative for how the organization registered this
    system in APMS, so we use it to cross-check eMASS.
    """
    row = getattr(ctx, "apms_first_row_raw", None) or {}
    return _ci_get(row, *keys)


def _row_sys_id(row: dict) -> str:
    """
    Try to extract a 'system id'-like value from a generic row dict.
    Supports a bunch of common key spellings from different dumps.

    Returns:
        system id coerced to str, or "" if not found.
    """
    if not isinstance(row, dict):
        return ""
    return str(
        _ci_get(
            row,
            "System ID",
            "SystemID",
            "systemId",
            "system_id",
            "sysId",
            "id",
            "systemid",
        )
        or ""
    )


def _unwrap_data_like(obj: Any) -> Any:
    """
    If obj looks like {"data": [...]}, return that.
    Else just return obj.

    This mirrors the envelope style a lot of the JSON fixtures use.
    """
    if isinstance(obj, dict) and "data" in obj:
        return obj["data"]
    return obj


def _as_list_rows(obj: Any) -> list[dict]:
    """
    Normalize "whatever eMASS exported" into a list[dict].

    Handles:
    - already a list[dict]
    - {"data": [...rows...]}
    - {"114": {...}, "118": {...}} maps
    - single dict row
    """
    obj = _unwrap_data_like(obj)
    if obj is None:
        return []
    if isinstance(obj, list):
        return [r for r in obj if isinstance(r, dict)]
    if isinstance(obj, dict):
        # Map-of-id case or "just one row" case.
        # If values() are dicts, use those. Else treat the dict itself as a row.
        vals = [v for v in obj.values() if isinstance(v, dict)]
        if vals:
            return vals
        return [obj]
    return []


def _sys_row(ctx: SystemContext) -> dict:
    """
    Return the single 'SystemInfo-like' row for this system id as a dict.

    Why:
    Historically ctx carried a bunch of raw blobs like ctx.system_info_raw.
    After refactors, we still want a consistent way to say
    "give me the canonical eMASS SystemInfo row for THIS system".

    We try, in order:
    - ctx.system_info if it exists and looks like a dict/envelope.
    - ctx.system_info if it's already THE dict row.
    - fall back to {} if we can't find anything.

    This lets tests work regardless of whether SystemContext is the
    old dict-heavy shape or the newer Pydantic-backed shape.
    """
    # Newer builder: ctx.system_info might already be a dict row OR an envelope.
    blob = getattr(ctx, "system_info", None)

    # Older builder sometimes stored an envelope under ctx.system_info,
    # or even already gave filtered dicts. Normalize to first row.
    rows = _as_list_rows(blob)
    if rows:
        # If there are multiple rows, pick the one matching our ctx.system_id.
        want = str(getattr(ctx, "system_id", ""))
        hit = next((r for r in rows if _row_sys_id(r) == want), None)
        if hit:
            return hit
        return rows[0]

    # Sometimes ctx.system_info was already just one dict row, not a list/envelope.
    if isinstance(blob, dict):
        return blob

    # Last-ditch: build a dict view out of known top-level scalars on ctx.
    # This keeps tests from instantly dying if we have only flattened fields.
    fallback = {
        "authorizationStatus": getattr(ctx, "authorization_status", None),
        "authTerminationDate": None,
        "hasCUI": getattr(ctx, "cui", None),
        "hasPII": getattr(ctx, "pii", None),
        "hasPHI": getattr(ctx, "phi", None),
        "isNSS": getattr(ctx, "nss", None),
        "isPublicFacing": getattr(ctx, "pii", None),  # best-effort; may be None
        "whitelistId": None,
        "whitelistInventory": None,
        "highestSystemDataClassification": getattr(ctx, "classification", None),
        "missionCriticality": getattr(ctx, "mission_criticality", None),
        "systemType": getattr(ctx, "system_type", None),
        "versionReleaseNo": getattr(ctx, "system_version", None),
        "name": getattr(ctx, "system_name", None),
        "acronym": getattr(ctx, "system_acronym", None),
        "description": getattr(ctx, "system_description", None),
        "confidentiality": getattr(ctx, "confidentiality", None),
        "integrity": getattr(ctx, "integrity", None),
        "availability": getattr(ctx, "availability", None),
        "rmfActivity": getattr(ctx, "rmf_activity", None),
        "cloudComputing": getattr(ctx, "cloud_computing", None),
        "cloudType": getattr(ctx, "cloud_type", None),
        "isSaaS": getattr(ctx, "is_saas", None),
        "isPaaS": getattr(ctx, "is_paas", None),
        "isIaaS": getattr(ctx, "is_iaas", None),
        "otherServiceModels": getattr(ctx, "other_service_models", None),
        "isFinancialManagement": getattr(ctx, "fms", None),
        "isReciprocity": None,  # not always bubbled up
        "isPublicFacing": None,  # not always bubbled up
        "whitelistId": None,
        "whitelistInventory": None,
        "hasPII": getattr(ctx, "pii", None),
        "hasPHI": getattr(ctx, "phi", None),
        "hasCUI": getattr(ctx, "cui", None),
    }
    return fallback


def _first_match_for_system(rows: list[dict], ctx: SystemContext) -> dict:
    """
    From a list of row dicts (like ctx.system_status_details), return
    the row whose system ID matches ctx.system_id. If none match,
    return {}.
    """
    want = str(getattr(ctx, "system_id", ""))
    for r in rows or []:
        if _row_sys_id(r) == want:
            return r
    return {}


# -----------------------------
# Individual compliance tests
# -----------------------------
def test_1(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 1 — Assess Only approval path.

    Behavior (parity with PowerShell)
    ---------------------------------
    • If Registration Type clearly indicates **A&A** (not Assess Only) → **N/A**.
    • If system is **IS Major System** → **FAIL** (cannot be Assess Only).
    • If not major system:
        - Mission **Critical**  → **FAIL** (cannot be Assess Only).
        - Mission **Essential** → **PASS** only if C/I/A all **Low**, else **FAIL**.
        - Mission **Support**   → **PASS** if none of C/I/A is **High**, else **FAIL**.
        - Missing mission criticality → **CONCERN**.
        - Unrecognized mission criticality text → **CONCERN**.

    Inputs (tolerant of fixture shapes)
    -----------------------------------
    Registration Type: ctx.registration_type
                       or ctx.system_info.registrationtype
                       or ctx.system_details_dashboard.registration_type
    System Type:       ctx.system_type
                       or ctx.system_info.systemtype
                       or ctx.system_details_dashboard.system_type
    Mission Crit.:     ctx.mission_criticality
    CIA:               ctx.confidentiality / ctx.integrity / ctx.availability
    """
    test_number = 1
    test_name = "Test 1: Assess Only Approval Path"
    logger.debug("[T001] Running %s", test_name)

    # --- Gather/normalize inputs in-place (no helpers) ---
    reg_type_raw = ""
    for candidate in (
        getattr(ctx, "registration_type", None),
        getattr(getattr(ctx, "system_info", None) or object(), "registrationtype", None),
        getattr(getattr(ctx, "system_details_dashboard", None) or object(), "registration_type", None),
    ):
        if candidate and str(candidate).strip():
            reg_type_raw = str(candidate).strip()
            break
    reg_type_norm = reg_type_raw.lower()

    system_type_raw = ""
    for candidate in (
        getattr(ctx, "system_type", None),
        getattr(getattr(ctx, "system_info", None) or object(), "systemtype", None),
        getattr(getattr(ctx, "system_details_dashboard", None) or object(), "system_type", None),
    ):
        if candidate and str(candidate).strip():
            system_type_raw = str(candidate).strip()
            break
    system_type_norm = system_type_raw.lower()

    mc_norm = (getattr(ctx, "mission_criticality", None) or "").strip().lower()
    c_norm = (getattr(ctx, "confidentiality", None) or "").strip().lower()
    i_norm = (getattr(ctx, "integrity", None) or "").strip().lower()
    a_norm = (getattr(ctx, "availability", None) or "").strip().lower()

    logger.debug(
        "[T001] Inputs: reg_type_raw='%s' reg_type_norm='%s' system_type='%s' mc='%s' C/I/A=%s/%s/%s",
        reg_type_raw, reg_type_norm, system_type_norm, mc_norm, c_norm, i_norm, a_norm
    )

    # --- N/A when NOT Assess Only (explicit A&A or synonyms) ---
    if reg_type_raw and any(
        key in reg_type_norm
        for key in (
            "assess and authorize", "assess & authorize", "a&a", "a & a",
            "assess/authorize", "assess-authorize"
        )
    ):
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.NA,
            message="Test is not applicable (Not Assess Only)",
        )
        status.add(tr)
        logger.info("[T001] N/A: registration type indicates A&A → %s", reg_type_raw)
        return tr

    # --- Major system restriction ---
    if "is major system" in system_type_norm:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="Major System cannot be Assess Only",
        )
        status.add(tr)
        logger.error("[T001] FAIL: major system cannot be Assess Only")
        return tr

    # --- Mission Criticality branches ---
    if "critical" in mc_norm:  # Mission Critical
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="Mission Critical System cannot be Assess Only",
        )
        status.add(tr)
        logger.error("[T001] FAIL: Mission Critical cannot be Assess Only")
        return tr

    if "essential" in mc_norm:  # Mission Essential
        if c_norm == "low" and i_norm == "low" and a_norm == "low":
            tr = TestResult(
                test_number=test_number,
                name=test_name,
                result=Result.PASS,
                message="CIA levels match mission criticality (all Low)",
            )
            status.add(tr)
            logger.info("[T001] PASS: Essential + CIA all Low")
            return tr
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="CIA levels must be Low for Mission Essential system to be Assess Only",
        )
        status.add(tr)
        logger.error("[T001] FAIL: Essential requires CIA all Low")
        return tr

    if "support" in mc_norm:  # Mission Support
        if c_norm == "high" or i_norm == "high" or a_norm == "high":
            tr = TestResult(
                test_number=test_number,
                name=test_name,
                result=Result.FAIL,
                message="CIA levels must be Medium or Low for Mission Support system to be Assess Only",
            )
            status.add(tr)
            logger.error("[T001] FAIL: Support has a High CIA value")
            return tr
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.PASS,
            message="CIA levels match mission criticality (no High values)",
        )
        status.add(tr)
        logger.info("[T001] PASS: Support with no High CIA values")
        return tr

    # Missing or unrecognized mission criticality
    if mc_norm == "":
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.CONCERN,
            message="Unable to complete test: Mission Criticality not defined",
        )
        status.add(tr)
        logger.warning("[T001] CONCERN: mission criticality missing")
        return tr

    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.CONCERN,
        message=f"Unrecognized mission criticality: '{getattr(ctx, 'mission_criticality', None)}'",
    )
    status.add(tr)
    logger.warning(
        "[T001] CONCERN: unrecognized mission criticality '%s'",
        getattr(ctx, "mission_criticality", None),
    )
    return tr


def test_2(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Validate workflow naming convention for the active RMF workflow.

    Behavior:
      * If there are no active workflows (equivalent to `$WorkFlowData.data -eq $null`),
        the test is marked N/A with:
            "Test is not applicable: System has no active workflows"
      * Otherwise, the workflow name must match one of the allowed patterns:

            ConMon <ACR> - Initial
            ConMon <ACR> - Ongoing
            ATC <ACR> - Initial
            ATC <ACR> - Ongoing
            ConMon and ATC <ACR> - Initial
            ConMon and ATC <ACR> - Ongoing

        If a pattern matches, the test passes with a type-specific message
        (ConMon, ATC, or ConMon and ATC). If no pattern matches, the test fails with:
            "Test Failed: WorkFlow Naming convention is not correct or could not
             be verified: <workflow_name>"

    Args:
        ctx: Fully-populated system context snapshot, including workflow metadata.
        status: Aggregator that collects and counts test results.

    Returns:
        TestResult: Outcome of Test 2 (PASS, FAIL, or NA).
    """
    test_number = 2
    test_name = "Test 2: Workflow title has the correct Naming Convention"
    logger.debug("[T002] Running %s", test_name)

    workflows = ctx.workflows
    workflow_data = workflows.data if workflows is not None else None

    # N/A: no active workflows
    if not workflow_data:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.NA,
            message="Test is not applicable: System has no active workflows",
        )
        status.add(tr)
        logger.info("[T002] N/A — System has no active workflows")
        return tr

    workflow_name = ctx.workflow_name or ""
    system_acr = ctx.system_acronym or ""
    logger.debug(
        "[T002] Evaluating workflow_name=%r with system_acronym=%r",
        workflow_name,
        system_acr,
    )

    # Exact parity with the original branching:
    if (
        workflow_name == f"ConMon {system_acr} - Initial"
        or workflow_name == f"ConMon {system_acr} - Ongoing"
    ):
        message = "Test Passed: ConMon has the correct naming convention"
        result = Result.PASS

    elif (
        workflow_name == f"ATC {system_acr} - Initial"
        or workflow_name == f"ATC {system_acr} - Ongoing"
    ):
        message = "Test Passed: ATC has the correct naming convention"
        result = Result.PASS

    elif (
        workflow_name == f"ConMon and ATC {system_acr} - Initial"
        or workflow_name == f"ConMon and ATC {system_acr} - Ongoing"
    ):
        message = "Test Passed: ConMon and ATC has the correct naming convention"
        result = Result.PASS

    else:
        message = (
            "Test Failed: WorkFlow Naming convention is not correct or could not be "
            f"verified: {workflow_name}"
        )
        result = Result.FAIL

    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=result,
        message=message,
    )
    status.add(tr)

    if result == Result.PASS:
        logger.info("[T002] PASS — %s", workflow_name)
    else:
        logger.error("[T002] FAIL — %s", workflow_name)

    return tr



def test_3(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 3: eMASS 'System Name' matches APMS 'Item Name'.

    NOTES:
    - Requires both values:
        - eMASS system name (ctx.system_name)
        - APMS Item Name (ctx.apms_item_name)
    - Exact, case-sensitive comparison (mirrors typical governance checks).
    - If eMASS name is missing → FAIL (authoritative source missing).
    - If APMS name is missing → CONCERN (cannot validate).
    - PASS when names match exactly, otherwise FAIL with both values echoed.
    """
    test_name = "Test 3: eMASS System Name matches APMS Item Name"
    logger.debug("Running %s", test_name)

    emass_name = (ctx.system_name or "").strip()
    apms_name = (ctx.apms_item_name or "").strip()
    logger.debug("eMASS name='%s', APMS name='%s'", emass_name, apms_name)

    if not emass_name:
        tr = TestResult(
            test_number=3,
            name=test_name,
            result=Result.FAIL,
            message="eMASS system name is not defined.",
        )
        status.add(tr)
        logger.error("%s → %s (%s)", test_name, tr.result, tr.message)
        return tr

    if not apms_name:
        tr = TestResult(
            test_number=3,
            name=test_name,
            result=Result.CONCERN,
            message="APMS Item Name is not available; cannot validate match.",
        )
        status.add(tr)
        logger.warning("%s → %s (%s)", test_name, tr.result, tr.message)
        return tr

    if emass_name == apms_name:
        tr = TestResult(
            test_number=3,
            name=test_name,
            result=Result.PASS,
            message=f"Names match: '{emass_name}'.",
        )
        status.add(tr)
        logger.info("%s → %s (%s)", test_name, tr.result, tr.message)
        return tr

    tr = TestResult(
        test_number=3,
        name=test_name,
        result=Result.FAIL,
        message=f"Names do not match. eMASS='{emass_name}', APMS='{apms_name}'.",
    )
    status.add(tr)
    logger.error("%s → %s (%s)", test_name, tr.result, tr.message)
    return tr


def test_4(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 4: eMASS 'Acronym' matches APMS 'Acronym'.

    NOTES:
    - Requires both values:
        - eMASS acronym (ctx.system_acronym)
        - APMS acronym (ctx.apms_acronym)
    - Exact, case-sensitive comparison.
    - If eMASS acronym is missing → FAIL.
    - If APMS acronym is missing → CONCERN.
    - PASS when acronyms match exactly; otherwise FAIL and echo both values.
    - The original PowerShell snippet appears to mark PASS in the mismatch branch;
      that looks like a bug. Here we treat mismatch as FAIL (best practice).
    """
    test_name = "Test 4: eMASS Acronym matches APMS Acronym"
    logger.debug("Running %s", test_name)

    emass_acronym = (ctx.system_acronym or "").strip()
    apms_acronym = (ctx.apms_acronym or "").strip()
    logger.debug("eMASS acronym='%s', APMS acronym='%s'", emass_acronym, apms_acronym)

    if not emass_acronym:
        tr = TestResult(
            test_number=4,
            name=test_name,
            result=Result.FAIL,
            message="eMASS system acronym is not defined.",
        )
        status.add(tr)
        logger.error("%s → %s (%s)", test_name, tr.result, tr.message)
        return tr

    if not apms_acronym:
        tr = TestResult(
            test_number=4,
            name=test_name,
            result=Result.CONCERN,
            message="APMS acronym is not available; cannot validate match.",
        )
        status.add(tr)
        logger.warning("%s → %s (%s)", test_name, tr.result, tr.message)
        return tr

    if emass_acronym == apms_acronym:
        tr = TestResult(
            test_number=4,
            name=test_name,
            result=Result.PASS,
            message=f"Acronyms match: '{emass_acronym}'.",
        )
        status.add(tr)
        logger.info("%s → %s (%s)", test_name, tr.result, tr.message)
        return tr

    tr = TestResult(
        test_number=4,
        name=test_name,
        result=Result.FAIL,
        message=f"Acronyms do not match. eMASS='{emass_acronym}', APMS='{apms_acronym}'.",
    )
    status.add(tr)
    logger.error("%s → %s (%s)", test_name, tr.result, tr.message)
    return tr
def test_5(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 5 — Connection point(s) details provided (if applicable).

    Behavior (parity with PowerShell)
    ---------------------------------
    • If Connectivity/CCSD text is missing/empty  → CONCERN ("Connection Points are not provided").
    • Otherwise                                   → PASS and echo the connectivity type.

    Data sources (in order; no raw_payloads access)
    ------------------------------------------------
    1) ctx.connectivity_ccsd_connectivity  → str precomputed during context build.
    2) ctx.system_info.connectivityccsd    → optional list/dict/string from SystemInfo;
       scan for the first item where key "Connectivity" (case-insensitive) is a non-empty str.

    Notes
    -----
    • Values are trimmed; only non-empty strings count as provided.
    • Logging uses concise “[T005] …” tags.
    """

    test_number = 5
    test_name = "Test 5: Connection point(s) details provided (if applicable)"
    logger.debug("[T005] Running %s", test_name)

    # 1) Prefer the precomputed convenience field.
    connectivity = (getattr(ctx, "connectivity_ccsd_connectivity", None) or "").strip()

    # 2) Fallback: SystemInfo.connectivityccsd (shape can vary: list/dict/str)
    if not connectivity and getattr(ctx, "system_info", None) is not None:
        ccsd = getattr(ctx.system_info, "connectivityccsd", None)

        def _extract_connectivity(val) -> str:
            """Return a trimmed connectivity string from a loose value or ''."""
            if isinstance(val, str):
                return val.strip()
            if isinstance(val, dict):
                for k, v in val.items():
                    if isinstance(k, str) and k.strip().lower() == "connectivity" and isinstance(v, str):
                        return v.strip()
            return ""

        if isinstance(ccsd, (list, tuple, set)):
            for item in ccsd:
                connectivity = _extract_connectivity(item)
                if connectivity:
                    break
        elif ccsd is not None:
            connectivity = _extract_connectivity(ccsd)

    # --- Final decision (mirror PowerShell) ---
    if not connectivity:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.CONCERN,
            message="Connection points / Connectivity (CCSD) not provided.",
        )
        status.add(tr)
        logger.warning("[T005] CONCERN: CCSD connectivity missing.")
        return tr

    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=f"Connectivity type reported: {connectivity}",
    )
    status.add(tr)
    logger.info("[T005] PASS: CCSD connectivity present → %s", connectivity)
    return tr

def test_6(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 6 – Version / Release Number present.

    Mirrors the PowerShell behavior:

    - FAIL if no version / release number is found.
    - PASS if a non-empty version string is present, and remind the reviewer
      that they must manually confirm correctness.

    The version is resolved from structured models only (no raw payloads), in
    the following priority order:

    1. SystemContext.system_version
    2. SystemInfo.versionreleaseno
    3. SystemDetailsDashboard.version_release_number

    Args:
        ctx: Fully populated SystemContext for the target system.
        status: Aggregate ATOStatus object to which this result will be added.

    Returns:
        TestResult: Final outcome for Test 6.
    """
    test_number = 6
    test_name = "Test 6: Version / Release Number matches System"
    logger.debug("[T006] Running %s", test_name)

    # Collect candidate version strings from structured models only.
    candidates: list[str] = []

    # 1) Promoted scalar on SystemContext
    if ctx.system_version:
        candidates.append(str(ctx.system_version).strip())

    # 2) SystemInfo.versionreleaseno
    if ctx.system_info and getattr(ctx.system_info, "versionreleaseno", None):
        candidates.append(str(ctx.system_info.versionreleaseno).strip())

    # 3) SystemDetailsDashboard.version_release_number
    if ctx.system_details_dashboard and getattr(
        ctx.system_details_dashboard, "version_release_number", None
    ):
        candidates.append(str(ctx.system_details_dashboard.version_release_number).strip())

    # First non-empty candidate wins.
    version = next((v for v in candidates if v), "")

    if not version:
        msg = "System version / release number not entered."
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error("[T006] FAIL — System version / release number not entered.")
        return tr

    msg = (
        f"System version recorded: {version} "
        "(reviewer should confirm correctness)."
    )
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=msg,
    )
    status.add(tr)
    logger.info("[T006] PASS — Version present: %s", version)
    return tr



def test_7(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 7: System Type is provided (and sanity-checked).

    NOTES:
    - PowerShell version checks presence and reminds reviewer to validate against
      IS Enclave / IS Major Application / Platform IT System definitions.
    - We FAIL if missing; otherwise PASS and echo the type.
    - Optional: soft sanity check against common values (no failure).
    """
    name = "Test 7: Verify System Type is correct"

    system_type = (ctx.system_type or "").strip()
    if not system_type:
        tr = TestResult(
            test_number=7,
            name=name,
            result=Result.FAIL,
            message="System Type not entered.",
        )
        status.add(tr)
        logger.error("[T7] System type missing.")
        return tr

    # Soft sanity check, no failure—just log if uncommon
    common = {"is enclave", "is major application", "platform it system", "is major system"}
    if system_type.lower() not in common:
        logger.warning("[T7] Uncommon system type value: %s", system_type)

    tr = TestResult(
        test_number=7,
        name=name,
        result=Result.PASS,
        message=f"System Type recorded: {system_type} (reviewer should confirm correctness).",
    )
    status.add(tr)
    logger.info("[T7] System type present: %s", system_type)
    return tr

def test_8(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 8: 'Authorization Termination Date' aligns with APMS.

    Policy:
    1. If Authorization Status is "Not Yet Authorized" → N/A.
    2. Else:
        - If eMASS termination epoch is missing → FAIL.
        - Else parse epoch → YYYY-MM-DD.
          * If parse fails → FAIL.
          * If that epoch is in the past → CONCERN (expired).
          * If APMS date exists AND matches → PASS.
          * If APMS date exists AND mismatches → FAIL.
          * If APMS date missing → CONCERN.
    """

    logger = logging.getLogger(__name__)

    def _epoch_to_ymd(epoch_val) -> str:
        """
        Convert epoch seconds to 'YYYY-MM-DD' string.
        Returns "" if conversion fails.
        """
        try:
            iv = int(epoch_val)
            return datetime.utcfromtimestamp(iv).strftime("%Y-%m-%d")
        except Exception:
            return ""

    def _ci_get(row: dict, *keys: str):
        """
        Case-insensitive getter from a dict.
        Returns the first non-None value found.
        """
        if not isinstance(row, dict):
            return None
        lowered = {str(k).lower(): v for k, v in row.items()}
        for k in keys:
            v = lowered.get(k.lower())
            if v is not None:
                return v
        return None

    def _apms_get_ci(context: SystemContext, *keys: str):
        """
        Get a value from ctx.apms_first_row_raw using case-insensitive keys.
        """
        row = context.apms_first_row_raw or {}
        return _ci_get(row, *keys)

    test_name = "Test 8: Authorization Termination Date"
    logger.debug("Running %s", test_name)

    # --- grab system_info safely ---
    sysinfo = ctx.system_info

    # If we don't even have SystemInfo for this system, fail hard.
    if sysinfo is None:
        tr = TestResult(
            test_number=8,
            name=test_name,
            result=Result.FAIL,
            message="SystemInfo not available; cannot validate authorization termination date.",
        )
        status.add(tr)
        logger.error("[T8] Missing ctx.system_info entirely.")
        return tr

    # Normalize key fields from SystemInfo model
    authorization_status_raw = sysinfo.authorizationstatus or ""
    authorization_status = authorization_status_raw.strip().lower()

    auth_epoch = sysinfo.authterminationdate  # Optional[int] in the model

    # 1. If "Not Yet Authorized" => N/A
    if "not yet authorized" in authorization_status:
        tr = TestResult(
            test_number=8,
            name=test_name,
            result=Result.NA,
            message="System is not yet authorized.",
        )
        status.add(tr)
        logger.info(
            "[T8] N/A due to authorization status: %s",
            authorization_status_raw,
        )
        return tr

    # 2a. If authorized but missing termination date => FAIL
    if auth_epoch is None:
        tr = TestResult(
            test_number=8,
            name=test_name,
            result=Result.FAIL,
            message="System is authorized, but Authorization Termination Date is missing.",
        )
        status.add(tr)
        logger.error("[T8] Missing Authorization Termination epoch.")
        return tr

    # 2b. Convert epoch -> YYYY-MM-DD
    emass_auth_date_ymd = _epoch_to_ymd(auth_epoch)
    if not emass_auth_date_ymd:
        tr = TestResult(
            test_number=8,
            name=test_name,
            result=Result.FAIL,
            message="Authorization Termination Date present but could not be parsed.",
        )
        status.add(tr)
        logger.error(
            "[T8] Failed to parse epoch %r into date.",
            auth_epoch,
        )
        return tr

    # Check if expired
    now_epoch = int(_time.time())
    try:
        auth_epoch_int = int(auth_epoch)
    except Exception:
        auth_epoch_int = now_epoch  # treat garbage as expired

    if auth_epoch_int <= now_epoch:
        tr = TestResult(
            test_number=8,
            name=test_name,
            result=Result.CONCERN,
            message=f"Authorization appears expired as of {emass_auth_date_ymd}.",
        )
        status.add(tr)
        logger.warning(
            "[T8] Authorization expired on %s",
            emass_auth_date_ymd,
        )
        return tr

    # Pull APMS comparison date
    apms_auth_date_ymd = _apms_get_ci(
        ctx,
        "NIPR - Authorization Expiration Date",
    )

    # If APMS has a date → compare
    if apms_auth_date_ymd:
        if apms_auth_date_ymd == emass_auth_date_ymd:
            tr = TestResult(
                test_number=8,
                name=test_name,
                result=Result.PASS,
                message=(
                    f"Authorization termination date matches APMS: "
                    f"{emass_auth_date_ymd}."
                ),
            )
            status.add(tr)
            logger.info(
                "[T8] eMASS date matches APMS: %s",
                emass_auth_date_ymd,
            )
            return tr

        # mismatch
        tr = TestResult(
            test_number=8,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Auth termination date mismatch. "
                f"eMASS={emass_auth_date_ymd}, APMS={apms_auth_date_ymd}."
            ),
        )
        status.add(tr)
        logger.error(
            "[T8] Mismatch: eMASS=%s APMS=%s",
            emass_auth_date_ymd,
            apms_auth_date_ymd,
        )
        return tr

    # No APMS comparison date → CONCERN
    tr = TestResult(
        test_number=8,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "Authorization termination date present "
            f"({emass_auth_date_ymd}), but APMS date not available for validation."
        ),
    )
    status.add(tr)
    logger.warning(
        "[T8] APMS expiration date missing; eMASS=%s",
        emass_auth_date_ymd,
    )
    return tr

def test_9(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 9: National Security System (NSS) alignment between eMASS and APMS.

    Objective
    ---------
    Validate that the system's NSS designation is consistent across:
      - eMASS data (ctx.nss / ctx.classification)
      - APMS CSV snapshot (ctx.apms_first_row_raw)

    Why this matters:
    - NSS drives special handling and review rigor.
    - A mismatch between APMS and eMASS is a compliance red flag.

    Data we use
    -----------
    eMASS side:
      - ctx.nss                (bool-ish) whether system is marked NSS
      - ctx.classification     (str) highest data classification level
    APMS side (from ctx.apms_first_row_raw):
      - "NIPR - National Security System"         -> APMS NSS yes/no
      - "Classification level of network"         -> APMS network classification

    Logic
    -----
    1. Coerce the eMASS NSS flag (ctx.nss) and APMS NSS field to strict booleans
       using _to_bool_loose().
    2. If either side is missing/None -> FAIL
       (we consider that "not fully declared", not "N/A").
    3. If both sides are defined:
         * PASS if equal
         * FAIL if not equal
    4. Heuristic: if APMS network classification or eMASS high classification
       suggests SIPR / Secret, but NSS is False, we still PASS/FAIL using step 3
       but we log a warning because it smells off.

    Returns
    -------
    TestResult with status PASS or FAIL.
    """
    test_name = "Test 9: National Security System matches APMS and ITS"
    logger = logging.getLogger(__name__)
    logger.debug("Running %s", test_name)

    # eMASS view of NSS: builder bubbled this onto ctx.nss
    emass_nss = _to_bool_loose(getattr(ctx, "nss", None))

    # eMASS classification (string like "Secret", "CUI", etc)
    classification_text = (getattr(ctx, "classification", "") or "").strip().lower()

    # APMS view of NSS
    apms_nss_raw = _apms_get_ci(ctx, "NIPR - National Security System")
    apms_nss = _to_bool_loose(apms_nss_raw)

    # APMS network classification string ("NIPR", "SIPR", etc)
    apms_net_class = (_apms_get_ci(ctx, "Classification level of network") or "")
    apms_net_class_norm = apms_net_class.strip().lower()

    # Missing either side -> FAIL
    if emass_nss is None or apms_nss is None:
        tr = TestResult(
            test_number=9,
            name=test_name,
            result=Result.FAIL,
            message="NSS designation missing in eMASS and/or APMS.",
        )
        status.add(tr)
        logger.error(
            "[T9] Missing NSS fields: eMASS=%r APMS=%r (raw APMS=%r)",
            emass_nss,
            apms_nss,
            apms_nss_raw,
        )
        return tr

    # Soft sanity: SIPR / Secret should basically always be NSS.
    if "sipr" in apms_net_class_norm or "secret" in classification_text:
        if emass_nss is False:
            logger.warning(
                "[T9] Suspicious combo: classification implies SIPR/Secret but eMASS NSS=False. "
                "apms_net_class=%r classification=%r",
                apms_net_class_norm,
                classification_text,
            )

    # Final comparison
    if bool(emass_nss) == bool(apms_nss):
        tr = TestResult(
            test_number=9,
            name=test_name,
            result=Result.PASS,
            message="NSS designation matches between eMASS and APMS.",
        )
        status.add(tr)
        logger.info("[T9] NSS match: eMASS=%s APMS=%s", emass_nss, apms_nss)
        return tr

    tr = TestResult(
        test_number=9,
        name=test_name,
        result=Result.FAIL,
        message=f"NSS mismatch between eMASS ({emass_nss}) and APMS ({apms_nss}).",
    )
    status.add(tr)
    logger.error(
        "[T9] NSS mismatch: eMASS=%r APMS=%r APMS_raw=%r",
        emass_nss,
        apms_nss,
        apms_nss_raw,
    )
    return tr
def test_10(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 10: NSS questionnaire completion is recorded.

    Objective
    ---------
    For NSS systems, there’s supposed to be a special NSS checklist/
    questionnaire completed. We verify that this was captured.

    Where we read from
    ------------------
    Older context builder:
        ctx.system_status_details  -> List[dict] filtered to this system
    Each dict row is basically one "SystemDetailsDashboard" row (flattened).
    In those dicts there's usually a column like "NSS Questionnaire Completed".

    We:
      1. Find the row in ctx.system_status_details whose SystemID matches
         ctx.system_id.
      2. Case-insensitive grab "NSS Questionnaire Completed"
         (and variants) from that row.
      3. Coerce to bool with _to_bool_loose().

    Logic
    -----
    - If True  -> PASS
    - Else     -> FAIL

    Unlike some other tests, we don't return N/A here. If there's no data,
    that's a straight FAIL because an NSS system without a completed
    questionnaire is a blocker.
    """
    test_name = "Test 10: National Security System checklist filled out completely"
    logger = logging.getLogger(__name__)
    logger.debug("Running %s", test_name)

    details_rows = getattr(ctx, "system_status_details", None) or []
    row = _first_match_for_system(details_rows, ctx)

    raw_flag = _ci_get(
        row,
        "NSS Questionnaire Completed",
        "nss_questionnaire_completed",
        "NSSQuestionnaireCompleted",
    )
    completed = _to_bool_loose(raw_flag)

    if completed is True:
        tr = TestResult(
            test_number=10,
            name=test_name,
            result=Result.PASS,
            message="NSS Questionnaire is marked complete.",
        )
        status.add(tr)
        logger.info("[T10] Questionnaire complete (raw=%r).", raw_flag)
        return tr

    tr = TestResult(
        test_number=10,
        name=test_name,
        result=Result.FAIL,
        message="NSS Questionnaire not completed or not recorded.",
    )
    status.add(tr)
    logger.error("[T10] Questionnaire missing/incomplete (raw=%r).", raw_flag)
    return tr


def test_11(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 11: Financial Management System (FMS) flag matches APMS.

    Objective
    ---------
    Determine if the system is considered a Financial Management System /
    Financial Feeder System, and ensure that eMASS and APMS agree.

    Data we use
    -----------
    eMASS side:
        ctx.fms
        (builder typically normalizes SystemInfo.isFinancialManagement into ctx.fms)
    APMS side:
        ctx.apms_first_row_raw["Accounting System or Financial Feeder System"]

    Logic
    -----
    - If eMASS FMS is None -> FAIL (not declared)
    - If APMS FMS is None  -> FAIL (ambiguous APMS stance)
    - If both exist:
        * PASS if they agree
        * FAIL if they differ

    Returns
    -------
    PASS or FAIL.
    """
    test_name = "Test 11: Financial Management System matches APMS"
    logger = logging.getLogger(__name__)
    logger.debug("Running %s", test_name)

    # eMASS stance: builder surfaced this as ctx.fms
    emass_fms_flag = _to_bool_loose(getattr(ctx, "fms", None))

    # APMS stance
    apms_fms_raw = _apms_get_ci(ctx, "Accounting System or Financial Feeder System")
    apms_fms_bool = _to_bool_loose(apms_fms_raw)

    # Missing eMASS value -> FAIL
    if emass_fms_flag is None:
        tr = TestResult(
            test_number=11,
            name=test_name,
            result=Result.FAIL,
            message="Financial Management indicator is not provided in eMASS.",
        )
        status.add(tr)
        logger.error("[T11] Missing eMASS FMS flag.")
        return tr

    # Missing APMS value -> FAIL (ambiguous)
    if apms_fms_bool is None:
        tr = TestResult(
            test_number=11,
            name=test_name,
            result=Result.FAIL,
            message=f"APMS FMS value is undefined/ambiguous (raw='{apms_fms_raw}'); cannot validate.",
        )
        status.add(tr)
        logger.error("[T11] Ambiguous APMS FMS: raw=%r", apms_fms_raw)
        return tr

    # Compare stances
    if bool(emass_fms_flag) == bool(apms_fms_bool):
        tr = TestResult(
            test_number=11,
            name=test_name,
            result=Result.PASS,
            message="eMASS and APMS Financial Management indicators match.",
        )
        status.add(tr)
        logger.info("[T11] Match: eMASS=%s, APMS=%s", emass_fms_flag, apms_fms_bool)
        return tr

    tr = TestResult(
        test_number=11,
        name=test_name,
        result=Result.FAIL,
        message=(
            f"FMS mismatch. eMASS={emass_fms_flag}, "
            f"APMS(raw)='{apms_fms_raw}'."
        ),
    )
    status.add(tr)
    logger.error(
        "[T11] Mismatch: eMASS=%r, APMS(raw)=%r",
        emass_fms_flag,
        apms_fms_raw,
    )
    return tr

def test_12(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 12 – Reciprocity System is Yes.

    Mirrors the original PowerShell behavior:

    - Read reciprocity from structured eMASS models (no raw payloads):
      1. SystemInfo.isreciprocity (primary, boolean in eMASS)
      2. SystemDetailsDashboard.reciprocity_system (fallback, often 'YES'/'NO')

    - If the value is missing/None from all known sources:
        FAIL with "Reciprocity System is Not provided".
    - If the value is logically True/YES:
        PASS with "Reciprocity System is YES".
    - Otherwise (explicit False/NO/anything else):
        FAIL with "Reciprocity System is NO".

    Args:
        ctx: Fully populated system context for the target system.
        status: Aggregate ATOStatus object to which this result will be added.

    Returns:
        TestResult: Final outcome for Test 12.
    """
    test_number = 12
    test_name = "Test 12: Reciprocity System is Yes"
    logger = logging.getLogger(__name__)
    logger.debug("[T012] Running %s", test_name)

    # -----------------------------
    # 1) Gather candidate values
    # -----------------------------
    candidates: list[Any] = []

    # Primary: SystemInfo.isreciprocity (true eMASS field)
    if ctx.system_info is not None and ctx.system_info.isreciprocity is not None:
        candidates.append(ctx.system_info.isreciprocity)

    # Fallback: SystemDetailsDashboard.reciprocity_system (often "YES"/"NO")
    if (
        ctx.system_details_dashboard is not None
        and getattr(ctx.system_details_dashboard, "reciprocity_system", None) is not None
    ):
        candidates.append(ctx.system_details_dashboard.reciprocity_system)

    # -----------------------------
    # 2) Normalize to a loose bool
    # -----------------------------
    reciprocity: Optional[bool] = None

    for raw in candidates:
        # If you already have _to_bool_loose in this module, use it.
        # Otherwise, this inline logic is equivalent.
        if isinstance(raw, bool):
            reciprocity = raw
        else:
            s = str(raw).strip().lower()
            if s in {"true", "yes", "y", "1"}:
                reciprocity = True
            elif s in {"false", "no", "n", "0"}:
                reciprocity = False
            else:
                reciprocity = None

        if reciprocity is not None:
            break

    # -----------------------------
    # 3) Apply PowerShell semantics
    # -----------------------------
    if reciprocity is None:
        # $null case -> FAIL
        msg = "Reciprocity System is Not provided"
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error("[T012] FAIL — Reciprocity System is Not provided.")
        return tr

    if reciprocity is True:
        # "True" -> PASS
        msg = "Reciprocity System is YES"
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.PASS,
            message=msg,
        )
        status.add(tr)
        logger.info("[T012] PASS — Reciprocity System is YES.")
        return tr

    # Anything else -> FAIL "NO"
    msg = "Reciprocity System is NO"
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.FAIL,
        message=msg,
    )
    status.add(tr)
    logger.error("[T012] FAIL — Reciprocity System is NO.")
    return tr

def test_13(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 13: Public-facing boundary is documented with whitelist info.

    Objective
    ---------
    If the system is "public facing" (internet-exposed), we expect to see
    boundary registration data (whitelist inventory, whitelist ID).
    If you're on the internet, you don't get to be mysterious.

    Where we read from
    ------------------
    We pull the normalized SystemInfo row via _sys_row(ctx), and then look for:
      - isPublicFacing / ispublicfacing
      - whitelistId / WhiteListId
      - whitelistInventory / WhiteListInventory

    Logic
    -----
    1. If isPublicFacing is None        -> FAIL (not declared)
    2. If isPublicFacing is False       -> N/A  (not externally exposed)
    3. If isPublicFacing is True:
        - PASS if whitelistId and whitelistInventory are both populated
        - FAIL otherwise
    """
    test_name = "Test 13: Public Facing/Auth boundary"
    logger = logging.getLogger(__name__)
    logger.debug("Running %s", test_name)

    sys_row = _sys_row(ctx)

    public_facing_raw = _ci_get(sys_row, "isPublicFacing", "ispublicfacing")
    public_facing = _to_bool_loose(public_facing_raw)

    whitelist_id = (
        _ci_get(
            sys_row,
            "whitelistId",
            "whitelistID",
            "WhiteListId",
            "WhiteListID",
        )
    )
    whitelist_inventory = (
        _ci_get(
            sys_row,
            "whitelistInventory",
            "WhiteListInventory",
        )
    )

    # Missing declaration -> FAIL
    if public_facing is None:
        tr = TestResult(
            test_number=13,
            name=test_name,
            result=Result.FAIL,
            message="Public Facing info is not provided.",
        )
        status.add(tr)
        logger.error("[T13] Public Facing information not provided.")
        return tr

    # Not public facing -> N/A
    if public_facing is False:
        tr = TestResult(
            test_number=13,
            name=test_name,
            result=Result.NA,
            message="System is not public facing.",
        )
        status.add(tr)
        logger.info("[T13] System is not public facing.")
        return tr

    # Public-facing but missing whitelist boundary data -> FAIL
    if not whitelist_id or not whitelist_inventory:
        tr = TestResult(
            test_number=13,
            name=test_name,
            result=Result.FAIL,
            message="Whitelist ID or Inventory not provided for a public-facing system.",
        )
        status.add(tr)
        logger.error(
            "[T13] Missing whitelist data. whitelist_id=%r whitelist_inventory=%r",
            whitelist_id,
            whitelist_inventory,
        )
        return tr

    # All good
    tr = TestResult(
        test_number=13,
        name=test_name,
        result=Result.PASS,
        message=(
            "Whitelist boundary documented. "
            f"Whitelist ID: {whitelist_id}; "
            f"Inventory Ref: {whitelist_inventory}."
        ),
    )
    status.add(tr)
    logger.info(
        "[T13] PASS public-facing. whitelist_id=%r whitelist_inventory=%r",
        whitelist_id,
        whitelist_inventory,
    )
    return tr


def test_14(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 14: CUI / PII / PHI handling matches APMS declarations.

    Objective
    ---------
    Reconcile how the system reports sensitive data handling across eMASS
    versus APMS, specifically for PII and PHI. (CUI is logged but not used
    for the pass/fail branch here.)

    Why this matters:
    - PII, PHI => triggers Privacy Impact Assessment (PIA), SORN, HIPAA, etc.
    - If APMS and eMASS disagree about PII/PHI, that’s a red flag because
      it means governance artifacts may be missing or outdated.

    Where we read from
    ------------------
    eMASS side (SystemInfo row via _sys_row(ctx)):
        hasPII / haspii
        hasPHI / hasphi
        hasCUI / hascui        (we log it for context)
    APMS side (ctx.apms_first_row_raw first row of APMS CSV):
        "PIA Required"
        "Does the system contain Protected Health Information (PHI)"

    Normalization
    -------------
    For each boolean-ish field we call _to_bool_loose().
    For reporting we translate True->"Yes", False->"No", None->None.

    APMS quirk:
    "PIA Required" is treated as "contains PII" in most review workflows.
    If APMS says "Yes" there, we consider PII="Yes". Anything else => "No".

    Pass/Fail
    ---------
    PASS if:
        - eMASS PII matches APMS-derived PII
        - eMASS PHI matches APMS PHI
    Otherwise FAIL.
    """
    test_name = "Test 14: System contains CUI, PII and/or PHI and matches data"
    logger = logging.getLogger(__name__)
    logger.debug("Running %s", test_name)

    sys_row = _sys_row(ctx)

    # eMASS view
    is_cui = _to_bool_loose(_ci_get(sys_row, "hasCUI", "hascui"))
    is_pii = _to_bool_loose(_ci_get(sys_row, "hasPII", "haspii"))
    is_phi = _to_bool_loose(_ci_get(sys_row, "hasPHI", "hasphi"))

    def _yesno(b: Optional[bool]) -> Optional[str]:
        return None if b is None else ("Yes" if b else "No")

    pii_yesno = _yesno(is_pii)
    phi_yesno = _yesno(is_phi)

    # APMS view
    apms_pii_raw = _apms_get_ci(ctx, "PIA Required")
    apms_phi_raw = _apms_get_ci(
        ctx,
        "Does the system contain Protected Health Information (PHI)",
    )

    # APMS PII normalization:
    # convention: if "PIA Required" contains "yes", then PII="Yes", else "No"
    apms_pii_yesno = (
        "Yes"
        if isinstance(apms_pii_raw, str) and "yes" in apms_pii_raw.strip().lower()
        else "No"
    )

    # APMS PHI we assume is already "Yes"/"No"/blank; just trim.
    apms_phi_norm = (apms_phi_raw or "").strip()

    pii_match = (pii_yesno == apms_pii_yesno)
    phi_match = ((phi_yesno or "") == apms_phi_norm)

    if pii_match and phi_match:
        tr = TestResult(
            test_number=14,
            name=test_name,
            result=Result.PASS,
            message="PII and PHI values match with APMS.",
        )
        status.add(tr)
        logger.info(
            "[T14] PASS. PII eMASS=%r APMS=%r | PHI eMASS=%r APMS=%r | CUI=%r",
            pii_yesno,
            apms_pii_yesno,
            phi_yesno,
            apms_phi_norm,
            is_cui,
        )
        return tr

    tr = TestResult(
        test_number=14,
        name=test_name,
        result=Result.FAIL,
        message=(
            "PII / PHI values do not align with APMS. "
            f"APMS PII={apms_pii_yesno}, eMASS PII={pii_yesno}; "
            f"APMS PHI={apms_phi_norm}, eMASS PHI={phi_yesno}"
        ),
    )
    status.add(tr)
    logger.error(
        "[T14] FAIL mismatch. PII eMASS=%r APMS=%r | PHI eMASS=%r APMS=%r | CUI=%r",
        pii_yesno,
        apms_pii_yesno,
        phi_yesno,
        apms_phi_norm,
        is_cui,
    )
    return tr

def test_15(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 15 — System Description matches data Description.

    This test mirrors the legacy PowerShell implementation:

        Test 15: System Description matches data Description

    Behavior (PowerShell parity)
    -----------------------------
    * eMASS description is taken from ``ctx.system_description``.
    * APMS/data description is taken from the first row's ``"Description"``
      column. The lookup order is:
        1. ``ctx.apms_first_row_raw["Description"]`` (case-insensitive key).
        2. The first row of the CSV at ``ctx.data_path`` if present.

    * If the eMASS description is missing (``None`` or empty after strip):
        - Result: FAIL
        - Message: ``"Test Failed: System Description Missing"``

    * Otherwise, the APMS description is used as a wildcard pattern and the
      eMASS description as the value in a case-insensitive comparison that
      is equivalent to PowerShell's ``-like``:
        - If it matches:
            - Result: PASS
            - Message:
              ``"Test Passed: System description matches data and eMASS: <desc>"``
        - If it does not match (including when APMS description is empty):
            - Result: FAIL
            - Message: ``"Test Failed: System Descriptions do not match"``

    Args:
        ctx: Populated system context for the system under test.
        status: Mutable aggregate status object to which this result is added.

    Returns:
        A ``TestResult`` instance capturing the outcome of Test 15.
    """
    test_number = 15
    test_name = "Test 15: System Description matches data Description"
    logger = logging.getLogger(__name__)
    logger.debug("[T%03d] Running %s", test_number, test_name)

    # ------------------------------------------------------------------
    # 1. eMASS side (system description)
    # ------------------------------------------------------------------
    system_description_raw = (ctx.system_description or "").strip()
    if not system_description_raw:
        message = "Test Failed: System Description Missing"
        result = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(result)
        logger.error("[T%03d] %s", test_number, message)
        return result

    # ------------------------------------------------------------------
    # 2. APMS side (data description) — first row, "Description" column
    # ------------------------------------------------------------------
    def get_case_insensitive(row: Dict[str, Any], key: str) -> Optional[str]:
        """Return row[key] using case-insensitive key lookup."""
        lowered = {str(k).lower(): v for k, v in row.items()}
        return lowered.get(key.lower())

    apms_description_raw: Optional[str] = None

    # 2.1 Prefer the already-parsed APMS first row, if available.
    if ctx.apms_first_row_raw:
        apms_description_raw = get_case_insensitive(ctx.apms_first_row_raw, "Description")

    # 2.2 Fallback to reading the CSV at ctx.data_path, mirroring $dataReport[0]
    if apms_description_raw is None and ctx.data_path:
        try:
            with open(ctx.data_path, newline="", encoding="utf-8") as csv_file:
                reader = csv.DictReader(csv_file)
                first_row = next(reader, None)
                if first_row:
                    apms_description_raw = get_case_insensitive(first_row, "Description")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "[T%03d] Failed to read APMS CSV at %r: %s",
                test_number,
                ctx.data_path,
                exc,
            )

    # PowerShell semantics: if APMS description is missing/null, the -like
    # comparison will not succeed and we fall into the generic "do not match"
    # failure branch.
    apms_description = (apms_description_raw or "").strip()
    system_description = system_description_raw

    logger.debug(
        "[T%03d] Comparing system and data descriptions.\n"
        "  eMASS description: %r\n"
        "  APMS description:  %r",
        test_number,
        system_description,
        apms_description,
    )

    # ------------------------------------------------------------------
    # 3. Comparison logic — mimic PowerShell `-like` behavior
    # ------------------------------------------------------------------
    is_match = False
    if apms_description:
        # PowerShell `-like` is case-insensitive and uses * / ? wildcards.
        pattern = apms_description.lower()
        value = system_description.lower()
        is_match = fnmatch.fnmatch(value, pattern)
    else:
        logger.debug(
            "[T%03d] APMS description is empty; wildcard comparison will not match.",
            test_number,
        )

    if is_match:
        # PASS: Test Passed: System description matches data and eMASS: <systemDescription>
        message = (
            "Test Passed: System description matches data and eMASS: "
            f"{system_description}"
        )
        result = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.PASS,
            message=message,
        )
        status.add(result)
        logger.info("[T%03d] %s", test_number, message)
        return result

    # FAIL: Test Failed: System Descriptions do not match
    message = "Test Failed: System Descriptions do not match"
    result = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.FAIL,
        message=message,
    )
    status.add(result)
    logger.error(
        "[T%03d] %s (eMASS=%r, APMS=%r)",
        test_number,
        message,
        system_description,
        apms_description,
    )
    return result

def test_16(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 16: data ID matches data AITR Number

    Logic (ported from PowerShell):
      - Compare eMASS data ID to APMS AITR/DATA Number.
      - FAIL if eMASS data ID missing.
      - CONCERN if APMS AITR/DATA number missing (can't validate).
      - Case-insensitive comparison (PS `-eq` is case-insensitive).
      - PASS on match; FAIL otherwise (echo both).
    """


    test_name = "Test 16: data ID matches data AITR Number"
    logger.debug("Running %s", test_name)

    emass_id = (getattr(ctx, "emass_data_id", None) or "").strip()
    if not emass_id:
        tr = TestResult(
            test_number=16,
            name=test_name,
            result=Result.FAIL,
            message="eMASS data ID is not defined.",
        )
        status.add(tr)
        logger.error("[T16] Missing eMASS data ID.")
        return tr

    apms_csv = (ctx.data_path or "").strip()
    if not apms_csv or not os.path.exists(apms_csv):
        tr = TestResult(
            test_number=16,
            name=test_name,
            result=Result.CONCERN,
            message="APMS CSV not available; cannot validate AITR/DATA Number.",
        )
        status.add(tr)
        logger.warning("[T16] APMS CSV missing or not found: %r", apms_csv)
        return tr

    # Helpers (local, to avoid imports from test_api)
    def _first_or_none(reader: csv.DictReader):
        try:
            return next(reader)
        except StopIteration:
            return None

    def _get_ci(row: dict, *keys: str):
        if not isinstance(row, dict):
            return None
        lowered = {str(k).lower(): v for k, v in row.items()}
        for k in keys:
            v = lowered.get(k.lower())
            if v is not None:
                return v
        return None

    apms_aitr_raw = None
    try:
        with open(apms_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            first = _first_or_none(reader)
            if first:
                # Prefer "AITR Number", fall back to "DATA Number"
                apms_aitr_raw = _get_ci(first, "AITR Number", "DATA Number")
    except Exception as exc:
        logger.warning("[T16] Failed to read APMS CSV %r: %r", apms_csv, exc)

    apms_aitr = (apms_aitr_raw or "").strip()
    if not apms_aitr:
        tr = TestResult(
            test_number=16,
            name=test_name,
            result=Result.CONCERN,
            message="APMS AITR/DATA Number not present in CSV; cannot validate.",
        )
        status.add(tr)
        logger.warning("[T16] APMS AITR/DATA Number missing in first row.")
        return tr

    # PowerShell -eq is case-insensitive; normalize to strings and compare lower()
    if str(emass_id).lower() == str(apms_aitr).lower():
        tr = TestResult(
            test_number=16,
            name=test_name,
            result=Result.PASS,
            message=f"AITR Numbers match: {emass_id!r}.",
        )
        status.add(tr)
        logger.info("[T16] Match: eMASS=%r APMS(AITR/DATA)=%r", emass_id, apms_aitr)
        return tr

    tr = TestResult(
        test_number=16,
        name=test_name,
        result=Result.FAIL,
        message=f"AITR Numbers do not match. eMASS data ID={emass_id!r}, APMS AITR/DATA={apms_aitr!r}.",
    )
    status.add(tr)
    logger.error("[T16] Mismatch: eMASS=%r APMS(AITR/DATA)=%r", emass_id, apms_aitr)
    return tr


def test_17(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 17: System User Categories' Identify roles, responsibilities and categories for system

    Parity with PowerShell:
      - eMASS API/fixtures do not include this dataset → CONCERN.
    """
    test_name = "Test 17: System User Categories identify roles/responsibilities/categories"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=17,
        name=test_name,
        result=Result.CONCERN,
        message="eMASS API does not have data for this test.",
    )
    status.add(tr)
    logger.warning("[T17] eMASS API does not have data for this test.")
    return tr



def test_18(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 18 — Is this a Cloud Computer?

    This test enforces one-to-one parity with the legacy PowerShell
    implementation:

        Test 18: Is this a Cloud Computer?

    Data sources (already normalized on SystemContext)
    --------------------------------------------------
    From eMASS:
        * ctx.cloud_computing       -> bool | None
        * ctx.cloud_type            -> str | None
        * ctx.is_saas               -> bool | None
        * ctx.is_paas               -> bool | None
        * ctx.is_iaas               -> bool | None
        * ctx.other_service_models  -> str | None   (not used in PS logic)

    From APMS (first row, via builder crosswalk):
        * ctx.apms_cloud_assessment_designation -> "Cloud Assessment Designation"
        * ctx.apms_is_saas_system               -> "Is this a SaaS System"
        * ctx.apms_cloud_service_type           -> "Cloud Service Type"

    The APMS fields are translated exactly as in PowerShell:

        $dataCloud2:
            * "System is hosted in the cloud"                         -> True
            * "This system is migrating to the cloud"                 -> True
            * "Cloud computing is NOT applicable for this system"    -> False
            * "Cloud computing had been considered, but was not selected" -> False
            * "Cloud computing has NOT been considered"              -> False
            * "This investment is considering cloud computing"       -> False
            * "-" or empty or other                                  -> None

        $dataSaaS2:
            * "Yes"  -> True
            * "No"   -> False
            * "-" or null/empty -> None

        ($dataSaaS3, $dataPaaS3, $dataIaaS3 from "Cloud Service Type"):
            * contains "SaaS" -> dataSaaS3 = True else False
            * contains "PaaS" -> dataPaaS3 = True else False
            * contains "IaaS" -> dataIaaS3 = True else False

    Behavior (PowerShell parity)
    -----------------------------
    Let:
        Cloud      := ctx.cloud_computing
        CloudType  := ctx.cloud_type
        SAAS/PAAS/IAAS := ctx.is_saas / ctx.is_paas / ctx.is_iaas

        dataCloud2  := mapped APMS cloud flag
        dataSaaS2   := mapped APMS SaaS boolean
        dataSaaS3/3/3 := booleans from Cloud Service Type tokens

    1. If Cloud is True:
        * If any of CloudType, SAAS, PAAS, IAAS is None:
              FAIL  "Test Failed: Cloud System is Yes, But cloud type or service models are missing."
        * Else, if SAAS == dataSaaS2 AND Cloud == dataCloud2:
              - If SAAS == dataSaaS3 and PAAS == dataPaaS3 and IAAS == dataIaaS3:
                    PASS "Cloud data in eMASS matches data"
              - Else:
                    FAIL "Test Failed: Cloud is Yes, but service models do not match data"
        * Else:
              FAIL "Test Failed: data Cloud value or software as a service do not match eMASS."

    2. If Cloud is False:
        * If Cloud == dataCloud2:
              PASS "Test Passed: Cloud data in eMASS matches data"
        * Else:
              FAIL "Test Failed: data Cloud value does not match eMASS."

    3. If Cloud is None:
        * FAIL "Test Failed: Cloud information question not answered in eMASS"

    Result semantics
    ----------------
    * PASS → Cloud posture + service model(s) consistent with APMS under PS rules.
    * FAIL → Any of the PowerShell failure branches above.
    * No CONCERN/NA branch for this test.

    Args:
        ctx: Populated `SystemContext` instance for the system under test.
        status: Aggregate `ATOStatus` object updated with this test result.

    Returns:
        A `TestResult` describing the Test 18 outcome.
    """
    logger = logging.getLogger(__name__)
    test_number = 18
    test_name = "Test 18: Is this a Cloud Computer?"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    # ------------------------------------------------------------------
    # Helpers: APMS normalization (mirror PowerShell behavior)
    # ------------------------------------------------------------------

    def map_cloud_designation(designation: Optional[str]) -> Optional[bool]:
        """Map APMS 'Cloud Assessment Designation' to a coarse bool.

        Returns:
            True  if APMS explicitly indicates cloud or migration to cloud.
            False if APMS explicitly indicates non-cloud / cloud not used.
            None  if value is "-", empty, or unrecognized (ambiguous).
        """
        text = (designation or "").strip()
        if not text or text == "-":
            return None

        value = text.lower()

        if value == "system is hosted in the cloud":
            return True
        if value == "this system is migrating to the cloud":
            return True

        if value == "cloud computing is not applicable for this system":
            return False
        if value == "cloud computing had been considered, but was not selected":
            return False
        if value == "cloud computing has not been considered":
            return False
        if value == "this investment is considering cloud computing":
            return False

        # Any other prose is treated as ambiguous / not mapped.
        return None

    def map_yes_no(value: Optional[str]) -> Optional[bool]:
        """Map common APMS Yes/No fields into booleans.

        Returns:
            True  if value is "Yes" (case-insensitive).
            False if value is "No" (case-insensitive).
            None  if "-", empty, None, or unrecognized.
        """
        text = (value or "").strip().lower()
        if not text or text == "-":
            return None
        if text == "yes":
            return True
        if text == "no":
            return False
        return None

    def map_service_models(cloud_service_type: Optional[str]) -> Tuple[bool, bool, bool]:
        """Infer SaaS/PaaS/IaaS flags from APMS 'Cloud Service Type' text."""
        text = (cloud_service_type or "").strip().lower()
        has_saas = "saas" in text
        has_paas = "paas" in text
        has_iaas = "iaas" in text
        return has_saas, has_paas, has_iaas

    # ------------------------------------------------------------------
    # eMASS view (already flattened by builder)
    # ------------------------------------------------------------------
    emass_cloud = ctx.cloud_computing
    emass_cloud_type = ctx.cloud_type
    emass_saas = ctx.is_saas
    emass_paas = ctx.is_paas
    emass_iaas = ctx.is_iaas

    # ------------------------------------------------------------------
    # APMS view (crosswalk fields on SystemContext)
    # ------------------------------------------------------------------
    apms_cloud_flag = map_cloud_designation(ctx.apms_cloud_assessment_designation)
    apms_saas_flag = map_yes_no(ctx.apms_is_saas_system)
    apms_saas_from_type, apms_paas_from_type, apms_iaas_from_type = map_service_models(
        ctx.apms_cloud_service_type
    )

    logger.debug(
        "[T%03d] Cloud posture snapshot:\n"
        "  eMASS: Cloud=%r, CloudType=%r, SaaS=%r, PaaS=%r, IaaS=%r\n"
        "  APMS:  CloudText=%r -> %r, SaaSText=%r -> %r, CloudTypeText=%r "
        "(SaaS=%r, PaaS=%r, IaaS=%r)",
        test_number,
        emass_cloud,
        emass_cloud_type,
        emass_saas,
        emass_paas,
        emass_iaas,
        ctx.apms_cloud_assessment_designation,
        apms_cloud_flag,
        ctx.apms_is_saas_system,
        apms_saas_flag,
        ctx.apms_cloud_service_type,
        apms_saas_from_type,
        apms_paas_from_type,
        apms_iaas_from_type,
    )

    # ------------------------------------------------------------------
    # Branch 1: Cloud is True in eMASS
    # ------------------------------------------------------------------
    if emass_cloud is True:
        missing_detail = (
            emass_cloud_type is None
            or emass_saas is None
            or emass_paas is None
            or emass_iaas is None
        )
        if missing_detail:
            message = (
                "Test Failed: Cloud System is Yes, But cloud type or service models are missing."
            )
            result = TestResult(
                test_number=test_number,
                name=test_name,
                result=Result.FAIL,
                message=message,
            )
            status.add(result)
            logger.error(
                "[T%03d] %s CloudType=%r SaaS=%r PaaS=%r IaaS=%r",
                test_number,
                message,
                emass_cloud_type,
                emass_saas,
                emass_paas,
                emass_iaas,
            )
            return result

        # PowerShell:
        #   if ($SAAS -eq $dataSaaS2 -and $Cloud -eq $dataCloud2 )
        # We require both APMS SaaS and Cloud flags to be explicitly present and equal.
        if (
            apms_saas_flag is not None
            and apms_cloud_flag is not None
            and emass_saas == apms_saas_flag
            and emass_cloud == apms_cloud_flag
        ):
            # PowerShell:
            #   if ($SAAS -like $dataSaaS3 -and $PAAS -like $dataPaaS3 -and $IAAS -like $dataIaaS3)
            # With bools, this is equivalent to equality between eMASS flags and
            # APMS service-type inference.
            svc_models_match = (
                (emass_saas is True) == apms_saas_from_type
                and (emass_paas is True) == apms_paas_from_type
                and (emass_iaas is True) == apms_iaas_from_type
            )

            if svc_models_match:
                message = "Cloud data in eMASS matches data"
                result = TestResult(
                    test_number=test_number,
                    name=test_name,
                    result=Result.PASS,
                    message=message,
                )
                status.add(result)
                logger.info(
                    "[T%03d] %s SaaS/PaaS/IaaS eMASS=%s/%s/%s APMS=%s/%s/%s",
                    test_number,
                    message,
                    emass_saas,
                    emass_paas,
                    emass_iaas,
                    apms_saas_from_type,
                    apms_paas_from_type,
                    apms_iaas_from_type,
                )
                return result

            # Cloud is True and SaaS/Cloud map match, but service models differ.
            message = "Test Failed: Cloud is Yes, but service models do not match data"
            result = TestResult(
                test_number=test_number,
                name=test_name,
                result=Result.FAIL,
                message=message,
            )
            status.add(result)
            logger.error(
                "[T%03d] %s eMASS SaaS/PaaS/IaaS=%s/%s/%s APMS=%s/%s/%s",
                test_number,
                message,
                emass_saas,
                emass_paas,
                emass_iaas,
                apms_saas_from_type,
                apms_paas_from_type,
                apms_iaas_from_type,
            )
            return result

        # APMS Cloud or SaaS values do not match eMASS when Cloud is True.
        message = "Test Failed: data Cloud value or software as a service do not match eMASS."
        result = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(result)
        logger.error(
            "[T%03d] %s eMASS Cloud=%r SaaS=%r APMS Cloud=%r SaaS=%r",
            test_number,
            message,
            emass_cloud,
            emass_saas,
            apms_cloud_flag,
            apms_saas_flag,
        )
        return result

    # ------------------------------------------------------------------
    # Branch 2: Cloud is False in eMASS
    # ------------------------------------------------------------------
    if emass_cloud is False:
        # PowerShell: if ($Cloud -like $dataCloud2)
        # With our mapping, this is equivalent to requiring APMS to explicitly
        # indicate False; None (no mapping) is treated as mismatch.
        if apms_cloud_flag is False:
            message = "Test Passed: Cloud data in eMASS matches data"
            result = TestResult(
                test_number=test_number,
                name=test_name,
                result=Result.PASS,
                message=message,
            )
            status.add(result)
            logger.info(
                "[T%03d] %s eMASS Cloud=%r APMS Cloud=%r",
                test_number,
                message,
                emass_cloud,
                apms_cloud_flag,
            )
            return result

        message = "Test Failed: data Cloud value does not match eMASS."
        result = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(result)
        logger.error(
            "[T%03d] %s eMASS Cloud=%r APMS Cloud=%r",
            test_number,
            message,
            emass_cloud,
            apms_cloud_flag,
        )
        return result

    # ------------------------------------------------------------------
    # Branch 3: Cloud is None in eMASS
    # ------------------------------------------------------------------
    message = "Test Failed: Cloud information question not answered in eMASS"
    result = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.FAIL,
        message=message,
    )
    status.add(result)
    logger.error("[T%03d] %s (ctx.cloud_computing is None)", test_number, message)
    return result

def test_19(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 19: Cloud systems must declare HIGH confidentiality and HIGH integrity.

    Overview
    --------
    DoD cloud-hosted systems are expected to meet elevated information
    protection requirements (for example, IL5 in the DoD Cloud Computing SRG).
    At a minimum, that means both Confidentiality and Integrity should be
    assessed at "High".

    This test enforces that rule.

    Why this matters:
    - If you're in the cloud, you're handling mission data in someone
      else's infrastructure. The bar is higher.
    - If you're not in the cloud, this requirement doesn't apply.

    Inputs (from SystemContext)
    ---------------------------
    ctx.cloud_computing : Optional[bool]
        Whether the system is identified as cloud-hosted in eMASS.

    ctx.confidentiality : Optional[str]
        The system's confidentiality impact level ("Low", "Moderate", "High", ...).

    ctx.integrity : Optional[str]
        The system's integrity impact level ("Low", "Moderate", "High", ...).

    Evaluation logic
    ----------------
    1. If ctx.cloud_computing is not True:
        - System is not being tracked as cloud → this control is out of scope.
        - Result: N/A.

    2. If ctx.cloud_computing is True:
        - Both confidentiality and integrity MUST be present and MUST be "High"
          (case-insensitive).
        - PASS  if both are High.
        - FAIL  if either is missing OR either is not High.

    Result semantics
    ----------------
    PASS   → Cloud system has Confidentiality=High and Integrity=High.
    FAIL   → Cloud system missing CIA data or not High/High.
    N/A    → System is not marked cloud, so IL5-style requirement doesn't apply.
    """

    logger.debug("Running Test 19: Cloud system has confidentiality and integrity of HIGH")

    test_name = "Test 19: Cloud system has confidentiality and integrity of HIGH"

    # -------------------------------------------------
    # Step 1: Scope gate — only apply to cloud systems
    # -------------------------------------------------
    is_cloud = ctx.cloud_computing  # bool | None

    # If it's not explicitly True, we treat this requirement as out of scope.
    if is_cloud is not True:
        tr = TestResult(
            test_number=19,
            name=test_name,
            result=Result.NA,
            message="Not applicable: system is not identified as cloud-hosted.",
        )
        status.add(tr)
        logger.info(
            "[T19] N/A — cloud_computing=%r (requirement only applies to cloud systems)",
            is_cloud,
        )
        return tr

    # -------------------------------------------------
    # Step 2: Cloud = True → enforce High/High
    # -------------------------------------------------

    conf_raw = (ctx.confidentiality or "").strip()
    integ_raw = (ctx.integrity or "").strip()

    conf_norm = conf_raw.lower()
    integ_norm = integ_raw.lower()

    # Missing either value is an automatic FAIL. We do not guess.
    if not conf_raw or not integ_raw:
        tr = TestResult(
            test_number=19,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Cloud system is missing confidentiality and/or integrity values "
                "in eMASS. Both must be defined and set to High."
            ),
        )
        status.add(tr)
        logger.error(
            "[T19] FAIL — missing CIA fields for cloud system. "
            "Confidentiality=%r Integrity=%r",
            conf_raw,
            integ_raw,
        )
        return tr

    # Now enforce High/High.
    if conf_norm == "high" and integ_norm == "high":
        tr = TestResult(
            test_number=19,
            name=test_name,
            result=Result.PASS,
            message=(
                "Cloud system meets IL5-style expectation: "
                "Confidentiality=High and Integrity=High."
            ),
        )
        status.add(tr)
        logger.info(
            "[T19] PASS — Cloud CIA OK. Confidentiality=%s Integrity=%s",
            conf_raw,
            integ_raw,
        )
        return tr

    # Otherwise, we are cloud but not High/High → FAIL.
    tr = TestResult(
        test_number=19,
        name=test_name,
        result=Result.FAIL,
        message=(
            "Cloud system does not meet High/High requirement. "
            f"Confidentiality={conf_raw!r}, Integrity={integ_raw!r}; "
            "both must be 'High'."
        ),
    )
    status.add(tr)
    logger.error(
        "[T19] FAIL — Cloud CIA not High/High. Confidentiality=%s Integrity=%s",
        conf_raw,
        integ_raw,
    )
    return tr

def test_20(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 20: Cloud Service Offering (CSO) has valid DoD PA / FedRAMP / IL alignment.

    Summary
    -------
    For cloud-hosted systems, the Cloud Service Offering (CSO) must have:
    - A current DoD Provisional Authorization (PA), or an accepted in-process PA.
    - FedRAMP authorization (where applicable).
    - An approved Impact Level (IL) that matches how the system is using it.
    - Documented inheritance of the CSO's security controls.

    This test checks whether we can prove that automatically.

    Why this matters
    ----------------
    Mission systems in DoD are often deployed on a CSP platform (e.g. AWS IL5,
    Azure IL6, etc.). If the CSP platform itself is not properly authorized
    and aligned to the mission's required IL, the whole package is dead on arrival.

    Problem
    -------
    eMASS (and therefore our offline fixtures) does NOT expose:
    - PA letters
    - FedRAMP status
    - IL mapping for the CSP
    - Inheritance chain details

    So we cannot confirm this programmatically.

    Inputs
    ------
    ctx.cloud_computing : Optional[bool]
        True  → system is declared "cloud" in eMASS.
        False → system is on-prem / not cloud.
        None  → not populated.

    Behavior
    --------
    - If ctx.cloud_computing is not True:
        -> N/A
           This control only applies to cloud systems.

    - If ctx.cloud_computing is True:
        -> CONCERN
           We flag that manual validation is required because we don't have
           PA / FedRAMP / IL evidence in the data provided to us.

    Returned Result values
    ----------------------
    PASS    → never (we don't have enough evidence to assert PASS).
    FAIL    → never automatically (lack of evidence ≠ definitely noncompliant).
    CONCERN → cloud system, but we can't prove PA/FedRAMP/IL automatically.
    NA      → non-cloud system, requirement out of scope.
    """

    test_name = "Test 20: CSO DoD PA / FedRAMP approvals present and aligned"
    logger.debug("Running %s", test_name)

    # -------------------------------------------------
    # Step 1: Scope gate — this only applies to cloud
    # -------------------------------------------------
    is_cloud = ctx.cloud_computing  # bool | None

    if is_cloud is not True:
        # Not a cloud system (or not declared as such) → this check doesn't apply.
        tr = TestResult(
            test_number=20,
            name=test_name,
            result=Result.NA,
            message="Not applicable: system is not identified as cloud-hosted.",
        )
        status.add(tr)
        logger.info(
            "[T20] N/A — cloud_computing=%r (CSO PA/FedRAMP requirement applies only to cloud systems)",
            is_cloud,
        )
        return tr

    # -------------------------------------------------
    # Step 2: Cloud system → require PA/FedRAMP evidence
    # -------------------------------------------------
    #
    # We *should* verify:
    # - The CSP / CSO has an active DoD PA at the correct IL.
    # - FedRAMP status (if applicable) is current.
    # - The system actually inherits those controls instead of pretending.
    #
    # Reality check:
    # None of that is exposed in eMASS data we ingest into SystemContext.
    # It's all in external artifacts (PA letters, CSP package, DISA repository).
    #
    # So we surface a CONCERN and kick it to manual review.
    #
    tr = TestResult(
        test_number=20,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "Cloud system detected, but eMASS / fixture data does not include CSO "
            "Provisional Authorization, FedRAMP status, Impact Level mapping, or "
            "inheritance evidence. Manually verify CSP PA letter, FedRAMP ATO, "
            "IL alignment, and control inheritance."
        ),
    )
    status.add(tr)

    logger.warning(
        "[T20] CONCERN — cloud system requires manual CSO review "
        "(PA letter, FedRAMP auth, IL alignment, control inheritance); "
        "not available via SystemContext."
    )

    return tr

def test_21(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 21: SaaS system must have a PPSM Registry Number.

    Summary
    -------
    For systems delivered as Software-as-a-Service (SaaS), DoD expects a
    PPSM (Ports, Protocols, and Services Management) Registry Number. This
    number is how the service is tracked/approved for use on DoD networks.

    This test enforces:
    - If the system is SaaS → it must declare a PPSM Registry Number.
    - If the system is not SaaS → this requirement is not applicable.

    Why we care
    -----------
    Public/external services (especially SaaS) often introduce new ports,
    protocols, and data flows. Failing to register them is a classic ATO
    blocker because it prevents proper boundary control review.

    Data sources
    ------------
    We read from normalized, structured fields on `SystemContext` and
    its attached `SystemInfo` model. No raw dict walking.

    From `ctx` (SystemContext):
        - ctx.is_saas : Optional[bool]
            Normalized SaaS flag surfaced during context build.
            Mirrors/derives from SystemInfo.issaas.
        - ctx.system_info : Optional[SystemInfo]
            Parsed eMASS System Info record for this system.

    From `ctx.system_info` (SystemInfo model):
        - issaas                : Optional[bool]
            Original SaaS indicator from eMASS.
        - ppsmregistrynumber    : Optional[str]
            PPSM Registry Number assigned to this system/service.

    Behavior
    --------
    1. Resolve SaaS status:
        - Prefer ctx.is_saas if present.
        - Otherwise fall back to ctx.system_info.issaas.
        - Coerce with _to_bool_loose(...) to handle True/"Yes"/"1"/etc.

    2. If SaaS is not True:
        - Return N/A (out of scope for non-SaaS systems).

    3. If SaaS is True:
        - PASS  → PPSM Registry Number is present and non-empty.
        - FAIL  → PPSM Registry Number is missing/blank.
        - We also log a soft warning if the prefix of the PPSM number
          is unexpected (DoD convention: "U" for Unclassified, "C" for
          Classified), but that warning does not affect PASS/FAIL.

    Returns
    -------
    TestResult
        Result.NA      → system is not SaaS.
        Result.PASS    → SaaS system with PPSM number.
        Result.FAIL    → SaaS system missing PPSM number.
    """

    test_name = "Test 21: PPSM Registry Number provided for SaaS systems"
    logger.debug("Running %s", test_name)

    # -------------------------------------------------
    # Step 1: Get SystemInfo safely
    # -------------------------------------------------
    sysinfo = ctx.system_info  # SystemInfo | None

    if sysinfo is None:
        # We don't even have the structured SystemInfo block.
        # We cannot verify SaaS/PPSM in that case, so treat as FAIL.
        tr = TestResult(
            test_number=21,
            name=test_name,
            result=Result.FAIL,
            message="SystemInfo not available; cannot verify SaaS status or PPSM Registry Number.",
        )
        status.add(tr)
        logger.error("[T21] FAIL — ctx.system_info is None.")
        return tr

    # -------------------------------------------------
    # Step 2: Resolve SaaS flag
    # -------------------------------------------------
    # Prefer the normalized flag on SystemContext (ctx.is_saas),
    # otherwise fall back to the raw-ish issaas field from SystemInfo.
    saas_flag_raw = ctx.is_saas if ctx.is_saas is not None else sysinfo.issaas
    is_saas_bool = _to_bool_loose(saas_flag_raw)

    # -------------------------------------------------
    # Step 3: If not SaaS → out of scope
    # -------------------------------------------------
    if is_saas_bool is not True:
        tr = TestResult(
            test_number=21,
            name=test_name,
            result=Result.NA,
            message="Not applicable: system is not marked as SaaS.",
        )
        status.add(tr)
        logger.info(
            "[T21] N/A — is_saas=%r (ctx.is_saas=%r, sysinfo.issaas=%r)",
            is_saas_bool,
            ctx.is_saas,
            sysinfo.issaas,
        )
        return tr

    # -------------------------------------------------
    # Step 4: This IS SaaS → PPSM Registry Number is required
    # -------------------------------------------------
    ppsm_number_raw = sysinfo.ppsmregistrynumber or ""
    ppsm_number = ppsm_number_raw.strip()

    if not ppsm_number:
        # SaaS but no PPSM number = FAIL
        tr = TestResult(
            test_number=21,
            name=test_name,
            result=Result.FAIL,
            message="SaaS system is missing a PPSM Registry Number in eMASS.",
        )
        status.add(tr)
        logger.error(
            "[T21] FAIL — SaaS=True but ppsmregistrynumber is empty. "
            "saas_flag_raw=%r",
            saas_flag_raw,
        )
        return tr

    # -------------------------------------------------
    # Step 5: Advisory prefix sanity (non-fatal)
    # -------------------------------------------------
    # Historical guidance: PPSM Registry Numbers typically start with:
    #   U... → Unclassified
    #   C... → Classified
    # We don't enforce that as a hard rule, but we log if it's off-pattern.
    prefix = ppsm_number[:1].upper()
    if prefix not in {"U", "C"}:
        logger.warning(
            "[T21] PPSM Registry Number '%s' has unexpected prefix '%s' "
            "(expected to start with 'U' or 'C').",
            ppsm_number,
            prefix,
        )

    # -------------------------------------------------
    # Step 6: PASS — SaaS + PPSM present
    # -------------------------------------------------
    tr = TestResult(
        test_number=21,
        name=test_name,
        result=Result.PASS,
        message=f"PPSM Registry Number present for SaaS system: {ppsm_number}.",
    )
    status.add(tr)
    logger.info(
        "[T21] PASS — SaaS=True with PPSM Registry Number '%s'.",
        ppsm_number,
    )
    return tr

def test_22(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 22: Authorization Boundary artifact is present and current (≤ 1 year old).

    What we're enforcing
    --------------------
    For an ATO package to be viable, the system needs an up-to-date
    Authorization Boundary Diagram. This test validates two things:

      1. The system has at least one artifact whose name is
         exactly "Authorization Boundary Diagram" (case-insensitive match).

      2. That artifact has a Signed Date, and that Signed Date is
         no more than 365 days old from "now".

    This is effectively a currency check:
    if you're still using a year-old boundary diagram, someone
    is going to ask "is this still accurate?" in kickoff, and
    that turns into delay.

    Data contract
    -------------
    We pull from `ctx.artifact_details`, which in the new world is a typed
    `ArtifactDetails` Pydantic model. That model itself has a `.data` field,
    which is (optionally) a list of artifact rows.

    In practice:
    - ctx.artifact_details may be None (builder couldn't populate).
    - ctx.artifact_details.data may be None/[].
    - In some builder implementations, `artifact_details` might hold only
      "the first row" while the full list sits in `.data`. We treat both:
         - each dict in artifact_details.data, and
         - the top-level artifact_details itself as a row if it looks row-ish.

    Expected artifact row fields (case-insensitive):
    - "Artifact Name" / "artifactName"
    - "Filename" / "fileName"
    - "Signed Date" / "signedDate"
        Signed Date is expected to be epoch seconds (int-like string, etc.).

    Result semantics
    ----------------
    PASS:
        Authorization Boundary Diagram found,
        Signed Date exists,
        Signed Date is within last 365 days.
    FAIL:
        No Authorization Boundary Diagram found,
        OR it has no Signed Date,
        OR Signed Date is older than 1 year,
        OR we can't access artifact detail data at all.

    Side effects / logging
    ----------------------
    - On FAIL we log with logger.error to surface why.
    - On PASS we log filename + signed date (YYYY-MM-DD).
    """

    test_name = (
        "Test 22: Authorization Boundary is current & accurate; "
        "artifact present and signed within last year"
    )
    logger.debug("Running %s", test_name)

    # ---------------------------------------------------------------------
    # Local helpers
    # ---------------------------------------------------------------------

    def _ci_get(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        """
        Case-insensitive getter across multiple fallback keys.

        Example:
            _ci_get(r, "Artifact Name", "artifactName")
        """
        if not isinstance(row, dict):
            return default
        lowered = {str(k).lower(): v for k, v in row.items()}
        for k in keys:
            hit = lowered.get(k.lower())
            if hit is not None:
                return hit
        return default

    def _row_system_id(row: Dict[str, Any]) -> str:
        """
        Normalize possible system id keys to a string for matching against ctx.system_id.
        """
        return str(
            _ci_get(
                row,
                "System ID",
                "SystemID",
                "systemId",
                "system_id",
                "sysId",
                "id",
                default="",
            )
        )

    def _to_int_or_none(v: Any) -> Optional[int]:
        """
        Coerce numeric-like values to int. Return None if not parseable.
        Handles "1708569600", 1708569600, "1,708,569,600", etc.
        """
        if v is None:
            return None
        try:
            if isinstance(v, str):
                v_clean = v.replace(",", "").strip()
                return int(v_clean)
            return int(v)
        except Exception:
            return None

    def _epoch_to_ymd(epoch_s: int) -> str:
        """
        Convert epoch seconds -> 'YYYY-MM-DD' string.
        If conversion fails, return fallback like 'epoch:1234567890'.
        """
        try:
            return time.strftime("%Y-%m-%d", time.gmtime(int(epoch_s)))
        except Exception:
            return f"epoch:{epoch_s}"

    def _is_auth_boundary(row: Dict[str, Any]) -> bool:
        """
        True if the artifact row looks like an Authorization Boundary Diagram.
        We match exact string (case-insensitive) because that's how auditors ask
        for it: "Show me the Authorization Boundary Diagram".
        """
        name_raw = _ci_get(row, "Artifact Name", "artifactName")
        if not isinstance(name_raw, str):
            return False
        return name_raw.strip().lower() == "authorization boundary diagram"

    # ---------------------------------------------------------------------
    # Step 1. Gather artifact rows
    #
    # We'll build `artifact_rows` as a list[dict] that (best effort) represents
    # every artifact for this system. Sources:
    #   - ctx.artifact_details.data  (preferred full list)
    #   - ctx.artifact_details       (single row fallback)
    # ---------------------------------------------------------------------

    artifact_rows: List[Dict[str, Any]] = []

    details_model = getattr(ctx, "artifact_details", None)
    if details_model is None:
        # If we can't even access artifact_details, we can't pass.
        tr = TestResult(
            test_number=22,
            name=test_name,
            result=Result.FAIL,
            message="Authorization Boundary artifact not found (no artifact details available).",
        )
        status.add(tr)
        logger.error("[T22] FAIL — ctx.artifact_details is None.")
        return tr

    # Preferred: a list of rows under .data
    if isinstance(details_model.data, list):
        artifact_rows.extend([r for r in details_model.data if isinstance(r, dict)])

    # Fallback: treat the top-level model itself as a row
    # (builder may have set fields like artifact_name / signed_date directly at root)
    root_like_row: Dict[str, Any] = {}
    for field_name, field_value in details_model.dict(exclude_none=True).items():
        # We don't want to inject the nested .data back into itself and recurse,
        # so skip if this is literally the 'data' field.
        if field_name == "data":
            continue
        root_like_row[field_name] = field_value
    if root_like_row:
        artifact_rows.append(root_like_row)

    if not artifact_rows:
        tr = TestResult(
            test_number=22,
            name=test_name,
            result=Result.FAIL,
            message="Authorization Boundary artifact not found (artifact list is empty).",
        )
        status.add(tr)
        logger.error("[T22] FAIL — artifact_details.data is empty / unusable.")
        return tr

    # ---------------------------------------------------------------------
    # Step 2. Keep only rows for THIS system (if rows even carry system id).
    #
    # Some exports are org-wide. If rows include a System ID, filter by ctx.system_id.
    # If none of them include a System ID, assume the list is already scoped.
    # ---------------------------------------------------------------------

    current_sys_id = str(ctx.system_id)

    rows_with_sys_id = [r for r in artifact_rows if _row_system_id(r)]
    if rows_with_sys_id:
        artifact_rows = [r for r in rows_with_sys_id if _row_system_id(r) == current_sys_id]

    if not artifact_rows:
        tr = TestResult(
            test_number=22,
            name=test_name,
            result=Result.FAIL,
            message="Authorization Boundary artifact not found for this system.",
        )
        status.add(tr)
        logger.error("[T22] FAIL — artifact rows exist but none match system_id=%s.", current_sys_id)
        return tr

    # ---------------------------------------------------------------------
    # Step 3. Extract Authorization Boundary Diagram rows
    # ---------------------------------------------------------------------

    boundary_rows = [r for r in artifact_rows if _is_auth_boundary(r)]
    if not boundary_rows:
        tr = TestResult(
            test_number=22,
            name=test_name,
            result=Result.FAIL,
            message="Authorization Boundary artifact was not found.",
        )
        status.add(tr)
        logger.error("[T22] FAIL — no artifact named 'Authorization Boundary Diagram'.")
        return tr

    # ---------------------------------------------------------------------
    # Step 4. For each boundary row, grab (signed_epoch, filename, row).
    # We only consider rows with a Signed Date we can parse.
    # We'll pick the most recent signed date (max epoch).
    # ---------------------------------------------------------------------

    enriched: List[Tuple[int, Optional[str], Dict[str, Any]]] = []
    for row in boundary_rows:
        signed_raw = _ci_get(row, "Signed Date", "signedDate", "signed_epoch", "signeddate")
        signed_epoch = _to_int_or_none(signed_raw)

        filename_raw = _ci_get(row, "Filename", "FileName", "filename", "file")
        filename = filename_raw.strip() if isinstance(filename_raw, str) else None

        if signed_epoch is not None:
            enriched.append((signed_epoch, filename, row))

    if not enriched:
        tr = TestResult(
            test_number=22,
            name=test_name,
            result=Result.FAIL,
            message="Authorization Boundary artifact found, but Signed Date is missing.",
        )
        status.add(tr)
        logger.error("[T22] FAIL — boundary artifact(s) present but all missing Signed Date.")
        return tr

    # Most recent signature wins
    newest_epoch, newest_filename, newest_row = max(enriched, key=lambda t: t[0])

    # ---------------------------------------------------------------------
    # Step 5. Check that Signed Date is within the last 365 days
    # ---------------------------------------------------------------------

    ONE_YEAR_SECONDS = 365 * 24 * 60 * 60
    now_epoch = int(time.time())
    cutoff_epoch = now_epoch - ONE_YEAR_SECONDS

    signed_ymd = _epoch_to_ymd(newest_epoch)

    if newest_epoch <= cutoff_epoch:
        tr = TestResult(
            test_number=22,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Authorization Boundary artifact is older than one year "
                f"(Signed: {signed_ymd})."
            ),
        )
        status.add(tr)
        logger.error(
            "[T22] FAIL — Authorization Boundary Signed Date too old: %s (filename=%r)",
            signed_ymd,
            newest_filename,
        )
        return tr

    # ---------------------------------------------------------------------
    # Step 6. PASS
    # ---------------------------------------------------------------------
    tr = TestResult(
        test_number=22,
        name=test_name,
        result=Result.PASS,
        message=(
            "Authorization Boundary artifact is current "
            f"(Signed: {signed_ymd}); file: {newest_filename or 'N/A'}."
        ),
    )
    status.add(tr)
    logger.info(
        "[T22] PASS — Authorization Boundary signed %s (filename=%r)",
        signed_ymd,
        newest_filename,
    )
    return tr

def test_23(ctx: SystemContext, status: ATOStatus) -> TestResult:

    """Validate HW/SW baselines and the currency of the Hardware/Software/Firmware (H/S/F) artifact.

    This test enforces the eMASS/ATO expectation that an accreditable system must:
    1. **Have inventory**: a non-empty Hardware baseline **and** a non-empty Software baseline
       for the target `system_id`, unless the record is clearly SaaS/PaaS or Assess-Only.
    2. **Have evidence**: an artifact whose name is some reasonable variant of
       `"Hardware Software Firmware Diagram"` attached for this system.
    3. **Have currency**: that artifact must have a `Last Reviewed` timestamp that is not
       older than 365 days from “now”.

    This is a Python reimplementation of the legacy PowerShell check. The legacy script
    assumed a very clean eMASS dump (one artifact list, exact name match, epoch seconds),
    but real-world exports are noisier. This version is deliberately defensive and will
    look in **multiple places** for artifact rows — in the structured Pydantic model
    (`ctx.artifact_details.data`) **and** in the raw payloads
    (`ctx.raw_payloads.artifact_details`) — and will normalize common naming variants
    such as:
        - "Hardware / Software / Firmware Diagram"
        - "Hardware Software Firmware Diagram"
        - "Hardware Software and Firmware Diagram"
        - "HW/SW/FW Diagram"

    If the system is a cloud service (SaaS/PaaS) or an Assess-Only record, the hardware
    baseline is often legitimately empty in eMASS. In that case we **downgrade** the
    result to `CONCERN` instead of hard-failing, but we still require the H/S/F artifact
    to be present and current so a human can verify the boundary.

    Args:
        ctx (SystemContext):
            Fully hydrated context for **one** eMASS/RMF system. Must contain, at minimum:
            - `system_id` (int): used to scope org-wide artifact/inventory dumps.
            - `artifact_details` (ArtifactDetails | None): preferred source for attached
              artifacts; we read both the top-level fields and the `.data` list.
            - `raw_payloads.artifact_details` (list[dict] | None): fallback source for
              artifact rows if the Pydantic model didnt retain them.
            - `hardware` (Hardware | None): list-like object whose `.data` can be filtered
              to the current system.
            - `software` (Software | None): list-like object whose `.data` can be filtered
              to the current system.
            - Cloud / registration hints (`cloud_computing`, `is_saas`, `is_paas`,
              `registration_type`) so we can apply the Assess-Only/SaaS waiver logic.

        status (ATOStatus):
            Shared test run accumulator. This function **appends** a `TestResult`
            for test number 23 to it. Callers typically pass the same `ATOStatus`
            instance to every test so that the final report can be rendered once.

    Returns:
        TestResult:
            One of:
            - **PASS**: hardware baseline present, software baseline present, an H/S/F
              artifact exists for this system, and its `Last Reviewed` date is ≤ 365 days old.
            - **FAIL**: any of the above is missing or too old (no artifact, no baselines,
              artifact older than 1 year, or artifacts couldnt be scoped to this system).
            - **CONCERN**: baselines are empty **but** the record appears to be SaaS/PaaS
              or Assess-Only, so we cant prove noncompliance automatically and a human
              should review.

    Behavior:
        - **Artifact discovery**:
            1. Collect rows from `ctx.artifact_details.data` (preferred).
            2. Collect a root-like row from the artifact model itself (some builders put
               a single row there).
            3. If still empty, look at `ctx.raw_payloads.artifact_details`.
            4. If still empty → **FAIL** immediately.
        - **System scoping**:
            If artifact rows carry a per-row system identifier (any common variant of
            `"System ID"`), we filter to `ctx.system_id`. If nothing survives the filter → **FAIL**.
        - **Name matching**:
            We normalize the artifact name (lowercase, strip punctuation separators,
            collapse spaces) and compare against a small allowlist of H/S/F names.
        - **Recency**:
            We accept epoch seconds, or (best effort) ISO-ish strings (`YYYY-MM-DD`,
            `YYYY-MM-DDTHH:MM:SSZ`, `MM/DD/YYYY`). We interpret “not older than 365 days”
            relative to `time.time()` at runtime.
        - **Baselines**:
            We extract hardware/software rows from their `.data` lists, try to scope to
            the current system if per-row IDs exist, and treat “≥ 1 row” as “populated.”
            We also OR that with the high-level hints `ctx.has_hardware_data` /
            `ctx.has_software_data`.
        - **Waiver logic**:
            If baselines are missing **and** the record looks cloudish (SaaS/PaaS) or is
            explicitly “Assess Only,” we **do not** hard-fail; we return `CONCERN` so
            auditors can make the final call.

    Side Effects:
        - Appends the produced `TestResult` to the provided `status`.
        - Logs at DEBUG for discovery steps, at ERROR for hard failures, and at WARNING
          for waiver / concern outcomes. This is intentional — boundary/diagram issues
          are expensive to triage later.

    Rationale:
        Stale or missing HW/SW/FW diagrams are a common ATO blocker because they prevent
        assessors from confirming the actual deployed boundary, checking alignment with
        CM-8, and validating that the eMASS inventory matches what’s in the artifacts.
        Enforcing this early (at ingestion/test time) shortens the feedback loop for
        system owners and ISSMs.

    """

    test_name = (
        "Test 23: Hardware & Software baselines populated; H/S/F artifact current"
    )
    logger.debug("Running %s", test_name)

    ONE_YEAR_SECONDS = 365 * 24 * 60 * 60
    now_epoch = int(time.time())
    cutoff_epoch = now_epoch - ONE_YEAR_SECONDS
    sys_id_str = str(ctx.system_id)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _ci_get(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        if not isinstance(row, dict):
            return default
        lowered = {str(k).lower(): v for k, v in row.items()}
        for k in keys:
            v = lowered.get(str(k).lower())
            if v is not None:
                return v
        return default

    def _row_system_id(row: Dict[str, Any]) -> str:
        return str(
            _ci_get(
                row,
                "System ID",
                "SystemID",
                "systemId",
                "system_id",
                "sysId",
                "id",
                default="",
            )
        )

    def _to_int_or_none(v: Any) -> Optional[int]:
        if v is None:
            return None
        # sometimes it's ISO – let caller handle
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str):
            vs = v.replace(",", "").strip()
            if vs.isdigit():
                return int(vs)
        return None

    def _to_epoch_best_effort(v: Any) -> Optional[int]:
        """
        eMASS sometimes gives epoch seconds, sometimes ISO strings.
        We'll try epoch first, then ISO.
        """
        # epoch-ish
        as_int = _to_int_or_none(v)
        if as_int is not None:
            return as_int

        if not v:
            return None

        # ISO-ish: 2024-03-14, 2024-03-14T00:00:00Z, etc.
        s = str(v).strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%m/%d/%Y"):
            try:
                dt = datetime.datetime.strptime(s, fmt)
                return int(dt.replace(tzinfo=datetime.timezone.utc).timestamp())
            except Exception:
                continue
        return None

    def _epoch_to_ymd(epoch_s: int) -> str:
        try:
            return time.strftime("%Y-%m-%d", time.gmtime(int(epoch_s)))
        except Exception:
            return f"epoch:{epoch_s}"

    def _normalize_artifact_name(name: str) -> str:
        """
        Normalize things like:
          - "Hardware / Software / Firmware Diagram"
          - "Hardware Software Firmware Diagram"
          - "HW/SW/FW Diagram"
        down to a simple, comparable token.
        """
        if not isinstance(name, str):
            return ""
        s = name.lower().strip()
        # drop punctuation-ish separators
        s = s.replace("/", " ").replace(",", " ").replace("-", " ")
        s = " ".join(s.split())  # collapse spaces
        return s

    def _is_hsf_artifact(row: Dict[str, Any]) -> bool:
        name_raw = _ci_get(row, "Artifact Name", "artifactName", "name")
        norm = _normalize_artifact_name(name_raw or "")
        # accept several forms
        return norm in {
            "hardware software firmware diagram",
            "hardware software firmware",
            "hardware software firmware list",
            "hsf diagram",
            "hardware software and firmware diagram",
        }

    # ------------------------------------------------------------------
    # 1) Gather artifact rows from as many places as possible
    # ------------------------------------------------------------------
    artifact_rows: List[Dict[str, Any]] = []

    # a) structured model
    details_model = getattr(ctx, "artifact_details", None)
    if details_model is not None:
        # preferred path: .data
        data_list = getattr(details_model, "data", None)
        if isinstance(data_list, list):
            artifact_rows.extend([r for r in data_list if isinstance(r, dict)])

        # some Pydantic versions expose .dict(), v2 uses .model_dump()
        root_like: Dict[str, Any] = {}
        try:
            if hasattr(details_model, "model_dump"):
                dump = details_model.model_dump(exclude_none=True)
            else:
                dump = details_model.dict(exclude_none=True)  # type: ignore
            for k, v in dump.items():
                if k == "data":
                    continue
                root_like[k] = v
        except Exception:
            root_like = {}
        if root_like:
            artifact_rows.append(root_like)

    # b) raw payloads fallback (our builder put the filtered rows here)
    if not artifact_rows and getattr(ctx, "raw_payloads", None) is not None:
        raw_rows = getattr(ctx.raw_payloads, "artifact_details", None)
        if isinstance(raw_rows, list):
            artifact_rows.extend([r for r in raw_rows if isinstance(r, dict)])

    if not artifact_rows:
        tr = TestResult(
            test_number=23,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Hardware / Software / Firmware artifact not found "
                "(no artifact details available)."
            ),
        )
        status.add(tr)
        logger.error("[T23] FAIL — ctx.artifact_details is missing or empty.")
        return tr

    # try to scope to this system if the rows even have system IDs
    rows_with_sys = [r for r in artifact_rows if _row_system_id(r)]
    if rows_with_sys:
        artifact_rows = [r for r in rows_with_sys if _row_system_id(r) == sys_id_str]
        if not artifact_rows:
            tr = TestResult(
                test_number=23,
                name=test_name,
                result=Result.FAIL,
                message="Hardware / Software / Firmware artifact not found for this system.",
            )
            status.add(tr)
            logger.error(
                "[T23] FAIL — artifact rows exist, but none match system_id=%s.",
                sys_id_str,
            )
            return tr

    # ------------------------------------------------------------------
    # 2) Find H/S/F artifact and newest Last Reviewed
    # ------------------------------------------------------------------
    hsf_rows = [r for r in artifact_rows if _is_hsf_artifact(r)]
    if not hsf_rows:
        tr = TestResult(
            test_number=23,
            name=test_name,
            result=Result.FAIL,
            message="Hardware / Software / Firmware artifact was not found.",
        )
        status.add(tr)
        logger.error(
            "[T23] FAIL — no artifact named 'Hardware Software Firmware Diagram'."
        )
        return tr

    enriched: List[Tuple[int, Optional[str], Dict[str, Any]]] = []
    for r in hsf_rows:
        lr_raw = _ci_get(
            r,
            "Last Reviewed",
            "lastReviewed",
            "last_reviewed",
            "lastreviewed",
        )
        lr_epoch = _to_epoch_best_effort(lr_raw)
        filename_raw = _ci_get(r, "Filename", "FileName", "filename", "file")
        filename = filename_raw.strip() if isinstance(filename_raw, str) else None
        if lr_epoch is not None:
            enriched.append((lr_epoch, filename, r))

    if not enriched:
        tr = TestResult(
            test_number=23,
            name=test_name,
            result=Result.FAIL,
            message="H/S/F artifact found, but 'Last Reviewed' date is missing or unparsable.",
        )
        status.add(tr)
        logger.error("[T23] FAIL — H/S/F artifact present but missing Last Reviewed.")
        return tr

    newest_epoch, newest_filename, _ = max(enriched, key=lambda t: t[0])
    reviewed_ymd = _epoch_to_ymd(newest_epoch)

    # ------------------------------------------------------------------
    # 3) Check hardware / software baselines
    # ------------------------------------------------------------------
    def _filter_baseline_rows(raw_model: Any) -> List[Dict[str, Any]]:
        if raw_model is None:
            return []
        rows = getattr(raw_model, "data", None)
        if not isinstance(rows, list):
            return []
        rows_with_sid = [r for r in rows if isinstance(r, dict) and _row_system_id(r)]
        if rows_with_sid:
            return [r for r in rows_with_sid if _row_system_id(r) == sys_id_str]
        return [r for r in rows if isinstance(r, dict)]

    hardware_rows = _filter_baseline_rows(getattr(ctx, "hardware", None))
    software_rows = _filter_baseline_rows(getattr(ctx, "software", None))

    has_hw_baseline = len(hardware_rows) > 0 or bool(getattr(ctx, "has_hardware_data", False))
    has_sw_baseline = len(software_rows) > 0 or bool(getattr(ctx, "has_software_data", False))

    # SaaS / PaaS / Assess-Only waiver (per note in PS comments)
    is_cloudish = bool(ctx.cloud_computing) and (bool(ctx.is_saas) or bool(ctx.is_paas))
    is_assess_only = (
        (ctx.registration_type or "").strip().lower() in {"assess only", "assess-only"}
    )

    if (not has_hw_baseline or not has_sw_baseline) and (is_cloudish or is_assess_only):
        # Don't fail the whole test — data is often absent by design
        tr = TestResult(
            test_number=23,
            name=test_name,
            result=Result.CONCERN,
            message=(
                "H/S/F artifact is present and current, but baseline(s) are empty and this "
                "appears to be a cloud / assess-only record — manual review required."
            ),
        )
        status.add(tr)
        logger.warning(
            "[T23] CONCERN — baselines empty but record is SaaS/PaaS or Assess-Only."
        )
        return tr

    if not has_hw_baseline or not has_sw_baseline:
        tr = TestResult(
            test_number=23,
            name=test_name,
            result=Result.FAIL,
            message="Hardware or Software baseline not found for this system.",
        )
        status.add(tr)
        logger.error(
            "[T23] FAIL — Missing baseline(s): hardware=%s software=%s",
            has_hw_baseline,
            has_sw_baseline,
        )
        return tr

    # ------------------------------------------------------------------
    # 4) Check recency
    # ------------------------------------------------------------------
    if newest_epoch <= cutoff_epoch:
        tr = TestResult(
            test_number=23,
            name=test_name,
            result=Result.FAIL,
            message=(
                "H/S/F artifact review date is older than one year "
                f"(Last Reviewed: {reviewed_ymd})."
            ),
        )
        status.add(tr)
        logger.error(
            "[T23] FAIL — H/S/F 'Last Reviewed' too old: %s (file=%r)",
            reviewed_ymd,
            newest_filename,
        )
        return tr

    # ------------------------------------------------------------------
    # PASS
    # ------------------------------------------------------------------
    tr = TestResult(
        test_number=23,
        name=test_name,
        result=Result.PASS,
        message=(
            "Hardware / Software baselines are present and H/S/F artifact is "
            f"current (Last Reviewed: {reviewed_ymd}); file: {newest_filename or 'N/A'}."
        ),
    )
    status.add(tr)
    logger.info(
        "[T23] PASS — baselines ok, H/S/F reviewed %s (file=%r)",
        reviewed_ymd,
        newest_filename,
    )
    return tr


def test_24(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 24: Enterprise & Information Security Architecture (E/ISA) artifact present and current.

    What we're enforcing
    --------------------
    We expect every system to maintain an up-to-date "Enterprise and Information
    Security Architecture Diagram". Auditors use this to confirm the system's
    security / data flows are actually designed and governed, not accidental.

    This test asserts:
    1. The expected artifact exists.
    2. The artifact has a "Last Modified" timestamp.
    3. That timestamp is not older than 365 days.

    If any of those fail, you fail this test. This aligns with the legacy
    PowerShell check that blocks ATO packages with stale/absent security
    architecture diagrams.

    Data contract (SystemContext)
    -----------------------------
    - ctx.artifact_details : ArtifactDetails | None
        - artifact_details.data -> list[dict]
            Each dict is an artifact row with fields like:
                "Artifact Name"
                "Filename"
                "Last Modified"  (epoch seconds)
                "System ID"      (optional; for org-scoped exports)

        The builder may also hydrate top-level fields on artifact_details
        that correspond to one artifact row. We treat that as an additional row.

    - ctx.system_id : int
        Used to filter artifacts down to the current system if rows are org-scoped.

    Result semantics
    ----------------
    PASS  → artifact found AND last modified ≤ 365 days ago
    FAIL  → artifact missing, missing date, or older than 1 year
    """

    test_name = (
        "Test 24: Enterprise & Information Security Architecture artifact current"
    )
    logger.debug("Running %s", test_name)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ci_get(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        """
        Case-insensitive dict getter.

        Example:
            _ci_get(r, "Artifact Name", "artifactName")
        """
        if not isinstance(row, dict):
            return default
        lowered = {str(k).lower(): v for k, v in row.items()}
        for k in keys:
            hit = lowered.get(k.lower())
            if hit is not None:
                return hit
        return default

    def _row_system_id(row: Dict[str, Any]) -> str:
        """
        Extract system ID from a row using common key variants.
        Returns "" if not present.
        """
        return str(
            _ci_get(
                row,
                "System ID",
                "SystemID",
                "systemId",
                "system_id",
                "sysId",
                "id",
                default="",
            )
        )

    def _to_int_or_none(v: Any) -> Optional[int]:
        """
        Convert numeric-like values (int, '1708569600', '1,708,569,600') to int.
        Returns None on failure.
        """
        if v is None:
            return None
        try:
            if isinstance(v, str):
                v_clean = v.replace(",", "").strip()
                return int(v_clean)
            return int(v)
        except Exception:
            return None

    def _epoch_to_ymd(epoch_s: int) -> str:
        """
        Convert epoch seconds to 'YYYY-MM-DD' (UTC).
        Falls back to 'epoch:<value>' if conversion fails.
        """
        try:
            return time.strftime("%Y-%m-%d", time.gmtime(int(epoch_s)))
        except Exception:
            return f"epoch:{epoch_s}"

    # ------------------------------------------------------------------
    # Step 1. Gather candidate artifact rows from ctx.artifact_details
    #
    # artifact_details.data is authoritative, but the builder might also
    # copy one artifact's fields directly onto artifact_details.*.
    # We'll merge both into a working list.
    # ------------------------------------------------------------------

    artifact_rows: List[Dict[str, Any]] = []

    ad_model = getattr(ctx, "artifact_details", None)
    if ad_model is not None:
        # Primary source: list of artifact dicts
        if isinstance(ad_model.data, list):
            artifact_rows.extend(
                [r for r in ad_model.data if isinstance(r, dict)]
            )

        # Secondary source: treat the model itself as a single row snapshot
        root_like_row: Dict[str, Any] = {}
        for field_name, field_value in ad_model.dict(exclude_none=True).items():
            if field_name == "data":
                continue
            root_like_row[field_name] = field_value
        if root_like_row:
            artifact_rows.append(root_like_row)

    # If we still don't have artifacts, we cannot verify anything.
    if not artifact_rows:
        tr = TestResult(
            test_number=24,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Enterprise & Information Security Architecture artifact not found "
                "(no artifact details available)."
            ),
        )
        status.add(tr)
        logger.error("[T24] FAIL — ctx.artifact_details is missing or empty.")
        return tr

    # Filter by system_id if rows are org-scoped. If rows include any
    # per-row system id, we ONLY keep rows matching ctx.system_id.
    sys_id_str = str(ctx.system_id)
    rows_with_sid = [r for r in artifact_rows if _row_system_id(r)]
    if rows_with_sid:
        artifact_rows = [r for r in rows_with_sid if _row_system_id(r) == sys_id_str]

    if not artifact_rows:
        tr = TestResult(
            test_number=24,
            name=test_name,
            result=Result.FAIL,
            message="Enterprise & Information Security Architecture artifact not found for this system.",
        )
        status.add(tr)
        logger.error(
            "[T24] FAIL — artifact details exist, but none match system_id=%s.",
            sys_id_str,
        )
        return tr

    # ------------------------------------------------------------------
    # Step 2. Identify the Enterprise & Information Security Architecture Diagram
    #
    # We match on exact-ish name:
    #   "Enterprise and Information Security Architecture Diagram"
    # Case-insensitive, trimmed.
    # ------------------------------------------------------------------

    TARGET_NAME = "enterprise and information security architecture diagram"

    def _is_eisa(row: Dict[str, Any]) -> bool:
        name_raw = _ci_get(row, "Artifact Name", "artifactName")
        if not isinstance(name_raw, str):
            return False
        return name_raw.strip().lower() == TARGET_NAME

    eisa_rows = [r for r in artifact_rows if _is_eisa(r)]
    if not eisa_rows:
        tr = TestResult(
            test_number=24,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Enterprise & Information Security Architecture artifact was not found."
            ),
        )
        status.add(tr)
        logger.error(
            "[T24] FAIL — no artifact named "
            "'Enterprise and Information Security Architecture Diagram'."
        )
        return tr

    # ------------------------------------------------------------------
    # Step 3. Among matches, grab the most recent Last Modified timestamp
    #
    # We allow these key variants:
    #   "Last Modified", "lastModified", "last_modified", etc.
    #
    # We keep (epoch, filename, row) triples for sorting.
    # ------------------------------------------------------------------

    candidates: List[Tuple[int, Optional[str], Dict[str, Any]]] = []

    for row in eisa_rows:
        last_mod_raw = _ci_get(
            row,
            "Last Modified",
            "lastModified",
            "last_modified",
            "lastmodified",
        )
        last_mod_epoch = _to_int_or_none(last_mod_raw)

        filename_raw = _ci_get(row, "Filename", "FileName", "filename", "file")
        filename = filename_raw.strip() if isinstance(filename_raw, str) else None

        if last_mod_epoch is not None:
            candidates.append((last_mod_epoch, filename, row))

    if not candidates:
        tr = TestResult(
            test_number=24,
            name=test_name,
            result=Result.FAIL,
            message=(
                "E/ISA artifact found, but 'Last Modified' timestamp is missing."
            ),
        )
        status.add(tr)
        logger.error(
            "[T24] FAIL — E/ISA artifact present but all missing Last Modified."
        )
        return tr

    newest_epoch, newest_filename, _ = max(
        candidates,
        key=lambda t: t[0],
    )

    # ------------------------------------------------------------------
    # Step 4. Enforce staleness policy
    #
    # Must be modified within the last 365 days.
    # ------------------------------------------------------------------

    ONE_YEAR_SECONDS = 365 * 24 * 60 * 60
    now_epoch = int(time.time())
    cutoff_epoch = now_epoch - ONE_YEAR_SECONDS

    newest_ymd = _epoch_to_ymd(newest_epoch)

    if newest_epoch <= cutoff_epoch:
        tr = TestResult(
            test_number=24,
            name=test_name,
            result=Result.FAIL,
            message=(
                "E/ISA artifact is older than one year "
                f"(Last Modified: {newest_ymd})."
            ),
        )
        status.add(tr)
        logger.error(
            "[T24] FAIL — E/ISA 'Last Modified' too old: %s (file=%r)",
            newest_ymd,
            newest_filename,
        )
        return tr

    # ------------------------------------------------------------------
    # PASS
    # ------------------------------------------------------------------

    tr = TestResult(
        test_number=24,
        name=test_name,
        result=Result.PASS,
        message=(
            "E/ISA artifact is current "
            f"(Last Modified: {newest_ymd}); file: {newest_filename or 'N/A'}."
        ),
    )
    status.add(tr)
    logger.info(
        "[T24] PASS — E/ISA current as of %s (file=%r)",
        newest_ymd,
        newest_filename,
    )
    return tr
def test_25(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 25: Information Flows / Paths artifact present and current.

    What we're enforcing
    --------------------
    Systems need a current "Information Flows Paths Diagram". This is the dataflow
    view auditors use to verify boundaries, encryption, trust zones, cross-domain
    paths, etc. If it's missing or stale, that's an ATO red flag.

    This test asserts:
    1. An artifact named "Information Flows Paths Diagram" exists.
    2. That artifact has a "Last Modified" timestamp.
    3. That timestamp is ≤ 365 days old.

    We do not analyze content (encryption annotations, etc.) because we don't
    have the file. Humans still have to confirm those details.

    Data contract (SystemContext)
    -----------------------------
    - ctx.artifact_details : ArtifactDetails | None
        - artifact_details.data -> list[dict]
          Each dict is an artifact row with keys like:
            "Artifact Name"
            "Filename"
            "Last Modified" (epoch seconds)
            "System ID"     (optional, for org-scoped dumps)
        - The builder may also hoist one row's fields to the top-level model
          (artifact_details.filename, etc.). We treat that as an extra row.

    - ctx.system_id : int
        Used to filter multi-system payloads down to "this" system.

    Return semantics
    ----------------
    PASS → diagram exists and is current
    FAIL → missing diagram, missing date, or older than 1 year
    """

    test_name = "Test 25: Information Flows / Paths artifact current"
    logger.debug("Running %s", test_name)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ci_get(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        """
        Case-insensitive getter.
        Example:
            _ci_get(r, "Artifact Name", "artifactName")
        """
        if not isinstance(row, dict):
            return default
        lowered = {str(k).lower(): v for k, v in row.items()}
        for k in keys:
            hit = lowered.get(k.lower())
            if hit is not None:
                return hit
        return default

    def _row_system_id(row: Dict[str, Any]) -> str:
        """
        Best-effort system ID extraction across common variants.
        Returns "" if none found.
        """
        return str(
            _ci_get(
                row,
                "System ID",
                "SystemID",
                "systemId",
                "system_id",
                "sysId",
                "id",
                default="",
            )
        )

    def _to_int_or_none(v: Any) -> Optional[int]:
        """
        Convert numeric-like values (e.g. "1708569600", "1,708,569,600") to int.
        Returns None if conversion fails.
        """
        if v is None:
            return None
        try:
            if isinstance(v, str):
                return int(v.replace(",", "").strip())
            return int(v)
        except Exception:
            return None

    def _epoch_to_ymd(epoch_s: int) -> str:
        """
        Convert epoch seconds → 'YYYY-MM-DD' (UTC).
        Falls back to 'epoch:<value>' if conversion fails.
        """
        try:
            return time.strftime("%Y-%m-%d", time.gmtime(int(epoch_s)))
        except Exception:
            return f"epoch:{epoch_s}"

    # ------------------------------------------------------------------
    # Step 1. Consolidate all artifact rows in scope
    #
    # We pull from:
    #   - ctx.artifact_details.data  (list of rows)
    #   - flattened fields directly on ctx.artifact_details (treated as 1 row)
    #
    # Then we filter for this ctx.system_id if possible.
    # ------------------------------------------------------------------

    artifact_rows: List[Dict[str, Any]] = []
    ad_model = getattr(ctx, "artifact_details", None)

    if ad_model is not None:
        # Full list from data[]
        if isinstance(ad_model.data, list):
            artifact_rows.extend([r for r in ad_model.data if isinstance(r, dict)])

        # Flattened single-row projection on the model
        root_like_row: Dict[str, Any] = {}
        for field_name, field_value in ad_model.dict(exclude_none=True).items():
            if field_name == "data":
                continue
            root_like_row[field_name] = field_value
        if root_like_row:
            artifact_rows.append(root_like_row)

    if not artifact_rows:
        tr = TestResult(
            test_number=25,
            name=test_name,
            result=Result.FAIL,
            message="Information Flows / Paths artifact not found (no artifact details available).",
        )
        status.add(tr)
        logger.error("[T25] FAIL — ctx.artifact_details is missing or empty.")
        return tr

    # Filter to this system if the payload is org-wide.
    sys_id_str = str(ctx.system_id)
    rows_with_sid = [r for r in artifact_rows if _row_system_id(r)]
    if rows_with_sid:
        artifact_rows = [r for r in rows_with_sid if _row_system_id(r) == sys_id_str]

    if not artifact_rows:
        tr = TestResult(
            test_number=25,
            name=test_name,
            result=Result.FAIL,
            message="Information Flows / Paths artifact not found for this system.",
        )
        status.add(tr)
        logger.error(
            "[T25] FAIL — artifact details exist, but none match system_id=%s.",
            sys_id_str,
        )
        return tr

    # ------------------------------------------------------------------
    # Step 2. Find the "Information Flows Paths Diagram" artifact
    #
    # We match by exact-ish artifact name (case-insensitive, trimmed).
    # ------------------------------------------------------------------

    TARGET_NAME = "information flows paths diagram"

    def _is_info_flows_paths(row: Dict[str, Any]) -> bool:
        name_raw = _ci_get(row, "Artifact Name", "artifactName")
        if not isinstance(name_raw, str):
            return False
        return name_raw.strip().lower() == TARGET_NAME

    flow_rows = [r for r in artifact_rows if _is_info_flows_paths(r)]
    if not flow_rows:
        tr = TestResult(
            test_number=25,
            name=test_name,
            result=Result.FAIL,
            message="Information Flows / Paths artifact was not found.",
        )
        status.add(tr)
        logger.error(
            "[T25] FAIL — no artifact named 'Information Flows Paths Diagram'."
        )
        return tr

    # ------------------------------------------------------------------
    # Step 3. Among matches, get the newest Last Modified timestamp
    #
    # PowerShell grabbed a timestamp but had a bug (it echoed a different var).
    # We fix that — we consistently read from the same row we're evaluating.
    # ------------------------------------------------------------------

    candidates: List[Tuple[int, Optional[str], Dict[str, Any]]] = []

    for row in flow_rows:
        last_mod_raw = _ci_get(
            row,
            "Last Modified",
            "lastModified",
            "last_modified",
            "lastmodified",
        )
        last_mod_epoch = _to_int_or_none(last_mod_raw)

        filename_raw = _ci_get(row, "Filename", "FileName", "filename", "file")
        filename = filename_raw.strip() if isinstance(filename_raw, str) else None

        if last_mod_epoch is not None:
            candidates.append((last_mod_epoch, filename, row))

    if not candidates:
        tr = TestResult(
            test_number=25,
            name=test_name,
            result=Result.FAIL,
            message="Information Flows / Paths artifact found, but 'Last Modified' date is missing.",
        )
        status.add(tr)
        logger.error(
            "[T25] FAIL — artifact present but all missing Last Modified timestamp."
        )
        return tr

    newest_epoch, newest_filename, _ = max(
        candidates,
        key=lambda t: t[0],
    )

    # ------------------------------------------------------------------
    # Step 4. Enforce freshness (≤ 365 days old)
    # ------------------------------------------------------------------

    ONE_YEAR_SECONDS = 365 * 24 * 60 * 60
    now_epoch = int(time.time())
    cutoff_epoch = now_epoch - ONE_YEAR_SECONDS

    newest_ymd = _epoch_to_ymd(newest_epoch)

    if newest_epoch <= cutoff_epoch:
        tr = TestResult(
            test_number=25,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Information Flows / Paths artifact is older than one year "
                f"(Last Modified: {newest_ymd})."
            ),
        )
        status.add(tr)
        logger.error(
            "[T25] FAIL — Last Modified too old: %s (file=%r)",
            newest_ymd,
            newest_filename,
        )
        return tr

    # ------------------------------------------------------------------
    # PASS
    # ------------------------------------------------------------------

    tr = TestResult(
        test_number=25,
        name=test_name,
        result=Result.PASS,
        message=(
            "Information Flows / Paths artifact is current "
            f"(Last Modified: {newest_ymd}); file: {newest_filename or 'N/A'}."
        ),
    )
    status.add(tr)
    logger.info(
        "[T25] PASS — diagram current as of %s (file=%r)",
        newest_ymd,
        newest_filename,
    )
    return tr

def test_26(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 26: Cloud Service Provider (CSP) / Cloud Service Offering (CSO) depicted in Network Topology.

    Goal
    ----
    We care about two things:
    1. Does a "Network Topology Diagram" artifact exist for this system?
    2. If the system is cloud-hosted, has anyone confirmed that diagram actually
       shows the CSP/CSO boundary and how traffic leaves/enters DoD space?

    Why this matters:
    - DoD Cloud Computing SRG expects the network topology to clearly depict the CSP /
      CSO, external connections, security stack, etc. That's how AO and SCA review
      shared responsibility and inherited protections.
    - eMASS doesn't expose diagram content. We only know the artifact exists, not
      whether it's correct.
    - So for cloud systems we raise CONCERN instead of PASS. A human has to look.

    Behavior / return codes
    -----------------------
    - FAIL
        No "Network Topology Diagram" artifact found.
    - N/A
        System is not cloud (cloud_computing == False).
        Diagram exists, but cloud rules don't apply.
    - CONCERN
        System is cloud (cloud_computing == True or unknown/None),
        diagram exists, but requires manual review to confirm CSP/CSO depiction.

    Data contract
    -------------
    ctx: SystemContext
        .system_id: int
        .cloud_computing: Optional[bool]
        .artifact_details: ArtifactDetails | None
            - artifact_details.data: list[dict] of artifacts for (potentially) many systems
            - plus flattened fields (artifact_name, filename, etc.) on the model itself

        Each artifact row may contain (case-insensitive keys):
            "Artifact Name"
            "System ID" / "systemId" / etc.

    We filter artifacts down to ctx.system_id when possible before evaluating.
    """

    test_name = "Test 26: CSP/CSO depicted in Network Topology Diagram"
    logger.debug("Running %s", test_name)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ci_get(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        """
        Case-insensitive dict getter across possible key variants.
        """
        if not isinstance(row, dict):
            return default
        lowered = {str(k).lower(): v for k, v in row.items()}
        for k in keys:
            if k.lower() in lowered:
                return lowered[k.lower()]
        return default

    def _row_system_id(row: Dict[str, Any]) -> str:
        """
        Try to pull a system identifier from the artifact row.
        Returns '' if not present.
        """
        return str(
            _ci_get(
                row,
                "System ID",
                "SystemID",
                "systemId",
                "system_id",
                "sysId",
                "id",
                default="",
            )
        )

    # ------------------------------------------------------------------
    # Step 1. Gather artifact rows for THIS system
    #
    # We look at:
    #   - ctx.artifact_details.data[]  (list of artifacts)
    #   - a pseudo-row synthesized from ctx.artifact_details' own top-level
    #     fields (artifact_name, filename, etc.). This covers cases where
    #     there's only a single artifact in the fixture and it's hoisted.
    # ------------------------------------------------------------------

    artifact_rows: list[dict] = []
    ad_model = getattr(ctx, "artifact_details", None)

    if ad_model is not None:
        # Full list under .data
        if isinstance(ad_model.data, list):
            artifact_rows.extend([r for r in ad_model.data if isinstance(r, dict)])

        # Flattened single-row projection from top-level fields on ArtifactDetails
        flattened_row: Dict[str, Any] = {}
        for field_name, field_value in ad_model.dict(exclude_none=True).items():
            if field_name == "data":
                continue
            flattened_row[field_name] = field_value
        if flattened_row:
            artifact_rows.append(flattened_row)

    if not artifact_rows:
        tr = TestResult(
            test_number=26,
            name=test_name,
            result=Result.FAIL,
            message="Network Topology Diagram artifact not found (no artifact details available).",
        )
        status.add(tr)
        logger.error("[T26] FAIL — ctx.artifact_details is missing or empty.")
        return tr

    # Narrow to our system_id if rows appear to be org-scoped.
    sys_id_str = str(ctx.system_id)
    rows_with_sid = [r for r in artifact_rows if _row_system_id(r)]
    if rows_with_sid:
        artifact_rows = [r for r in rows_with_sid if _row_system_id(r) == sys_id_str]

    if not artifact_rows:
        tr = TestResult(
            test_number=26,
            name=test_name,
            result=Result.FAIL,
            message="Network Topology Diagram artifact not found for this system.",
        )
        status.add(tr)
        logger.error(
            "[T26] FAIL — artifact records exist, but none match system_id=%s.",
            sys_id_str,
        )
        return tr

    # ------------------------------------------------------------------
    # Step 2. Check for "Network Topology Diagram"
    #
    # Match by exact-ish artifact name (case-insensitive, trimmed).
    # ------------------------------------------------------------------

    TARGET_NAME = "network topology diagram"

    def _is_network_topology(row: Dict[str, Any]) -> bool:
        name_raw = _ci_get(row, "Artifact Name", "artifactName", "artifact_name")
        if not isinstance(name_raw, str):
            return False
        return name_raw.strip().lower() == TARGET_NAME

    has_network_topology = any(_is_network_topology(r) for r in artifact_rows)

    if not has_network_topology:
        tr = TestResult(
            test_number=26,
            name=test_name,
            result=Result.FAIL,
            message="Network Topology Diagram artifact could not be found.",
        )
        status.add(tr)
        logger.error("[T26] FAIL — no artifact named 'Network Topology Diagram'.")
        return tr

    # ------------------------------------------------------------------
    # Step 3. Interpret cloud posture
    #
    # Rules:
    #   - If system is explicitly NOT cloud → N/A.
    #   - Else (True or None/unknown) → CONCERN.
    #
    # Rationale:
    #   We can't confirm visually whether the CSP/CSO boundary is drawn.
    #   For cloud systems, reviewer must verify manually.
    # ------------------------------------------------------------------

    cloud_flag = getattr(ctx, "cloud_computing", None)

    if cloud_flag is False:
        tr = TestResult(
            test_number=26,
            name=test_name,
            result=Result.NA,
            message="Test not applicable: system is not cloud-based.",
        )
        status.add(tr)
        logger.info("[T26] N/A — cloud_computing=False.")
        return tr

    tr = TestResult(
        test_number=26,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "Network Topology Diagram exists. Manual review required to confirm "
            "the CSP/CSO is clearly depicted per DoD Cloud Computing SRG."
        ),
    )
    status.add(tr)
    logger.warning(
        "[T26] CONCERN — cloud system; verify CSP/CSO depiction and external "
        "boundary/security stack in the Network Topology Diagram."
    )
    return tr


def test_27(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 27 — CAP connectivity depicted for sensitive data in Network Topology.

    Purpose
    -------
    We require systems (especially cloud systems handling sensitive data like CUI
    at IL4/IL5 or classified workloads at IL6) to document boundary connectivity
    via DoD CAP / BCAP in their network topology diagrams.

    This test enforces:
    - FAIL     → No "Network Topology Diagram" artifact at all.
    - N/A      → System is clearly *not* cloud-based.
    - CONCERN  → Diagram exists, and system *is* (or may be) cloud-based.
                 Human must verify the diagram shows CAP/BCAP connectivity.

    Why CONCERN instead of PASS?
    ----------------------------
    Artifact metadata doesn't include actual diagram content. We can prove the
    file exists and is recent-ish, but we cannot confirm that CAP/BCAP ingress/
    egress paths are depicted. So we raise CONCERN to force manual validation.

    Inputs from SystemContext (new contract)
    ----------------------------------------
    - ctx.artifact_details : ArtifactDetails | None
         - .data : list[dict] rows from ArtifactDetails.json
           Each row may include:
             "Artifact Name"
             "System ID"
             ...other descriptive fields...
         - The builder may also hoist one row's fields (filename, etc.)
           directly onto the model. We treat that as an additional row.

    - ctx.system_id : int
         Used to filter multi-system exports down to just "this" system.

    - ctx.cloud_computing : Optional[bool]
         True  → declared cloud system
         False → not cloud
         None  → unknown/unspecified, treat as potentially cloud
    """
    test_name = (
        "Test 27: CAP connectivity depicted in Network Topology for sensitive data"
    )
    logger.debug("Running %s", test_name)

    # -------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------
    def ci_get(row: Dict[str, Any], *keys: str, default=None):
        """
        Case-insensitive getter over possible key spellings.
        Example:
            ci_get(r, "Artifact Name", "artifactName")
        """
        if not isinstance(row, dict):
            return default
        lowered = {str(k).lower(): v for k, v in row.items()}
        for k in keys:
            hit = lowered.get(k.lower())
            if hit is not None:
                return hit
        return default

    def row_system_id(row: Dict[str, Any]) -> str:
        """
        Best-effort extraction of a system identifier from an artifact row.
        Returns "" if nothing usable exists.
        """
        return str(
            ci_get(
                row,
                "System ID",
                "SystemID",
                "systemId",
                "system_id",
                "sysId",
                "id",
                default="",
            )
        )

    def collect_artifact_rows() -> List[Dict[str, Any]]:
        """
        Normalize all artifact rows we can infer from ctx.artifact_details.

        We combine:
        1. ctx.artifact_details.data (list of dicts)
        2. a synthetic row built from the top-level fields of ctx.artifact_details
           (minus the .data attribute itself). This mirrors tests 24/25 behavior.

        Always returns a list[dict]; never raises.
        """
        rows: List[Dict[str, Any]] = []

        ad_model = getattr(ctx, "artifact_details", None)
        if ad_model is None:
            return rows

        # 1. the primary list
        if isinstance(ad_model.data, list):
            rows.extend([r for r in ad_model.data if isinstance(r, dict)])

        # 2. treat the model's own fields (except .data) like one more artifact row
        root_like_row: Dict[str, Any] = {}
        for field_name, field_value in ad_model.dict(exclude_none=True).items():
            if field_name == "data":
                continue
            root_like_row[field_name] = field_value
        if root_like_row:
            rows.append(root_like_row)

        return rows

    # -------------------------------------------------------------
    # Step 1. Gather candidate artifact rows and scope them to this system
    # -------------------------------------------------------------
    all_rows = collect_artifact_rows()

    # If the feed is org-wide (lots of system IDs), only keep rows
    # where System ID == ctx.system_id. If rows don't advertise a system ID,
    # assume they're already scoped and keep them all.
    sys_id_str = str(ctx.system_id)

    rows_with_sid = [r for r in all_rows if row_system_id(r)]
    if rows_with_sid:
        scoped_rows = [
            r for r in rows_with_sid if row_system_id(r) == sys_id_str
        ]
    else:
        scoped_rows = all_rows

    # -------------------------------------------------------------
    # Step 2. Confirm presence of "Network Topology Diagram"
    # -------------------------------------------------------------
    TARGET_NAME = "network topology diagram"

    def is_network_topology(row: Dict[str, Any]) -> bool:
        name_raw = ci_get(row, "Artifact Name", "artifactName")
        if not isinstance(name_raw, str):
            return False
        return name_raw.strip().lower() == TARGET_NAME

    has_network_topology = any(is_network_topology(r) for r in scoped_rows)

    if not has_network_topology:
        tr = TestResult(
            test_number=27,
            name=test_name,
            result=Result.FAIL,
            message="Network Topology Diagram artifact not found.",
        )
        status.add(tr)
        logger.error("[T27] FAIL — missing 'Network Topology Diagram' artifact.")
        return tr

    # -------------------------------------------------------------
    # Step 3. Interpret cloud posture
    #
    # - If system is explicitly NOT cloud → N/A.
    # - Otherwise (cloud=True or cloud=None) → CONCERN, because humans
    #   still have to verify CAP/BCAP routing in the diagram.
    # -------------------------------------------------------------
    cloud_flag = ctx.cloud_computing  # bool | None

    if cloud_flag is False:
        tr = TestResult(
            test_number=27,
            name=test_name,
            result=Result.NA,
            message="Test not applicable: system is not cloud-based.",
        )
        status.add(tr)
        logger.info("[T27] N/A — system not cloud-based.")
        return tr

    tr = TestResult(
        test_number=27,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "Network Topology Diagram exists. Manual verification required to confirm "
            "CAP/BCAP connectivity is depicted for IL4/IL5/IL6 scenarios."
        ),
    )
    status.add(tr)
    logger.warning(
        "[T27] CONCERN — diagram present; verify CAP/BCAP / boundary control path manually."
    )
    return tr

def test_28(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 28 — Network Topology aligns with declared cloud service model.

    Summary
    -------
    We expect a "Network Topology Diagram" artifact to exist. For systems that
    claim to be cloud-hosted, we can’t automatically confirm that the diagram
    actually reflects the declared hosting model (SaaS / PaaS / IaaS), so we
    flag it for manual review.

    Behavior
    --------
    - FAIL:
        No artifact named exactly "Network Topology Diagram".
    - N/A:
        System is explicitly not cloud-based.
    - CONCERN:
        Artifact exists and system is (or might be) cloud-based. Human must
        confirm the diagram matches stated service model.

    Data Inputs (SystemContext)
    ---------------------------
    - ctx.artifact_details.data : List[Dict[str, Any]]
        Expected keys (case-insensitive):
            "Artifact Name"
            "System ID"
    - ctx.cloud_computing : Optional[bool]
    - ctx.is_saas / ctx.is_paas / ctx.is_iaas : Optional[bool]
      (used only to give the reviewer context in the message)
    """

    test_name = "Test 28: Network Topology aligns with cloud service model"
    logger.debug("Running %s", test_name)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _emit(result: Result, message: str, level: int) -> TestResult:
        """
        Create/log/register a TestResult in a consistent way.
        """
        tr_local = TestResult(
            test_number=28,
            name=test_name,
            result=result,
            message=message,
        )
        status.add(tr_local)
        logger.log(level, "[T28] %s", message)
        return tr_local

    def _ci_get(row: dict, *keys: str, default: str = "") -> str:
        """
        Case-insensitive dict getter. Returns first match (as string),
        or default if not present.
        """
        if not isinstance(row, dict):
            return default
        lowered = {str(k).lower(): v for k, v in row.items()}
        for k in keys:
            if k.lower() in lowered and lowered[k.lower()] is not None:
                return str(lowered[k.lower()])
        return default

    def _row_system_id(row: dict) -> str:
        """
        Extract a system ID from an artifact row under a bunch of possible keys.
        Returns '' if none found.
        """
        return _ci_get(
            row,
            "System ID",
            "SystemID",
            "systemId",
            "system_id",
            "sysId",
            "id",
            default="",
        )

    # -------------------------------------------------------------------------
    # Gather candidate artifacts
    # -------------------------------------------------------------------------

    # artifact_details is now structured (ArtifactDetails model).
    # The .data field is the list we used to call artifact_details_raw.
    artifact_rows = (ctx.artifact_details.data if ctx.artifact_details and ctx.artifact_details.data else [])
    if not isinstance(artifact_rows, list):
        artifact_rows = []

    sys_id_str = str(ctx.system_id)

    # Prefer artifacts either explicitly scoped to this system_id,
    # falling back to global artifacts if nothing matches.
    scoped_rows = [
        row for row in artifact_rows
        if not _row_system_id(row) or _row_system_id(row) == sys_id_str
    ] or artifact_rows

    TARGET_NAME = "network topology diagram"

    has_network_topology = any(
        _ci_get(row, "Artifact Name", "artifactName").strip().lower() == TARGET_NAME
        for row in scoped_rows
    )

    if not has_network_topology:
        return _emit(
            Result.FAIL,
            "Network Topology Diagram artifact not found.",
            logging.ERROR,
        )

    # -------------------------------------------------------------------------
    # Evaluate based on cloud posture
    # -------------------------------------------------------------------------

    # cloud_computing is already normalized on SystemContext (bool or None).
    cloud_flag = ctx.cloud_computing

    # If we are explicitly *not* cloud-based, this test does not apply.
    if cloud_flag is False:
        return _emit(
            Result.NA,
            "Not applicable: system is not cloud-based.",
            logging.INFO,
        )

    # Otherwise (True or unknown): we have a diagram and we're at least partially
    # claiming some cloud service model. We can't auto-validate alignment,
    # so raise a CONCERN and provide SaaS/PaaS/IaaS hints for the reviewer.

    msg = (
        "Network Topology Diagram exists. Manually confirm it reflects the declared "
        f"cloud service model (SaaS={ctx.is_saas}, PaaS={ctx.is_paas}, IaaS={ctx.is_iaas})."
    )

    return _emit(
        Result.CONCERN,
        msg,
        logging.WARNING,
    )

def test_29(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 29 — DMZ whitelist entry present.

    Scope
    -----
    Validates whether an internet-accessible L4/L5 cloud system is registered
    on the DoD DMZ whitelist. The original PowerShell test **cannot** verify
    this automatically from eMASS/APMS and therefore always flags a concern.

    Behavior (parity with PowerShell)
    ---------------------------------
    - **CONCERN** unconditionally: eMASS/APMS do not expose DMZ whitelist data.
      A human must confirm in the SIPR portal
      (https://niprdmzwhitelist.csd.disa.smil.mil/home.aspx).

    Context surfaced (best-effort)
    ------------------------------
    We include hints if available to guide the reviewer:
      - whether the system is cloud-based,
      - whether it is marked public-facing.

    Inputs (SystemContext)
    ----------------------
    - `cloud_computing`: Optional[bool]
    - `public` (aka `isPublicFacing` in raw): Optional[bool]
    """
    test_name = "Test 29: DMZ whitelist entry"
    logger.debug("Running %s", test_name)

    # Pull optional hints for the reviewer; lack of data doesn't change result.
    cloud = getattr(ctx, "cloud_computing", None)
    public_facing = getattr(ctx, "public", None)

    hint_parts = []
    if cloud is not None:
        hint_parts.append(f"cloud={cloud}")
    if public_facing is not None:
        hint_parts.append(f"publicFacing={public_facing}")
    hint_suffix = f" Context: {', '.join(hint_parts)}." if hint_parts else ""

    tr = TestResult(
        test_number=29,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "eMASS/APMS do not expose DMZ whitelist data; manual verification on SIPR is required."
            + hint_suffix
        ),
    )
    status.add(tr)
    logger.warning("[T29] DMZ whitelist requires manual verification.%s", hint_suffix)
    return tr

def test_30(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 30 — Network Connection Rules / ISA artifact present.

    What this enforces
    ------------------
    We expect an Interconnection Security Agreement (ISA) document
    describing external connections into/out of the authorization boundary.
    This is a required part of boundary protection / external interfaces
    review.

    Outcomes:
      - PASS  → We found at least one "Interconnection Security Agreement"
                artifact. We surface the most recently reviewed one.
      - FAIL  → No such artifact exists.

    Why we surface filename
    -----------------------
    Humans still need to confirm that the ISA covers all external interfaces,
    and that it is actually signed/approved. The artifact row gives us a
    filename and timestamps, but not full contents.

    Inputs from SystemContext (new contract)
    ----------------------------------------
    - ctx.artifact_details : ArtifactDetails | None
        - .data : list[dict]
            Each dict is a row from ArtifactDetails.json and may include:
                "Artifact Name"
                "Filename"
                "Last Reviewed" (epoch seconds)
                "System ID"     (optional)
        - The builder may also copy one representative artifact row's fields
          (e.g. filename, last_modified, etc.) directly onto the model. We
          treat that as an additional row.

    - ctx.system_id : int
        Used to scope org-wide artifact dumps down to the current system.
    """
    test_name = "Test 30: Network Connection Rules / ISA"
    logger.debug("Running %s", test_name)

    # -------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------
    def ci_get(row: Dict[str, Any], *keys: str, default=None):
        """
        Case-insensitive getter across possible key spellings.
        Example:
            ci_get(r, "Artifact Name", "artifactName")
        """
        if not isinstance(row, dict):
            return default
        lowered = {str(k).lower(): v for k, v in row.items()}
        for k in keys:
            hit = lowered.get(k.lower())
            if hit is not None:
                return hit
        return default

    def row_system_id(r: Dict[str, Any]) -> str:
        """
        Extract a system identifier from a heterogeneous artifact row.
        Returns '' if nothing useful present.
        """
        return str(
            ci_get(
                r,
                "System ID",
                "SystemID",
                "systemId",
                "system_id",
                "sysId",
                "id",
                default="",
            )
        )

    def collect_artifact_rows() -> List[Dict[str, Any]]:
        """
        Build a normalized list of artifact row dicts from ctx.artifact_details.

        We merge:
          1. ctx.artifact_details.data (list of rows)
          2. one synthetic row made from the top-level fields of
             ctx.artifact_details (minus .data itself)

        Always returns list[dict]; never throws.
        """
        rows: List[Dict[str, Any]] = []

        ad_model = getattr(ctx, "artifact_details", None)
        if ad_model is None:
            return rows

        # (1) pull explicit rows from .data
        if isinstance(ad_model.data, list):
            rows.extend([r for r in ad_model.data if isinstance(r, dict)])

        # (2) treat the ArtifactDetails model itself as a possible single-row
        root_like_row: Dict[str, Any] = {}
        for field_name, field_value in ad_model.dict(exclude_none=True).items():
            if field_name == "data":
                continue
            root_like_row[field_name] = field_value
        if root_like_row:
            rows.append(root_like_row)

        return rows

    def parse_epoch_or_min(r: Dict[str, Any], *keys: str) -> int:
        """
        Return an integer epoch timestamp from the first matching key,
        or -1 if not parseable.

        We prefer 'Last Reviewed' for this test, since auditors usually
        care about when the ISA was last affirmed.
        """
        raw_val = None
        for k in keys:
            raw_val = ci_get(r, k)
            if raw_val is not None:
                break

        if raw_val is None:
            return -1
        try:
            # Handle strings like "1,708,569,600"
            if isinstance(raw_val, str):
                raw_val = raw_val.replace(",", "").strip()
            return int(raw_val)
        except Exception:
            return -1

    # -------------------------------------------------------------
    # Step 1. Gather all artifacts we know about
    # -------------------------------------------------------------
    all_rows = collect_artifact_rows()

    # Narrow to this system if the artifacts are org-wide (multiple system IDs).
    sys_id_str = str(ctx.system_id)
    rows_with_sid = [r for r in all_rows if row_system_id(r)]
    if rows_with_sid:
        scoped_rows = [
            r for r in rows_with_sid if row_system_id(r) == sys_id_str
        ]
    else:
        scoped_rows = all_rows

    # -------------------------------------------------------------
    # Step 2. Filter down to "Interconnection Security Agreement"
    # -------------------------------------------------------------
    TARGET_NAME = "interconnection security agreement"

    isa_rows = [
        r
        for r in scoped_rows
        if (
            (ci_get(r, "Artifact Name", "artifactName") or "")
            .strip()
            .lower()
            == TARGET_NAME
        )
    ]

    if not isa_rows:
        tr = TestResult(
            test_number=30,
            name=test_name,
            result=Result.FAIL,
            message="No Interconnection Security Agreement (ISA) artifact found.",
        )
        status.add(tr)
        logger.error("[T30] FAIL — ISA artifact not found.")
        return tr

    # -------------------------------------------------------------
    # Step 3. Choose the 'best' ISA
    #
    # Sort newest-first by "Last Reviewed" (epoch seconds).
    # If no timestamps, ordering is stable and we just take first.
    # -------------------------------------------------------------
    isa_rows.sort(
        key=lambda row: parse_epoch_or_min(
            row,
            "Last Reviewed",
            "lastReviewed",
            "Last_Reviewed",
            "last_reviewed",
        ),
        reverse=True,
    )
    latest = isa_rows[0]

    isa_filename = ci_get(
        latest,
        "filename",
        "fileName",
        "Filename",
        "file",
        default="(unnamed)",
    )

    # -------------------------------------------------------------
    # Step 4. PASS result
    #
    # We don't attempt staleness logic here (PowerShell didn't either for ISA,
    # and "Last Reviewed" doesn't always exist in export). We just assert it exists
    # and surface what to review.
    # -------------------------------------------------------------
    tr = TestResult(
        test_number=30,
        name=test_name,
        result=Result.PASS,
        message=(
            "ISA artifact present; "
            f"filename: {isa_filename}. Manual verification required "
            "to confirm completeness and currency."
        ),
    )
    status.add(tr)
    logger.info(
        "[T30] PASS — ISA artifact found; filename=%s",
        isa_filename,
    )
    return tr


def test_31(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 31 — Interconnected Information Systems & Identifiers (IISI) and ISA.

    This test mirrors the legacy PowerShell logic:

        - If IISI is null       → CONCERN
        - If IISI is not null
            - and ISA is null   → FAIL
            - and ISA is present→ PASS

    Only a true `null` (None) is treated as "not provided". An empty string is
    considered "provided" for parity with the original PowerShell behavior.

    Data sources (nested models only)
    ---------------------------------
    From `ctx.system_info` (SystemInfo):
        interconnectedinformationsystemsandidentifiers: Optional[str]
            Interconnected Information Systems and Identifiers (IISI).

    From `ctx.artifact_details` (ArtifactDetails):
        data: Optional[List[Dict[str, Any]]]
            Artifact rows. We infer ISA presence by searching for an
            "Interconnection Security Agreement" artifact name in these
            rows (case-insensitive), plus a synthetic row made from the
            top-level ArtifactDetails fields.

    Args:
        ctx: Populated `SystemContext` instance for the system under test.
        status: Aggregate ATOStatus collection to append this result to.

    Returns:
        TestResult: The outcome for Test 31.
    """

    test_number = 31
    test_name = "Test 31: Interconnected Information Systems & Identifiers"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    # ------------------------------------------------------------------
    # Helpers (nested-model only; no raw JSON access)
    # ------------------------------------------------------------------
    def ci_get(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        """Return the first matching key from `row` in a case-insensitive way."""
        if not isinstance(row, dict):
            return default
        lowered = {str(k).lower(): v for k, v in row.items()}
        for key in keys:
            val = lowered.get(key.lower())
            if val is not None:
                return val
        return default

    def collect_iisi() -> Optional[str]:
        """Return the IISI text from the SystemInfo model on the context."""
        sys_info_model = getattr(ctx, "system_info", None)
        if sys_info_model is None:
            return None
        return getattr(
            sys_info_model,
            "interconnectedinformationsystemsandidentifiers",
            None,
        )

    def collect_artifact_rows() -> List[Dict[str, Any]]:
        """Build a list of artifact row dicts from `ctx.artifact_details`."""
        rows: List[Dict[str, Any]] = []
        artifact_model = getattr(ctx, "artifact_details", None)
        if artifact_model is None:
            return rows

        # Rows from .data
        if isinstance(artifact_model.data, list):
            rows.extend([r for r in artifact_model.data if isinstance(r, dict)])

        # Synthetic row from artifact_model top-level fields (excluding .data)
        synthetic_row: Dict[str, Any] = {}
        for field_name, field_value in artifact_model.dict(exclude_none=True).items():
            if field_name == "data":
                continue
            synthetic_row[field_name] = field_value
        if synthetic_row:
            rows.append(synthetic_row)

        return rows

    def isa_present() -> bool:
        """Return True if an ISA artifact can be found for this system."""
        rows = collect_artifact_rows()
        if not rows:
            return False

        target_name = "interconnection security agreement"

        # If artifacts contain multiple systems, you could optionally filter
        # by system_id here. For now we match the original PS behavior by
        # only checking for presence of an ISA artifact by name.
        for row in rows:
            artifact_name = (ci_get(row, "Artifact Name", "artifact_name") or "").strip().lower()
            if artifact_name == target_name:
                return True
        return False

    # ------------------------------------------------------------------
    # Step 1: Evaluate IISI (PowerShell parity: only None is "not provided")
    # ------------------------------------------------------------------
    iisi_value = collect_iisi()
    logger.debug("[T%03d] IISI value (raw) = %r", test_number, iisi_value)

    if iisi_value is None:
        # PowerShell:
        #   CONCERN: The Interconnected Information Systems and Identifiers has not been
        #   provided, verify this is accurate.
        message = (
            "CONCERN: The Interconnected Information Systems and Identifiers has not "
            "been provided, verify this is accurate."
        )
        result = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.CONCERN,
            message=message,
        )
        status.add(result)
        logger.warning("[T%03d] CONCERN — IISI is null (not provided).", test_number)
        return result

    # At this point, IISI is considered "provided" (even if empty string).
    # ------------------------------------------------------------------
    # Step 2: Require ISA artifact when IISI is provided
    # ------------------------------------------------------------------
    if not isa_present():
        # PowerShell:
        #   Test Failed: The Interconnected Information Systems and Identifiers
        #   have been provided, but no ISA Artifact was found.
        message = (
            "Test Failed: The Interconnected Information Systems and Identifiers have "
            "been provided, but no ISA Artifact was found."
        )
        result = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(result)
        logger.error(
            "[T%03d] FAIL — IISI provided but ISA artifact not found.", test_number
        )
        return result

    # ------------------------------------------------------------------
    # PASS: IISI provided and ISA artifact is present
    # ------------------------------------------------------------------
    message = (
        "Test Passed: The Interconnected Information Systems and Identifiers have "
        "been provided and the ISA Artifact has been found."
    )
    result = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=message,
    )
    status.add(result)
    logger.info(
        "[T%03d] PASS — IISI provided and ISA artifact present.", test_number
    )
    return result


def test_32(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 32 — Encryption techniques documented for DAR/DIT (CUI/PII/PHI).

    Purpose
    -------
    Ensure encryption techniques protecting Data-at-Rest (DAR) and Data-in-Transit (DIT)
    are documented—especially for systems handling CUI/PII/PHI or CRN-IV.

    Behavior (parity with PowerShell)
    ---------------------------------
    - **CONCERN** unconditionally because eMASS/APMS payloads do not expose a
      structured list of encryption techniques via the API snapshots used here.
      Reviewer must manually verify artifacts and control inheritance.

    Notes
    -----
    If data model starts surfacing a structured field for techniques,
    upgrade this test to validate presence + basic content checks.
    """
    test_name = "Test 32: Encryption Techniques for DAR/DIT"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=32,
        name=test_name,
        result=Result.CONCERN,
        message="Encryption techniques not available via API; manual verification required.",
    )
    status.add(tr)
    logger.warning("[T32] Encryption techniques require manual verification.")
    return tr


def test_33(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 33 — Cryptographic Key Management Information present when handling CUI/PII/PHI.

    Purpose
    -------
    Validate that cryptographic key management information (PKI/CA/EKMS/KMI, etc.)
    is identified for systems processing sensitive data.

    Behavior (parity with PowerShell)
    ---------------------------------
    - If any of `cui`, `pii`, or `phi` is **True**:
        * **CONCERN** (data not exposed via API; reviewer must verify artifacts).
    - Else (no sensitive data flags):
        * **N/A**.

    Inputs (SystemContext)
    ----------------------
    - `cui`, `pii`, `phi`: Optional[bool]
    """
    test_name = "Test 33: Cryptographic Key Management Information"
    logger.debug("Running %s", test_name)

    handles_sensitive = any(bool(getattr(ctx, fld, False)) for fld in ("cui", "pii", "phi"))

    if handles_sensitive:
        tr = TestResult(
            test_number=33,
            name=test_name,
            result=Result.CONCERN,
            message="System processes CUI/PII/PHI; key management details must be verified manually (not exposed via API).",
        )
        status.add(tr)
        logger.warning("[T33] Sensitive data present; key management requires manual verification.")
        return tr

    tr = TestResult(
        test_number=33,
        name=test_name,
        result=Result.NA,
        message="Not applicable: system not flagged for CUI/PII/PHI.",
    )
    status.add(tr)
    logger.info("[T33] N/A — no sensitive data flags set.")
    return tr


def test_34(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 34 — Non-compliant / N/A controls must have a POA&M.

    Purpose
    -------
    For any security control that's not compliant, we expect a Plan of
    Actions & Milestones (POA&M) entry documenting mitigation, owner,
    milestones, funding, etc. This is a classic ATO gating rule.

    Behavior
    --------
    - Look at the system's control assessments/implementation status.
      Any control with a "bad" compliance status (like "NC") is considered
      an open weakness.
    - For each "bad" control, verify that at least one POA&M entry links
      back to that control (by acronym).
    - PASS → Every bad control has a POA&M.
    - FAIL → At least one bad control is missing POA&M coverage.

    Data contract (new SystemContext style)
    ---------------------------------------
    We DO NOT use ctx.controls_details_raw / test_results_raw / system_poam_details_raw.

    Instead we rely on the typed models already hydrated by the builder:

    - ctx.controls : Controls | None
        .data : list[dict] of individual controls
        top-level fields like:
            - acronym
            - compliancestatus
            - etc.
      We treat both .data rows and the top-level snapshot as candidate rows.

    - ctx.test_results : TestResults | None
        .data : list[dict]
        top-level fields (same idea).
      We use this as a fallback source for control compliance rows because some
      eMASS exports put per-control compliance in TestResults instead of Controls.

    - ctx.system_poam_dashboard : SystemPOAMDashboard | None
        .data : list[dict] of POA&M items
        top-level fields that may include control mapping fields, e.g.
            control_criticality, control_title, etc.
      We'll treat any case-insensitive key that looks like "controlAcronym" or
      "control_acronym" etc. as the link back to a control.

    Notes on matching
    -----------------
    - We case-fold acronyms (lowercase compare).
    - We consider these control status tokens as "requires POA&M":
        {"nc", "[redacted]"}
      (This mirrors the legacy script's intent.)
    """
    test_name = "Test 34: Non-compliant/NA controls must have a POA&M"
    logger.debug("Running %s", test_name)

    # -------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------
    def ci_get(d: Dict[str, Any], *keys: str, default=None):
        """
        Case-insensitive dict getter.
        Returns the first non-None hit for any of the provided keys.
        """
        if not isinstance(d, dict):
            return default
        lowered = {str(k).lower(): v for k, v in d.items()}
        for k in keys:
            v = lowered.get(k.lower())
            if v is not None:
                return v
        return default

    def rows_from_model(model_obj: Any) -> List[Dict[str, Any]]:
        """
        Normalize a Pydantic model like Controls / TestResults / SystemPOAMDashboard
        into a list of row dicts.

        We merge:
          1. model_obj.data (if it's a list[dict])
          2. a synthetic row built from top-level fields on the model,
             excluding 'data' itself. Some exports stuff a single control
             or single POA&M at the root instead of only using .data[].

        Always returns a list and never throws.
        """
        rows: List[Dict[str, Any]] = []
        if model_obj is None:
            return rows

        # (1) detailed rows in .data
        data_block = getattr(model_obj, "data", None)
        if isinstance(data_block, list):
            rows.extend([r for r in data_block if isinstance(r, dict)])

        # (2) flattened root row
        try:
            root_dict = model_obj.dict(exclude_none=True)
        except Exception:
            root_dict = {}
        if root_dict:
            root_row = {k: v for k, v in root_dict.items() if k != "data"}
            if any(v is not None for v in root_row.values()):
                rows.append(root_row)

        return rows

    # -------------------------------------------------------------
    # Step 1. Collect control-ish rows
    #
    # Some packages surface compliance status under Controls, some under
    # TestResults. We'll merge both, de-dupe later logically.
    # -------------------------------------------------------------
    control_rows: List[Dict[str, Any]] = []
    control_rows.extend(rows_from_model(getattr(ctx, "controls", None)))
    control_rows.extend(rows_from_model(getattr(ctx, "test_results", None)))

    # -------------------------------------------------------------
    # Step 2. Collect POA&M rows
    # -------------------------------------------------------------
    poam_rows: List[Dict[str, Any]] = rows_from_model(
        getattr(ctx, "system_poam_dashboard", None)
    )

    # Build a quick lookup set of control acronyms referenced in POA&M.
    # We'll lowercase for case-insensitive compare.
    poam_control_acronyms: set[str] = set()
    for p in poam_rows:
        acr = ci_get(
            p,
            "controlAcronym",
            "Control Acronym",
            "control_acronym",
            "controlacronym",
            "acronym",
            default="",
        )
        if isinstance(acr, str) and acr.strip():
            poam_control_acronyms.add(acr.strip().lower())

    # -------------------------------------------------------------
    # Step 3. Figure out which controls REQUIRE a POA&M
    # -------------------------------------------------------------
    REQUIRES_POAM = {"nc", "[redacted]"}  # matches legacy logic

    missing_poam_acronyms: List[str] = []

    for ctrl in control_rows:
        comp_status_raw = ci_get(
            ctrl,
            "complianceStatus",
            "compliance_status",
            "compliancestatus",
            default="",
        )
        status_token = (
            str(comp_status_raw).strip().lower() if comp_status_raw is not None else ""
        )

        # Only care if this control is non-compliant / requires tracking.
        if status_token not in REQUIRES_POAM:
            continue

        # What's the control acronym?
        acr_raw = ci_get(
            ctrl,
            "acronym",
            "Acronym",
            "controlAcronym",
            "control_acronym",
            "controlacronym",
            default="",
        )
        acronym = acr_raw.strip() if isinstance(acr_raw, str) else ""

        if not acronym:
            # If there's literally no acronym at all, that's also bad.
            missing_poam_acronyms.append("(unnamed-control)")
            continue

        # Does POA&M reference this acronym?
        if acronym.lower() not in poam_control_acronyms:
            missing_poam_acronyms.append(acronym)

    # -------------------------------------------------------------
    # Step 4. Produce the final result
    # -------------------------------------------------------------
    if not missing_poam_acronyms:
        tr = TestResult(
            test_number=34,
            name=test_name,
            result=Result.PASS,
            message=(
                "All non-compliant / not-applicable controls have matching POA&M entries."
            ),
        )
        status.add(tr)
        logger.info("[T34] PASS — all NC/[REDACTED] controls accounted for in POA&M.")
        return tr

    offenders_csv = ", ".join(sorted(set(missing_poam_acronyms)))
    tr = TestResult(
        test_number=34,
        name=test_name,
        result=Result.FAIL,
        message=f"Controls missing POA&M coverage: {offenders_csv}",
    )
    status.add(tr)
    logger.error("[T34] FAIL — missing POA&M for controls: %s", offenders_csv)
    return tr



def test_35(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 35 — Authorizing Official Repository (AO-R) registration present.

    Purpose
    -------
    Check whether the system is registered in the **Authorizing Official Repository (AO-R)**.

    Behavior (parity with PowerShell)
    ---------------------------------
    - **CONCERN** unconditionally — this check is external to eMASS/APMS and cannot
      be validated programmatically here. Reviewer must verify via AO-R references.

    Notes
    -----
    Reference locations (per original guidance):
    - RMF Knowledge Service → Collaboration → US Army Component Workspace → Policy.
    - Look for file named “CUI AO-R <date>”.
    """
    test_name = "Test 35: AO-R registration present"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=35,
        name=test_name,
        result=Result.CONCERN,
        message="External check: verify AO-R registration manually; cannot be validated via eMASS/APMS.",
    )
    status.add(tr)
    logger.warning("[T35] Manual verification required for AO-R.")
    return tr


def test_36(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 36 — Baseline Location present.

    Mirrors the legacy PowerShell logic:

        $MainLocation = $SystemDetailsSorted | Select-Object -ExpandProperty "Baseline Location"
        if ($null -eq $MainLocation) {
            FAIL: Location Information is not provided or undefined.
        } else {
            PASS: Location is: <MainLocation>
            Verify this information is accurate
        }

    Semantics
    ---------
    - If `SystemDetailsDashboard.baseline_location` is `None`:
        - Result: FAIL
        - Message: "FAIL: Location Information is not provided or undefined."
    - If `SystemDetailsDashboard.baseline_location` is *not* `None` (even if empty string):
        - Result: PASS
        - Message: "PASS: Location is: <value>. Verify this information is accurate"

    The test uses only the typed nested model `SystemDetailsDashboard` from the
    `SystemContext` and does not access any raw JSON payloads.

    Args:
        ctx: Fully-populated `SystemContext` instance for the system under test.
        status: Aggregated ATOStatus object that collects all TestResult entries.

    Returns:
        TestResult: The outcome for Test 36.
    """
    test_number = 36
    test_name = "Test 36: Baseline Location present"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    details = getattr(ctx, "system_details_dashboard", None)
    if details is None:
        logger.info("[T%03d] SystemDetailsDashboard is None.", test_number)
        message = "FAIL: Location Information is not provided or undefined."
        result = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(result)
        logger.error("[T%03d] FAIL — Baseline Location missing (no dashboard).", test_number)
        return result

    baseline_location = getattr(details, "baseline_location", None)
    logger.info(
        "[T%03d] Raw SystemDetailsDashboard.baseline_location: %r",
        test_number,
        baseline_location,
    )

    if baseline_location is None:
        # Optional: emit a structured dump for debugging when baseline is missing.
        try:
            details_dump = details.dict(exclude_none=False)
        except Exception:
            details_dump = repr(details)

        logger.info(
            "[T%03d] Baseline Location is None. Full SystemDetailsDashboard: %r",
            test_number,
            details_dump,
        )

        message = "FAIL: Location Information is not provided or undefined."
        result = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(result)
        logger.error("[T%03d] FAIL — Baseline Location missing.", test_number)
        return result

    # PowerShell considers any non-null value as "provided", without trimming.
    message = f"PASS: Location is: {baseline_location}. Verify this information is accurate"
    result = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=message,
    )
    status.add(result)
    logger.info(
        "[T%03d] PASS — Baseline Location present: %s",
        test_number,
        baseline_location,
    )
    return result



def test_37(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 37 — Deployment Locations provided.

    Mirrors the legacy PowerShell behavior:

        $DeployLocation = $SystemDetailsSorted | Select-Object -ExpandProperty "Deployment Locations"

        if ($null -eq $DeployLocation) {
            FAIL: Location Information is not provided or undefined.
        } else {
            PASS: Location is: <DeployLocation>
            Verify this information is accurate
        }

    Semantics
    ---------
    - We use only the structured `SystemDetailsDashboard` model attached to
      `SystemContext` and do not read any raw JSON payloads.
    - PASS if `deployment_locations` is *not* None, regardless of whether the
      string is empty or whitespace.
    - FAIL if `deployment_locations` is None.

    Args:
        ctx: Fully-populated `SystemContext` snapshot for the current system.
        status: Aggregated ATOStatus object collecting all TestResult entries.

    Returns:
        TestResult: The outcome for Test 37.
    """
    test_number = 37
    test_name = "Test 37: Deployment Locations present"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    details = getattr(ctx, "system_details_dashboard", None)
    if details is None:
        logger.info("[T%03d] SystemDetailsDashboard is None.", test_number)
        message = "FAIL: Location Information is not provided or undefined."
        result = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(result)
        logger.error("[T%03d] FAIL — Deployment Locations missing (no dashboard).", test_number)
        return result

    deploy_locations = getattr(details, "deployment_locations", None)
    logger.info(
        "[T%03d] Raw SystemDetailsDashboard.deployment_locations: %r",
        test_number,
        deploy_locations,
    )

    if deploy_locations is None:
        # Optional: structured dump for debug parity, still via the typed model.
        try:
            details_dump = details.dict(exclude_none=False)
        except Exception:
            details_dump = repr(details)

        logger.info(
            "[T%03d] Deployment Locations is None. Full SystemDetailsDashboard: %r",
            test_number,
            details_dump,
        )

        message = "FAIL: Location Information is not provided or undefined."
        result = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(result)
        logger.error("[T%03d] FAIL — Deployment Locations missing.", test_number)
        return result

    # PowerShell considers any non-null value as "provided" (no trimming, no blank check).
    message = f"PASS: Location is:  {deploy_locations}. Verify this information is accurate"
    result = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=message,
    )
    status.add(result)
    logger.info(
        "[T%03d] PASS — Deployment Locations present: %s",
        test_number,
        deploy_locations,
    )
    return result


import logging

logger = logging.getLogger(__name__)


def test_38(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 38 — Baseline Location provided.

    This test verifies that the system's baseline location is defined, mirroring
    the legacy PowerShell logic:

        if ($null -eq $MainLocation) {
            FAIL: Location Information is not provided or undefined.
        } else {
            PASS: Location is:  <MainLocation>
            Verify this information is accurate
        }

    Semantics
    ---------
    - Uses only the structured `SystemDetailsDashboard` model attached to
      `SystemContext`; no raw JSON payloads are inspected.
    - Treats any non-None value for `baseline_location` as "provided".
      Whitespace or empty strings are still considered present, matching the
      PowerShell `$null` check (which does not treat empty strings as null).
    - Fails only when `baseline_location` is `None`.

    Args:
        ctx: Fully-populated `SystemContext` snapshot for the current system.
        status: Aggregated `ATOStatus` accumulator that collects all test
            outcomes and maintains summary counters.

    Returns:
        TestResult: The outcome object for Test 38.
    """
    test_number = 38
    test_name = "Test 38: Baseline Location provided"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    details = getattr(ctx, "system_details_dashboard", None)
    if details is None:
        message = "FAIL: Location Information is not provided or undefined."
        result = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(result)
        logger.error(
            "[T%03d] FAIL — Baseline Location missing (SystemDetailsDashboard is None).",
            test_number,
        )
        return result

    baseline_location = getattr(details, "baseline_location", None)
    logger.info(
        "[T%03d] Raw SystemDetailsDashboard.baseline_location: %r",
        test_number,
        baseline_location,
    )

    if baseline_location is None:
        # Optional structured dump for debugging; still via the typed model,
        # not raw JSON blobs.
        try:
            details_dump = details.dict(exclude_none=False)
        except Exception:
            details_dump = repr(details)

        logger.info(
            "[T%03d] Baseline Location is None. Full SystemDetailsDashboard: %r",
            test_number,
            details_dump,
        )

        message = "FAIL: Location Information is not provided or undefined."
        result = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(result)
        logger.error("[T%03d] FAIL — Baseline Location missing.", test_number)
        return result

    # Parity with PowerShell: any non-None value counts as provided.
    message = (
        f"PASS: Location is:  {baseline_location}. "
        "Verify this information is accurate"
    )
    result = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=message,
    )
    status.add(result)
    logger.info(
        "[T%03d] PASS — Baseline Location present: %s",
        test_number,
        baseline_location,
    )
    return result


def test_39(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 39 — Physical Location(s) provided.

    This test verifies that the primary physical location fields are present on
    the structured `SystemDetailsDashboard` model, mirroring the legacy
    PowerShell behavior:

        $InstallationName = $SystemDetailsSorted | Select-Object -ExpandProperty "Installation Name (Primary Location)"
        $StreetAddress    = $SystemDetailsSorted | Select-Object -ExpandProperty "Street Address (Primary Location)"
        $InstallCity      = $SystemDetailsSorted | Select-Object -ExpandProperty "City (Primary Location)"
        $InstallState     = $SystemDetailsSorted | Select-Object -ExpandProperty "State (Primary Location)"
        $InstallZip       = $SystemDetailsSorted | Select-Object -ExpandProperty "Zip Code (Primary Location)"

        if ($null -eq $InstallationName -or
            $null -eq $StreetAddress   -or
            $null -eq $InstallCity     -or
            $null -eq $InstallState    -or
            $null -eq $InstallZip) {

            FAIL: Location information missing or undefined
        } else {
            PASS: Location information provided
        }

    Semantics
    ---------
    - Uses only the nested `SystemDetailsDashboard` model on `SystemContext`;
      raw JSON payloads are not inspected.
    - A field is considered **present** if its value is not ``None``.
      This is intentionally aligned with the PowerShell `$null` check and
      does **not** treat empty strings or placeholder values as missing.
    - Fails if any of the five required fields are ``None``; otherwise passes.

    Args:
        ctx: Snapshot of the current system, including `system_details_dashboard`.
        status: Aggregated ATO status object that collects all test results.

    Returns:
        TestResult: Outcome object for Test 39.
    """
    test_number = 39
    test_name = "Test 39: Physical Location(s) provided"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    details = getattr(ctx, "system_details_dashboard", None)

    if details is None:
        # If the dashboard itself is missing, all fields are effectively $null.
        installation_name = None
        street_address = None
        install_city = None
        install_state = None
        install_zip = None
    else:
        installation_name = details.installation_name_primary_location
        street_address = details.street_address_primary_location
        install_city = details.city_primary_location
        install_state = details.state_primary_location
        install_zip = details.zip_code_primary_location

    logger.info(
        "[T%03d] Physical location fields — Installation: %r, Street: %r, "
        "City: %r, State: %r, Zip: %r",
        test_number,
        installation_name,
        street_address,
        install_city,
        install_state,
        install_zip,
    )

    missing_any = any(
        value is None
        for value in (
            installation_name,
            street_address,
            install_city,
            install_state,
            install_zip,
        )
    )

    if missing_any:
        # Primary message matches PowerShell wording for parity.
        message = "FAIL: Location information missing or undefined"
        result = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(result)
        logger.error(
            "[T%03d] FAIL — Location information missing or undefined. "
            "Installation=%r, Street=%r, City=%r, State=%r, Zip=%r",
            test_number,
            installation_name,
            street_address,
            install_city,
            install_state,
            install_zip,
        )
        return result

    # All five fields are non-None → match PS "PASS: Location information provided".
    message = "PASS: Location information provided"
    result = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=message,
    )
    status.add(result)
    logger.info(
        "[T%03d] PASS — Location information provided. "
        "Installation=%r, Street=%r, City=%r, State=%r, Zip=%r",
        test_number,
        installation_name,
        street_address,
        install_city,
        install_state,
        install_zip,
    )
    return result



def test_40(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 40 — Security Plan (SP) approval within one year of SP workflow decision.

    What we're checking
    -------------------
    1. The system's Security Plan (SP) is marked Approved.
    2. We have a Security Plan approval *date* (epoch seconds).
    3. We have a recorded workflow decision for "Security Plan Approval".
    4. The approval happened AFTER that workflow decision, and within 1 year.
    5. A "Security Plan" artifact exists.

    Outcomes
    --------
    - FAIL
        * SP not approved
        * missing approval date or workflow decision date
        * approval is more than 1 year (> 31,536,000 seconds) after decision
        * no Security Plan artifact found
    - CONCERN
        * approval timestamp is <= workflow decision timestamp
          (chrono smells weird, but not an auto-fail)
    - PASS
        * approved, timestamps sane and within one year, artifact present

    Inputs (new-style SystemContext)
    --------------------------------
    - ctx.system_info : SystemInfo | None
        expected fields (case-insensitive variants handled):
            securityplanapprovalstatus
            securityplanapprovaldate
    - ctx.workflows : Workflows | None
        we look at .data (list[dict]) rows and try to find rows where:
            workflow == "Security Plan Approval" (case-insensitive)
            systemId matches ctx.system_id
        then we read lastEditedDate / lastediteddate.
    - ctx.artifact_details : ArtifactDetails | None
        we look at .data (list[dict]) rows where
            "Artifact Name" contains "Security Plan" (case-insensitive)
        then we read filename and lastReviewed/last_reviewed to pick newest.

    Notes
    -----
    - We use case-insensitive lookups, handle minor schema drift, and tolerate
      non-integer epoch-like values.
    - Epoch math is performed in seconds (UTC). One year = 31,536,000 seconds.
    """

    test_name = "Test 40: SP approved within one year of SP workflow"
    logger.debug("Running %s", test_name)

    ONE_YEAR_SECONDS = 31_536_000  # 365 days * 24h * 3600s

    # ---------------------------------------------------------------------
    # Helper utilities (kept local to avoid import churn in tests.py)
    # ---------------------------------------------------------------------
    def ci_get(d: dict, *keys: str, default=None):
        """
        Case-insensitive dict getter. Returns first non-None hit.
        """
        if not isinstance(d, dict):
            return default
        lowered = {str(k).lower(): v for k, v in d.items()}
        for k in keys:
            if k.lower() in lowered and lowered[k.lower()] is not None:
                return lowered[k.lower()]
        return default

    def to_int_or_none(v) -> Optional[int]:
        """
        Best-effort convert strings like "1708569600" or "1,708,569,600"
        or floats to an int (epoch seconds). Returns None on failure.
        """
        if v is None:
            return None
        try:
            s = str(v).replace(",", "").strip()
            if not s:
                return None
            return int(float(s))
        except Exception:
            return None

    def extract_sp_fields_from_system_info(si: Optional[SystemInfo]) -> tuple[str, Optional[int]]:
        """
        Pull SP approval status + date from ctx.system_info or its .dict().
        Returns (status_str, approval_epoch or None).
        """
        if si is None:
            return "", None

        # We'll look both at attributes and at si.dict() for robustness.
        si_dict: dict[str, Any] = {}
        try:
            si_dict = si.dict(exclude_none=False)
        except Exception:
            pass

        # direct attributes first
        status_attr = getattr(si, "securityplanapprovalstatus", None)
        date_attr = getattr(si, "securityplanapprovaldate", None)

        # if missing, fall back to dict keys in any case variant
        status_val = status_attr or ci_get(si_dict, "securityPlanApprovalStatus", "securityplanapprovalstatus")
        date_val = date_attr or ci_get(si_dict, "securityPlanApprovalDate", "securityplanapprovaldate")

        status_str = (status_val or "").strip() if isinstance(status_val, str) else str(status_val or "").strip()
        approval_epoch = to_int_or_none(date_val)

        return status_str, approval_epoch

    def latest_sp_workflow_decision_epoch(
        workflows_model: Optional[Workflows],
        system_id_val: int,
    ) -> Optional[int]:
        """
        Walk ctx.workflows.data (list[dict]) and:
        - keep only rows where workflow == 'Security Plan Approval' (ci compare),
        - and where the systemId matches ctx.system_id (if systemId is present).
        - then pick the newest lastEditedDate / lastediteddate epoch.
        """
        if workflows_model is None:
            return None

        rows = []
        # workflows_model.data can be Any, but we only care if it's list[dict]
        if isinstance(workflows_model.data, list):
            rows = [r for r in workflows_model.data if isinstance(r, dict)]

        if not rows:
            return None

        sys_id_str = str(system_id_val)

        def matches_sp_workflow(row: dict) -> bool:
            wf_name = ci_get(row, "workflow", "Workflow", default="") or ""
            return wf_name.strip().lower() == "security plan approval"

        def row_sys_id_ok(row: dict) -> bool:
            # If row has a systemId-ish field, require match; otherwise accept.
            row_sid = ci_get(row, "systemId", "System ID", "system_id", "id")
            if row_sid is None or str(row_sid).strip() == "":
                return True
            return str(row_sid).strip() == sys_id_str

        def edited_epoch(row: dict) -> Optional[int]:
            return to_int_or_none(
                ci_get(row, "lastEditedDate", "lastediteddate", "lastEdited", "lastedited")
            )

        # collect candidate epochs
        candidate_epochs = [
            edited_epoch(r)
            for r in rows
            if matches_sp_workflow(r) and row_sys_id_ok(r)
        ]
        candidate_epochs = [e for e in candidate_epochs if e is not None]

        if not candidate_epochs:
            return None

        # newest (max epoch)
        return max(candidate_epochs)

    def find_latest_security_plan_artifact(ad: Optional[ArtifactDetails]) -> tuple[Optional[dict], str]:
        """
        Search ctx.artifact_details.data for an artifact whose name contains
        'Security Plan' (case-insensitive). Return:
            (artifact_row_dict or None, filename_str)
        We pick the newest by 'Last Reviewed' / 'lastReviewed' / 'Signed Date'.
        """
        if ad is None:
            return None, ""

        rows = []
        if isinstance(ad.data, list):
            rows = [r for r in ad.data if isinstance(r, dict)]

        if not rows:
            return None, ""

        def is_security_plan(row: dict) -> bool:
            name_val = ci_get(row, "Artifact Name", "artifactName", "name", default="")
            name_str = (name_val or "").strip().lower()
            return "security plan" in name_str

        def reviewed_epoch(row: dict) -> int:
            raw = ci_get(
                row,
                "Last Reviewed",
                "lastReviewed",
                "Signed Date",
                "signedDate",
                "signed_date",
            )
            val = to_int_or_none(raw)
            return val if val is not None else -1  # -1 == ancient

        sp_candidates = [r for r in rows if is_security_plan(r)]
        if not sp_candidates:
            return None, ""

        sp_candidates.sort(key=reviewed_epoch, reverse=True)
        newest = sp_candidates[0]

        filename_val = ci_get(newest, "filename", "Filename", "fileName", "file", default="")
        filename_str = (filename_val or "").strip()
        return newest, filename_str

    # ---------------------------------------------------------------------
    # 1. Get SP approval status + timestamp from ctx.system_info
    # ---------------------------------------------------------------------
    sp_status_str, sp_approval_epoch = extract_sp_fields_from_system_info(ctx.system_info)

    if sp_status_str.lower() != "approved":
        tr = TestResult(
            test_number=40,
            name=test_name,
            result=Result.FAIL,
            message="Security Plan is not Approved. Check workflows and artifacts.",
        )
        status.add(tr)
        logger.error("[T40] FAIL — SP not approved (status=%r).", sp_status_str)
        return tr

    if sp_approval_epoch is None:
        tr = TestResult(
            test_number=40,
            name=test_name,
            result=Result.FAIL,
            message="Security Plan approval date is missing.",
        )
        status.add(tr)
        logger.error("[T40] FAIL — Missing SP approval epoch.")
        return tr

    # ---------------------------------------------------------------------
    # 2. Pull latest workflow decision timestamp for 'Security Plan Approval'
    # ---------------------------------------------------------------------
    wf_decision_epoch = latest_sp_workflow_decision_epoch(ctx.workflows, ctx.system_id)

    if wf_decision_epoch is None:
        tr = TestResult(
            test_number=40,
            name=test_name,
            result=Result.FAIL,
            message="Security Plan Approval workflow decision date not found.",
        )
        status.add(tr)
        logger.error("[T40] FAIL — Missing SP workflow decision date.")
        return tr

    # ---------------------------------------------------------------------
    # 3. Sanity check ordering + 1-year window
    # ---------------------------------------------------------------------
    delta_seconds = sp_approval_epoch - wf_decision_epoch
    logger.debug(
        "[T40] SP approval delta_seconds=%s (approval=%s, workflow_decision=%s)",
        delta_seconds,
        sp_approval_epoch,
        wf_decision_epoch,
    )

    if delta_seconds <= 0:
        tr = TestResult(
            test_number=40,
            name=test_name,
            result=Result.CONCERN,
            message="Security Plan approval date is ≤ workflow decision date; chronology appears inconsistent.",
        )
        status.add(tr)
        logger.warning("[T40] CONCERN — approval <= workflow decision.")
        return tr

    if delta_seconds > ONE_YEAR_SECONDS:
        tr = TestResult(
            test_number=40,
            name=test_name,
            result=Result.FAIL,
            message="Security Plan approval occurred more than one year after the workflow decision.",
        )
        status.add(tr)
        logger.error("[T40] FAIL — SP approval beyond one year (Δ=%s s).", delta_seconds)
        return tr

    # ---------------------------------------------------------------------
    # 4. Confirm we actually have a Security Plan artifact
    # ---------------------------------------------------------------------
    sp_art, sp_filename = find_latest_security_plan_artifact(ctx.artifact_details)

    if sp_art is None:
        tr = TestResult(
            test_number=40,
            name=test_name,
            result=Result.FAIL,
            message="Security Plan artifact not found.",
        )
        status.add(tr)
        logger.error("[T40] FAIL — SP artifact not found.")
        return tr

    # ---------------------------------------------------------------------
    # PASS
    # ---------------------------------------------------------------------
    tr = TestResult(
        test_number=40,
        name=test_name,
        result=Result.PASS,
        message=(
            "SP Approved within one year of workflow decision; "
            f"artifact present ({sp_filename or 'filename unavailable'})."
        ),
    )
    status.add(tr)
    logger.info(
        "[T40] PASS — SP approved within one year; artifact present: %s",
        sp_filename or "<unknown>",
    )
    return tr

def test_41(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 41 — System Life Cycle / Acquisition Phase provided and synchronized with APMS.

    Purpose
    -------
    Check that:
    1. eMASS lifecycle phase is populated.
    2. eMASS lifecycle phase makes sense next to APMS lifecycle phase.
    3. For later phases, the system has a valid authorization (ATO / ATO w/ Conditions / IATT).

    Mapping rules (from the legacy PowerShell logic)
    ------------------------------------------------
    eMASS lifecycle                          → APMS lifecycle must contain...
    --------------------------------------------------------------------------
    "Pre-Milestone A"                        → "Material Solution Analysis"
    "Post-Milestone A"                       → "Acquisition, Testing, & Deployment"
    "Post-Milestone B"                       → "Engineering & Manufacturing Development"
    "Post-Milestone C"                       → "Production & Deployment"
                                              and auth must be valid
    "Post-Full Rate Production/Deployment"   → "Operations & Support"
                                              and auth must be valid

    Outcomes
    --------
    - FAIL if lifecycle missing.
    - FAIL if mapping doesn't match, or required auth missing.
    - PASS if mapping matches (+auth when required).
    - If lifecycle is some weird unexpected value → FAIL with explanation.

    Inputs (SystemContext)
    ----------------------
    - ctx.lifecycle_phase          : Optional[str]
    - ctx.authorization_status     : Optional[str]
    - ctx.apms_first_row_raw       : Optional[Dict[str, Any]]
        We expect APMS row to expose something like "Life Cycle Phase Name".
        We'll read that case-insensitively.
    """

    test_name = "Test 41: System Life Cycle / Acquisition Phase Provided"
    logger.debug("Running %s", test_name)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _norm(s: Optional[str]) -> str:
        """Lowercase+strip string for robust comparisons."""
        if s is None:
            return ""
        return str(s).strip().lower()

    def _norm_contains(haystack: Optional[str], needle: str) -> bool:
        """Case-insensitive substring check."""
        return _norm(needle) in _norm(haystack)

    def _get_ci(d: dict, *keys: str) -> Optional[str]:
        """
        Case-insensitive key lookup. Returns first matching value (as str),
        or None if not found.
        """
        if not isinstance(d, dict):
            return None
        lowered = {str(k).lower(): v for k, v in d.items()}
        for k in keys:
            key_l = k.lower()
            if key_l in lowered and lowered[key_l] is not None:
                return str(lowered[key_l])
        return None

    def _has_valid_auth(auth_text: str) -> bool:
        """
        "Valid" means some recognized authorization posture:
        - Authorization To Operate (ATO)
        - ATO with Conditions
        - Interim Authorization To Test (IATT)
        We'll normalize/loosen wording to tolerate drift.
        """
        a = _norm(auth_text)
        return (
            "authorization to operate" in a
            or "ato w" in a        # catches "ATO w/ Conditions"
            or "ato with" in a
            or "iatt" in a
            or "interim authorization to test" in a
        )

    # ------------------------------------------------------------------
    # Pull context data
    # ------------------------------------------------------------------

    lifecycle_emass_raw = ctx.lifecycle_phase or ""
    lifecycle_emass_norm = _norm(lifecycle_emass_raw)

    if not lifecycle_emass_norm:
        tr = TestResult(
            test_number=41,
            name=test_name,
            result=Result.FAIL,
            message="Lifecycle Phase is not provided.",
        )
        status.add(tr)
        logger.error("[T41] FAIL — lifecycle_phase missing.")
        return tr

    auth_status_raw = ctx.authorization_status or ""
    apms_row = ctx.apms_first_row_raw or {}
    lifecycle_apms_raw = (_get_ci(apms_row, "Life Cycle Phase Name", "lifeCyclePhaseName") or "").strip()

    # ------------------------------------------------------------------
    # Decision matrix
    # ------------------------------------------------------------------

    # --- Pre-Milestone A ---
    if "pre-milestone a" in lifecycle_emass_norm:
        if _norm_contains(lifecycle_apms_raw, "material solution analysis"):
            tr = TestResult(
                test_number=41,
                name=test_name,
                result=Result.PASS,
                message=(
                    "Lifecycle matches APMS "
                    "(Pre-Milestone A ↔ Material Solution Analysis)."
                ),
            )
        else:
            tr = TestResult(
                test_number=41,
                name=test_name,
                result=Result.FAIL,
                message=(
                    "Lifecycle mismatch. Expected APMS to reference "
                    "'Material Solution Analysis'. "
                    f"eMASS='{lifecycle_emass_raw}', "
                    f"APMS='{lifecycle_apms_raw or '—'}'."
                ),
            )

        status.add(tr)
        logger.log(
            logging.INFO if tr.result == Result.PASS else logging.ERROR,
            "[T41] %s",
            tr.message,
        )
        return tr

    # --- Post-Milestone A ---
    if "post-milestone a" in lifecycle_emass_norm:
        if _norm_contains(lifecycle_apms_raw, "acquisition, testing, & deployment"):
            tr = TestResult(
                test_number=41,
                name=test_name,
                result=Result.PASS,
                message=(
                    "Lifecycle matches APMS "
                    "(Post-Milestone A ↔ Acquisition, Testing, & Deployment)."
                ),
            )
        else:
            tr = TestResult(
                test_number=41,
                name=test_name,
                result=Result.FAIL,
                message=(
                    "Lifecycle mismatch. Expected APMS to reference "
                    "'Acquisition, Testing, & Deployment'. "
                    f"eMASS='{lifecycle_emass_raw}', "
                    f"APMS='{lifecycle_apms_raw or '—'}'."
                ),
            )

        status.add(tr)
        logger.log(
            logging.INFO if tr.result == Result.PASS else logging.ERROR,
            "[T41] %s",
            tr.message,
        )
        return tr

    # --- Post-Milestone B ---
    if "post-milestone b" in lifecycle_emass_norm:
        if _norm_contains(lifecycle_apms_raw, "engineering & manufacturing development"):
            tr = TestResult(
                test_number=41,
                name=test_name,
                result=Result.PASS,
                message=(
                    "Lifecycle matches APMS "
                    "(Post-Milestone B ↔ Engineering & Manufacturing Development)."
                ),
            )
        else:
            tr = TestResult(
                test_number=41,
                name=test_name,
                result=Result.FAIL,
                message=(
                    "Lifecycle mismatch. Expected APMS to reference "
                    "'Engineering & Manufacturing Development'. "
                    f"eMASS='{lifecycle_emass_raw}', "
                    f"APMS='{lifecycle_apms_raw or '—'}'."
                ),
            )

        status.add(tr)
        logger.log(
            logging.INFO if tr.result == Result.PASS else logging.ERROR,
            "[T41] %s",
            tr.message,
        )
        return tr

    # --- Post-Milestone C ---
    if "post-milestone c" in lifecycle_emass_norm:
        # must have valid auth
        if not _has_valid_auth(auth_status_raw):
            tr = TestResult(
                test_number=41,
                name=test_name,
                result=Result.FAIL,
                message=(
                    "Systems in Post-Milestone C must have "
                    "ATO / ATO w/ Conditions / IATT. "
                    f"Authorization status is '{auth_status_raw or '—'}'."
                ),
            )
            status.add(tr)
            logger.error(
                "[T41] FAIL — missing valid auth for Post-Milestone C."
            )
            return tr

        # APMS must align
        if _norm_contains(lifecycle_apms_raw, "production & deployment"):
            tr = TestResult(
                test_number=41,
                name=test_name,
                result=Result.PASS,
                message=(
                    "Lifecycle matches APMS and valid auth present "
                    "(Post-Milestone C ↔ Production & Deployment)."
                ),
            )
        else:
            tr = TestResult(
                test_number=41,
                name=test_name,
                result=Result.FAIL,
                message=(
                    "APMS lifecycle does not align. Expected "
                    "'Production & Deployment'. "
                    f"eMASS='{lifecycle_emass_raw}', "
                    f"APMS='{lifecycle_apms_raw or '—'}'."
                ),
            )

        status.add(tr)
        logger.log(
            logging.INFO if tr.result == Result.PASS else logging.ERROR,
            "[T41] %s",
            tr.message,
        )
        return tr

    # --- Post-Full Rate Production/Deployment Decision ---
    if (
        "post-full rate production/deployment decision" in lifecycle_emass_norm
        or "post full rate production/deployment decision" in lifecycle_emass_norm
        or "post full rate" in lifecycle_emass_norm
        or "post-full rate" in lifecycle_emass_norm
    ):
        # must have valid auth
        if not _has_valid_auth(auth_status_raw):
            tr = TestResult(
                test_number=41,
                name=test_name,
                result=Result.FAIL,
                message=(
                    "Systems in Post-Full Rate Production/Deployment must have "
                    "ATO / ATO w/ Conditions / IATT. "
                    f"Authorization status is '{auth_status_raw or '—'}'."
                ),
            )
            status.add(tr)
            logger.error(
                "[T41] FAIL — missing valid auth for Post-Full Rate Production/Deployment."
            )
            return tr

        # APMS must align
        if _norm_contains(lifecycle_apms_raw, "operations & support"):
            tr = TestResult(
                test_number=41,
                name=test_name,
                result=Result.PASS,
                message=(
                    "Lifecycle matches APMS and valid auth present "
                    "(Post-Full Rate ↔ Operations & Support)."
                ),
            )
        else:
            tr = TestResult(
                test_number=41,
                name=test_name,
                result=Result.FAIL,
                message=(
                    "APMS lifecycle does not align. Expected "
                    "'Operations & Support'. "
                    f"eMASS='{lifecycle_emass_raw}', "
                    f"APMS='{lifecycle_apms_raw or '—'}'."
                ),
            )

        status.add(tr)
        logger.log(
            logging.INFO if tr.result == Result.PASS else logging.ERROR,
            "[T41] %s",
            tr.message,
        )
        return tr

    # ------------------------------------------------------------------
    # Fallback: lifecycle didn't match any known bucket.
    # ------------------------------------------------------------------
    tr = TestResult(
        test_number=41,
        name=test_name,
        result=Result.FAIL,
        message=(
            "Lifecycle value not recognized by policy mapping. "
            f"eMASS='{lifecycle_emass_raw}', "
            f"APMS='{lifecycle_apms_raw or '—'}'."
        ),
    )
    status.add(tr)
    logger.error(
        "[T41] FAIL — Unexpected lifecycle phase: %s",
        lifecycle_emass_raw,
    )
    return tr


def test_42(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 42 — Type Authorization is Yes.

    This test mirrors the legacy PowerShell behavior:

        $TypeAuthorization = $systemdata | Select-Object -ExpandProperty isTypeAuthorization

        if ($null -eq $TypeAuthorization) {
            "Fail: Type Authorization is not provided."
        } elseif ($TypeAuthorization -like "True") {
            "PASS: Type Authorization is Yes."
        } elseif ($TypeAuthorization -like "False") {
            "Fail: Type Authorization is No."
        } else {
            "Fail: Type Authorization is not in an expected value."
        }

    Data sources (structured models only)
    -------------------------------------
    Primary:
        - ctx.system_info.istypeauthorization : Optional[bool]
          Parsed from the eMASS "System Info" surface.

    Fallback:
        - ctx.system_details_dashboard.type_authorization : Optional[str]
          Parsed from the eMASS "System Details Dashboard" surface.

    Decision rules
    --------------
    - If both fields are absent (None):
        * FAIL with message: "Fail: Type Authorization is not provided."
    - If the resolved value is "True" (case-insensitive) or True:
        * PASS with message: "PASS: Type Authorization is Yes."
    - If the resolved value is "False" (case-insensitive) or False:
        * FAIL with message: "Fail: Type Authorization is No."
    - Any other non-None value:
        * FAIL with message: "Fail: Type Authorization is not in an expected value."

    Args:
        ctx: Snapshot of the current system, including typed eMASS models.
        status: Aggregated ATO status collector that tracks all test results.

    Returns:
        TestResult: Outcome object for Test 42.
    """
    test_number = 42
    test_name = "Test 42: Type Authorization is Yes"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    # ------------------------------------------------------------------
    # Helper: normalize to "true" / "false" / other for comparison
    # ------------------------------------------------------------------
    def classify_type_auth(value: object) -> str:
        """Classify the raw Type Authorization value.

        Returns:
            str: One of:
                - "missing"  → value is None
                - "true"     → value logically represents True
                - "false"    → value logically represents False
                - "other"    → non-None but not clearly true/false
        """
        if value is None:
            return "missing"

        if isinstance(value, bool):
            return "true" if value else "false"

        text = str(value).strip()
        if not text:
            # PowerShell would not treat empty string as $null, but our
            # typed models are unlikely to coerce that. Treat as "other"
            # so it lands in the "not in an expected value" bucket.
            return "other"

        lowered = text.lower()
        if "true" == lowered:
            return "true"
        if "false" == lowered:
            return "false"

        # PowerShell uses `-like "True"` / `-like "False"`; that is
        # substring matching. If you want to be extremely literal:
        if "true" in lowered:
            return "true"
        if "false" in lowered:
            return "false"

        return "other"

    # ------------------------------------------------------------------
    # Extract from structured context (no raw JSON)
    # ------------------------------------------------------------------
    raw_type_auth: object | None = None

    # Primary source: SystemInfo.istypeauthorization
    if ctx.system_info is not None:
        raw_type_auth = ctx.system_info.istypeauthorization

    # Fallback: SystemDetailsDashboard.type_authorization
    if raw_type_auth is None and ctx.system_details_dashboard is not None:
        raw_type_auth = ctx.system_details_dashboard.type_authorization

    classification = classify_type_auth(raw_type_auth)

    logger.info(
        "[T%03d] Type Authorization raw value=%r, classification=%s",
        test_number,
        raw_type_auth,
        classification,
    )

    # ------------------------------------------------------------------
    # Decision logic — mirror PowerShell messages and outcomes
    # ------------------------------------------------------------------
    if classification == "missing":
        message = "Fail: Type Authorization is not provided."
        result = Result.FAIL
        logger.error("[T%03d] FAIL — Type Authorization is not provided.", test_number)
    elif classification == "true":
        message = "PASS: Type Authorization is Yes."
        result = Result.PASS
        logger.info("[T%03d] PASS — Type Authorization is Yes.", test_number)
    elif classification == "false":
        message = "Fail: Type Authorization is No."
        result = Result.FAIL
        logger.error("[T%03d] FAIL — Type Authorization is No.", test_number)
    else:
        message = "Fail: Type Authorization is not in an expected value."
        result = Result.FAIL
        logger.error(
            "[T%03d] FAIL — Type Authorization not in an expected value (value=%r).",
            test_number,
            raw_type_auth,
        )

    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=result,
        message=message,
    )
    status.add(tr)
    return tr



def test_43(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 43 — Highest System Data Classification present.

    Purpose
    -------
    Ensure the system’s overall highest data classification is explicitly provided.

    Outcome
    -------
    - PASS: classification is present (echo value).
    - FAIL: classification is missing.

    Inputs (SystemContext)
    ----------------------
    Preferred: ctx.classification
    Fallback:  ctx.system_info.highestsystemdataclassification
    """
    test_name = "Test 43: Highest System Data Classification"
    logger.debug("Running %s", test_name)

    # 1. Prefer normalized value that the builder already surfaced
    classification = (ctx.classification or "").strip() if ctx.classification else ""

    # 2. Fallback: pull from structured model ctx.system_info
    if not classification and ctx.system_info and isinstance(ctx.system_info, SystemInfo):
        fallback_val = getattr(ctx.system_info, "highestsystemdataclassification", None)
        if isinstance(fallback_val, str):
            classification = fallback_val.strip()
        elif fallback_val is not None:
            classification = str(fallback_val).strip()

    # 3. If still nothing → FAIL
    if not classification:
        tr = TestResult(
            test_number=43,
            name=test_name,
            result=Result.FAIL,
            message="Classification not provided.",
        )
        status.add(tr)
        logger.error("[T43] Missing classification.")
        return tr

    # 4. Otherwise → PASS
    tr = TestResult(
        test_number=43,
        name=test_name,
        result=Result.PASS,
        message=f"The highest system classification is: {classification}",
    )
    status.add(tr)
    logger.info("[T43] Classification present: %s", classification)
    return tr

def test_44(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 44 — 'RMF Activity' identifies current RMF phase.

    Purpose
    -------
    Confirm the eMASS record includes the current RMF Activity phase text.

    Notes
    -----
    PowerShell guidance calls out specific defaults for *System Registration*,
    but this automated check only verifies presence; reviewers validate semantics.

    Outcome
    -------
    - PASS: RMF Activity present (echo value).
    - FAIL: RMF Activity missing.

    Inputs (SystemContext)
    ----------------------
    Preferred: ctx.rmf_activity
    Fallback:  ctx.system_info.rmfactivity
    """
    test_name = "Test 44: 'RMF Activity' identifies current RMF phase"
    logger.debug("Running %s", test_name)

    # 1. Prefer normalized/builder-surfaced field on the context
    rmf_activity = (ctx.rmf_activity or "").strip() if ctx.rmf_activity else ""

    # 2. Fallback to structured SystemInfo model if not provided at top-level
    if not rmf_activity and ctx.system_info and isinstance(ctx.system_info, SystemInfo):
        fallback_val = getattr(ctx.system_info, "rmfactivity", None)
        if isinstance(fallback_val, str):
            rmf_activity = fallback_val.strip()
        elif fallback_val is not None:
            rmf_activity = str(fallback_val).strip()

    # 3. If still nothing → FAIL
    if not rmf_activity:
        tr = TestResult(
            test_number=44,
            name=test_name,
            result=Result.FAIL,
            message="RMF Phase not provided.",
        )
        status.add(tr)
        logger.error("[T44] Missing RMF activity.")
        return tr

    # 4. Otherwise → PASS (human still validates correctness)
    tr = TestResult(
        test_number=44,
        name=test_name,
        result=Result.PASS,
        message=f"The RMF Phase is: {rmf_activity} (verify correctness).",
    )
    status.add(tr)
    logger.info("[T44] RMF activity present: %s", rmf_activity)
    return tr

def test_47(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 47 — Security Review field(s) answered.

    This test mirrors the legacy PowerShell behavior:

        $SecurityReviewReq          = $systemdata.securityReviewRequired
        $SecurityReviewCompleted    = $systemdata.securityReviewCompleted
        $SecurityReviewDate         = $systemdata.securityReviewCompletionDate
        $NextSecurityReviewDate     = $systemdata.nextSecurityReviewDueDate
        $SecurityReviewDateDiff     = $NextSecurityReviewDate - $SecurityReviewDate

        if ($null -eq any of the four fields) {
            "FAIL: Security Review Information is missing incomplete."
        } elseif ($SecurityReviewReq -like "True") {
            if ($SecurityReviewCompleted -like "True") {
                if ($SecurityReviewDateDiff -gt "31536000") {
                    "FAIL: Next Security Review date is greater than one year since previous review: yyyy-MM-dd"
                } else {
                    "PASS: Security Review equals yes, Security Review Completed and dated within one year."
                }
            } else {
                "FAIL: Security Review has not been completed"
            }
        } else {
            "FAIL: Security Review Required is not set to YES"
        }

    Data sources (typed models only)
    --------------------------------
    ctx.system_info (SystemInfo):

      - securityreviewrequired       : Optional[bool]
      - securityreviewcompleted      : Optional[bool]
      - securityreviewcompletiondate : Optional[int]  (epoch seconds)
      - nextsecurityreviewduedate    : Optional[int]  (epoch seconds)

    Args:
        ctx: Fully populated system snapshot, including SystemInfo.
        status: Aggregated ATO status collector for all tests.

    Returns:
        TestResult: Outcome object for Test 47.
    """
    import datetime  # local import to avoid polluting module namespace

    test_number = 47
    test_name = "Test 47: Security Review field(s) answered"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    ONE_YEAR_SECONDS = 31_536_000  # 365 * 24 * 60 * 60

    sys_info = ctx.system_info

    # If SystemInfo itself is missing, all fields are effectively missing.
    if sys_info is None:
        message = "FAIL: Security Review Information is missing incomplete."
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(tr)
        logger.error(
            "[T%03d] %s (SystemInfo is None)", test_number, message
        )
        return tr

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _is_true_or_false_like(value: object) -> Optional[bool]:
        """Best-effort replication of PowerShell `-like "True"/"False"` semantics.

        Returns:
            True  → value looks like a truthy "True".
            False → value looks like a falsy "False".
            None  → not interpretable as either.
        """
        if value is None:
            return None
        if isinstance(value, bool):
            return value

        text = str(value).strip()
        if not text:
            return None

        lowered = text.lower()
        # PowerShell `-like "True"` is case-insensitive and string-based.
        if "true" in lowered:
            return True
        if "false" in lowered:
            return False
        return None

    def _to_epoch_safe(value: object) -> Optional[int]:
        """Convert arbitrary numeric-ish input into epoch seconds."""
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _format_next_review_date(epoch_seconds: int) -> str:
        """Format next review date as yyyy-MM-dd, matching PowerShell output."""
        try:
            dt = datetime.datetime.utcfromtimestamp(epoch_seconds)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return f"epoch:{epoch_seconds}"

    def _fail(message: str) -> TestResult:
        """Create, record, and return a FAIL result."""
        tr_local = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(tr_local)
        logger.error("[T%03d] %s", test_number, message)
        return tr_local

    # ------------------------------------------------------------------
    # Extract fields from SystemInfo (no raw JSON)
    # ------------------------------------------------------------------
    required_raw = getattr(sys_info, "securityreviewrequired", None)
    completed_raw = getattr(sys_info, "securityreviewcompleted", None)
    completion_epoch_raw = getattr(sys_info, "securityreviewcompletiondate", None)
    next_due_epoch_raw = getattr(sys_info, "nextsecurityreviewduedate", None)

    # Presence check — exact parity with the PowerShell `$null` check.
    if (
        required_raw is None
        or completed_raw is None
        or completion_epoch_raw is None
        or next_due_epoch_raw is None
    ):
        return _fail("FAIL: Security Review Information is missing incomplete.")

    # Boolean interpretation mimicking `-like "True"` / `-like "False"`.
    required_flag = _is_true_or_false_like(required_raw)
    completed_flag = _is_true_or_false_like(completed_raw)

    # Epoch conversion
    completion_epoch = _to_epoch_safe(completion_epoch_raw)
    next_due_epoch = _to_epoch_safe(next_due_epoch_raw)

    # If epochs cannot be parsed, treat as missing/incomplete in practice.
    if completion_epoch is None or next_due_epoch is None:
        return _fail("FAIL: Security Review Information is missing incomplete.")

    review_date_diff = next_due_epoch - completion_epoch
    logger.info(
        "[T%03d] SecurityReviewRequired=%r (flag=%r), "
        "SecurityReviewCompleted=%r (flag=%r), "
        "completionEpoch=%r, nextDueEpoch=%r, diffSeconds=%r",
        test_number,
        required_raw,
        required_flag,
        completed_raw,
        completed_flag,
        completion_epoch,
        next_due_epoch,
        review_date_diff,
    )

    # ------------------------------------------------------------------
    # Branch logic — mirror PowerShell structure and messages
    # ------------------------------------------------------------------
    if required_flag is True:
        # Security Review Required == YES
        if completed_flag is True:
            # Completed == YES
            if review_date_diff > ONE_YEAR_SECONDS:
                next_due_human = _format_next_review_date(next_due_epoch)
                message = (
                    "FAIL: Next Security Review date is greater than one year "
                    f"since previous review: {next_due_human}"
                )
                return _fail(message)
            else:
                message = (
                    "PASS: Security Review equals yes, Security Review Completed "
                    "and dated within one year."
                )
                tr = TestResult(
                    test_number=test_number,
                    name=test_name,
                    result=Result.PASS,
                    message=message,
                )
                status.add(tr)
                logger.info("[T%03d] %s", test_number, message)
                return tr
        else:
            # Required == YES, but not completed.
            return _fail("FAIL: Security Review has not been completed")
    else:
        # Required is not set to YES.
        return _fail("FAIL: Security Review Required is not set to YES")


def test_48(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 48 — Contingency Plan field(s) answered.

    This test mirrors the legacy PowerShell behavior:

        $contingencyPlanRequired  = $systemdata.contingencyPlanRequired
        $contingencyPlanArtifact  = $systemdata.contingencyPlanArtifact
        $contingencyPlanTested    = $systemdata.contingencyPlanTested
        $contingencyPlanTestDate  = $systemdata.contingencyPlanTestDate
        $contingencyPlanDateDiff  = $TodayDate - $contingencyPlanTestDate

        if ($null -eq any of the four fields) {
            "FAIL: Contingency Plan information is missing Information is missing incomplete or no Artifact."
        } elseif ($contingencyPlanRequired -like "True") {
            if ($contingencyPlanTested -like "True") {
                if ($contingencyPlanDateDiff -gt "31536000") {
                    "FAIL: Contingency Plan test is greater than one year old."
                } else {
                    "PASS: Contingency Plan is required, artifact uploaded, Tested within this year."
                }
            } else {
                "FAIL: Contingency Plan has not been tested."
            }
        } else {
            "FAIL: Contingency Plan Required is not set to YES"
        }

    Data sources (typed models only)
    --------------------------------
    ctx.system_info (SystemInfo):

      - contingencyplanrequired   : Optional[bool]
      - contingencyplanartifact   : Optional[str]
      - contingencyplantested     : Optional[bool]
      - contingencyplantestdate   : Optional[int]  (epoch seconds)

    Args:
        ctx: Fully populated system snapshot, including SystemInfo.
        status: Aggregated ATO status collector for all tests.

    Returns:
        TestResult: Outcome object for Test 48.
    """
    import time

    test_number = 48
    test_name = "Test 48: Contingency Plan field(s) answered"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    one_year_seconds = 31_536_000  # 365 * 24 * 60 * 60

    sys_info = ctx.system_info
    if sys_info is None:
        message = (
            "FAIL: Contingency Plan information is missing "
            "Information is missing incomplete or no Artifact."
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(tr)
        logger.error("[T%03d] %s (SystemInfo is None)", test_number, message)
        return tr

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _is_true_like(value: object) -> Optional[bool]:
        """Return True if value matches PowerShell `-like "True"` semantics.

        This approximates PowerShell pattern matching by:
        - Treating bool True as True.
        - Treating case-insensitive string 'true' as True.
        - Treating other values as False or None when ambiguous.
        """
        if value is None:
            return None
        if isinstance(value, bool):
            return value

        text = str(value).strip()
        if not text:
            return None
        return text.lower() == "true"

    def _to_epoch_safe(value: object) -> Optional[int]:
        """Convert a numeric-ish input into epoch seconds.

        Returns:
            int: Epoch seconds if conversion succeeds.
            None: If value is missing or not convertible.
        """
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _now_epoch() -> int:
        """Return current time as epoch seconds."""
        return int(time.time())

    def _fail(message: str) -> TestResult:
        """Create, record, and return a FAIL result."""
        tr_local = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(tr_local)
        logger.error("[T%03d] %s", test_number, message)
        return tr_local

    # ------------------------------------------------------------------
    # Extract fields from typed SystemInfo (no raw JSON access)
    # ------------------------------------------------------------------
    required_raw = getattr(sys_info, "contingencyplanrequired", None)
    artifact_raw = getattr(sys_info, "contingencyplanartifact", None)
    tested_raw = getattr(sys_info, "contingencyplantested", None)
    test_date_raw = getattr(sys_info, "contingencyplantestdate", None)

    # Presence check — parity with `$null` checks in PowerShell.
    if (
        required_raw is None
        or artifact_raw is None
        or tested_raw is None
        or test_date_raw is None
    ):
        return _fail(
            "FAIL: Contingency Plan information is missing "
            "Information is missing incomplete or no Artifact."
        )

    required_flag = _is_true_like(required_raw)
    tested_flag = _is_true_like(tested_raw)
    test_epoch = _to_epoch_safe(test_date_raw)

    # If test date cannot be parsed, treat as missing/incomplete.
    if test_epoch is None:
        return _fail(
            "FAIL: Contingency Plan information is missing "
            "Information is missing incomplete or no Artifact."
        )

    now_epoch = _now_epoch()
    age_seconds = now_epoch - test_epoch

    logger.info(
        "[T%03d] contingencyPlanRequired=%r (flag=%r), "
        "contingencyPlanArtifact=%r, "
        "contingencyPlanTested=%r (flag=%r), "
        "contingencyPlanTestDateEpoch=%r, ageSeconds=%r",
        test_number,
        required_raw,
        required_flag,
        artifact_raw,
        tested_raw,
        tested_flag,
        test_epoch,
        age_seconds,
    )

    # ------------------------------------------------------------------
    # Branch logic — mirror PowerShell structure and messages
    # ------------------------------------------------------------------
    if required_flag is True:
        # Contingency Plan is required.
        if tested_flag is True:
            # Plan has been tested; now check recency.
            if age_seconds > one_year_seconds:
                # MATCH PS: "FAIL: Contingency Plan test is greater than one year old."
                return _fail("FAIL: Contingency Plan test is greater than one year old.")
            else:
                # MATCH PS: PASS string.
                message = (
                    "PASS: Contingency Plan is required, artifact uploaded, "
                    "Tested within this year."
                )
                tr = TestResult(
                    test_number=test_number,
                    name=test_name,
                    result=Result.PASS,
                    message=message,
                )
                status.add(tr)
                logger.info("[T%03d] %s", test_number, message)
                return tr
        else:
            # Required == YES, but not tested.
            return _fail("FAIL: Contingency Plan has not been tested.")
    else:
        # Required is not set to YES.
        return _fail("FAIL: Contingency Plan Required is not set to YES")


def test_49(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 49 — Incident Response Plan field(s) answered.

    This test mirrors the legacy PowerShell behavior:

        $incidentResponsePlanRequired = $systemdata.incidentResponsePlanRequired
        $incidentResponsePlanArtifact = $systemdata.incidentResponsePlanArtifact

        $incidentArtifact     = $ArtifactDetailsData | Where-Object {
                                    $_.filename -like "$incidentResponsePlanArtifact"
                                }
        $incidentArtifactdate = $incidentArtifact | Select-Object -ExpandProperty "Last Reviewed"

        if ($incidentResponsePlanRequired -like "True") {
            if (($null -eq $incidentResponsePlanArtifact -or $null -eq $incidentArtifactdate)
                -or ($incidentArtifactdate -le $OneYearAgoEpoch)) {
                "FAIL: The Incident Response Plan requires is Yes, but the Artifact "
                "is missing or older than one Year"
            } else {
                "PASS: The Incident Response Artifact is Present and current: <artifact>"
            }
        } else {
            "CONCERN: Incident response required is No, verify this is correct. "
        }

    Data sources (typed models only)
    --------------------------------
    SystemInfo (primary, mirrors `$systemdata` in PowerShell):
        - incidentresponseplanrequired    : Optional[bool]
        - incidentresponseplanartifact    : Optional[str]

    SystemContext (fallback if SystemInfo is missing/partial):
        - incident_response_plan_required : Optional[Any]
        - incident_response_plan_artifact : Optional[str]

    ArtifactDetails:
        - data: Optional[List[Dict[str, Any]]]
          Each row may contain:
            - "filename"
            - "Last Reviewed" (epoch seconds in string/int form)

    Result semantics
    ----------------
    PASS
        - Incident Response Plan Required is effectively "True".
        - Artifact name is present.
        - Matching artifact has "Last Reviewed" epoch > one-year-ago cutoff.

    FAIL
        - IRP required is "True", and
          - artifact name is null/empty, OR
          - matching artifact date is null, OR
          - matching artifact date ≤ one-year-ago epoch.

    CONCERN
        - IRP required is not "True".
        - Human must verify that "No" (or unknown) is acceptable.

    Args:
        ctx: System context containing typed eMASS surfaces.
        status: Aggregated ATO status to which this result is appended.

    Returns:
        TestResult: Outcome for Test 49.
    """

    test_number = 49
    test_name = "Test 49: Incident Response Plan field(s) answered"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    one_year_seconds = 31_536_000  # 365 * 24 * 60 * 60

    system_info = ctx.system_info
    artifact_details = ctx.artifact_details

    def _is_true_like(value: object) -> bool:
        """Return True if value matches PowerShell `-like "True"` semantics.

        PowerShell comparison:
            $incidentResponsePlanRequired -like "True"

        Implementation notes:
        - bool(True)                → True
        - case-insensitive "true"   → True
        - everything else           → False
        """
        if value is True:
            return True
        if value is None:
            return False
        text = str(value).strip()
        return text.lower() == "true"

    def _to_epoch(value: object) -> int | None:
        """Convert an arbitrary value to epoch seconds.

        Args:
            value: Raw value from the artifact metadata.

        Returns:
            int: Epoch seconds if conversion succeeds.
            None: If the value is null or not numeric-ish.
        """
        if value is None:
            return None
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None

    def _now_epoch() -> int:
        """Return current time in epoch seconds."""
        return int(time.time())

    def _fail(message: str) -> TestResult:
        """Create, log, and record a FAIL result."""
        result = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(result)
        logger.error("[T%03d] %s", test_number, message)
        return result

    def _concern(message: str) -> TestResult:
        """Create, log, and record a CONCERN result."""
        result = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.CONCERN,
            message=message,
        )
        status.add(result)
        logger.warning("[T%03d] %s", test_number, message)
        return result

    # ------------------------------------------------------------------
    # Extract required fields via nested models only (no raw JSON).
    # SystemInfo is authoritative because PowerShell uses `$systemdata`.
    # SystemContext top-level fields are a fallback when SystemInfo is
    # missing or incomplete.
    # ------------------------------------------------------------------
    required_raw: object | None = None
    artifact_name_raw: object | None = None

    if system_info is not None:
        required_raw = getattr(system_info, "incidentresponseplanrequired", None)
        artifact_name_raw = getattr(system_info, "incidentresponseplanartifact", None)

    # Fallback to promoted SystemContext fields if SystemInfo is missing/partial.
    if required_raw is None:
        required_raw = getattr(ctx, "incident_response_plan_required", None)
    if artifact_name_raw is None or str(artifact_name_raw).strip() == "":
        artifact_name_raw = getattr(ctx, "incident_response_plan_artifact", None)

    required_is_true = _is_true_like(required_raw)
    artifact_name = str(artifact_name_raw).strip() if artifact_name_raw is not None else ""

    # PowerShell `else` branch:
    #     else {
    #         "CONCERN: Incident response required is No, verify this is correct. "
    #     }
    if not required_is_true:
        return _concern(
            "CONCERN: Incident response required is No, verify this is correct. "
        )

    # From here on, IRP is required (`-like "True"` branch).
    now_epoch = _now_epoch()
    one_year_ago_epoch = now_epoch - one_year_seconds

    artifact_rows = (
        artifact_details.data
        if artifact_details is not None and isinstance(artifact_details.data, list)
        else []
    )

    matching_date_epoch: int | None = None
    if artifact_name and artifact_rows:
        for row in artifact_rows:
            if not isinstance(row, dict):
                continue
            filename = str(row.get("filename") or "").strip()
            if filename == artifact_name:
                # PowerShell: Select-Object -ExpandProperty "Last Reviewed"
                date_value = row.get("Last Reviewed")
                matching_date_epoch = _to_epoch(date_value)
                break

    # PowerShell condition:
    # if (($null -eq $incidentResponsePlanArtifact -or $null -eq $incidentArtifactdate)
    #     -or ($incidentArtifactdate -le $OneYearAgoEpoch))
    if (
        not artifact_name
        or matching_date_epoch is None
        or matching_date_epoch <= one_year_ago_epoch
    ):
        return _fail(
            "FAIL: The Incident Response Plan requires is Yes, but the Artifact is "
            "missing or older than one Year"
        )

    # PASS branch:
    # "PASS: The Incident Response Artifact is Present and current: $incidentResponsePlanArtifact"
    pass_message = (
        f"PASS: The Incident Response Artifact is Present and current: {artifact_name}"
    )
    result = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=pass_message,
    )
    status.add(result)
    logger.info(
        "[T%03d] %s (artifact=%s, lastReviewedEpoch=%s, oneYearAgoEpoch=%s)",
        test_number,
        pass_message,
        artifact_name,
        matching_date_epoch,
        one_year_ago_epoch,
    )
    return result




def test_51(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 51 — Disaster Recovery Plan (DRP)

    Goal
    ----
    Validate Disaster Recovery Plan posture and freshness.

    Policy logic:
    - If DRP "required" is not answered at all    → FAIL
    - If DRP "required" is explicitly False       → CONCERN (reviewer must confirm this is acceptable)
    - If DRP "required" is True:
        * Artifact name must be provided
        * Matching artifact must exist in artifacts list
        * Artifact must have a 'Last Reviewed' date within the last year

    Inputs (from SystemContext)
    ---------------------------
    ctx.system_info.disasterrecoveryplanrequired : Optional[bool-like]
    ctx.system_info.disasterrecoveryplanartifact : Optional[str]
    ctx.artifact_details.data                    : Optional[List[Dict]]

    We assume artifact_details.data rows include:
      - "filename"
      - some form of "Last Reviewed" timestamp (epoch seconds). Key names vary.
    """


    ONE_YEAR_SECONDS = 365 * 24 * 60 * 60
    test_name = "Test 51: Disaster Recovery Plan"
    logger.debug("Running %s", test_name)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _emit(result: Result, message: str, level: int) -> TestResult:
        """
        Create, log, and register a TestResult. Keeps the body readable.
        """
        tr_local = TestResult(
            test_number=51,
            name=test_name,
            result=result,
            message=message,
        )
        status.add(tr_local)
        logger.log(level, "[T51] %s", message)
        return tr_local

    def _to_bool_loose(v) -> Optional[bool]:
        """
        Normalize common truthy/falsey representations to bools.
        Returns None if we can't confidently interpret it.
        """
        if isinstance(v, bool):
            return v
        if v is None:
            return None
        s = str(v).strip().lower()
        if s in {"true", "yes", "y", "1"}:
            return True
        if s in {"false", "no", "n", "0"}:
            return False
        return None

    def _ci_get(d: dict, *keys: str) -> Optional[str]:
        """
        Case-insensitive getter across multiple candidate keys.
        Returns first non-None match as a string, else None.
        """
        if not isinstance(d, dict):
            return None
        lowered = {str(k).lower(): v for k, v in d.items()}
        for k in keys:
            val = lowered.get(k.lower())
            if val is not None:
                return str(val)
        return None

    def _parse_epoch(value: Any) -> Optional[int]:
        """
        Best-effort conversion of an arbitrary value into an int epoch.
        Returns None if invalid.
        """
        try:
            if value is None:
                return None
            s = str(value).strip()
            if not s:
                return None
            return int(float(s))
        except Exception:
            return None

    # -------------------------------------------------------------------------
    # Pull source data from the structured context
    # -------------------------------------------------------------------------

    sys_info = ctx.system_info or SystemInfo()  # safe fallback to empty model

    required_raw = sys_info.disasterrecoveryplanrequired
    artifact_name = (sys_info.disasterrecoveryplanartifact or "").strip()

    required_flag = _to_bool_loose(required_raw)

    # -------------------------------------------------------------------------
    # Required flag must be explicitly answered
    # -------------------------------------------------------------------------

    if required_flag is None:
        return _emit(
            Result.FAIL,
            "Disaster Recovery Plan 'required' is not defined.",
            logging.ERROR,
        )

    # If DRP is explicitly NOT required, we don't fail outright. We surface CONCERN
    # because policy often expects a DRP; humans need to sanity check this.
    if required_flag is False:
        return _emit(
            Result.CONCERN,
            "Disaster Recovery Plan is marked NOT required. Reviewer must confirm this is accurate.",
            logging.WARNING,
        )

    # -------------------------------------------------------------------------
    # DRP is required → verify artifact presence & freshness
    # -------------------------------------------------------------------------

    # Get the artifact rows we ingested for this system
    artifact_rows = (
        ctx.artifact_details.data
        if (ctx.artifact_details and ctx.artifact_details.data)
        else []
    )

    # Find any artifact rows whose filename matches the DRP artifact reference.
    # (PowerShell logic matched on filename equality.)
    matches = [
        row
        for row in artifact_rows
        if isinstance(row, dict)
        and str(row.get("filename") or "").strip() == artifact_name
    ]

    if not artifact_name or not matches:
        return _emit(
            Result.FAIL,
            "DRP is required, but no matching DRP artifact name was found in artifacts.",
            logging.ERROR,
        )

    # From matching artifacts, grab the newest 'Last Reviewed' timestamp.
    # Different exports spell this differently, so we try several keys.
    last_reviewed_epochs: list[int] = []
    for row in matches:
        epoch_candidate = _parse_epoch(
            _ci_get(
                row,
                "Last Reviewed",     # CSV-style
                "lastReviewed",      # camelCase-ish
                "last_reviewed",     # snake_case-ish
                "Signed Date",       # sometimes SP/DRP reuse "Signed Date"
                "signedDate",
                "signed_date",
            )
        )
        if epoch_candidate is not None:
            last_reviewed_epochs.append(epoch_candidate)

    newest_review_epoch = max(last_reviewed_epochs) if last_reviewed_epochs else None

    if newest_review_epoch is None:
        return _emit(
            Result.FAIL,
            "DRP artifact found, but no valid 'Last Reviewed' / signature date is recorded.",
            logging.ERROR,
        )

    # Check staleness: must be reviewed within the last year.
    one_year_ago_epoch = int(_time.time()) - ONE_YEAR_SECONDS
    if newest_review_epoch <= one_year_ago_epoch:
        return _emit(
            Result.FAIL,
            "DRP artifact is older than one year.",
            logging.ERROR,
        )

    # -------------------------------------------------------------------------
    # Passed all automated gates
    # -------------------------------------------------------------------------
    return _emit(
        Result.PASS,
        f"DRP is required, artifact '{artifact_name}' exists, and it was reviewed within the last year.",
        logging.INFO,
    )



def test_52(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 52 — Privacy Impact Assessment (PIA) presence + recency.

    Policy intent
    -------------
    We validate Privacy Impact Assessment (PIA) posture against policy:
    1. The system must explicitly answer whether a PIA is required.
    2. If the system says "PIA not required":
       - If the system is marked National Security System (NSS), that's allowed → N/A.
       - Otherwise, that's not allowed → FAIL.
    3. If the system says "PIA is required":
       - There must be a referenced PIA artifact.
       - There must be a PIA date.
       - That date must be within the last 3 years.

    Outcomes
    --------
    - FAIL:
        * PIA requirement not answered at all.
        * PIA marked not required for a non-NSS system.
        * PIA required but artifact missing / date missing / date > 3 years old.
    - N/A:
        * PIA not required AND system is NSS.
    - PASS:
        * PIA required, artifact given, and PIA date is ≤ 3 years old.

    Data contract (SystemContext)
    -----------------------------
    ctx.system_info : SystemInfo
        .privacyimpactassessmentrequired  : Optional[bool | str | int]
        .privacyimpactassessmentartifact  : Optional[str]
        .privacyimpactassessmentdate      : Optional[int]

    ctx.nss : Optional[bool]
        Whether the system is designated as a National Security System.

    Notes
    -----
    - We do not attempt content validation of the PIA. This test only checks
      existence, NSS exception logic, and age.
    """


    test_name = "Test 52: Privacy Impact Assessment (PIA)"
    logger.debug("Running %s", test_name)

    THREE_YEARS_SECONDS = 3 * 365 * 24 * 60 * 60
    now_epoch = int(time.time())

    sys_info = ctx.system_info

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _to_bool_loose(value: Any) -> Optional[bool]:
        """
        Convert common truthy/falsy shapes ("true", "1", "no", etc.) into bools.
        Returns None if we can't confidently parse it.
        """
        if isinstance(value, bool):
            return value
        if value is None:
            return None

        s = str(value).strip().lower()
        if s in {"true", "yes", "y", "1"}:
            return True
        if s in {"false", "no", "n", "0"}:
            return False
        return None

    def _to_int_or_none(value: Any) -> Optional[int]:
        """
        Best-effort convert value to int. Returns None if it can't be parsed.
        """
        try:
            if value is None:
                return None
            s = str(value).strip()
            if not s:
                return None
            return int(float(s))
        except Exception:
            return None

    def _emit(result: Result, message: str, level: int) -> TestResult:
        """
        Create a TestResult, record on status, and log consistently.
        """
        tr_local = TestResult(
            test_number=52,
            name=test_name,
            result=result,
            message=message,
        )
        status.add(tr_local)
        logger.log(level, "[T52] %s", message)
        return tr_local

    # -------------------------------------------------------------------------
    # Extract relevant fields from the typed context
    # -------------------------------------------------------------------------

    required_raw = getattr(sys_info, "privacyimpactassessmentrequired", None)
    artifact_raw = getattr(sys_info, "privacyimpactassessmentartifact", None)
    pia_date_raw = getattr(sys_info, "privacyimpactassessmentdate", None)

    required = _to_bool_loose(required_raw)
    artifact_name = (str(artifact_raw).strip() if artifact_raw is not None else "")
    pia_epoch = _to_int_or_none(pia_date_raw)

    # ctx.nss is already normalized by the builder (bool-ish),
    # but we'll run it through the helper in case it's "true"/"false" as string.
    nss_flag = _to_bool_loose(getattr(ctx, "nss", None))

    # -------------------------------------------------------------------------
    # Decision logic
    # -------------------------------------------------------------------------

    # 1. We must know whether a PIA is required at all.
    if required is None:
        return _emit(
            Result.FAIL,
            "PIA requirement flag is missing (cannot determine if a Privacy Impact Assessment is required).",
            logging.ERROR,
        )

    # 2. If PIA is *not* required:
    #    - NSS systems are exempt: N/A.
    #    - Non-NSS systems should FAIL.
    if required is False:
        if nss_flag is True:
            return _emit(
                Result.NA,
                "PIA is not required and the system is flagged as an NSS (exempt).",
                logging.INFO,
            )
        return _emit(
            Result.FAIL,
            "PIA marked as NOT REQUIRED for a non-NSS system. This is not allowed.",
            logging.ERROR,
        )

    # 3. If PIA *is* required:
    #    It must have an artifact reference and a recent date.
    if not artifact_name:
        return _emit(
            Result.FAIL,
            "PIA is REQUIRED but no PIA artifact reference was provided.",
            logging.ERROR,
        )

    if pia_epoch is None:
        return _emit(
            Result.FAIL,
            "PIA is REQUIRED and an artifact is referenced, "
            "but the PIA date is missing or invalid.",
            logging.ERROR,
        )

    age_seconds = now_epoch - pia_epoch
    if age_seconds > THREE_YEARS_SECONDS:
        return _emit(
            Result.FAIL,
            "PIA is REQUIRED but the last recorded PIA date is older than three years.",
            logging.ERROR,
        )

    # 4. All checks pass.
    return _emit(
        Result.PASS,
        f"PIA is REQUIRED, artifact '{artifact_name}' is provided, "
        "and the PIA date is within the last 3 years.",
        logging.INFO,
    )


def test_53(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 53 — Privacy Act SORN answered.

    This test validates that the Privacy Act System of Records Notice (SORN)
    required flag is explicitly answered, mirroring the legacy PowerShell
    implementation:

        $SORN = $systemdata | Select-Object -ExpandProperty privacyActSystemOfRecordsNoticeRequired

        if ($null -eq $SORN -or $SORN -like "-") {
            "FAIL: Privacy Act SORN question is not answered."
        } else {
            "PASS: Privacy Act SORN question is:  $SORN"
        }

    Semantics (parity with PowerShell)
    ----------------------------------
    - FAIL:
        * SORN flag is null / missing.
        * SORN flag is a literal "-" placeholder.
    - PASS:
        * Any other value (including False, empty string, "N/A", etc.) is
          treated as "answered" and passes the test.

    Data sources (typed models only)
    --------------------------------
    SystemContext:
        - system_info : Optional[SystemInfo]
            - privacyimpactsystemofrecordsnoticerequired : Optional[bool]
              (camelCase in JSON, snake_case in Pydantic:
               `privacyactsystemofrecordsnoticerequired`)

        - sorn_required : Optional[Any]
          Top-level rollup that may be populated by the builder; used as a
          fallback if `system_info.privacyactsystemofrecordsnoticerequired`
          is absent.

    Args:
        ctx: Fully-hydrated `SystemContext` for the target system.
        status: Mutable `ATOStatus` accumulator to which this result is appended.

    Returns:
        TestResult: Outcome for Test 53 with PowerShell-compatible messaging.
    """
    import logging

    test_number = 53
    test_name = "Test 53: Privacy Act SORN"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    def _to_display_token(value: object) -> str:
        """Render any input as a trimmed display token."""
        if value is None:
            return ""
        return str(value).strip()

    def _emit(result: Result, message: str, level: int) -> TestResult:
        """Create, record, and log a `TestResult` for this test."""
        tr_local = TestResult(
            test_number=test_number,
            name=test_name,
            result=result,
            message=message,
        )
        status.add(tr_local)
        logger.log(level, "[T%03d] %s", test_number, message)
        return tr_local

    # ----------------------------------------------------------------------
    # Extract SORN flag from typed models (no raw JSON access).
    # Primary source: SystemInfo. Fallback: top-level `sorn_required`.
    # ----------------------------------------------------------------------
    sys_info = ctx.system_info
    if sys_info is not None:
        sorn_raw: object | None = getattr(
            sys_info,
            "privacyactsystemofrecordsnoticerequired",
            None,
        )
    else:
        sorn_raw = None

    if sorn_raw is None:
        # Optional rollup fallback if the builder only populated the summary.
        sorn_raw = getattr(ctx, "sorn_required", None)

    # PowerShell behavior:
    #   if ($null -eq $SORN -or $SORN -like "-") { FAIL } else { PASS }
    if sorn_raw is None:
        return _emit(
            Result.FAIL,
            "FAIL: Privacy Act SORN question is not answered.",
            logging.ERROR,
        )

    sorn_display = _to_display_token(sorn_raw)

    if sorn_display == "-":
        return _emit(
            Result.FAIL,
            "FAIL: Privacy Act SORN question is not answered.",
            logging.ERROR,
        )

    # Any non-null, non-"-" value is treated as "answered", including False.
    # Message mirrors PowerShell:
    #   "PASS: Privacy Act SORN question is:  <value>"
    return _emit(
        Result.PASS,
        f"PASS: Privacy Act SORN question is:  {sorn_display}",
        logging.INFO,
    )


def test_54(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 54 — E-Authentication Risk Assessment field(s) answered.

    This test enforces parity with the legacy PowerShell implementation:

        $eAuthenticationRiskAssessmentRequired = $systemdata |
            Select-Object -ExpandProperty eAuthenticationRiskAssessmentRequired
        $eAuthenticationRiskAssessmentArtifact = $systemdata |
            Select-Object -ExpandProperty eAuthenticationRiskAssessmentArtifact
        $dataeAuthCompleteDate = $dataReport[0]."Risk Assessment Comp Plan Date"

        if ($null -eq $eAuthenticationRiskAssessmentRequired) {
            "FAIL: E-Authentication Risk Assesment question is not answered"
        } elseif ($eAuthenticationRiskAssessmentRequired -like "True") {
            if ($null -eq $eAuthenticationRiskAssessmentArtifact) {
                "FAIL: E-Auth Risk Assessment is Yes, but no artifact is provided"
            } elseif ($null -eq $dataeAuthCompleteDate) {
                "FAIL: data eAuthentication field was blank or could not be verified."
            } else {
                "PASS: E-Auth Risk Assesment required is Yes, and the Artifact name is: <artifact>"
            }
        } elseif ($eAuthenticationRiskAssessmentRequired -like "False") {
            "PASS: E-Auth Risk Assesment Required is No."
        }

    Semantics (mirrors PowerShell)
    ------------------------------
    - FAIL:
        * eAuthenticationRiskAssessmentRequired is null / missing.
        * eAuthenticationRiskAssessmentRequired is "True", but:
            - eAuthenticationRiskAssessmentArtifact is null, OR
            - APMS "Risk Assessment Comp Plan Date" is null.
    - PASS:
        * eAuthenticationRiskAssessmentRequired is "False".
        * eAuthenticationRiskAssessmentRequired is "True" AND:
            - eAuthenticationRiskAssessmentArtifact is non-null, AND
            - APMS "Risk Assessment Comp Plan Date" is non-null.

    Data sources (typed models only)
    --------------------------------
    SystemContext:
        system_info: SystemInfo
            eauthenticationriskassessmentrequired: Optional[bool]
            eauthenticationriskassessmentartifact: Optional[str]

        apms_first_row_raw: Optional[Dict[str, Any]]
            "Risk Assessment Comp Plan Date": Optional[str]

        eauth_required: Optional[Any]
            Top-level rollup used as a fallback when
            `system_info.eauthenticationriskassessmentrequired` is not populated.

    Args:
        ctx: Fully-hydrated `SystemContext` for the target system.
        status: Mutable `ATOStatus` accumulator to which this result is appended.

    Returns:
        TestResult: Outcome for Test 54 with PowerShell-compatible logic and messages.
    """
    import logging

    test_number = 54
    test_name = "Test 54: E-Authentication Risk Assessment field(s) answered"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    sys_info = ctx.system_info or SystemInfo()
    apms_row = ctx.apms_first_row_raw or {}

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------
    def _to_bool_loose(value: object | None) -> Optional[bool]:
        """Best-effort boolean coercion for required flags.

        Returns:
            True if the value semantically represents "yes".
            False if the value semantically represents "no".
            None if the value is missing or unrecognized.
        """
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        text = str(value).strip().lower()
        if text in {"true", "yes", "y", "1"}:
            return True
        if text in {"false", "no", "n", "0"}:
            return False
        return None

    def _normalize_str(value: object | None) -> str:
        """Normalize arbitrary input to a trimmed string for display."""
        if value is None:
            return ""
        return str(value).strip()

    def _emit(result: Result, message: str, level: int) -> TestResult:
        """Create, record, and log a `TestResult` for this test."""
        tr_local = TestResult(
            test_number=test_number,
            name=test_name,
            result=result,
            message=message,
        )
        status.add(tr_local)
        logger.log(level, "[T%03d] %s", test_number, message)
        return tr_local

    # ----------------------------------------------------------------------
    # Extract from typed context (no raw JSON)
    # ----------------------------------------------------------------------
    required_raw: object | None = getattr(
        sys_info, "eauthenticationriskassessmentrequired", None
    )

    # Fallback to top-level rollup if SystemInfo is not populated.
    if required_raw is None:
        required_raw = getattr(ctx, "eauth_required", None)

    artifact_raw: object | None = getattr(
        sys_info, "eauthenticationriskassessmentartifact", None
    )
    apms_completion_raw: object | None = apms_row.get(
        "Risk Assessment Comp Plan Date"
    )

    required_flag = _to_bool_loose(required_raw)
    artifact_name = _normalize_str(artifact_raw)

    # ----------------------------------------------------------------------
    # Decision logic — mirror the PowerShell branches
    # ----------------------------------------------------------------------

    # 1. Required question not answered at all.
    if required_raw is None or required_flag is None:
        return _emit(
            Result.FAIL,
            "FAIL: E-Authentication Risk Assesment question is not answered",
            logging.ERROR,
        )

    # 2. Required == True branch.
    if required_flag is True:
        # 2a. Artifact must be non-null (PowerShell only checks for $null).
        if artifact_raw is None:
            return _emit(
                Result.FAIL,
                "FAIL: E-Auth Risk Assessment is Yes, but no artifact is provided",
                logging.ERROR,
            )

        # 2b. APMS completion/plan date must be non-null.
        if apms_completion_raw is None:
            return _emit(
                Result.FAIL,
                "FAIL: data eAuthentication field was blank or could not be verified.",
                logging.ERROR,
            )

        # 2c. All good — mirror the exact PASS string, including typo.
        return _emit(
            Result.PASS,
            (
                "PASS: E-Auth Risk Assesment required is Yes, and the Artifact "
                f"name is: {artifact_name}"
            ),
            logging.INFO,
        )

    # 3. Required == False branch.
    # PowerShell message (typo and capitalization preserved):
    # "PASS: E-Auth Risk Assesment Required is No."
    if required_flag is False:
        return _emit(
            Result.PASS,
            "PASS: E-Auth Risk Assesment Required is No.",
            logging.INFO,
        )

    # Safety net: if we ever land here with a weird value, treat it as not answered.
    return _emit(
        Result.FAIL,
        "FAIL: E-Authentication Risk Assesment question is not answered",
        logging.ERROR,
    )



def test_55(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 55 — Mission Criticality matches APMS and Assess Only rules.

    This test mirrors the legacy PowerShell behavior:

        $dataMissionCrit    = $dataReport[0]."Mission Criticality"
        $MissionCriticality = $systemdata | Select-Object -ExpandProperty missionCriticality

        if ($MissionCriticality -like "Mission Support (MS)") { $MissionCriticality2 = "MS" }
        elseif ($MissionCriticality -like "Mission Essential (ME)") { $MissionCriticality2 = "ME" }
        elseif ($MissionCriticality -like "Mission Critical (MC)")  { $MissionCriticality2 = "MC" }

        if ($MissionCriticality2 -like $dataMissionCrit) {
            # Assess Only rules based on MissionCriticality2, CIA, and SystemType
            ...
        } else {
            "Fail: data mission criticality does not match eMASS"
        }

    In other words:

    * First, translate the eMASS mission criticality label to a short code
      (MC/ME/MS) and compare that code directly against the raw APMS value.
      If they do not match, the test FAILs immediately.

    * If they do match, and the registration type is "Assess Only", additional
      constraints are applied:
        - MC (Mission Critical) can never be Assess Only.
        - ME (Mission Essential) can be Assess Only only if all CIA are Low.
        - MS (Mission Support) can be Assess Only unless:
            • All CIA are High, or
            • SystemType is a Major Application.

    If registration is not Assess Only and the mission criticality values match,
    the test simply passes.

    Args:
        ctx: Fully built system context, including `SystemInfo`, dashboard
            fields, and APMS snapshot.
        status: Mutable ATOStatus accumulator to which this test result will
            be appended.

    Returns:
        TestResult: The outcome for Test 55 with PowerShell-compatible logic
        and message text.
    """
    import logging

    test_number = 55
    test_name = "Test 55: Mission Criticality matches APMS (Assess-Only rules)"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------
    def _emit(result: Result, message: str, level: int) -> TestResult:
        """Create, record, and log a TestResult for this test."""
        tr_local = TestResult(
            test_number=test_number,
            name=test_name,
            result=result,
            message=message,
        )
        status.add(tr_local)
        logger.log(level, "[T%03d] %s", test_number, message)
        return tr_local

    def _normalize_emass_mission_crit(raw: str | None) -> str | None:
        """Map eMASS mission criticality text to MC/ME/MS, like the PowerShell.

        The PowerShell script only translates values that look like:

            "Mission Support (MS)"
            "Mission Essential (ME)"
            "Mission Critical (MC)"

        Anything else is treated as unmapped (None).
        """
        if raw is None:
            return None
        text = raw.strip().lower()
        if not text:
            return None

        if "mission support (ms" in text:
            return "MS"
        if "mission essential (me" in text:
            return "ME"
        if "mission critical (mc" in text:
            return "MC"

        # Do not add extra mappings here if you want strict parity with PS.
        return None

    def _equals_ci(lhs: str | None, rhs: str) -> bool:
        """Case-insensitive equality helper."""
        if lhs is None:
            return False
        return lhs.strip().lower() == rhs.strip().lower()

    def _contains_ci(haystack: str | None, needle: str) -> bool:
        """Case-insensitive substring helper."""
        if haystack is None:
            return False
        return needle.lower() in haystack.lower()

    def _is_assess_only(reg_type: str | None) -> bool:
        """Determine whether the registration type indicates Assess Only."""
        return _contains_ci(reg_type, "assess only")

    # ----------------------------------------------------------------------
    # Pull context from structured models (no raw JSON)
    # ----------------------------------------------------------------------
    sys_info = ctx.system_info or SystemInfo()
    sys_dash = ctx.system_details_dashboard or SystemDetailsDashboard()

    # eMASS mission criticality (SystemInfo is the PowerShell source).
    emass_raw_mc = (
        getattr(sys_info, "missioncriticality", None)
        or getattr(sys_dash, "mission_criticality", None)
        or ctx.mission_criticality
    )
    emass_mc_code = _normalize_emass_mission_crit(emass_raw_mc)

    # APMS "Mission Criticality" comes from the APMS first-row snapshot.
    apms_row = ctx.apms_first_row_raw or {}
    apms_mc_raw = apms_row.get("Mission Criticality")

    # Registration type (to detect Assess Only).
    reg_type = (
        ctx.registration_type
        or getattr(sys_dash, "registration_type", None)
        or getattr(sys_info, "registrationtype", None)
    )

    # CIA from normalized context, falling back to SystemInfo/SystemDetails.
    confidentiality = (
        ctx.confidentiality
        or getattr(sys_info, "confidentiality", None)
        or getattr(sys_dash, "confidentiality", None)
    )
    integrity = (
        ctx.integrity
        or getattr(sys_info, "integrity", None)
        or getattr(sys_dash, "integrity", None)
    )
    availability = (
        ctx.availability
        or getattr(sys_info, "availability", None)
        or getattr(sys_dash, "availability", None)
    )

    # System type (for Major Application check).
    system_type = (
        ctx.system_type
        or getattr(sys_info, "systemtype", None)
        or getattr(sys_dash, "system_type", None)
    )

    logger.debug(
        "[T%03d] Derived values → emass_raw_mc=%r, emass_mc_code=%r, "
        "apms_mc_raw=%r, reg_type=%r, CIA=(%r, %r, %r), system_type=%r",
        test_number,
        emass_raw_mc,
        emass_mc_code,
        apms_mc_raw,
        reg_type,
        confidentiality,
        integrity,
        availability,
        system_type,
    )

    # ----------------------------------------------------------------------
    # Step 1: Mission criticality must match between eMASS and APMS
    # ----------------------------------------------------------------------
    # PowerShell behavior:
    #   if ($MissionCriticality2 -like $dataMissionCrit) { ... } else { FAIL }
    #
    # Here `MissionCriticality2` is the short code (MS/ME/MC) and
    # `dataMissionCrit` is the raw APMS string. There is no normalization of
    # the APMS value, so "MS" vs "Mission Support (MS)" will be treated as
    # a mismatch. We mirror this by comparing the code to the raw APMS string.
    if not emass_mc_code or apms_mc_raw is None:
        return _emit(
            Result.FAIL,
            "Fail: data mission criticality does not match eMASS",
            logging.ERROR,
        )

    if not _equals_ci(emass_mc_code, str(apms_mc_raw)):
        return _emit(
            Result.FAIL,
            "Fail: data mission criticality does not match eMASS",
            logging.ERROR,
        )

    # At this point, "data and eMASS match" from the PowerShell point of view.

    # ----------------------------------------------------------------------
    # Step 2: If registration is not Assess Only → PASS directly.
    # ----------------------------------------------------------------------
    if not _is_assess_only(reg_type):
        return _emit(
            Result.PASS,
            "PASS: data and eMASS match and Mission Criticality is correct",
            logging.INFO,
        )

    # ----------------------------------------------------------------------
    # Step 3: Registration is Assess Only — apply MC/CIA/SystemType rules.
    # ----------------------------------------------------------------------
    mc_code = emass_mc_code  # shorthand
    conf = (confidentiality or "").strip()
    integ = (integrity or "").strip()
    avail = (availability or "").strip()
    is_major_app = _contains_ci(system_type, "major application")

    # MC: cannot be Assess Only.
    if mc_code == "MC":
        return _emit(
            Result.FAIL,
            (
                "FAIL: data and eMASS match, but system cannot be Assess only "
                "and Mission Critical."
            ),
            logging.ERROR,
        )

    # ME: Assess Only allowed only if CIA all Low.
    if mc_code == "ME":
        is_all_low = (
            _equals_ci(conf, "Low")
            and _equals_ci(integ, "Low")
            and _equals_ci(avail, "Low")
        )
        if is_all_low:
            return _emit(
                Result.PASS,
                "PASS: data and eMASS match and Mission Criticality is correct",
                logging.INFO,
            )
        return _emit(
            Result.FAIL,
            (
                "FAIL: data and eMASS match, but system cannot be Assess only "
                "with provided criticality levels."
            ),
            logging.ERROR,
        )

    # MS: Assess Only allowed unless all CIA are High OR system is Major App.
    if mc_code == "MS":
        all_high = (
            _equals_ci(conf, "High")
            and _equals_ci(integ, "High")
            and _equals_ci(avail, "High")
        )
        if all_high or is_major_app:
            return _emit(
                Result.FAIL,
                (
                    "FAIL: data and eMASS match, but system cannot be Assess "
                    "only with provided criticality levels."
                ),
                logging.ERROR,
            )
        return _emit(
            Result.PASS,
            "PASS: data and eMASS match and Mission Criticality is correct",
            logging.INFO,
        )

    # Defensive fallback: unexpected mission criticality label.
    return _emit(
        Result.FAIL,
        f"Fail: data mission criticality does not match eMASS",
        logging.ERROR,
    )


def test_56(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 56 — Governing Mission Area matches APMS Mission Area.

    This test mirrors the legacy PowerShell logic:

        $governingMissionArea = $systemdata | Select-Object -ExpandProperty governingMissionArea
        $dataMissionArea      = $dataReport[0]."Mission Area"

        # translate eMASS data to match data
        if ($governingMissionArea -like "Enterprise Information Environment MA (EIEMA)") {
            $governingMissionArea2 = "EIEMA"
        } elseif ($governingMissionArea -like "Business MA (BMA)") {
            $governingMissionArea2 = "BMA"
        } elseif ($governingMissionArea -like "Warfighting MA (WMA)") {
            $governingMissionArea2 = "WMA"
        } elseif ($governingMissionArea -like "DoD portion of the Intelligence MA (DIMA)") {
            $governingMissionArea2 = "DIMA"
        }

        if ($dataMissionArea -like $governingMissionArea2) {
            "PASS: eMASS and data Mission Areas match."
        } else {
            "FAIL: eMASS and data Mission Areas do not match."
        }

    Behavior:
    * Read eMASS governing mission area from structured models.
    * Normalize it to one of: "EIEMA", "BMA", "WMA", "DIMA".
    * Compare APMS "Mission Area" to that normalized code.
    * PASS if they match (case-insensitive); otherwise FAIL.

    Args:
        ctx: Fully built system context for the target system.
        status: Mutable ATOStatus accumulator that collects all test results.

    Returns:
        TestResult: The outcome of Test 56, with PASS/FAIL and message text
        aligned to the PowerShell implementation.
    """
    import logging

    test_number = 56
    test_name = "Test 56: Governing Mission Area matches APMS Mission Area"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------
    def _emit(result: Result, message: str, level: int) -> TestResult:
        """Create, log, and record the TestResult for this test."""
        tr_local = TestResult(
            test_number=test_number,
            name=test_name,
            result=result,
            message=message,
        )
        status.add(tr_local)
        logger.log(level, "[T%03d] %s", test_number, message)
        return tr_local

    def _normalize_governing_mission_area(raw: str | None) -> str | None:
        """Normalize eMASS governing mission area text to EIEMA/BMA/WMA/DIMA.

        This mirrors the PowerShell `if`/`elseif` chain, but uses
        case-insensitive substring checks to be slightly more resilient
        to cosmetic formatting differences while preserving behavior.
        """
        if raw is None:
            return None

        text = raw.strip()
        if not text:
            return None

        lower_text = text.lower()

        if "enterprise information environment ma (eiema)" in lower_text or "eiema" in lower_text:
            return "EIEMA"
        if "business ma (bma)" in lower_text or "bma" in lower_text:
            return "BMA"
        if "warfighting ma (wma)" in lower_text or "wma" in lower_text:
            return "WMA"
        if "dod portion of the intelligence ma (dima)" in lower_text or "dima" in lower_text:
            return "DIMA"

        return None

    def _equals_ci(lhs: str | None, rhs: str | None) -> bool:
        """Return True if two strings are equal, ignoring case and whitespace."""
        if lhs is None or rhs is None:
            return False
        return lhs.strip().lower() == rhs.strip().lower()

    # ----------------------------------------------------------------------
    # Pull data from structured context (no raw JSON)
    # ----------------------------------------------------------------------
    sys_info = ctx.system_info or SystemInfo()
    sys_dash = ctx.system_details_dashboard or SystemDetailsDashboard()
    apms_row = ctx.apms_first_row_raw or {}

    # PowerShell source:
    #   $governingMissionArea = $systemdata | Select-Object -ExpandProperty governingMissionArea
    emass_area_raw = (
        getattr(sys_info, "governingmissionarea", None)
        or getattr(sys_dash, "governing_mission_area", None)
        or getattr(ctx, "governing_mission_area", None)
    )
    emass_area_code = _normalize_governing_mission_area(emass_area_raw)

    # PowerShell source:
    #   $dataMissionArea = $dataReport[0]."Mission Area"
    apms_area_raw = apms_row.get("Mission Area")
    apms_area_value = str(apms_area_raw).strip() if apms_area_raw is not None else None

    logger.debug(
        "[T%03d] Derived mission areas → eMASS_raw=%r, eMASS_code=%r, APMS_raw=%r",
        test_number,
        emass_area_raw,
        emass_area_code,
        apms_area_value,
    )

    # ----------------------------------------------------------------------
    # Match / mismatch semantics (PowerShell parity)
    # ----------------------------------------------------------------------
    # PowerShell has no special “missing info” branch; if the code does not
    # match the APMS value, it simply reports a generic FAIL.
    if emass_area_code is not None and _equals_ci(apms_area_value, emass_area_code):
        return _emit(
            Result.PASS,
            "PASS: eMASS and data Mission Areas match.",
            logging.INFO,
        )

    return _emit(
        Result.FAIL,
        "FAIL: eMASS and data Mission Areas do not match.",
        logging.ERROR,
    )


def test_57(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 57 — Acquisition Category matches APMS.

    Parity
    ------
    The legacy PowerShell implementation does **not** attempt to validate
    Acquisition Category alignment. Instead, it always emits:

        CONCERN: This test is unable to run due to a report issue with data, please verify manualy.

    and marks the test as CONCERN, regardless of system data.

    To preserve one-for-one behavior across toolchains, this Python test:
    * Does not inspect ``ctx`` at all.
    * Always returns ``Result.CONCERN``.
    * Uses the exact same message text (including spelling) as the
      PowerShell output so diff tooling stays clean.

    Args:
        ctx: SystemContext for the current system. Present for interface
            consistency, but not used by this test.
        status: Mutable ATOStatus accumulator that collects all test results.

    Returns:
        TestResult: The CONCERN result for Test 57.
    """
    test_number = 57
    test_name = "Test 57: Acquisition Category matches APMS"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    message = (
        "CONCERN: This test is unable to run due to a report issue with data, "
        "please verify manualy."
    )

    result = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.CONCERN,
        message=message,
    )
    status.add(result)
    logger.warning("[T%03d] %s", test_number, message)
    return result


def test_58(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 58 — Software Category matches APMS (Assess Only)

    Summary
    -------
    For systems on the "Assess Only" path, policy expects alignment between
    eMASS "Software Category" (e.g. COTS vs. GOTS) and APMS. Today we do *not*
    get those fields in a consistent, machine-checkable way from either feed.

    Because we can't verify this automatically, this test becomes a reminder:
    - If the system is Assess Only → raise CONCERN so a human checks.
    - Otherwise → N/A.

    Inputs (SystemContext)
    ----------------------
    - ctx.registration_type : Optional[str]
        Example values include "Assess Only", "Initial Authorization", etc.

    Results
    -------
    - CONCERN : registration_type indicates "Assess Only".
    - N/A     : all other registration types.
    """

    test_name = "Test 58: Software Category matches APMS (Assess Only)"
    logger.debug("Running %s", test_name)

    def _emit(result: Result, message: str, level: int) -> TestResult:
        """
        Record, log, and return a test result.
        Keeps return branches small and uniform.
        """
        tr_local = TestResult(
            test_number=58,
            name=test_name,
            result=result,
            message=message,
        )
        status.add(tr_local)
        logger.log(level, "[T58] %s", message)
        return tr_local

    reg_type_norm = (ctx.registration_type or "").strip().lower()

    # If this is an Assess Only package, we can't auto-verify COTS vs GOTS
    # alignment between eMASS and APMS. Flag for manual review.
    if "assess only" in reg_type_norm:
        return _emit(
            Result.CONCERN,
            (
                "Registration type is Assess Only. Automated COTS/GOTS alignment "
                "between eMASS and APMS is not supported; manual validation required."
            ),
            logging.WARNING,
        )

    # Otherwise this control doesn't apply.
    return _emit(
        Result.NA,
        "Not applicable: system is not on the Assess Only path.",
        logging.INFO,
    )



def test_59(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 59 — System Ownership / Control matches APMS "System Operation".

    Goal
    ----
    Determine whether eMASS ownership/operation assertions (e.g. DoD-owned and
    DoD-operated vs. DoD-owned but contractor-operated vs. partner-operated)
    align with APMS "System Operation".

    Why this is manual
    ------------------
    APMS exports we ingest do not consistently expose a normalized, machine-
    readable "System Operation" field that can be joined to eMASS ownership
    semantics. The legacy PowerShell script flagged this for reviewer judgment
    instead of auto-pass/fail.

    Behavior
    --------
    Always returns CONCERN to force human review. Reviewer should confirm:
    - Ownership / operational control in eMASS matches APMS.
    - Any contractor / partner operation is accurately disclosed.

    Result
    ------
    - CONCERN: Automated verification not currently possible.
    """
    test_name = "Test 59: System Ownership / Control matches APMS System Operation"
    logger.debug("Running %s", test_name)

    def _emit(result: Result, message: str, level: int) -> TestResult:
        """Create, log, and register a TestResult for this test."""
        tr_local = TestResult(
            test_number=59,
            name=test_name,
            result=result,
            message=message,
        )
        status.add(tr_local)
        logger.log(level, "[T59] %s", message)
        return tr_local

    return _emit(
        Result.CONCERN,
        "Ownership / operation alignment with APMS cannot be validated automatically; manual review required.",
        logging.WARNING,
    )

def test_60(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 60 — All External Security Services (ESS) fields addressed.

    Purpose
    -------
    Confirm that External Security Services (ESS) / Cybersecurity Service Provider
    (CSSP) information has been captured: provider, service scope, agreements,
    responsibilities, etc.

    Why this is manual
    ------------------
    The fixture data we ingest today (SystemContext) does not surface those ESS/CSSP
    fields in a reliable, structured way. The legacy PowerShell scripts also treated
    this as a manual verification step.

    Behavior
    --------
    Always returns CONCERN, prompting a human reviewer to verify:
    - Do we have an ESS/CSSP provider documented?
    - Is there a formal agreement/MOU/MOA?
    - Are responsibilities and monitoring services clearly defined?
    - Is risk acceptance / determination captured?

    Result
    ------
    - CONCERN: Automated validation not possible; SME review required.
    """
    test_name = "Test 60: All External Security Services (ESS) Fields Addressed"
    logger.debug("Running %s", test_name)

    def _emit(result: Result, message: str, level: int) -> TestResult:
        tr_local = TestResult(
            test_number=60,
            name=test_name,
            result=result,
            message=message,
        )
        status.add(tr_local)
        logger.log(level, "[T60] %s", message)
        return tr_local

    return _emit(
        Result.CONCERN,
        "ESS / CSSP details are not exposed in the current data model; manual verification required.",
        logging.WARNING,
    )



def test_61(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 61 — Connection point(s) details provided if applicable.

    Parity
    ------
    This test mirrors the legacy PowerShell behavior:

        $ConnectionPoints = $systemdata | Select-Object -ExpandProperty connectivityCcsd
        $CCSD = $ConnectionPoints | Select-Object -ExcludeProperty ccsdNumber

        if ($null -eq $ConnectionPoints) {
            FAIL: No connection points are provided.
        } else {
            if ($null -eq $CCSD) {
                CONCERN: Connetion points provided, but no CCSD number provided
            } else {
                PASS: Connection points are provided, a manual check is needed.
            }
        }

    Interpreted into Python using only nested models:

    * ``connection_points`` comes from ``ctx.system_info.connectivityccsd``.
    * If ``connection_points is None``                  → FAIL.
    * If ``connection_points`` is a list/tuple and empty → CONCERN.
    * For any other non-None value                       → PASS.

    We intentionally do **not** inspect any ``ccsdNumber`` field or raw JSON.
    The goal is strict output parity with the PowerShell implementation.

    Args:
        ctx: Populated ``SystemContext`` for the system under test.
        status: Aggregated ``ATOStatus`` to which this test appends its result.

    Returns:
        TestResult: The outcome for Test 61, with status and explanation.
    """
    test_number = 61
    test_name = "Test 61: Connection point(s) details provided if applicable"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    def _emit(result: Result, message: str, level: int) -> TestResult:
        """Create, log, and register a TestResult before returning it."""
        tr_local = TestResult(
            test_number=test_number,
            name=test_name,
            result=result,
            message=message,
        )
        status.add(tr_local)
        logger.log(level, "[T%03d] %s", test_number, message)
        return tr_local

    # -------------------------------------------------------------------------
    # 1. Pull connection points from the structured SystemInfo model.
    # -------------------------------------------------------------------------
    system_info = ctx.system_info
    connection_points = system_info.connectivityccsd if system_info else None

    # PowerShell: if ($null -eq $ConnectionPoints) { FAIL ... }
    if connection_points is None:
        return _emit(
            Result.FAIL,
            "FAIL: No connection points are provided.",
            logging.ERROR,
        )

    # -------------------------------------------------------------------------
    # 2. Simulate the $CCSD = $ConnectionPoints | Select-Object -ExcludeProperty ccsdNumber
    #
    # In PowerShell:
    #   * Non-null, non-empty collection/string → $CCSD is non-null → PASS.
    #   * Empty collection                      → $CCSD is $null   → CONCERN.
    #
    # We approximate that behavior as:
    #   * list/tuple with len == 0 → CONCERN.
    #   * any other non-None value → PASS.
    # -------------------------------------------------------------------------
    if isinstance(connection_points, (list, tuple)) and len(connection_points) == 0:
        # PowerShell: CONCERN: Connetion points provided, but no CCSD number provided
        # (Keep original misspelling for exact message parity.)
        return _emit(
            Result.CONCERN,
            "CONCERN: Connetion points provided, but no CCSD number provided",
            logging.WARNING,
        )

    # PowerShell: PASS: Connection points are provided, a manual check is needed.
    return _emit(
        Result.PASS,
        "PASS: Connection points are provided, a manual check is needed.",
        logging.INFO,
    )



def test_62(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 62 — All ATC/IATC fields addressed (if applicable).

    Parity
    ------
    This test mirrors the legacy PowerShell implementation:

        $ATCDecision    = $SystemDetailsSorted | Select-Object -ExpandProperty "ATC Decision"
        $ATCDecisionDate= $SystemDetailsSorted | Select-Object -ExpandProperty "ATC Decision Date"
        $ATCTermDate    = $SystemDetailsSorted | Select-Object -ExpandProperty "ATC Termination Date"

        if ($null -eq $ATCDecision -or
            $null -eq $ATCDecisionDate -or
            $null -eq $ATCTermDate) {
            CONCERN: No ATC/IATC information provided, if applicable
        } else {
            PASS: ATC/IATC fields are provided. <decision> <date> <term>
        }

    We intentionally consider a field "present" if it is *not None*,
    even if it is an empty string or "-" (to match the PowerShell behavior).

    Data Source
    -----------
    The structured `SystemDetailsDashboard` model hanging off the context:

        ctx.system_details_dashboard.atc_decision
        ctx.system_details_dashboard.atc_decision_date
        ctx.system_details_dashboard.atc_termination_date

    Args:
        ctx: Populated `SystemContext` for the system under test.
        status: Aggregated `ATOStatus` to which this test appends its result.

    Returns:
        TestResult: The outcome for Test 62, with status and explanation.
    """
    test_number = 62
    test_name = "Test 62: All ATC/IATC Fields Addressed (if applicable)"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    def _emit(result: Result, message: str, level: int) -> TestResult:
        """Create, log, and register a TestResult before returning it."""
        tr_local = TestResult(
            test_number=test_number,
            name=test_name,
            result=result,
            message=message,
        )
        status.add(tr_local)
        logger.log(level, "[T%03d] %s", test_number, message)
        return tr_local

    details = ctx.system_details_dashboard

    # If we don't even have SystemDetailsDashboard, treat this as "no ATC info"
    # to stay aligned with the PowerShell semantics.
    if details is None:
        return _emit(
            Result.CONCERN,
            "CONCERN: No ATC/IATC information provided, if applicable",
            logging.WARNING,
        )

    atc_decision = details.atc_decision
    atc_decision_date = details.atc_decision_date
    atc_termination_date = details.atc_termination_date

    # PowerShell only checks for $null, not placeholder values like "-" or "".
    if (
        atc_decision is None
        or atc_decision_date is None
        or atc_termination_date is None
    ):
        return _emit(
            Result.CONCERN,
            "CONCERN: No ATC/IATC information provided, if applicable",
            logging.WARNING,
        )

    # All three fields are present (not None) → PASS with appended values,
    # e.g., "PASS: ATC/IATC fields are provided. Approved 1736467200 -"
    message = (
        f"PASS: ATC/IATC fields are provided. "
        f"{atc_decision} {atc_decision_date} {atc_termination_date}"
    )
    return _emit(Result.PASS, message, logging.INFO)


def test_63(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 63 — “Applied Information Types” matches the Information Type Survey (ITS) evidence artifact.

    Goal
    ----
    Confirm there's documented evidence backing the system's applied information
    types (used for categorization / impact determination).

    What we look for
    ----------------
    We scan the artifact inventory for at least one artifact that:
      • has Category == "Information Type" (case-insensitive), AND
      • has a filename ending in ".msg" (the common format for saved ITS emails).

    Return semantics
    ----------------
    PASS
        Found ≥1 qualifying artifact.
    FAIL
        Could not locate such an artifact → manual follow-up required.

    Data source
    -----------
    ctx.artifact_details.data : List[Dict[str, Any]]
        Expected keys per row (case-insensitive, tolerate drift):
          - "Category"
          - "Filename"
          - "Artifact Name" / "Name" (for logging)
    """

    test_name = "Test 63: ITS evidence artifact present"
    logger.debug("Running %s", test_name)

    def get_ci(row: dict, key: str) -> str:
        """
        Case-insensitive dict getter.
        Returns "" if key not found or row isn't a dict.
        """
        if not isinstance(row, dict):
            return ""
        target = key.lower()
        for k, v in row.items():
            if str(k).lower() == target and v is not None:
                return str(v)
        return ""

    # Pull the artifact rows from the structured context.
    # If artifacts aren't available at all, treat that the same as "not found".
    artifact_rows = (ctx.artifact_details.data if ctx.artifact_details and ctx.artifact_details.data else [])

    matches: list[dict] = []
    for row in artifact_rows:
        category = get_ci(row, "Category").strip().lower()
        filename = get_ci(row, "Filename").strip()

        # Heuristic from legacy script:
        # - Category must literally indicate "Information Type"
        # - ITS evidence is usually captured/saved as an Outlook .msg file
        if category == "information type" and filename.lower().endswith(".msg"):
            matches.append(
                {
                    "filename": filename,
                    "name": (
                        get_ci(row, "Artifact Name")
                        or get_ci(row, "Name")
                    ).strip(),
                }
            )

    if not matches:
        tr = TestResult(
            test_number=63,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Information Type Survey (ITS) artifact not found. "
                "Expected Category='Information Type' with a .msg filename."
            ),
        )
        status.add(tr)
        logger.error("[T63] No ITS artifact found in artifact inventory.")
        return tr

    # Use the first good match just for messaging.
    first = matches[0]
    tr = TestResult(
        test_number=63,
        name=test_name,
        result=Result.PASS,
        message=(
            "ITS evidence located: "
            f"filename='{first['filename']}', name='{first['name'] or '(no title)'}'."
        ),
    )
    status.add(tr)
    logger.info("[T63] ITS artifact present: %s", first["filename"])
    return tr


def test_64(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 64 — “Control Attributes” supported by Information Type Survey (ITS) evidence.

    Goal
    ----
    Confirm there is at least one Information Type Survey (ITS) artifact
    on file. This artifact backs the system's control attributes and impact
    determinations (FIPS 199 / NIST SP 800-60 style rationale).

    What we consider valid ITS evidence
    -----------------------------------
    An artifact row where BOTH are true:
      • Category == "Information Type" (case-insensitive)
      • Filename ends with ".msg" (expected ITS evidence format)

    Outcomes
    --------
    PASS
        Found ≥1 qualifying ITS artifact.
    FAIL
        No qualifying ITS artifact found. Human follow-up required.

    Data source
    -----------
    ctx.artifact_details.data : List[Dict[str, Any]]
        Relevant keys (case-insensitive):
          - "Category"
          - "Filename"
          - "Artifact Name" / "Name"
    """

    test_name = "Test 64: Control Attributes supported by ITS artifact"
    logger.debug("Running %s", test_name)

    def get_ci(row: dict, key: str) -> str:
        """
        Case-insensitive dict getter.
        Returns "" if key not found or row isn't a dict.
        """
        if not isinstance(row, dict):
            return ""
        want = key.lower()
        for k, v in row.items():
            if str(k).lower() == want and v is not None:
                return str(v)
        return ""

    # Pull artifact rows from structured context.
    artifact_rows = (
        ctx.artifact_details.data
        if ctx.artifact_details and ctx.artifact_details.data
        else []
    )

    its_match = None  # store first valid match for messaging
    for row in artifact_rows:
        category = get_ci(row, "Category").strip().lower()
        filename = get_ci(row, "Filename").strip()

        if category == "information type" and filename.lower().endswith(".msg"):
            its_match = {
                "filename": filename,
                "name": (
                    get_ci(row, "Artifact Name")
                    or get_ci(row, "Name")
                ).strip(),
            }
            break

    if its_match is None:
        tr = TestResult(
            test_number=64,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Control Attributes evidence not found. "
                "Expected an Information Type Survey artifact "
                "(Category='Information Type', filename ending in .msg)."
            ),
        )
        status.add(tr)
        logger.error("[T64] No qualifying ITS artifact located for Control Attributes support.")
        return tr

    tr = TestResult(
        test_number=64,
        name=test_name,
        result=Result.PASS,
        message=(
            "Control Attributes supported by ITS artifact: "
            f"filename='{its_match['filename']}', "
            f"name='{its_match['name'] or '(no title)'}'."
        ),
    )
    status.add(tr)
    logger.info(
        "[T64] ITS artifact present for Control Attributes: %s",
        its_match["filename"],
    )
    return tr


def test_65(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 65 — “Impact Level” identified and consistent with CIA.

    Goal
    ----
    Check that the system's declared overall impact level (Low / Moderate / High)
    is actually supported by the Confidentiality / Integrity / Availability (CIA)
    levels, using standard FIPS 199-style logic:

        Impact = LOW
            → C == LOW and I == LOW and A == LOW
        Impact = MODERATE
            → At least one of {C, I, A} == MODERATE
              AND none == HIGH
        Impact = HIGH
            → At least one of {C, I, A} == HIGH

    Inputs (from ctx)
    -----------------
    ctx.impact
    ctx.confidentiality
    ctx.integrity
    ctx.availability

    Results
    -------
    PASS
        Declared impact matches CIA profile.
    FAIL
        Missing values, unexpected impact value, or mismatch with CIA profile.
    """

    test_name = "Test 65: Impact Level is identified and consistent with CIA"
    logger.debug("Running %s", test_name)

    def _norm(value: object) -> str:
        """Lowercase/trim normalization to make string comparisons resilient."""
        return str(value or "").strip().lower()

    overall_impact = _norm(getattr(ctx, "impact", None))
    conf_level = _norm(getattr(ctx, "confidentiality", None))
    integ_level = _norm(getattr(ctx, "integrity", None))
    avail_level = _norm(getattr(ctx, "availability", None))

    # -------- Required field checks --------
    if not overall_impact:
        tr = TestResult(
            test_number=65,
            name=test_name,
            result=Result.FAIL,
            message="System impact level is not provided.",
        )
        status.add(tr)
        logger.error("[T65] FAIL — Missing overall impact level.")
        return tr

    if not conf_level or not integ_level or not avail_level:
        tr = TestResult(
            test_number=65,
            name=test_name,
            result=Result.FAIL,
            message=(
                "CIA values are incomplete; cannot validate impact alignment. "
                f"C={conf_level or '—'}, I={integ_level or '—'}, A={avail_level or '—'}."
            ),
        )
        status.add(tr)
        logger.error(
            "[T65] FAIL — Missing CIA component(s): C=%r I=%r A=%r",
            conf_level,
            integ_level,
            avail_level,
        )
        return tr

    # -------- Derive CIA profile flags --------
    cia_set = {conf_level, integ_level, avail_level}
    any_high = "high" in cia_set
    any_moderate = "moderate" in cia_set
    all_low = cia_set == {"low"}

    # -------- Validate declared impact vs CIA --------
    if overall_impact == "low":
        aligns = all_low
    elif overall_impact == "moderate":
        aligns = any_moderate and not any_high
    elif overall_impact == "high":
        aligns = any_high
    else:
        # Unexpected label like "Very High", "Med", etc.
        tr = TestResult(
            test_number=65,
            name=test_name,
            result=Result.FAIL,
            message=f"Unexpected impact value: '{overall_impact}'.",
        )
        status.add(tr)
        logger.error("[T65] FAIL — Unexpected impact value: %s", overall_impact)
        return tr

    if aligns:
        tr = TestResult(
            test_number=65,
            name=test_name,
            result=Result.PASS,
            message="Impact level aligns with CIA values.",
        )
        status.add(tr)
        logger.info(
            "[T65] PASS — Impact alignment ok (impact=%s, C/I/A=%s/%s/%s).",
            overall_impact,
            conf_level,
            integ_level,
            avail_level,
        )
        return tr

    # Mismatch case
    tr = TestResult(
        test_number=65,
        name=test_name,
        result=Result.FAIL,
        message=(
            "Impact level does not match CIA values. "
            f"Impact={overall_impact}, C={conf_level}, I={integ_level}, A={avail_level}."
        ),
    )
    status.add(tr)
    logger.error(
        "[T65] FAIL — Impact mismatch (impact=%s, C/I/A=%s/%s/%s).",
        overall_impact,
        conf_level,
        integ_level,
        avail_level,
    )
    return tr



def test_66(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 66 — Information Type Evidence artifact linked.

    Goal
    ----
    We expect approved Information Type Survey (ITS) evidence to appear as an
    email approval captured as a .msg file under Category='Information Type'.

    Heuristics:
    - If we ONLY see spreadsheets (.xlsx) in that category, it's usually draft/WIP → CONCERN.
    - If we see any .msg in that category → PASS.
    - If we see neither → FAIL.

    Priority:
        PASS (has .msg) > CONCERN (only .xlsx) > FAIL.
    """

    test_name = "Test 66: Information Type Evidence artifact linked"
    logger.debug("Running %s", test_name)

    # pull artifact table rows from nested model
    rows: list[dict] = []
    if ctx.artifact_details and ctx.artifact_details.data:
        rows = ctx.artifact_details.data  # List[Dict[str, Any]]

    def ci_get(d: dict, key: str) -> str:
        """Case-insensitive dict get -> always return string ('' if missing)."""
        key_l = key.lower()
        for k, v in d.items():
            if str(k).lower() == key_l:
                return "" if v is None else str(v)
        return ""

    msg_files: list[str] = []
    xlsx_files: list[str] = []

    for row in rows:
        category = ci_get(row, "Category").strip().lower()
        if category != "information type":
            continue

        filename = ci_get(row, "Filename").strip()
        lower_name = filename.lower()

        if lower_name.endswith(".msg"):
            msg_files.append(filename or "<unnamed>")
        elif lower_name.endswith(".xlsx"):
            xlsx_files.append(filename or "<unnamed>")

    # PASS beats CONCERN
    if msg_files:
        tr = TestResult(
            test_number=66,
            name=test_name,
            result=Result.PASS,
            message=(
                "Information Type approval evidence present (.msg): "
                + ", ".join(sorted(set(msg_files)))
            ),
        )
        status.add(tr)
        logger.info("[T66] PASS — ITS .msg approval evidence found: %s", msg_files)
        return tr

    # No .msg, but we *did* see .xlsx → CONCERN
    if xlsx_files:
        tr = TestResult(
            test_number=66,
            name=test_name,
            result=Result.CONCERN,
            message=(
                "Only spreadsheet(s) found for Information Type; may be draft, not AO-approved: "
                + ", ".join(sorted(set(xlsx_files)))
            ),
        )
        status.add(tr)
        logger.warning("[T66] CONCERN — Only .xlsx ITS evidence: %s", xlsx_files)
        return tr

    # nothing at all
    tr = TestResult(
        test_number=66,
        name=test_name,
        result=Result.FAIL,
        message=(
            "Information Type evidence not found. "
            "Expected Category='Information Type' with an approval email (.msg)."
        ),
    )
    status.add(tr)
    logger.error("[T66] FAIL — No Information Type evidence.")
    return tr


def test_67(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 67 — Overlays applied and overlay questions answered.

    Policy intent
    -------------
    We’re checking that required overlays are both:
      1. actually applied, and
      2. (for Privacy) have been meaningfully answered.

    Rules enforced here:
    • If PII or PHI is present:
        - "Privacy" overlay must appear in applied overlays, AND
        - privacy overlay responses must be present and not just "-".
        - (Bonus business rule) If the Privacy responses claim an
          unauthorized "business rolodex" exemption, flag it.
    • If the system is Financial Management, OR APMS says it's a financial feeder:
        - "Financial Management" overlay must appear.
    • If no overlays are listed and nothing implies one is required:
        - PASS with a soft note (mirrors legacy behavior).
    • Otherwise:
        - FAIL with the collected issues.

    Surfaces used
    -------------
    - ctx.system_details_dashboard.applied_overlays : str | None
        (e.g. "Privacy; Financial Management")
    - ctx.privacy.privacy_overlays_responses       : str | None
        (Q&A / justification text for the privacy overlay)
    - ctx.pii, ctx.phi                              : bool | None
    - ctx.fms                                       : bool | None
    - ctx.apms_financial_feeder                     : str | bool | None
        (not modeled in SystemContext, may be injected at runtime)

    Outcome
    -------
    PASS   → overlays aligned with data flags and (if Privacy) answered
    FAIL   → missing required overlay or unanswered required overlay
    """

    test_name = "Test 67: Overlays applied and answered"
    logger.debug("Running %s", test_name)

    def to_bool_loose(val: object) -> Optional[bool]:
        """Best-effort boolean parse for values like 'Yes', 'No', '1', etc."""
        if isinstance(val, bool):
            return val
        if val is None:
            return None
        s = str(val).strip().lower()
        if s in {"true", "yes", "y", "1"}:
            return True
        if s in {"false", "no", "n", "0"}:
            return False
        return None

    # --- Gather inputs from structured models --------------------------------

    # Applied overlays come from SystemDetailsDashboard
    dash = ctx.system_details_dashboard or SystemDetailsDashboard()
    overlays_raw = dash.applied_overlays or ""
    overlays_str = overlays_raw.strip()
    overlays_lc = overlays_str.lower()

    # Privacy overlay questionnaire answers live under Privacy
    privacy_model = ctx.privacy or Privacy()
    privacy_answers_raw = privacy_model.privacy_overlays_responses
    privacy_answers = ("" if privacy_answers_raw is None else str(privacy_answers_raw)).strip()

    # Data flags that *drive* overlay requirements
    has_pii = bool(ctx.pii)
    has_phi = bool(ctx.phi)
    is_fms = bool(ctx.fms)

    # APMS financial feeder hint (may or may not exist on ctx)
    apms_financial_feeder_raw = getattr(ctx, "apms_financial_feeder", None)
    apms_financial_feeder = to_bool_loose(apms_financial_feeder_raw)

    # --- Begin validation logic ----------------------------------------------

    issues: list[str] = []

    # 1. Quick happy path: if there are zero overlays AND nothing suggests we
    #    *need* one, this is considered okay-ish by legacy logic.
    if (not overlays_str or overlays_str == "-") and not (
        has_pii or has_phi or is_fms or apms_financial_feeder is True
    ):
        tr = TestResult(
            test_number=67,
            name=test_name,
            result=Result.PASS,
            message="No overlays applied, and no indicators (PII/PHI/FMS) that an overlay is required. Verify correctness.",
        )
        status.add(tr)
        logger.info("[T67] PASS — No overlays required; none applied.")
        return tr

    # 2. Privacy overlay requirement
    if has_pii or has_phi:
        privacy_applied = "privacy" in overlays_lc
        if not privacy_applied:
            issues.append("Privacy overlay missing despite PII/PHI = True.")
        else:
            # Must have meaningful questionnaire responses
            if not privacy_answers:
                issues.append("Privacy overlay questions/justification are missing.")
            elif privacy_answers == "-" or privacy_answers.lower() == "n/a":
                issues.append("Privacy overlay questions appear unanswered ('-' / 'N/A').")

            # Special business rule:
            # If someone tries to justify PII with a 'business rolodex' carve-out,
            # that's considered noncompliant in legacy guidance.
            ans_lc = privacy_answers.lower()
            if "business rolodex" in ans_lc and "(yes)" in ans_lc:
                issues.append("Privacy overlay response claims an unauthorized 'business rolodex' exemption.")

    # 3. Financial Management overlay requirement
    needs_financial_overlay = is_fms or (apms_financial_feeder is True)
    if needs_financial_overlay and "financial management" not in overlays_lc:
        if is_fms:
            issues.append("Financial Management overlay missing (system flagged as Financial Management).")
        if apms_financial_feeder is True:
            issues.append("Financial Management overlay missing (APMS marks system as financial feeder).")

    # --- Emit result ---------------------------------------------------------

    if issues:
        tr = TestResult(
            test_number=67,
            name=test_name,
            result=Result.FAIL,
            message=" ".join(issues),
        )
        status.add(tr)
        logger.error("[T67] FAIL — Overlay validation issues: %s", issues)
        return tr

    tr = TestResult(
        test_number=67,
        name=test_name,
        result=Result.PASS,
        message=f"Overlays appear appropriate. Applied overlays: {overlays_str or '(none)'}",
    )
    status.add(tr)
    logger.info("[T67] PASS — Overlays validated: %s", overlays_str)
    return tr


def test_68(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 68 — Controls tailored due to overlays or manual tailoring.

    Summary
    -------
    The source check is inherently manual (requires reading overlay/tailoring rationale).
    We flag a **CONCERN** to prompt reviewer validation.

    Args:
        ctx: System context (not used here).
        status: Aggregator for results.

    Returns:
        TestResult: Always CONCERN with guidance.
    """
    test_name = "Test 68: Controls added/removed via overlay or manual tailoring"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=68,
        name=test_name,
        result=Result.CONCERN,
        message="Review tailoring notes: identify controls added/removed by overlays or manual tailoring and validate justification.",
    )
    status.add(tr)
    logger.warning("[T68] Manual verification required for control tailoring.")
    return tr

def test_69(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 69 — STIGs/SRGs identified and consistent.

    Parity
    ------
    This test mirrors the legacy PowerShell logic:

        $AppliedSTIGS = $systemdata | Select-Object -ExpandProperty appliedStigs

        if ($null -eq $AppliedSTIGS) {
            CONCERN: No Stig data was found.
        } else {
            CONCERN: The following STIGs are applied, manual verification is needed: <AppliedSTIGS>
        }

    We intentionally:
    * Read only from the structured `SystemInfo` model (no raw JSON access).
    * Do not split, normalize, or sort STIG names; we echo the value as-is.

    Data source
    -----------
    ctx.system_info.appliedstigs : Optional[str]
        Raw applied STIG list from eMASS system metadata.

    Args:
        ctx: Populated `SystemContext` for the system under test.
        status: Aggregated `ATOStatus` object to which this test will append its result.

    Returns:
        TestResult: The outcome for Test 69, always with result=CONCERN.
    """
    test_number = 69
    test_name = "Test 69: STIGs/SRGs identified and consistent"
    logger.debug("[T%03d] Running %s", test_number, test_name)

    def _emit(result: Result, message: str, level: int) -> TestResult:
        """Create, log, and register a TestResult before returning it."""
        tr_local = TestResult(
            test_number=test_number,
            name=test_name,
            result=result,
            message=message,
        )
        status.add(tr_local)
        logger.log(level, "[T%03d] %s", test_number, message)
        return tr_local

    # Structured STIG field from SystemInfo (no raw JSON access).
    system_info = ctx.system_info
    applied_stigs = system_info.appliedstigs if system_info is not None else None

    # PowerShell: if ($null -eq $AppliedSTIGS) { "CONCERN: No Stig data was found." }
    if applied_stigs is None:
        return _emit(
            Result.CONCERN,
            "CONCERN: No Stig data was found.",
            logging.WARNING,
        )

    # PowerShell: else { "CONCERN: The following STIGs are applied, manual verification is needed: " + $AppliedSTIGS }
    message = (
        "CONCERN: The following STIGs are applied, manual verification is needed: "
        f"{applied_stigs}"
    )
    return _emit(Result.CONCERN, message, logging.WARNING)

def test_70(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 70 — Recommended Added Controls are addressed?

    Context
    -------
    In legacy review, assessors look for any "Recommended Added Controls"
    (i.e. additional/adaptive security controls suggested by assessors
    beyond the baseline) and verify that the system owner has either:
      • implemented them, or
      • documented rationale for not implementing them.

    Limitation
    ----------
    That data is not exposed in the eMASS API surfaces we ingest, so we
    cannot automate verification.

    Behavior
    --------
    Always returns CONCERN to prompt manual review.
    """

    test_name = "Test 70: Recommended Added Controls are addressed?"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=70,
        name=test_name,
        result=Result.CONCERN,
        message="Not available via eMASS API. Manually confirm Recommended Added Controls are addressed.",
    )

    status.add(tr)
    logger.warning("[T70] Recommended Added Controls not machine-verifiable; manual review required.")
    return tr

def test_71(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 71 — Significant changes since last Authorization?

    Context
    -------
    Reviewers are expected to identify whether the system has undergone
    significant changes since the last Authorization decision. That drives
    re-authorization / reassessment requirements.

    Limitation
    ----------
    The current eMASS API payloads we ingest do not expose a reliable
    "significant change since last ATO" indicator.

    Behavior
    --------
    We always return CONCERN to force manual confirmation.

    Returns:
        TestResult: CONCERN with an explanation that this must be manually reviewed.
    """
    test_name = "Test 71: Significant changes since last Authorization?"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=71,
        name=test_name,
        result=Result.CONCERN,
        message="Not machine-verifiable: confirm whether significant changes occurred since the last Authorization.",
    )

    status.add(tr)
    logger.warning("[T71] Significant-change check not available via API; manual review required.")
    return tr


def test_72(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 72 — All 14 ATC Critical Controls have recent tests in eMASS.

    Parity
    ------
    This implementation is designed to mirror the intent and practical behavior
    of the legacy PowerShell script while staying inside the structured models:

      * Consider only the 14 ATC Critical Controls.
      * Use `ctx.fixtures.test_results.data` (DemoAssets JSON) if present,
        plus `ctx.test_results.data` as a secondary source.
      * If no rows exist at all for any of the 14 controls:
            "FAIL: No Controls Test data was returned"
      * For each control, treat it as **satisfied** if it has at least one row
        where:
            - testdate is present and > OneYearAgoEpoch
            - AND testdate is not "[REDACTED]"
            - AND complianceStatus != "Non-Compliant"
      * A control is marked failing only if it has **no** such good rows.
      * If no controls fail:
            "PASS: All 14 ATC Critical Controls have been tested within the past year."
        otherwise:
            "FAIL: One or more of the 14 ATC Critical Controls, has not been tested
             within one year, are noncompliant, or could not be verified: <list>"

    Args:
        ctx: Fully-populated `SystemContext` for the system under test.
        status: Aggregated `ATOStatus` object that collects all test results.

    Returns:
        TestResult: PASS or FAIL, aligned with the PowerShell behavior for the
        same TestResults.json input.
    """
    test_number = 72
    test_name = (
        "Test 72: All 14 ATC Critical Controls have test results in eMASS "
        "that are less than 1 yr old"
    )
    logger.debug("[T%03d] Running %s", test_number, test_name)

    def emit(result: Result, message: str, log_level: int) -> TestResult:
        """Create, log, and register a TestResult, then return it."""
        tr_local = TestResult(
            test_number=test_number,
            name=test_name,
            result=result,
            message=message,
        )
        status.add(tr_local)
        logger.log(log_level, "[T%03d] %s", test_number, message)
        return tr_local

    # ----------------------------------------------------------------------
    # Constants and time window (mirrors `$OneYearAgoEpoch` intent).
    # ----------------------------------------------------------------------
    atc_critical_controls = [
        "AC-17",
        "AC-17(2)",
        "IA-2(1)",
        "IA-2(2)",
        "IA-2(3)",
        "IA-2(4)",
        "IA-5(1)",
        "IR-8",
        "IR-9",
        "RA-5",
        "SC-7",
        "SC-8",
        "SC-28",
        "SI-2",
    ]
    # Case-insensitive canonical mapping.
    canonical_by_upper = {c.upper(): c for c in atc_critical_controls}

    now_epoch = int(_time.time())
    one_year_seconds = 365 * 24 * 60 * 60
    one_year_ago_epoch = now_epoch - one_year_seconds

    # ----------------------------------------------------------------------
    # Gather candidate rows from structured context (no raw JSON).
    # Prefer fixtures (DemoAssets/TestResults.json), then merged with
    # top-level ctx.test_results.data.
    # ----------------------------------------------------------------------
    test_rows: list[dict[str, Any]] = []

    fixtures = getattr(ctx, "fixtures", None)
    if fixtures is not None:
        fixtures_tr = getattr(fixtures, "test_results", None)
        if fixtures_tr is not None and isinstance(fixtures_tr.data, list):
            logger.debug(
                "[T%03d] Using ctx.fixtures.test_results.data for system_id=%s",
                test_number,
                ctx.system_id,
            )
            test_rows.extend(r for r in fixtures_tr.data if isinstance(r, dict))

    tr_model = getattr(ctx, "test_results", None)
    if tr_model is not None and isinstance(tr_model.data, list):
        logger.debug(
            "[T%03d] Using ctx.test_results.data for system_id=%s",
            test_number,
            ctx.system_id,
        )
        test_rows.extend(r for r in tr_model.data if isinstance(r, dict))

    # Filter down to the 14 ATC Critical Controls and group by control ID.
    atc_rows_by_control: dict[str, list[dict[str, Any]]] = {}
    for row in test_rows:
        control_raw = row.get("control")
        if control_raw is None:
            continue
        control_id = str(control_raw).strip()
        if not control_id:
            continue

        # Normalize to canonical name (case-insensitive).
        canonical = canonical_by_upper.get(control_id.upper())
        if canonical is None:
            continue

        atc_rows_by_control.setdefault(canonical, []).append(row)

    # “No Controls Test data was returned” — nothing for any of the 14 controls.
    total_atc_rows = sum(len(v) for v in atc_rows_by_control.values())
    if total_atc_rows == 0:
        return emit(
            Result.FAIL,
            "FAIL: No Controls Test data was returned",
            logging.ERROR,
        )

    # ----------------------------------------------------------------------
    # Helper: normalize testdate into epoch seconds or None.
    # ----------------------------------------------------------------------
    def coerce_epoch(value: Any) -> Optional[int]:
        """Return epoch seconds as int, or None if missing/redacted/invalid."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            v = value.strip()
            if v.upper() == "[REDACTED]":
                return None
            try:
                return int(float(v))
            except Exception:
                return None
        return None

    # ----------------------------------------------------------------------
    # Evaluate each ATC Critical Control.
    # A control fails only if it has *no* recent/compliant rows.
    # ----------------------------------------------------------------------
    failing_controls: list[str] = []

    for control_id in atc_critical_controls:
        rows_for_control = atc_rows_by_control.get(control_id, [])
        if not rows_for_control:
            # For parity with the original behavior, do not treat “missing
            # per-control” as an automatic failure; only the global “no data”
            # case above is a hard fail.
            continue

        has_good_row = False
        label_for_control: Optional[str] = None

        for row in rows_for_control:
            if label_for_control is None:
                label_raw = row.get("acronym") or row.get("control")
                label_for_control = (
                    str(label_raw).strip() if label_raw is not None else control_id
                )

            raw_testdate = row.get("testdate")
            raw_compliance = row.get("complianceStatus")

            is_redacted = (
                isinstance(raw_testdate, str)
                and raw_testdate.strip().upper() == "[REDACTED]"
            )
            test_epoch = coerce_epoch(raw_testdate)
            compliance_normalized = str(raw_compliance or "").strip().lower()
            is_non_compliant = (compliance_normalized == "non-compliant")

            # PowerShell condition equivalents.
            is_missing_or_stale = (
                test_epoch is None or test_epoch <= one_year_ago_epoch
            )
            is_bad_row = is_missing_or_stale or is_redacted or is_non_compliant

            if not is_bad_row:
                # One fresh, compliant row is enough to satisfy this control.
                has_good_row = True
                break

        if not has_good_row and label_for_control:
            failing_controls.append(label_for_control)

    # ----------------------------------------------------------------------
    # Final outcome (PASS / FAIL) with PowerShell-style messages.
    # ----------------------------------------------------------------------
    if not failing_controls:
        # "PASS: All 14 ATC Critical Controls have been tested within the past year."
        return emit(
            Result.PASS,
            "PASS: All 14 ATC Critical Controls have been tested within the past year.",
            logging.INFO,
        )

    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique_failing: list[str] = []
    for label in failing_controls:
        if label not in seen:
            seen.add(label)
            unique_failing.append(label)

    controls_list_str = ", ".join(unique_failing)
    fail_message = (
        "FAIL: One or more of the 14 ATC Critical Controls, has not been tested within one year, "
        "are noncompliant, or could not be verified: "
        f"{controls_list_str}"
    )
    return emit(Result.FAIL, fail_message, logging.ERROR)

def test_73(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 73 — All Controls/APs/CCIs have current (≤ 1 year) test results and
    are not Non-Compliant (ATO only).

    Behavior (parity-focused)
    -------------------------
    • Only applies if the system is in an Authorization to Operate (ATO) phase.
      - PowerShell: $ATOStatus -like "*Authorization to Operate*"
      - Python: case-insensitive containment check on ctx.authorization_status.

    • Data source:
      - Structured TestResults model on SystemContext:
            ctx.test_results.data -> list[dict]
        with an optional fallback to ctx.fixtures.test_results.data.

    • For each *control* (AC-2, IA-5, etc.), we look across all its Test Results:
        - A row is considered "GOOD" if:
              testdate is present and within the last year
              AND complianceStatus is not "Non-Compliant".
        - A row is considered "BAD" if:
              testdate is missing / "[REDACTED]" / non-numeric
              OR testdate is older than 1 year
              OR complianceStatus is "Non-Compliant".

      The control is FAILED only if it has **no GOOD rows**.

    • PASS:
        "PASS: All Controls have been tested within the past year."
    • FAIL:
        "FAIL: One or more of the Controls, has not been tested within one year,
         are noncompliant, or could not be verified: <control-list>"
    • N/A:
        "Not Applicable: System is not in ATO Phase"
    """
    test_name = (
        "Test 73: All Controls/APs/CCIs have current (≤1yr) test results and are not Non-Compliant"
    )
    logger.debug("Running %s", test_name)

    # Show current aggregate status before this test (debug aid)
    try:
        logger.info("[T73] ATOStatus summary BEFORE Test 73: %s", status.summary())
    except Exception:
        # summary() should be safe, but don't let it crash the test if something is odd
        logger.debug("[T73] Could not render ATOStatus summary before Test 73")

    # ---------- Applicability gate: only runs for ATO systems ----------
    auth_text = (ctx.authorization_status or "").strip().lower()
    if "authorization to operate" not in auth_text:
        msg = "Not Applicable: System is not in ATO Phase"
        tr = TestResult(
            test_number=73,
            name=test_name,
            result=Result.NA,
            message=msg,
        )
        status.add(tr)
        logger.info("[T73] N/A — authorization_status=%r", ctx.authorization_status)
        return tr

    # ---------- Pull control test evidence from structured models ----------
    rows: list[dict] = []

    # Primary source: top-level TestResults on the context
    results_block = getattr(ctx, "test_results", None)
    data_block = getattr(results_block, "data", None)
    if isinstance(data_block, list):
        rows = data_block

    # Optional fallback: fixtures.test_results (if your loader uses FixturesData)
    if not rows:
        fixtures = getattr(ctx, "fixtures", None)
        if fixtures is not None:
            fixtures_test_results = getattr(fixtures, "test_results", None)
            fixtures_data = getattr(fixtures_test_results, "data", None)
            if isinstance(fixtures_data, list):
                rows = fixtures_data

    if not rows:
        msg = "No Controls Test data was returned."
        tr = TestResult(
            test_number=73,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error("[T73] %s", msg)
        return tr

    logger.info(
        "[T73] Using %d structured TestResults rows from models (ctx.test_results / fixtures.test_results).",
        len(rows),
    )

    # ---------- Time helpers ----------
    now_epoch = int(_time.time())
    one_year_seconds = 365 * 24 * 60 * 60
    one_year_ago_epoch = now_epoch - one_year_seconds

    logger.info(
        "[T73] Rule: a control PASSES if it has at least one row with "
        "testdate > one_year_ago_epoch (%d) AND complianceStatus != 'Non-Compliant'. "
        "It FAILS if it has only rows with missing/[REDACTED]/old dates or 'Non-Compliant' status.",
        one_year_ago_epoch,
    )

    def coerce_epoch(value: object) -> Optional[int]:
        """
        Convert the given value into epoch seconds, or None if invalid / redacted.

        Accepts:
            - int / float (already epoch)
            - numeric string
            - "[REDACTED]" (treated as missing -> None)
        """
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            v = value.strip()
            if v.upper() == "[REDACTED]":
                return None
            try:
                return int(float(v))
            except Exception:
                return None
        return None

    # ---------- Evaluate every control across all its rows ----------
    control_state: dict[str, dict[str, bool]] = {}

    for row in rows:
        if not isinstance(row, dict):
            logger.debug("[T73] Skipping non-dict row in structured data: %r", row)
            continue

        raw_name = (
            row.get("acronym")
            or row.get("control")
            or row.get("controlAcronym")
            or row.get("ControlAcronym")
            or row.get("control_acronym")
        )
        control_name = str(raw_name or "").strip() or "<unknown-control>"

        test_epoch = coerce_epoch(row.get("testdate"))
        compliance = str(row.get("complianceStatus") or "").strip().lower()

        is_good = (
            test_epoch is not None
            and test_epoch > one_year_ago_epoch
            and compliance != "non-compliant"
        )
        is_bad = (
            test_epoch is None
            or test_epoch <= one_year_ago_epoch
            or compliance == "non-compliant"
        )

        state = control_state.setdefault(
            control_name,
            {"has_good": False, "has_bad": False},
        )
        if is_good:
            state["has_good"] = True
        if is_bad:
            state["has_bad"] = True

        logger.debug(
            "[T73] Row for control %s | testdate=%r (epoch=%r) | complianceStatus=%r "
            "=> is_good=%s, is_bad=%s",
            control_name,
            row.get("testdate"),
            test_epoch,
            row.get("complianceStatus"),
            is_good,
            is_bad,
        )

    # Controls fail only if they have no GOOD rows but do have at least one BAD row.
    failed_controls = [
        name
        for name, st in control_state.items()
        if st["has_bad"] and not st["has_good"]
    ]
    failed_controls_sorted = sorted(set(failed_controls))

    # ---------- If failing, also show raw JSON source rows for each failed control ----------
    if failed_controls_sorted:
        raw_rows: list[dict] = []
        raw_payloads = getattr(ctx, "raw_payloads", None)
        if raw_payloads is not None:
            try:
                # RawPayloads.test_results is the raw JSON for the TestResults endpoint
                raw_rows = getattr(raw_payloads, "test_results", None) or []
            except Exception:
                raw_rows = []
        logger.info(
            "[T73] Found %d failed controls based on structured model data: %s",
            len(failed_controls_sorted),
            ", ".join(failed_controls_sorted),
        )
        logger.info(
            "[T73] Raw TestResults payload rows available from ctx.raw_payloads.test_results: %d",
            len(raw_rows),
        )

        for control_name in failed_controls_sorted:
            # Model-side rows
            model_rows_for_control = [
                r for r in rows
                if isinstance(r, dict) and (
                    str(
                        r.get("acronym")
                        or r.get("control")
                        or r.get("controlAcronym")
                        or r.get("ControlAcronym")
                        or r.get("control_acronym")
                        or ""
                    ).strip()
                    or "<unknown-control>"
                ) == control_name
            ]

            # Raw JSON rows (best-effort match on same keys)
            raw_rows_for_control: list[dict] = []
            for rr in raw_rows:
                if not isinstance(rr, dict):
                    continue
                raw_cn = (
                    rr.get("acronym")
                    or rr.get("control")
                    or rr.get("controlAcronym")
                    or rr.get("ControlAcronym")
                    or rr.get("control_acronym")
                )
                raw_cn = str(raw_cn or "").strip() or "<unknown-control>"
                if raw_cn == control_name:
                    raw_rows_for_control.append(rr)

            logger.info("[T73] ---- DEBUG for control %s ----", control_name)
            logger.info(
                "[T73] Structured model rows (ctx.test_results/fixtures.test_results) for %s: %r",
                control_name,
                model_rows_for_control,
            )
            logger.info(
                "[T73] Raw JSON rows (ctx.raw_payloads.test_results) for %s: %r",
                control_name,
                raw_rows_for_control,
            )
            logger.info(
                "[T73] Decision rule applied: control %s FAILS because it has "
                "no rows where testdate > %d AND complianceStatus != 'Non-Compliant'.",
                control_name,
                one_year_ago_epoch,
            )

    # ---------- Final decision (messages aligned with PowerShell) ----------
    if not failed_controls_sorted:
        msg = "PASS: All Controls have been tested within the past year."
        tr = TestResult(
            test_number=73,
            name=test_name,
            result=Result.PASS,
            message=msg,
        )
        status.add(tr)
        logger.info("[T73] %s", msg)
        return tr

    msg = (
        "FAIL: One or more of the Controls, has not been tested within one year, "
        "are noncompliant, or could not be verified: "
        f"{', '.join(failed_controls_sorted)}"
    )
    tr = TestResult(
        test_number=73,
        name=test_name,
        result=Result.FAIL,
        message=msg,
    )
    status.add(tr)
    logger.error("[T73] %s", msg)
    return tr




def test_74(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 74 — All controls are compliant (proxy for “Official/Validated”); POA&M-traceable exceptions allowed.

    What this does
    --------------
    We look at the CAC / controls assessment data currently attached to the system
    and make sure none of the controls are marked Non-Compliant.

    This matches the real PowerShell behavior:
    - It *says* "Official/Validated" and "POA&M-traceable exceptions allowed,"
      but in practice it only flags rows whose complianceStatus == "Non-Compliant".

    Data contract
    -------------
    ctx.controls : Controls | None
        ctx.controls.data : list[dict] | None

        Each row should expose, case-insensitive:
          - "complianceStatus": str
              Examples: "Compliant", "Non-Compliant"
          - "controlAcronym" or "acronym": str
              e.g. "SC-7(18)"

    Result logic
    ------------
    - FAIL if there is no controls/CAC data at all.
    - FAIL if any row is Non-Compliant → include acronyms in the message.
    - PASS if no rows are Non-Compliant → still tell the reviewer to verify
      "Official/Validated" status manually.
    """
    test_name = (
        "Test 74: All controls have Official/Validated status (no Non-Compliant); "
        "POA&M-traceable exceptions allowed"
    )
    logger.debug("Running %s", test_name)

    # Grab CAC / controls assessment rows from the structured context.
    controls_block = getattr(ctx, "controls", None)
    rows = []
    if controls_block and isinstance(controls_block.data, list):
        rows = controls_block.data

    if not rows:
        msg = "No CAC/controls data was returned; cannot verify control compliance."
        tr = TestResult(
            test_number=74,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error("[T74] %s", msg)
        return tr

    def ci_get(d: dict, key: str):
        """Case-insensitive getter for dict-like rows."""
        if not isinstance(d, dict):
            return None
        key_l = key.lower()
        for k, v in d.items():
            if str(k).lower() == key_l:
                return v
        return None

    # Scan all rows for "Non-Compliant".
    non_compliant_acronyms: list[str] = []
    for row in rows:
        compliance = (ci_get(row, "complianceStatus") or "").strip().lower()
        if compliance == "non-compliant":
            acronym = (
                (ci_get(row, "controlAcronym") or ci_get(row, "acronym") or "")
                .strip()
                or "<unknown-control>"
            )
            non_compliant_acronyms.append(acronym)

    if not non_compliant_acronyms:
        msg = (
            "All controls are compliant or not applicable. "
            "Verification still required to confirm “Official/Validated” status."
        )
        tr = TestResult(
            test_number=74,
            name=test_name,
            result=Result.PASS,
            message=msg,
        )
        status.add(tr)
        logger.info("[T74] PASS — no Non-Compliant controls found.")
        return tr

    msg = (
        "One or more controls are Non-Compliant or could not be verified: "
        + ", ".join(non_compliant_acronyms)
    )
    tr = TestResult(
        test_number=74,
        name=test_name,
        result=Result.FAIL,
        message=msg,
    )
    status.add(tr)
    logger.error("[T74] FAIL — Non-Compliant controls: %s", non_compliant_acronyms)
    return tr


def test_75(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 75 — Any Non-Compliant “critical (red-diamond)” package controls?

    Purpose
    -------
    For ATO / post-ATO systems, confirm that none of the predefined "critical"
    (red-diamond) controls are currently Non-Compliant.

    Scope gate
    ----------
    Only runs if ctx.authorization_status contains "Authorization to Operate"
    (case-insensitive). Otherwise we return N/A.

    Data contract
    -------------
    ctx.test_results : TestResults | None
        ctx.test_results.data : list[dict] | None

        Each row is expected (best-effort, case-insensitive) to include:
          - "assessmentProcedure": str  (e.g. "SC-7(18)")
          - "complianceStatus":   str  ("Compliant", "Non-Compliant", ...)
          - "controlAcronym" or "acronym": str (used for reporting)

    Logic
    -----
    - Define the critical control set (same as PowerShell).
    - Look at only those rows whose assessmentProcedure is in that set.
    - If any of those rows are Non-Compliant → FAIL and list them.
    - If none are Non-Compliant → PASS (with manual verification note).
    - If there's no data to examine at all → FAIL (cannot verify).
    """
    test_name = "Test 75: Any Non-Compliant critical (red-diamond) controls?"
    logger.debug("Running %s", test_name)

    # ---------- Scope gate: ATO / post-ATO only ----------
    auth_text = (ctx.authorization_status or "").strip().lower()
    if "authorization to operate" not in auth_text:
        tr = TestResult(
            test_number=75,
            name=test_name,
            result=Result.NA,
            message="Not applicable: system is not in post-ATO phase.",
        )
        status.add(tr)
        logger.info(
            "[T75] N/A — authorization_status does not indicate ATO: %r",
            ctx.authorization_status,
        )
        return tr

    # ---------- Canonical critical (red-diamond) control set ----------
    critical_csv = (
        "AC-17,AC-17(2),IA-2(1),IA-2(2),IA-2(3),IA-2(4),IA-5(1),IR-8,IR-9,RA-5,"
        "SC-7,SC-8,SC-28,SI-2,AC-2,AC-3,AC-4,AC-5,AC-6,AC-6(9),AC-7,AC-9,AC-10,AC-11,"
        "AC-12,AC-18,AC-19,AC-20,AC-24,AC-25,AU-3,AU-4,AU-5,AU-6,AU-9,AU-10,AU-13,"
        "AU-14,AU-16,CM-6,CM-7,CM-7(1),CM-8,CM-10,IA-5,IR-6,PL-8,SA-22,SI-3,SI-4,"
        "SI-4(4),SI-4(5)"
    )
    critical_set = {s.strip().lower() for s in critical_csv.split(",") if s.strip()}

    # ---------- Pull candidate control test rows from structured context ----------
    test_results_block = getattr(ctx, "test_results", None)
    rows = []
    if test_results_block and isinstance(test_results_block.data, list):
        rows = test_results_block.data

    if not rows:
        msg = "No controls test data was returned."
        tr = TestResult(
            test_number=75,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error("[T75] %s", msg)
        return tr

    # ---------- Helper: case-insensitive dict access ----------
    def ci_get(d: dict, key: str):
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    # ---------- Evaluate only "critical" controls ----------
    failed_acronyms: list[str] = []

    for row in rows:
        assessment_proc = (ci_get(row, "assessmentProcedure") or "").strip()
        if not assessment_proc:
            continue

        # Only look at rows whose assessmentProcedure is in that critical set
        if assessment_proc.lower() not in critical_set:
            continue

        compliance = (ci_get(row, "complianceStatus") or "").strip().lower()
        if compliance == "non-compliant":
            # Prefer explicit control acronym for operator readability
            acronym = (
                (ci_get(row, "controlAcronym") or ci_get(row, "acronym") or assessment_proc)
                or "<unknown-control>"
            )
            failed_acronyms.append(str(acronym).strip() or "<unknown-control>")

    # ---------- Build result ----------
    if not failed_acronyms:
        msg = (
            "All critical (red-diamond) controls are compliant or not applicable. "
            "Verification still required to confirm official status."
        )
        tr = TestResult(
            test_number=75,
            name=test_name,
            result=Result.PASS,
            message=msg,
        )
        status.add(tr)
        logger.info("[T75] PASS — no Non-Compliant critical controls.")
        return tr

    msg = (
        "One or more critical controls are Non-Compliant or could not be verified: "
        + ", ".join(sorted(set(failed_acronyms)))
    )
    tr = TestResult(
        test_number=75,
        name=test_name,
        result=Result.FAIL,
        message=msg,
    )
    status.add(tr)
    logger.error("[T75] FAIL — Non-Compliant critical controls: %s", failed_acronyms)
    return tr

def test_76(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 76 — “Not Applicable” CCIs have valid justification (Existing or Expired ATO only)

    Purpose
    -------
    Surface any CCIs marked "Not Applicable" so reviewers can confirm the
    justification is legitimate. We do NOT auto-judge the justification; we
    just flag that NA CCIs exist.

    Scope Gate
    ----------
    Only applies to systems in ATO / post-ATO phase:
      ctx.authorization_status must contain "Authorization to Operate"
      (case-insensitive). Otherwise → N/A.

    Data Contract
    -------------
    ctx.test_results : TestResults | None
        ctx.test_results.data : list[dict] | None

        Each dict is expected (best-effort, case-insensitive) to include:
          - "complianceStatus": str (e.g., "Compliant", "Not Applicable")
          - "cci":              str|int (CCI identifier)

    Behavior (mirrors legacy PowerShell)
    ------------------------------------
    - If any row has complianceStatus == "Not Applicable":
        -> CONCERN with list of those CCIs (manual review required).
    - Else:
        -> PASS.
    """
    test_name = "Test 76: Not Applicable CCIs have valid justification (post-ATO)"
    logger.debug("Running %s", test_name)

    # ---------- Scope gate: only run for ATO / post-ATO systems ----------
    auth_text = (ctx.authorization_status or "").strip().lower()
    if "authorization to operate" not in auth_text:
        tr = TestResult(
            test_number=76,
            name=test_name,
            result=Result.NA,
            message="Not applicable: system is not in post-ATO phase.",
        )
        status.add(tr)
        logger.info(
            "[T76] N/A — authorization_status does not indicate ATO: %r",
            ctx.authorization_status,
        )
        return tr

    # ---------- Pull control assessment rows from structured context ----------
    test_results_block = getattr(ctx, "test_results", None)
    rows = []
    if test_results_block and isinstance(test_results_block.data, list):
        rows = test_results_block.data

    # ---------- Helper: case-insensitive dict access ----------
    def ci_get(d: dict, key: str):
        """Return d[key] in a case-insensitive way, or None if missing."""
        if not isinstance(d, dict):
            return None
        key_l = key.lower()
        for k, v in d.items():
            if str(k).lower() == key_l:
                return v
        return None

    # ---------- Scan rows for "Not Applicable" CCIs ----------
    not_applicable_ccis: list[str] = []

    for row in rows:
        compliance = (ci_get(row, "complianceStatus") or "").strip().lower()
        if compliance == "not applicable":
            cci_raw = ci_get(row, "cci")
            not_applicable_ccis.append(
                str(cci_raw).strip() if cci_raw is not None else "<unknown-cci>"
            )

    # ---------- Build result ----------
    if not not_applicable_ccis:
        # No NA CCIs → PASS
        tr = TestResult(
            test_number=76,
            name=test_name,
            result=Result.PASS,
            message="All CCIs are applicable. Verification may still be required to confirm official status.",
        )
        status.add(tr)
        logger.info("[T76] PASS — no Not Applicable CCIs found.")
        return tr

    # NA CCIs found → CONCERN
    msg = (
        "One or more CCIs are marked Not Applicable; verify justification: "
        + ", ".join(sorted(set(not_applicable_ccis)))
    )
    tr = TestResult(
        test_number=76,
        name=test_name,
        result=Result.CONCERN,
        message=msg,
    )
    status.add(tr)
    logger.warning(
        "[T76] CONCERN — NA CCIs present: %s", not_applicable_ccis
    )
    return tr

#Test 77 was removed. So its not here either.

def test_78(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 78 — SLCM (ConMon) strategy and fields populated for Implemented/Planned/NA controls (post-ATO).

    Purpose
    -------
    For controls that are Implemented, Planned, or Not Applicable, ensure required
    SLCM / Continuous Monitoring metadata exists:
      - slcmCriticality
      - slcmFrequency
      - slcmMethod
      - slcmReporting
      - slcmTracking
      - slcmComments

    Scope Gate
    ----------
    Only applies to systems in ATO / post-ATO phase:
      ctx.authorization_status must contain "Authorization to Operate"
      (case-insensitive). Otherwise → N/A.

    Data Contract
    -------------
    Primary:
        ctx.controls : Controls | None
            ctx.controls.data : list[dict] | None

    Fallback (fixture-based):
        ctx.fixtures.controls : Controls | None
            ctx.fixtures.controls.data : list[dict] | None

    Each dict should (best-effort, case-insensitive) include:
      - "implementationStatus": str
          e.g. "Implemented", "Planned", "Not Applicable"
          (may include additional text; we mimic PowerShell's -like substring behavior)
      - "acronym" or "controlAcronym": str   (for reporting)
      - SLCM fields listed above.
        Any of these being null / "" / "Undetermined" means "missing".

    Behavior (parity with legacy PowerShell)
    ----------------------------------------
    - Only look at controls whose implementationStatus is *like* one of:
        Implemented, Planned, Not Applicable.  (substring, case-insensitive)
    - For those controls, if *any* required SLCM field is null/missing/blank/
      "Undetermined" → that control is flagged.
    - If no flagged controls → PASS.
    - If any flagged → FAIL and list them.

    Debugging
    ---------
    This implementation logs, for each tracked control:
      - implementationStatus
      - full key set present in the row
      - values and "missing?" decision for each SLCM field
    """
    test_name = (
        "Test 78: SLCM (ConMon) fields populated for Implemented/Planned/NA controls"
    )
    logger.debug("Running %s", test_name)

    # ---------- Scope gate: only for ATO / post-ATO systems ----------
    auth_text = (ctx.authorization_status or "").strip().lower()
    if "authorization to operate" not in auth_text:
        tr = TestResult(
            test_number=78,
            name=test_name,
            result=Result.NA,
            message="Not Applicable: System is not in Post ATO Phase",
        )
        status.add(tr)
        logger.info(
            "[T78] N/A — authorization_status does not indicate ATO: %r",
            ctx.authorization_status,
        )
        return tr

    # ---------- Fetch control rows from structured context ----------
    rows: list[dict] = []

    # Primary: top-level controls model
    controls_block = getattr(ctx, "controls", None)
    data_block = getattr(controls_block, "data", None)
    if isinstance(data_block, list):
        rows = data_block

    # Fallback: fixtures.controls model (if loader hangs data there)
    if not rows:
        fixtures = getattr(ctx, "fixtures", None)
        if fixtures is not None:
            fixtures_controls = getattr(fixtures, "controls", None)
            fixtures_data = getattr(fixtures_controls, "data", None)
            if isinstance(fixtures_data, list):
                rows = fixtures_data

    logger.info(
        "[T78] Using %d controls rows from ctx.controls/fixtures.controls.",
        len(rows),
    )

    # ---------- Helpers ----------
    def ci_get(d: dict, key: str) -> Optional[Any]:
        """Case-insensitive dict get. Returns None if key not present or d not a dict."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def is_blank_or_undetermined(value: object) -> bool:
        """
        Return True if the field is considered "missing" for SLCM purposes.

        Mirrors the PowerShell checks:
          ($null -eq $control2.slcmX) -or ($control2.slcmX -like "Undetermined")
        but we also treat empty-string as missing for safety.
        """
        if value is None:
            return True
        s = str(value).strip()
        if s == "":
            return True
        return "undetermined" in s.lower()

    # mimic `-like "Implemented"` / `-like "Planned"` / `-like "Not Applicable"`
    def is_tracked_status(raw: object) -> bool:
        text = str(raw or "").lower()
        return (
            "implemented" in text
            or "planned" in text
            or "not applicable" in text
        )

    slcm_fields = [
        "slcmCriticality",
        "slcmFrequency",
        "slcmMethod",
        "slcmReporting",
        "slcmTracking",
        "slcmComments",
    ]

    missing_slcm_for: list[str] = []
    tracked_controls_count = 0

    logger.info("[T78] ---- BEGIN DEBUG DUMP FOR CONTROLS WITH IMPLEMENTED/PLANNED/NA ----")

    # ---------- Evaluate each relevant control ----------
    for ctrl in rows:
        if not isinstance(ctrl, dict):
            continue

        impl_status_raw = ci_get(ctrl, "implementationStatus")
        acronym = (
            (ci_get(ctrl, "acronym") or ci_get(ctrl, "controlAcronym") or "")
            .strip()
            or "<unknown-control>"
        )

        # Log the raw keys and implementationStatus for every row so we can
        # see exactly what shape we're working with.
        logger.info(
            "[T78] Control row keys for %s: %s",
            acronym,
            sorted(str(k) for k in ctrl.keys()),
        )
        logger.info(
            "[T78] Control %s implementationStatus raw: %r",
            acronym,
            impl_status_raw,
        )

        if not is_tracked_status(impl_status_raw):
            # Only care about Implemented / Planned / Not Applicable (substring match)
            continue

        tracked_controls_count += 1

        # For tracked controls, log each SLCM field value and missing decision
        any_missing = False
        for field_name in slcm_fields:
            raw_val = ci_get(ctrl, field_name)
            missing = is_blank_or_undetermined(raw_val)
            logger.info(
                "[T78]   %s: value=%r, missing=%s",
                field_name,
                raw_val,
                missing,
            )
            if missing:
                any_missing = True

        if any_missing:
            missing_slcm_for.append(acronym)
            logger.info(
                "[T78] -> Control %s flagged as missing SLCM data.", acronym
            )
        else:
            logger.info(
                "[T78] -> Control %s has all SLCM fields populated.", acronym
            )

    logger.info(
        "[T78] Tracked controls (Implemented/Planned/Not Applicable): %d",
        tracked_controls_count,
    )
    logger.info(
        "[T78] Controls flagged as missing SLCM: %s",
        sorted(set(missing_slcm_for)) if missing_slcm_for else "[]",
    )

    # ---------- Results ----------
    if not missing_slcm_for:
        tr = TestResult(
            test_number=78,
            name=test_name,
            result=Result.PASS,
            message=(
                "All Implemented/Planned/Not Applicable controls have SLCM data populated. "
                "Verification may still be required to confirm official status."
            ),
        )
        status.add(tr)
        logger.info("[T78] PASS — SLCM fields populated for all relevant controls.")
        return tr

    fail_msg = (
        "FAIL: One or more of the Controls have a status of Implemented, Planned, or "
        "Not applicable and have blank SLCM information: "
        f"{', '.join(sorted(set(missing_slcm_for)))}"
    )
    tr = TestResult(
        test_number=78,
        name=test_name,
        result=Result.FAIL,
        message=fail_msg,
    )
    status.add(tr)
    logger.error(
        "[T78] FAIL — Controls missing SLCM data: %s", sorted(set(missing_slcm_for))
    )
    return tr



def test_79(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 79 — Incident Response artifacts (IR-8 plan + IR-3 recent test evidence)

    Purpose
    -------
    Confirm that:
      - An Incident Response Plan (IRP) artifact is declared, and
      - That artifact has a "Last Reviewed" / test date within the last year.

    This mirrors the legacy check:
    - Only applies to systems in post-ATO (Authorization to Operate).
    - FAIL if missing artifact reference.
    - FAIL if no review/test date or the date is older than one year.
    - PASS otherwise.

    Data (new structured model)
    ---------------------------
    ctx.system_info.incidentresponseplanartifact : Optional[str]
        Exact filename reference recorded in eMASS.

    ctx.artifact_details.data : Optional[List[Dict[str, Any]]]
        Each row is an artifact record. Expected fields per row (case-insensitive):
        - "filename"         : str
        - "Last Reviewed"    : epoch seconds (int/str)  [legacy eMASS export]
          OR "last_reviewed" : epoch seconds (int/str)  [normalized]

    Returns
    -------
    TestResult:
        - NA      : if system is not post-ATO
        - PASS    : artifact exists AND reviewed/tested ≤ 1 year ago
        - FAIL    : otherwise
    """
    test_name = (
        "Test 79: IR-8 plan present and IR-3 evidence within one year"
    )
    logger.debug("Running %s", test_name)

    # ---------- Scope gate: only for post-ATO systems ----------
    auth_text = (ctx.authorization_status or "").strip().lower()
    if "authorization to operate" not in auth_text:
        tr = TestResult(
            test_number=79,
            name=test_name,
            result=Result.NA,
            message="Not applicable: system is not in post-ATO phase.",
        )
        status.add(tr)
        logger.info(
            "[T79] N/A — authorization_status does not indicate ATO: %r",
            ctx.authorization_status,
        )
        return tr

    # ---------- Pull Incident Response Plan filename from structured system_info ----------
    sys_info = getattr(ctx, "system_info", None)
    irp_name = ""
    if sys_info and hasattr(sys_info, "incidentresponseplanartifact"):
        irp_name = (sys_info.incidentresponseplanartifact or "").strip()

    # ---------- Pull artifact rows from structured artifact_details ----------
    art_block = getattr(ctx, "artifact_details", None)
    artifact_rows = []
    if art_block and isinstance(art_block.data, list):
        artifact_rows = art_block.data

    # Helper: case-insensitive getter on a dict row
    def ci_get(d: dict, key: str):
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    # Helper: best-effort parse to int epoch seconds
    def to_epoch(v) -> Optional[int]:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            try:
                return int(v)
            except Exception:
                return None
        # strings like "1716944927"
        try:
            s = str(v).strip()
            return int(float(s))
        except Exception:
            return None

    # Find the artifact row whose filename matches the system-declared IRP filename
    matching_row = None
    if irp_name:
        for row in artifact_rows:
            fname = (ci_get(row, "filename") or "").strip()
            if fname and fname == irp_name:
                matching_row = row
                break

    # If we can't even match an artifact by filename, this is a FAIL
    if not irp_name or not matching_row:
        tr = TestResult(
            test_number=79,
            name=test_name,
            result=Result.FAIL,
            message="Incident Response Plan artifact is missing or not found in artifacts list.",
        )
        status.add(tr)
        logger.error(
            "[T79] FAIL — Missing IRP artifact reference or no matching artifact. "
            "irp_name=%r match_found=%s",
            irp_name,
            bool(matching_row),
        )
        return tr

    # Extract "Last Reviewed" epoch from the matching row.
    # We support both legacy 'Last Reviewed' and normalized 'last_reviewed'.
    last_rev_raw = (
        ci_get(matching_row, "Last Reviewed")
        or ci_get(matching_row, "last_reviewed")
    )
    last_reviewed_epoch = to_epoch(last_rev_raw)

    # One-year cutoff
    ONE_YEAR_SECONDS = 365 * 24 * 60 * 60
    one_year_ago_epoch = int(_time.time()) - ONE_YEAR_SECONDS

    # Missing or stale review date → FAIL
    if last_reviewed_epoch is None:
        tr = TestResult(
            test_number=79,
            name=test_name,
            result=Result.FAIL,
            message="Incident Response Plan artifact found but lacks a valid Last Reviewed/test date.",
        )
        status.add(tr)
        logger.error(
            "[T79] FAIL — IRP artifact '%s' has no valid Last Reviewed epoch (%r).",
            irp_name,
            last_rev_raw,
        )
        return tr

    if last_reviewed_epoch <= one_year_ago_epoch:
        tr = TestResult(
            test_number=79,
            name=test_name,
            result=Result.FAIL,
            message="Incident Response Plan review/test date is older than one year.",
        )
        status.add(tr)
        logger.error(
            "[T79] FAIL — IRP artifact '%s' stale. last_reviewed_epoch=%s cutoff=%s",
            irp_name,
            last_reviewed_epoch,
            one_year_ago_epoch,
        )
        return tr

    # Good: artifact exists AND reviewed within the past year → PASS
    tr = TestResult(
        test_number=79,
        name=test_name,
        result=Result.PASS,
        message=f"Incident Response Plan present and current: {irp_name}",
    )
    status.add(tr)
    logger.info(
        "[T79] PASS — IRP artifact '%s' reviewed recently (epoch=%s).",
        irp_name,
        last_reviewed_epoch,
    )
    return tr


def test_80(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 80 — RA-5 (Vulnerability Scanning) included in the baseline

    Purpose
    -------
    Ensure RA-5 is part of the system's control baseline.

    Data Sources (new structured model)
    -----------------------------------
    ctx.controls: Controls | None
        ctx.controls.data : Optional[List[Dict[str, Any]]]
            Each element should describe one control and may contain:
              - "acronym" / "controlAcronym" : str  (e.g. "RA-5")
              - "includedStatus" / "includedstatus" : str  (expect "Baseline")

    Logic
    -----
    - Find the row for RA-5.
    - PASS if its includedStatus == "Baseline" (case-insensitive).
    - Otherwise FAIL.
    - If controls data is missing entirely → FAIL.
    """
    test_name = "Test 80: RA-5 is included in the baseline"
    logger.debug("Running %s", test_name)

    # --- Pull controls list from structured context ---
    controls_block = getattr(ctx, "controls", None)
    control_rows = []
    if controls_block and isinstance(controls_block.data, list):
        control_rows = controls_block.data

    # Helper: case-insensitive dict getter
    def ci_get(d: dict, key: str):
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    # --- Find RA-5 row ---
    ra5_row = None
    for row in control_rows:
        acr = (ci_get(row, "acronym") or ci_get(row, "controlAcronym") or "").strip()
        if acr.upper() == "RA-5":
            ra5_row = row
            break

    if not ra5_row:
        tr = TestResult(
            test_number=80,
            name=test_name,
            result=Result.FAIL,
            message="Control RA-5 not found in control catalog.",
        )
        status.add(tr)
        logger.error("[T80] FAIL — RA-5 control row not found.")
        return tr

    # --- Check included status (Baseline expected) ---
    included_status = (
        (ci_get(ra5_row, "includedStatus") or ci_get(ra5_row, "includedstatus") or "")
        .strip()
        .lower()
    )

    if included_status == "baseline":
        tr = TestResult(
            test_number=80,
            name=test_name,
            result=Result.PASS,
            message="Control RA-5 is included in the baseline.",
        )
        status.add(tr)
        logger.info("[T80] PASS — RA-5 includedStatus=Baseline")
        return tr

    tr = TestResult(
        test_number=80,
        name=test_name,
        result=Result.FAIL,
        message="Control RA-5 is not in the baseline or could not be verified.",
    )
    status.add(tr)
    logger.error("[T80] FAIL — RA-5 includedStatus=%r", included_status)
    return tr



def test_81(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 81 — Assess Only: required security controls are not marked “Not Applicable”

    Purpose
    -------
    For Assess Only packages (i.e. not full "Assess and Authorize"), make sure
    certain required controls are actually addressed and not waived as "Not Applicable".

    Required controls:
      AC-2.9, AC-2.18, SA-5.10, SA-11.4, SA-11.8, SC-5.1, SI-2.2, SI-2.4

    Scope Gate
    ----------
    - If ctx.registration_type == "Assess and Authorize" (case-insensitive match)
      → N/A (mirrors original behavior).

    Data Source (new structured world)
    ----------------------------------
    ctx.test_results : TestResults | None
        ctx.test_results.data : Optional[List[Dict[str, Any]]]

    Each row in .data may include (case-insensitive keys):
      - "controlAcronym" / "acronym" / "assessmentProcedure"
      - "complianceStatus"

    Logic
    -----
    - Pull all rows for those 8 control identifiers.
    - FAIL if any of them have complianceStatus "Not Applicable"/"N/A"/"NA".
    - FAIL if none of them are found at all (cannot verify).
    - PASS otherwise.
    """
    test_name = (
        "Test 81: Assess Only — AC-2.9, AC-2.18, SA-5.10, SA-11.4, SA-11.8, "
        "SC-5.1, SI-2.2, SI-2.4 must not be Not Applicable"
    )
    logger.debug("Running %s", test_name)

    # ---------- Scope gate ----------
    reg_type = (ctx.registration_type or "").strip().lower()
    if reg_type == "assess and authorize":
        tr = TestResult(
            test_number=81,
            name=test_name,
            result=Result.NA,
            message="Not applicable: system is not Assess Only.",
        )
        status.add(tr)
        logger.info("[T81] N/A — registration_type=%r", ctx.registration_type)
        return tr

    # ---------- Helpers ----------
    def ci_get(d: dict, key: str):
        """Case-insensitive dict get."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    # Grab the structured test results list
    test_results_block = getattr(ctx, "test_results", None)
    rows = []
    if test_results_block and isinstance(test_results_block.data, list):
        rows = test_results_block.data

    # The controls that must NOT be "Not Applicable"
    required_controls = {
        "AC-2.9",
        "AC-2.18",
        "SA-5.10",
        "SA-11.4",
        "SA-11.8",
        "SC-5.1",
        "SI-2.2",
        "SI-2.4",
    }

    def extract_control_id(row: dict) -> str:
        """
        Try to pull a recognizable control identifier from a row.
        We accept any of these fields, falling back in order.
        """
        for key in ("controlAcronym", "acronym", "assessmentProcedure", "control"):
            val = ci_get(row, key)
            if val:
                return str(val).strip().upper()
        return ""

    # Filter rows down to just the required control set
    relevant_rows = []
    for r in rows:
        ctrl_id = extract_control_id(r)
        if ctrl_id in (c.upper() for c in required_controls):
            relevant_rows.append((ctrl_id, r))

    # If we couldn't find ANY of the required controls, we can't verify → FAIL
    if not relevant_rows:
        tr = TestResult(
            test_number=81,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Required control test results not found; cannot verify non-NA status "
                "for AC-2.9 / AC-2.18 / SA-5.10 / SA-11.4 / SA-11.8 / SC-5.1 / SI-2.2 / SI-2.4."
            ),
        )
        status.add(tr)
        logger.error("[T81] FAIL — no rows for required control set.")
        return tr

    # Check complianceStatus for "Not Applicable"
    na_controls: list[str] = []
    for ctrl_id, row in relevant_rows:
        compliance_txt = (ci_get(row, "complianceStatus") or "").strip().lower()
        if compliance_txt in {"not applicable", "n/a", "na"}:
            na_controls.append(ctrl_id)

    # If any required control is NA → FAIL
    if na_controls:
        tr = TestResult(
            test_number=81,
            name=test_name,
            result=Result.FAIL,
            message=(
                "One or more required controls are marked Not Applicable: "
                + ", ".join(sorted(set(na_controls)))
            ),
        )
        status.add(tr)
        logger.error("[T81] FAIL — NA controls: %s", na_controls)
        return tr

    # Otherwise PASS
    tr = TestResult(
        test_number=81,
        name=test_name,
        result=Result.PASS,
        message="All required controls are addressed (none marked Not Applicable).",
    )
    status.add(tr)
    logger.info("[T81] PASS — all required controls addressed.")
    return tr


def test_82(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 82 — 'Compliant' controls must be Implemented or Inherited

    Purpose
    -------
    Ensure configuration consistency: any control whose complianceStatus is
    "Compliant" (or "C") must have implementationStatus of either "Implemented"
    or "Inherited". This mirrors the original PowerShell logic.

    Data Source (new structured world)
    ----------------------------------
    ctx.controls : Controls | None
        ctx.controls.data : Optional[List[Dict[str, Any]]]

    Expected fields per row (case-insensitive lookup):
      - acronym                → control ID (e.g. "AC-2")
      - complianceStatus       → "C" or "Compliant"
      - implementationStatus   → "Implemented" / "Inherited" / other

    Behavior
    --------
    - Collect all rows where complianceStatus is compliant.
    - For those rows, flag any whose implementationStatus is neither Implemented nor Inherited.
    - If any offenders → FAIL (list offending acronyms).
    - If none → PASS.
    - If no control data available at all → FAIL (cannot validate).
    """
    test_name = "Test 82: Compliant controls are Implemented or Inherited"
    logger.debug("Running %s", test_name)

    # -------- helpers --------
    def ci_get(d: dict, key: str):
        """Case-insensitive dict get."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    # Pull the structured controls dataset
    controls_block = getattr(ctx, "controls", None)
    rows = []
    if controls_block and isinstance(controls_block.data, list):
        rows = controls_block.data

    if not rows:
        tr = TestResult(
            test_number=82,
            name=test_name,
            result=Result.FAIL,
            message="No control catalog found to evaluate implementation status.",
        )
        status.add(tr)
        logger.error("[T82] FAIL — missing controls dataset.")
        return tr

    offenders: list[str] = []

    for row in rows:
        comp_status = (ci_get(row, "complianceStatus") or "").strip().lower()
        # Only care about rows that claim to be 'compliant'
        if comp_status in ("c", "compliant"):
            impl_status = (ci_get(row, "implementationStatus") or "").strip().lower()
            if impl_status not in ("implemented", "inherited"):
                acronym = (ci_get(row, "acronym") or "").strip() or "<unknown>"
                offenders.append(acronym)

    if offenders:
        tr = TestResult(
            test_number=82,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Compliant controls not marked Implemented/Inherited: "
                + ", ".join(sorted(offenders))
            ),
        )
        status.add(tr)
        logger.error("[T82] FAIL — offenders: %s", offenders)
        return tr

    tr = TestResult(
        test_number=82,
        name=test_name,
        result=Result.PASS,
        message="All compliant controls are Implemented or Inherited.",
    )
    status.add(tr)
    logger.info("[T82] PASS — compliance/implementation alignment OK.")
    return tr

def test_83(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 83 — Non-Compliant controls must be “Planned” or “Not Implemented”.

    Purpose
    -------
    Validate configuration hygiene: every control with complianceStatus == "NC"
    (Non-Compliant) must have an implementationStatus of either "Planned" or
    "Not Implemented". This mirrors the original PowerShell logic.

    Data Source (new structured context)
    ------------------------------------
    ctx.controls : Controls | None
        ctx.controls.data : Optional[List[Dict[str, Any]]]

    Expected fields per row (case-insensitive lookup):
      - acronym                (string)
      - complianceStatus       ("NC" / "Non-Compliant")
      - implementationStatus   ("Planned" / "Not Implemented")

    Behavior
    --------
    - Collect all rows whose complianceStatus is Non-Compliant.
    - For each of those, require implementationStatus ∈ {"Planned", "Not Implemented"}.
    - If any Non-Compliant control fails that rule → FAIL and list them.
    - If dataset missing entirely → FAIL (cannot validate).
    - Otherwise → PASS.
    """
    test_name = "Test 83: Non-Compliant controls have Planned or Not Implemented status"
    logger.debug("Running %s", test_name)

    def ci_get(d: dict, key: str):
        """Case-insensitive dict getter."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    # Pull structured control rows from the new context
    controls_block = getattr(ctx, "controls", None)
    rows = []
    if controls_block and isinstance(controls_block.data, list):
        rows = controls_block.data

    if not rows:
        tr = TestResult(
            test_number=83,
            name=test_name,
            result=Result.FAIL,
            message="No controls dataset available to evaluate non-compliant statuses.",
        )
        status.add(tr)
        logger.error("[T83] FAIL — controls dataset missing.")
        return tr

    offenders: list[str] = []

    for row in rows:
        compliance = (ci_get(row, "complianceStatus") or "").strip().lower()
        if compliance in ("nc", "non-compliant"):
            impl = (ci_get(row, "implementationStatus") or "").strip().lower()
            if impl not in ("planned", "not implemented"):
                acronym = (ci_get(row, "acronym") or "").strip() or "<unknown>"
                offenders.append(acronym)

    if offenders:
        tr = TestResult(
            test_number=83,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Non-Compliant controls not marked Planned/Not Implemented: "
                + ", ".join(sorted(offenders))
            ),
        )
        status.add(tr)
        logger.error("[T83] FAIL — offenders: %s", offenders)
        return tr

    tr = TestResult(
        test_number=83,
        name=test_name,
        result=Result.PASS,
        message="All non-compliant controls are Planned or Not Implemented.",
    )
    status.add(tr)
    logger.info("[T83] PASS — statuses aligned.")
    return tr


def test_84(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 84 — Estimated Completion Date (ECD) sanity checks by status.

    Purpose
    -------
    Validate `estimatedCompletionDate` (ECD) alignment with implementation/compliance state:
      • For Planned implementationStatus      → ECD must be in the future.
      • For Compliant complianceStatus        → ECD must be today or in the past (not future).
      • For Not Applicable complianceStatus   → ECD must be blank.

    Fidelity Note
    -------------
    The legacy PowerShell PASSes if ANY of the violation lists is empty (logical OR).
    We mirror that lenient behavior 1:1.

    Data Source (new structured context)
    ------------------------------------
    ctx.controls : Controls | None
        ctx.controls.data : Optional[List[Dict[str, Any]]]

    Expected fields per control row (case-insensitive):
      • complianceStatus
      • implementationStatus
      • estimatedCompletionDate (epoch seconds or ISO-8601)
      • acronym (for reporting)
    """
    test_name = "Test 84: ECD alignment with Planned/Compliant/Not Applicable"
    logger.debug("Running %s", test_name)

    now_epoch = int(_time.time())

    def ci_get(d: dict, key: str):
        """Case-insensitive dict getter."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def to_epoch_seconds(v) -> Optional[int]:
        """
        Accept:
          - numeric epoch (int/float or numeric string)
          - ISO-8601 string (YYYY-MM-DD...; naive assumed UTC)
        Return epoch seconds int, or None if unknown/unparseable.
        """
        if v is None:
            return None

        # Try numeric first
        try:
            f = float(v)
            if f > 0:
                return int(f)
        except (TypeError, ValueError):
            pass

        # Try ISO-8601-ish string
        if isinstance(v, str) and v.strip():
            try:
                # allow trailing Z
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                return int(dt.timestamp())
            except Exception:
                return None

        return None

    # Pull controls list from structured context
    controls_block = getattr(ctx, "controls", None)
    rows = []
    if controls_block and isinstance(controls_block.data, list):
        rows = controls_block.data

    if not rows:
        tr = TestResult(
            test_number=84,
            name=test_name,
            result=Result.FAIL,
            message="No controls dataset available to evaluate ECD rules.",
        )
        status.add(tr)
        logger.error("[T84] FAIL — controls dataset missing.")
        return tr

    # Buckets for violations
    compliant_wrong: list[str] = []
    na_wrong: list[str] = []
    planned_wrong: list[str] = []

    def is_compliant(s: str) -> bool:
        s = (s or "").strip().lower()
        return s in {"c", "compliant"}

    def is_na(s: str) -> bool:
        s = (s or "").strip().lower()
        return s in {"na", "n/a", "not applicable"}

    def is_planned(s: str) -> bool:
        s = (s or "").strip().lower()
        return s == "planned"

    for row in rows:
        acronym = (ci_get(row, "acronym") or "").strip() or "<unknown>"
        comp = (ci_get(row, "complianceStatus") or "").strip()
        impl = (ci_get(row, "implementationStatus") or "").strip()
        ecd_epoch = to_epoch_seconds(ci_get(row, "estimatedCompletionDate"))

        # Rule 1: Compliant -> ECD must NOT be in the future
        # PowerShell flags only if ECD is in the future.
        if is_compliant(comp):
            if ecd_epoch is not None and ecd_epoch > now_epoch:
                compliant_wrong.append(acronym)

        # Rule 2: Not Applicable -> ECD must be blank
        if is_na(comp):
            if ecd_epoch is not None:
                na_wrong.append(acronym)

        # Rule 3: Planned -> ECD must be in the future
        # PowerShell flags if ECD missing OR ECD in past/now.
        if is_planned(impl):
            if ecd_epoch is None or ecd_epoch <= now_epoch:
                planned_wrong.append(acronym)

    # Legacy lenient logic:
    # PASS if ANY of the violation buckets is empty.
    if (not compliant_wrong) or (not na_wrong) or (not planned_wrong):
        tr = TestResult(
            test_number=84,
            name=test_name,
            result=Result.PASS,
            message=(
                "Estimated completion dates are within expected tolerances "
                "(per original lenient logic)."
            ),
        )
        status.add(tr)
        logger.info(
            "[T84] PASS — lenient OR satisfied "
            "(compliant_wrong=%d, na_wrong=%d, planned_wrong=%d)",
            len(compliant_wrong),
            len(na_wrong),
            len(planned_wrong),
        )
        return tr

    # Otherwise FAIL; build details string
    details_parts = []
    if compliant_wrong:
        details_parts.append(
            "Compliant with future ECD: " + ", ".join(sorted(compliant_wrong))
        )
    if na_wrong:
        details_parts.append(
            "Not Applicable with non-blank ECD: " + ", ".join(sorted(na_wrong))
        )
    if planned_wrong:
        details_parts.append(
            "Planned with missing/past ECD: " + ", ".join(sorted(planned_wrong))
        )

    details_msg = " | ".join(details_parts)

    tr = TestResult(
        test_number=84,
        name=test_name,
        result=Result.FAIL,
        message=details_msg,
    )
    status.add(tr)
    logger.error("[T84] FAIL — %s", details_msg)
    return tr


def test_85(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 85 — “Not Applicable” controls have correct implementation status.

    Purpose
    -------
    Ensure every control marked Not Applicable has an implementationStatus of
    either "Not Applicable" or "Inherited". Direct 1:1 port of the legacy logic.

    Data source (structured context)
    --------------------------------
    ctx.controls : Controls | None
      ctx.controls.data : Optional[List[Dict[str, Any]]]

    For each control row (case-insensitive keys):
      - complianceStatus
      - implementationStatus
      - acronym (for reporting)

    Behavior
    --------
    - FAIL if controls dataset is missing.
    - For each control where complianceStatus ∈ {"NA","N/A","Not Applicable"}:
        * implementationStatus MUST be "Not Applicable" or "Inherited".
      If any violate → FAIL listing those control acronyms.
    - Otherwise PASS.
    """
    test_name = "Test 85: NA controls have Not Applicable or Inherited implementation status"
    logger.debug("Running %s", test_name)

    def ci_get(d: dict, key: str):
        """Case-insensitive dict getter."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def is_na(val: object) -> bool:
        s = (str(val or "")).strip().lower()
        return s in {"na", "n/a", "not applicable"}

    # Pull control rows from structured ctx
    controls_block = getattr(ctx, "controls", None)
    rows = []
    if controls_block and isinstance(controls_block.data, list):
        rows = controls_block.data

    if not rows:
        tr = TestResult(
            test_number=85,
            name=test_name,
            result=Result.FAIL,
            message="Controls dataset not available.",
        )
        status.add(tr)
        logger.error("[T85] FAIL — controls dataset missing.")
        return tr

    offenders: list[str] = []

    for row in rows:
        compliance = ci_get(row, "complianceStatus")
        if not is_na(compliance):
            continue

        impl = (ci_get(row, "implementationStatus") or "").strip().lower()
        if impl not in {"not applicable", "inherited"}:
            acronym = (ci_get(row, "acronym") or "").strip() or "<unknown>"
            offenders.append(acronym)

    if offenders:
        tr = TestResult(
            test_number=85,
            name=test_name,
            result=Result.FAIL,
            message=(
                "NA controls not in correct implementation status: "
                + ", ".join(sorted(offenders))
            ),
        )
        status.add(tr)
        logger.error("[T85] FAIL — offenders: %s", offenders)
        return tr

    tr = TestResult(
        test_number=85,
        name=test_name,
        result=Result.PASS,
        message="All Not Applicable controls have the correct implementation status.",
    )
    status.add(tr)
    logger.info("[T85] PASS — all NA controls properly marked.")
    return tr


def test_86(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 86 — Completed Risk Assessment for Non-Compliant controls.

    Purpose
    -------
    For every Non-Compliant control, verify required risk assessment fields exist:
      • vulnerabilitysummary
      • mitigations
      • impactdescription
      • recommendations

    Behavior (1:1 with legacy script)
    ---------------------------------
    - FAIL if we can't load the control dataset at all.
    - For each control where compliancestatus ∈ {"NC","Non-Compliant","Non Compliant"}:
        * If ANY of the four fields is None → that control is flagged.
    - FAIL if any flagged controls.
    - PASS if all NC controls include full RA content.

    Data source in new model
    ------------------------
    ctx.controls: Controls | None
      ctx.controls.data: Optional[List[Dict[str, Any]]]
    """

    test_name = "Test 86: Risk assessment completed for Non-Compliant controls"
    logger.debug("Running %s", test_name)

    def ci_get(d: dict, key: str):
        """Case-insensitive dict getter."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def is_nc(val: object) -> bool:
        s = (str(val or "")).strip().lower()
        return s in {"nc", "non-compliant", "non compliant"}

    # pull controls from structured ctx
    controls_block = getattr(ctx, "controls", None)
    rows: list[dict] = []
    if controls_block and isinstance(controls_block.data, list):
        rows = controls_block.data

    if not rows:
        tr = TestResult(
            test_number=86,
            name=test_name,
            result=Result.FAIL,
            message="Controls dataset not available.",
        )
        status.add(tr)
        logger.error("[T86] FAIL — controls dataset missing.")
        return tr

    missing_ra: list[str] = []

    for row in rows:
        if not is_nc(ci_get(row, "compliancestatus")):
            continue

        acronym = (ci_get(row, "acronym") or "").strip() or "<unknown>"

        vuln = ci_get(row, "vulnerabilitysummary")
        mits = ci_get(row, "mitigations")
        impact = ci_get(row, "impactdescription")
        recs = ci_get(row, "recommendations")

        # Legacy PS only checked for $null, not empty string.
        # We mirror that: None triggers failure; "" does not.
        if vuln is None or mits is None or impact is None or recs is None:
            missing_ra.append(acronym)

    if missing_ra:
        tr = TestResult(
            test_number=86,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Non-Compliant controls missing risk assessment fields: "
                + ", ".join(sorted(missing_ra))
            ),
        )
        status.add(tr)
        logger.error("[T86] FAIL — missing RA for: %s", missing_ra)
        return tr

    tr = TestResult(
        test_number=86,
        name=test_name,
        result=Result.PASS,
        message="All Non-Compliant controls include a completed risk assessment.",
    )
    status.add(tr)
    logger.info("[T86] PASS — all NC controls have risk assessment content.")
    return tr


def test_87(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 87 — ATC-specific Non-Compliant controls have a completed Risk Assessment.

    Plain English
    -------------
    For each control in the ATC critical control set:
      If that control is Non-Compliant, it MUST have all four RA fields populated:
        • vulnerabilitysummary
        • mitigations
        • impactdescription
        • recommendations

    Data contract
    -------------
    ctx.controls: Controls | None
      ctx.controls.data: list[dict] | None

    Each row in ctx.controls.data is expected to roughly match eMASS "CAC / Controls"
    export shape (case-insensitive keys), for example:

        {
          "acronym": "AC-17",
          "complianceStatus": "Non-Compliant",
          "vulnerabilitySummary": "...",
          "mitigations": "...",
          "impactDescription": "...",
          "recommendations": "..."
        }

    The source is extremely inconsistent about key casing, underscores, etc.
    We do best-effort case-insensitive lookups.

    Behavior
    --------
    - FAIL if we can't read any control rows at all.
    - For each ATC-critical control that is Non-Compliant:
        * If ANY required RA field is missing (i.e. key absent or value is None),
          we flag that control.
    - PASS if there are zero offenders, else FAIL listing them.
    """

    test_name = "Test 87: ATC NC controls include risk assessment content"
    logger.debug("Running %s", test_name)

    # ---------------------------------------------------------------------
    # Canonical ATC critical set (mirrors Test 72 / Test 75 "red diamond")
    # NOTE: we lower() both sides at compare time so we can match loosely,
    # but we keep originals for reporting.
    # ---------------------------------------------------------------------
    atc_critical = {
        "AC-17","AC-17(2)","IA-2(1)","IA-2(2)","IA-2(3)","IA-2(4)","IA-5(1)","IR-8","IR-9",
        "RA-5","SC-7","SC-8","SC-28","SI-2","AC-2","AC-3","AC-4","AC-5","AC-6","AC-6(9)",
        "AC-7","AC-9","AC-10","AC-11","AC-12","AC-18","AC-19","AC-20","AC-24","AC-25",
        "AU-3","AU-4","AU-5","AU-6","AU-9","AU-10","AU-13","AU-14","AU-16","CM-6",
        "CM-7","CM-7(1)","CM-8","CM-10","IA-5","IR-6","PL-8","SA-22","SI-3","SI-4",
        "SI-4(4)","SI-4(5)",
    }
    atc_critical_lc = {c.lower() for c in atc_critical}

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------

    def ci_get(d: dict, key: str):
        """
        Case-insensitive getter for dict-like rows.

        We do *not* normalize/strip values here; caller decides how to coerce.
        """
        if not isinstance(d, dict):
            return None
        wanted = key.lower()
        for k, v in d.items():
            if str(k).lower() == wanted:
                return v
        return None

    def is_nc(val: object) -> bool:
        """
        Return True if val is semantically "non-compliant".
        We accept:
          - "NC"
          - "Non-Compliant"
          - "Non Compliant"
          (case-insensitive, leading/trailing whitespace ignored)
        """
        s = (str(val or "")).strip().lower()
        return s in {"nc", "non-compliant", "non compliant"}

    # ---------------------------------------------------------------------
    # Pull candidate rows from ctx.controls
    # ctx.controls is a Controls model that we hydrated in build_system_context_from_emass
    # with .data = filtered["Controls"] (full list, not just first row).
    # ---------------------------------------------------------------------
    controls_block = getattr(ctx, "controls", None)

    rows: list[dict] = []
    if controls_block and isinstance(controls_block.data, list):
        rows = controls_block.data

    logger.debug(
        "[T87] ctx.controls present=%s row_count=%s sample_row=%s",
        bool(controls_block),
        len(rows),
        rows[0] if rows else None,
    )

    if not rows:
        # No controls to evaluate at all -> automatic FAIL.
        msg = "Controls dataset not available."
        tr = TestResult(
            test_number=87,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error("[T87] FAIL — %s", msg)
        return tr

    # ---------------------------------------------------------------------
    # Evaluate each ATC-critical control that is Non-Compliant
    #
    # Required RA fields (must not be None):
    #   - vulnerabilitysummary
    #   - mitigations
    #   - impactdescription
    #   - recommendations
    #
    # NOTE:
    # PowerShell logic only enforced "not null". Empty string "" counted as "present".
    # We'll mirror that: treat None/missing as violation; "" is OK.
    # ---------------------------------------------------------------------
    offenders: list[str] = []

    for row in rows:
        # Pull the control acronym / ID in a case-insensitive way.
        raw_acronym = ci_get(row, "acronym")
        acronym = (str(raw_acronym or "")).strip()

        # We also handle cases where "controlAcronym" is present instead of "acronym".
        if not acronym:
            raw_acronym = ci_get(row, "controlAcronym")
            acronym = (str(raw_acronym or "")).strip()

        if not acronym:
            # No acronym? We'll still try to evaluate, but we won't know if it's ATC-critical.
            logger.debug("[T87] Skipping row with no acronym: %s", row)
            continue

        # Only evaluate if this acronym is one of the ATC critical controls.
        if acronym.lower() not in atc_critical_lc:
            continue

        # Only enforce RA completeness if it's Non-Compliant.
        compliance_val = ci_get(row, "compliancestatus")
        if not is_nc(compliance_val):
            logger.debug(
                "[T87] Control %s is ATC-critical but NOT Non-Compliant (%r); skipping.",
                acronym,
                compliance_val,
            )
            continue

        vuln  = ci_get(row, "vulnerabilitysummary")
        mits  = ci_get(row, "mitigations")
        impact = ci_get(row, "impactdescription")
        recs  = ci_get(row, "recommendations")

        logger.debug(
            "[T87] Evaluating NC control %s: vuln=%r mits=%r impact=%r recs=%r",
            acronym, vuln, mits, impact, recs
        )

        # Mirror legacy audit logic:
        # - value must exist (not None). Empty string "" is allowed.
        missing_any = (
            vuln is None or
            mits is None or
            impact is None or
            recs is None
        )

        if missing_any:
            offenders.append(acronym)

    # ---------------------------------------------------------------------
    # Final decision
    # ---------------------------------------------------------------------
    if offenders:
        msg = (
            "ATC Non-Compliant controls missing risk assessment fields: "
            + ", ".join(sorted(set(offenders)))
        )
        tr = TestResult(
            test_number=87,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error("[T87] FAIL — offenders=%s", offenders)
        return tr

    msg = "All ATC Non-Compliant controls include a completed risk assessment."
    tr = TestResult(
        test_number=87,
        name=test_name,
        result=Result.PASS,
        message=msg,
    )
    status.add(tr)
    logger.info("[T87] PASS — all ATC NC controls have RA content.")
    return tr

def test_88(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 88 — Non-Compliant controls include Risk Assessment narrative fields.

    Purpose
    -------
    For every control whose compliancestatus is Non-Compliant ("NC", "Non-Compliant",
    "Non Compliant"), verify that the following RA narrative fields are populated
    (not None):
      • vulnerabilitysummary
      • impactdescription
      • recommendations

    Behavior
    --------
    - FAIL if we can't load the controls dataset.
    - For each Non-Compliant control:
        * If ANY of the three required fields is None → that control is flagged.
    - PASS if no offenders; otherwise FAIL with list of offending control acronyms.

    Data source in new model
    ------------------------
    ctx.controls: Controls | None
      ctx.controls.data: Optional[List[Dict[str, Any]]]
    """

    test_name = "Test 88: NC controls include RA narrative fields"
    logger.debug("Running %s", test_name)

    def ci_get(d: dict, key: str):
        """Case-insensitive dict getter."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def is_nc(val: object) -> bool:
        s = (str(val or "")).strip().lower()
        return s in {"nc", "non-compliant", "non compliant"}

    # Pull controls list from structured ctx.controls.data
    controls_block = getattr(ctx, "controls", None)
    rows: list[dict] = []
    if controls_block and isinstance(controls_block.data, list):
        rows = controls_block.data

    if not rows:
        tr = TestResult(
            test_number=88,
            name=test_name,
            result=Result.FAIL,
            message="Controls dataset not available.",
        )
        status.add(tr)
        logger.error("[T88] FAIL — controls dataset missing.")
        return tr

    offenders: list[str] = []

    for row in rows:
        if not is_nc(ci_get(row, "compliancestatus")):
            continue

        acronym = (ci_get(row, "acronym") or "").strip() or "<unknown>"

        vuln = ci_get(row, "vulnerabilitysummary")
        impact = ci_get(row, "impactdescription")
        recs = ci_get(row, "recommendations")

        # PowerShell semantics: only None means "missing".
        # Empty string still counts as "present".
        if vuln is None or impact is None or recs is None:
            offenders.append(acronym)

    if offenders:
        tr = TestResult(
            test_number=88,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Non-Compliant controls missing RA fields "
                "(vulnerability/impact/recommendations): "
                + ", ".join(sorted(offenders))
            ),
        )
        status.add(tr)
        logger.error("[T88] FAIL — Offenders: %s", offenders)
        return tr

    tr = TestResult(
        test_number=88,
        name=test_name,
        result=Result.PASS,
        message=(
            "All Non-Compliant controls include vulnerability, impact, "
            "and recommendation content."
        ),
    )
    status.add(tr)
    logger.info("[T88] PASS — all NC controls have RA narratives.")
    return tr



def test_89(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 89 — Compliant controls have no Risk Assessment content.

    Purpose
    -------
    For every control whose compliancestatus is Compliant ("C" or "Compliant"),
    verify that all Risk Assessment narrative fields have been cleared (i.e., are None):
      • vulnerabilitysummary
      • mitigations
      • impactdescription
      • recommendations

    Behavior
    --------
    - FAIL if we can't load the controls dataset.
    - For each Compliant control:
        * If ANY of those four fields is not None → offender.
    - PASS if no offenders; otherwise FAIL with list of offending control acronyms.

    Data source in new model
    ------------------------
    ctx.controls: Controls | None
      ctx.controls.data: Optional[List[Dict[str, Any]]]
    """

    test_name = "Test 89: Compliant controls have no RA content"
    logger.debug("Running %s", test_name)

    def ci_get(d: dict, key: str):
        """Case-insensitive dict getter."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def is_compliant(val: object) -> bool:
        s = (str(val or "")).strip().lower()
        return s in {"c", "compliant"}

    # Pull controls list from structured ctx.controls.data
    controls_block = getattr(ctx, "controls", None)
    rows: list[dict] = []
    if controls_block and isinstance(controls_block.data, list):
        rows = controls_block.data

    if not rows:
        tr = TestResult(
            test_number=89,
            name=test_name,
            result=Result.FAIL,
            message="Controls dataset not available.",
        )
        status.add(tr)
        logger.error("[T89] FAIL — controls dataset missing.")
        return tr

    offenders: list[str] = []

    for row in rows:
        if not is_compliant(ci_get(row, "compliancestatus")):
            continue

        acronym = (ci_get(row, "acronym") or "").strip() or "<unknown>"

        vuln = ci_get(row, "vulnerabilitysummary")
        mits = ci_get(row, "mitigations")
        impact = ci_get(row, "impactdescription")
        recs = ci_get(row, "recommendations")

        # Legacy PowerShell behavior:
        # For compliant controls, ALL FOUR must be $null.
        # If any field is not None, it means RA data wasn't scrubbed.
        if not (vuln is None and mits is None and impact is None and recs is None):
            offenders.append(acronym)

    if offenders:
        tr = TestResult(
            test_number=89,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Compliant controls still contain risk assessment content: "
                + ", ".join(sorted(offenders))
            ),
        )
        status.add(tr)
        logger.error("[T89] FAIL — Offenders: %s", offenders)
        return tr

    tr = TestResult(
        test_number=89,
        name=test_name,
        result=Result.PASS,
        message="All Compliant controls have risk assessment fields cleared.",
    )
    status.add(tr)
    logger.info("[T89] PASS — compliant controls have no RA content.")
    return tr


def test_90(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 90 — 'Not Applicable' controls have risk assessment fields removed.

    Purpose
    -------
    For every control whose compliancestatus is NA
    ("NA", "Not Applicable", "N/A"), verify that all Risk Assessment
    narrative fields are cleared (i.e., None):
      • vulnerabilitysummary
      • mitigations
      • impactdescription
      • recommendations

    Behavior
    --------
    - FAIL if we can't load the controls dataset.
    - For each NA control:
        * If ANY of those four fields is not None → offender.
    - PASS if no offenders; otherwise FAIL listing the offending control acronyms.

    Data source in new model
    ------------------------
    ctx.controls: Controls | None
      ctx.controls.data: Optional[List[Dict[str, Any]]]
    """

    test_name = "Test 90: NA controls have risk fields cleared"
    logger.debug("Running %s", test_name)

    def ci_get(d: dict, key: str):
        """Case-insensitive dict getter."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def is_na(val: object) -> bool:
        s = (str(val or "")).strip().lower()
        return s in {"na", "not applicable", "n/a"}

    # Pull controls from structured ctx.controls.data
    controls_block = getattr(ctx, "controls", None)
    rows: list[dict] = []
    if controls_block and isinstance(controls_block.data, list):
        rows = controls_block.data

    if not rows:
        tr = TestResult(
            test_number=90,
            name=test_name,
            result=Result.FAIL,
            message="Controls dataset not available.",
        )
        status.add(tr)
        logger.error("[T90] FAIL — controls dataset missing.")
        return tr

    offenders: list[str] = []

    for row in rows:
        if not is_na(ci_get(row, "compliancestatus")):
            continue

        acronym = (ci_get(row, "acronym") or "").strip() or "<unknown>"

        vuln = ci_get(row, "vulnerabilitysummary")
        mits = ci_get(row, "mitigations")
        impact = ci_get(row, "impactdescription")
        recs = ci_get(row, "recommendations")

        # PowerShell semantics: any non-None means the RA narrative wasn't cleared.
        if not (vuln is None and mits is None and impact is None and recs is None):
            offenders.append(acronym)

    if offenders:
        tr = TestResult(
            test_number=90,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Not Applicable controls still contain risk assessment data: "
                + ", ".join(sorted(offenders))
            ),
        )
        status.add(tr)
        logger.error("[T90] FAIL — Offenders: %s", offenders)
        return tr

    tr = TestResult(
        test_number=90,
        name=test_name,
        result=Result.PASS,
        message="All Not Applicable controls have risk assessment fields cleared.",
    )
    status.add(tr)
    logger.info("[T90] PASS — NA controls have no RA content.")
    return tr



def test_91(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 91 — Inherited controls identify a Common Control Provider (CCP).

    Purpose
    -------
    For any control flagged as inherited, verify a valid Common Control Provider
    (CCP) is populated. This mirrors the legacy rule:

      If the control is inherited (isInherited == True / isinherited == True),
      then commonControlProvider must not be empty/"-"/None.

    Behavior
    --------
    - FAIL if we can't load the controls dataset at all.
    - Scan each control row in ctx.controls.data:
        * if inherited → require CCP
    - If any inherited control is missing CCP → FAIL with list
    - Otherwise → PASS

    Data source in new model
    ------------------------
    ctx.controls: Controls | None
      ctx.controls.data: Optional[List[Dict[str, Any]]]

    We still read fields case-insensitively from each row dict:
      - "isInherited" / "isinherited"
      - "commonControlProvider" / "commoncontrolprovider"
      - "acronym"
    """

    test_name = "Test 91: Inherited controls have a Common Control Provider"
    logger.debug("Running %s", test_name)

    def ci_get(d: dict, key: str):
        """Case-insensitive dict getter."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    # Pull controls list from structured ctx.controls.data
    controls_block = getattr(ctx, "controls", None)
    rows: list[dict] = []
    if controls_block and isinstance(controls_block.data, list):
        rows = controls_block.data

    if not rows:
        tr = TestResult(
            test_number=91,
            name=test_name,
            result=Result.FAIL,
            message="Controls dataset not available.",
        )
        status.add(tr)
        logger.error("[T91] FAIL — controls dataset missing.")
        return tr

    offenders: list[str] = []

    for row in rows:
        # inherited flag can show up as True/False or "True"/"False"
        inherited_raw = ci_get(row, "isInherited")
        if inherited_raw is None:
            inherited_raw = ci_get(row, "isinherited")

        is_inherited = False
        if isinstance(inherited_raw, bool):
            is_inherited = inherited_raw
        else:
            # fall back to string-y truthiness
            s = (str(inherited_raw or "")).strip().lower()
            if s in {"true", "yes", "y", "1"}:
                is_inherited = True

        if not is_inherited:
            continue

        acronym = (ci_get(row, "acronym") or "").strip() or "<unknown>"

        ccp = ci_get(row, "commonControlProvider")
        if ccp is None:
            ccp = ci_get(row, "commoncontrolprovider")

        ccp_clean = (str(ccp or "")).strip()

        if ccp_clean == "" or ccp_clean == "-":
            offenders.append(acronym)

    if offenders:
        tr = TestResult(
            test_number=91,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Inherited controls missing Common Control Provider: "
                + ", ".join(sorted(offenders))
            ),
        )
        status.add(tr)
        logger.error("[T91] FAIL — offenders: %s", offenders)
        return tr

    tr = TestResult(
        test_number=91,
        name=test_name,
        result=Result.PASS,
        message="All inherited controls reference a Common Control Provider.",
    )
    status.add(tr)
    logger.info("[T91] PASS — all inherited controls have CCP.")
    return tr


def test_92(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 92 — Implementation Narrative present for Compliant controls.

    Purpose
    -------
    For any control whose complianceStatus is Compliant, ensure an
    implementation narrative is provided. This mirrors the legacy PowerShell rule:
    compliant controls must describe how they're implemented.

    Behavior
    --------
    - FAIL if we can't load the controls dataset at all.
    - For each control where complianceStatus ∈ {"C","Compliant"}:
        * implementationNarrative (any casing) must NOT be None.
    - If any compliant control is missing that narrative → FAIL and list them.
    - Otherwise → PASS.

    Data source in new model
    ------------------------
    ctx.controls: Controls | None
      ctx.controls.data: Optional[List[Dict[str, Any]]]
    """

    test_name = "Test 92: Compliant controls include implementation narrative"
    logger.debug("Running %s", test_name)

    def ci_get(d: dict, key: str):
        """Case-insensitive dict getter."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def is_compliant(val: object) -> bool:
        s = (str(val or "")).strip().lower()
        return s in {"c", "compliant"}

    # Pull control rows from structured context
    controls_block = getattr(ctx, "controls", None)
    rows: list[dict] = []
    if controls_block and isinstance(controls_block.data, list):
        rows = controls_block.data

    if not rows:
        tr = TestResult(
            test_number=92,
            name=test_name,
            result=Result.FAIL,
            message="Controls dataset not available.",
        )
        status.add(tr)
        logger.error("[T92] FAIL — controls dataset missing.")
        return tr

    offenders: list[str] = []

    for row in rows:
        if not is_compliant(ci_get(row, "complianceStatus")):
            continue

        acronym = (ci_get(row, "acronym") or "").strip() or "<unknown>"

        narrative = ci_get(row, "implementationNarrative")
        if narrative is None:
            # Legacy behavior: specifically checks for null. Empty string still counts as present.
            offenders.append(acronym)

    if offenders:
        tr = TestResult(
            test_number=92,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Compliant controls missing implementation narrative: "
                + ", ".join(sorted(offenders))
            ),
        )
        status.add(tr)
        logger.error("[T92] FAIL — offenders: %s", offenders)
        return tr

    tr = TestResult(
        test_number=92,
        name=test_name,
        result=Result.PASS,
        message="All Compliant controls include an implementation narrative.",
    )
    status.add(tr)
    logger.info("[T92] PASS — narratives present for compliant controls.")
    return tr


def test_93(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 93 — Responsible Entities documented (implementation narrative present)

    Purpose
    -------
    Validate that every control (except those marked Not Applicable) includes an
    implementation narrative. Mirrors the legacy intent of “Responsible Entities”.

    Behavior
    --------
    - FAIL if controls dataset is unavailable.
    - For each control where complianceStatus ∉ {NA, N/A, Not Applicable}:
        * implementationNarrative (any casing) must NOT be None.
    - If any are missing → FAIL listing the acronyms; else → PASS.

    Data (new model)
    ----------------
    ctx.controls: Controls | None
      ctx.controls.data: Optional[List[Dict[str, Any]]]
    """
    test_name = "Test 93: Responsible Entities (implementation narrative present)"
    logger.debug("Running %s", test_name)

    def ci_get(d: dict, key: str):
        """Case-insensitive dict get; returns None if missing."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def is_na(status: object) -> bool:
        s = (str(status or "")).strip().lower()
        return s in {"na", "n/a", "not applicable"}

    # Pull rows from structured context
    rows: list[dict] = []
    controls_block = getattr(ctx, "controls", None)
    if controls_block and isinstance(controls_block.data, list):
        rows = controls_block.data

    if not rows:
        tr = TestResult(
            test_number=93,
            name=test_name,
            result=Result.FAIL,
            message="Controls dataset not available.",
        )
        status.add(tr)
        logger.error("[T93] Controls dataset missing.")
        return tr

    offenders: list[str] = []
    for row in rows:
        if is_na(ci_get(row, "complianceStatus")):
            continue  # exclude NA controls
        narrative = ci_get(row, "implementationNarrative")
        if narrative is None:
            acronym = (ci_get(row, "acronym") or "").strip() or "<unknown>"
            offenders.append(acronym)

    if offenders:
        tr = TestResult(
            test_number=93,
            name=test_name,
            result=Result.FAIL,
            message="Controls missing implementation narrative (excluding NA): " + ", ".join(sorted(offenders)),
        )
        status.add(tr)
        logger.error("[T93] Offenders: %s", offenders)
        return tr

    tr = TestResult(
        test_number=93,
        name=test_name,
        result=Result.PASS,
        message="All non-NA controls include an implementation narrative.",
    )
    status.add(tr)
    logger.info("[T93] PASS — narratives present for all applicable controls.")
    return tr


def test_94(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 94 — Non-Compliant control Impact matches system categorization Impact level

    Purpose
    -------
    For every Non-Compliant control, confirm that the control-level `impact`
    matches the system's overall impact (ctx.impact), case-insensitive.

    Behavior
    --------
    - FAIL if:
        * controls dataset isn't available,
        * system impact is missing,
        * any Non-Compliant control has a missing/mismatched impact.
    - PASS otherwise.

    Data (new model)
    ----------------
    ctx.controls: Controls | None
      ctx.controls.data: Optional[List[Dict[str, Any]]]

    Fields used per row (case-insensitive lookup):
      - complianceStatus
      - impact
      - acronym
    """
    test_name = "Test 94: Non-Compliant control Impact matches system Impact"
    logger.debug("Running %s", test_name)

    def ci_get(d: dict, key: str):
        """Case-insensitive dict get; returns None if key missing or row not a dict."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def is_nc(status_val: object) -> bool:
        """True if status represents Non-Compliant."""
        s = (str(status_val or "")).strip().lower()
        return s in {"nc", "non-compliant", "non compliant", "noncompliant"}

    # --- Load controls from structured ctx.controls.data ---
    rows: list[dict] = []
    controls_block = getattr(ctx, "controls", None)
    if controls_block and isinstance(controls_block.data, list):
        rows = controls_block.data

    if not rows:
        tr = TestResult(
            test_number=94,
            name=test_name,
            result=Result.FAIL,
            message="Controls dataset not available.",
        )
        status.add(tr)
        logger.error("[T94] Controls dataset missing.")
        return tr

    # --- Normalize system impact ---
    sys_impact_norm = (ctx.impact or "").strip().lower()
    if not sys_impact_norm:
        tr = TestResult(
            test_number=94,
            name=test_name,
            result=Result.FAIL,
            message="System Impact level is missing.",
        )
        status.add(tr)
        logger.error("[T94] System impact missing in context.")
        return tr

    # --- Check each Non-Compliant control ---
    offenders: list[str] = []
    for row in rows:
        if not is_nc(ci_get(row, "complianceStatus")):
            continue

        ctrl_impact_norm = (str(ci_get(row, "impact") or "")).strip().lower()
        if ctrl_impact_norm != sys_impact_norm:
            acronym = (ci_get(row, "acronym") or "").strip() or "<unknown>"
            offenders.append(acronym)

    if offenders:
        msg = (
            "Non-Compliant controls with Impact not matching system Impact "
            f"({ctx.impact}): " + ", ".join(sorted(offenders))
        )
        tr = TestResult(
            test_number=94,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error("[T94] Impact mismatches: %s", offenders)
        return tr

    tr = TestResult(
        test_number=94,
        name=test_name,
        result=Result.PASS,
        message="All Non-Compliant controls have Impact matching the system Impact.",
    )
    status.add(tr)
    logger.info("[T94] PASS — all NC control impacts match system impact: %s", ctx.impact)
    return tr



def test_95(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 95 — Risk attributes populated for Non-Compliant controls (Army Risk Analysis)

    Purpose
    -------
    Confirm that every non-compliant control has required risk attributes populated:
      • Severity
      • relevanceOfThreat
      • likelihood
      • impact
      • residualRiskLevel

    Behavior
    --------
    - FAIL if we can't load the controls dataset at all.
    - For each control where complianceStatus is Non-Compliant:
        * If ANY of the above attributes is missing or empty → offender.
    - PASS if no offenders, else FAIL listing them.

    Data (new model)
    ----------------
    ctx.controls: Controls | None
      ctx.controls.data: Optional[List[Dict[str, Any]]]

    Notes
    -----
    We case-insensitively read dict keys like "complianceStatus", "Severity", etc.
    """
    test_name = "Test 95: Risk attributes populated for Non-compliant controls"
    logger.debug("Running %s", test_name)

    def ci_get(d: dict, key: str):
        """Case-insensitive dict getter."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def is_nc(status_val: object) -> bool:
        s = (str(status_val or "")).strip().lower()
        return s in {"nc", "non-compliant", "non compliant", "noncompliant"}

    # pull controls from structured ctx.controls.data
    rows: list[dict] = []
    controls_block = getattr(ctx, "controls", None)
    if controls_block and isinstance(controls_block.data, list):
        rows = controls_block.data

    if not rows:
        tr = TestResult(
            test_number=95,
            name=test_name,
            result=Result.FAIL,
            message="Controls dataset not available.",
        )
        status.add(tr)
        logger.error("[T95] Controls dataset missing.")
        return tr

    required_keys = (
        "Severity",
        "relevanceOfThreat",
        "likelihood",
        "impact",
        "residualRiskLevel",
    )

    offenders: list[str] = []

    for row in rows:
        if not is_nc(ci_get(row, "complianceStatus")):
            continue

        # any required key missing or "" counts as missing
        missing_any = False
        for key in required_keys:
            val = ci_get(row, key)
            if val is None or (str(val).strip() == ""):
                missing_any = True
                break

        if missing_any:
            acronym = (ci_get(row, "acronym") or "").strip() or "<unknown>"
            offenders.append(acronym)

    if offenders:
        msg = (
            "Non-compliant controls missing one or more required risk attributes "
            "(Severity, relevanceOfThreat, likelihood, impact, residualRiskLevel): "
            + ", ".join(sorted(offenders))
        )
        tr = TestResult(
            test_number=95,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error("[T95] Missing risk attributes for: %s", offenders)
        return tr

    tr = TestResult(
        test_number=95,
        name=test_name,
        result=Result.PASS,
        message="All required risk attributes are populated for non-compliant controls.",
    )
    status.add(tr)
    logger.info("[T95] PASS — risk attributes present for all NC controls.")
    return tr


def test_96(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 96 — CCP inheritance presence (DoD Tier 1, Army Tier 2, Army Sentinel)

    Purpose
    -------
    Determine whether any controls show successful inheritance from DoD Tier 1 CCP,
    Army Tier 2 CCP, or Army Sentinel CCP.

    Reality check
    -------------
    The structured data we ingest (ctx.controls, etc.) does not expose inheritance
    lineage at the provider tier granularity needed to validate this automatically.

    Outcome
    -------
    - CONCERN : We cannot validate automatically; call out the limitation and
                direct the reviewer to verify inheritance manually in eMASS.

    Behavior
    --------
    Always returns CONCERN with an explanation.
    """
    test_name = "Test 96: CCP inheritance (Tier 1/2/Sentinel) detectable"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=96,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "CCP inheritance lineage (DoD Tier 1 / Army Tier 2 / Army Sentinel) "
            "is not present in exported control data. Manual verification in eMASS UI required."
        ),
    )
    status.add(tr)
    logger.warning("[T96] Data gap: CCP inheritance granularity not in structured feeds.")
    return tr



def test_97(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 97 — No “Enter Non-Compliant Test Results for Compliant APs” suggested actions

    Purpose
    -------
    Detect a mismatch where a **Compliant** control has any **Non-Compliant**
    test result entry. In eMASS this would trigger the suggestion:
    “Enter Non-Compliant Test Results for Compliant APs”.

    Behavior (mirrors legacy semantics)
    -----------------------------------
    1. Build the set of compliant control acronyms from ctx.controls.data.
       - complianceStatus in {"C", "Compliant"}.
    2. Walk ctx.test_results.data.
       - If any row for one of those acronyms has complianceStatus Non-Compliant,
         that's a mismatch.
    3. Outcomes:
       - FAIL if datasets are missing,
       - FAIL if mismatches found (list offenders),
       - CONCERN otherwise (because eMASS "suggested actions" UI isn't exposed via API).

    Data source in new model
    ------------------------
    ctx.controls: Controls
      ctx.controls.data: List[dict-like rows of control metadata]

    ctx.test_results: TestResults
      ctx.test_results.data: List[dict-like rows of AP test results]
    """

    test_name = "Test 97: No NC test results for compliant controls"
    logger.debug("Running %s", test_name)

    # ---------- helpers -------------------------------------------------------
    def ci_get(d: dict, key: str):
        """Case-insensitive dict get."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def is_compliant(status_val: object) -> bool:
        s = (str(status_val or "")).strip().lower()
        return s in {"c", "compliant"}

    def is_non_compliant(status_val: object) -> bool:
        s = (str(status_val or "")).strip().lower()
        return s in {"nc", "non-compliant", "non compliant", "noncompliant"}

    # ---------- load normalized datasets -------------------------------------
    controls_block = getattr(ctx, "controls", None)
    tests_block = getattr(ctx, "test_results", None)

    control_rows = []
    if controls_block and isinstance(controls_block.data, list):
        control_rows = controls_block.data

    test_rows = []
    if tests_block and isinstance(tests_block.data, list):
        test_rows = tests_block.data

    if not control_rows:
        tr = TestResult(
            test_number=97,
            name=test_name,
            result=Result.FAIL,
            message="Controls dataset not available.",
        )
        status.add(tr)
        logger.error("[T97] Controls dataset missing.")
        return tr

    if not test_rows:
        tr = TestResult(
            test_number=97,
            name=test_name,
            result=Result.FAIL,
            message="Test results dataset not available.",
        )
        status.add(tr)
        logger.error("[T97] Test results dataset missing.")
        return tr

    # ---------- build set of compliant control acronyms ----------------------
    compliant_acronyms: set[str] = set()
    for row in control_rows:
        if is_compliant(ci_get(row, "complianceStatus")):
            acr = (ci_get(row, "acronym") or "").strip()
            if acr:
                compliant_acronyms.add(acr)

    if not compliant_acronyms:
        # Keep legacy spirit: no compliant controls means we can't compare,
        # so we surface CONCERN (manual review).
        tr = TestResult(
            test_number=97,
            name=test_name,
            result=Result.CONCERN,
            message=(
                "No compliant controls found; unable to compare for non-compliant test "
                "results. Manual review advised."
            ),
        )
        status.add(tr)
        logger.warning("[T97] No compliant controls to evaluate.")
        return tr

    # ---------- scan test results for mismatches -----------------------------
    mismatches: set[str] = set()

    for trow in test_rows:
        if not is_non_compliant(ci_get(trow, "complianceStatus")):
            continue

        # Try common fields that refer to which control was tested
        tested_control = (
            (ci_get(trow, "control") or
             ci_get(trow, "controlAcronym") or
             ci_get(trow, "assessmentProcedure") or "")
            .strip()
        )

        if tested_control and tested_control in compliant_acronyms:
            mismatches.add(tested_control)

    # ---------- decide outcome ----------------------------------------------
    if not mismatches:
        # Legacy script still doesn't "PASS" here — it flags that reviewers
        # should still eyeball the Suggested Actions UI.
        tr = TestResult(
            test_number=97,
            name=test_name,
            result=Result.CONCERN,
            message=(
                "All compliant controls appear to have compliant test results. "
                "However, eMASS 'suggested actions' are not exposed via API; "
                "perform a manual check."
            ),
        )
        status.add(tr)
        logger.warning("[T97] No mismatches detected; manual verification still required.")
        return tr

    mismatches_list = sorted(mismatches)
    tr = TestResult(
        test_number=97,
        name=test_name,
        result=Result.FAIL,
        message=(
            "Compliant controls with non-compliant test results detected "
            f"({len(mismatches_list)}): " + ", ".join(mismatches_list)
        ),
    )
    status.add(tr)
    logger.error(
        "[T97] Found NC test results for compliant controls: %s",
        mismatches_list,
    )
    return tr


def test_98(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 98 — All errors cleared (no control/test-result compliance conflicts)

    Purpose
    -------
    Ensure there are no conflicts between:
      • the control's package-level compliance status, and
      • any associated test-result record for that same control.

    We specifically care about mismatches like:
      - Control marked Compliant (C) but test result shows Non-Compliant (NC)
      - Control marked Non-Compliant (NC) but test result shows Compliant (C)

    Behavior (mirrors legacy script semantics)
    ------------------------------------------
    For each test result row:
      1. Identify the control acronym that row applies to.
      2. Look up that control in the controls dataset.
      3. Normalize both compliance statuses to "c" / "nc" / other.
      4. Flag a conflict if one side is "c" and the other is "nc".

    Outcomes
    --------
    - CONCERN : No conflicts detected. (Legacy script still told humans to do
                a manual eyeball, so we mirror that.)
    - FAIL    : Conflicts found; list offending control acronyms.
    - FAIL    : Controls or test-results datasets missing.

    Data source in new model
    ------------------------
    ctx.controls: Controls
      ctx.controls.data -> list[dict] of controls
    ctx.test_results: TestResults
      ctx.test_results.data -> list[dict] of test result rows
    """

    test_name = "Test 98: Errors cleared (no control/TR conflicts)"
    logger.debug("Running %s", test_name)

    # ---------- helpers -------------------------------------------------------
    def ci_get(d: dict, key: str):
        """Case-insensitive dict get."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def norm_status(value: object) -> str:
        """
        Normalize compliance status text to compact tokens:
        - "c", "compliant"        -> "c"
        - "nc", "non-compliant"   -> "nc"
        Everything else passes through lowercased, so "na" etc. won't
        trigger C/NC conflict logic.
        """
        s = (str(value or "")).strip().lower()
        if s in {"c", "compliant"}:
            return "c"
        if s in {"nc", "non-compliant", "non compliant", "noncompliant"}:
            return "nc"
        return s  # e.g. "na", "not applicable", etc.

    # ---------- load structured datasets -------------------------------------
    controls_block = getattr(ctx, "controls", None)
    tests_block = getattr(ctx, "test_results", None)

    control_rows = []
    if controls_block and isinstance(controls_block.data, list):
        control_rows = controls_block.data

    test_rows = []
    if tests_block and isinstance(tests_block.data, list):
        test_rows = tests_block.data

    if not control_rows:
        tr = TestResult(
            test_number=98,
            name=test_name,
            result=Result.FAIL,
            message="Controls dataset not available.",
        )
        status.add(tr)
        logger.error("[T98] Controls dataset missing.")
        return tr

    if not test_rows:
        tr = TestResult(
            test_number=98,
            name=test_name,
            result=Result.FAIL,
            message="Test results dataset not available.",
        )
        status.add(tr)
        logger.error("[T98] Test results dataset missing.")
        return tr

    # ---------- map control acronym -> normalized compliance status -----------
    control_status_by_acronym: dict[str, str] = {}
    for crow in control_rows:
        acronym = (ci_get(crow, "acronym") or "").strip()
        if not acronym:
            continue
        pkg_status_norm = norm_status(ci_get(crow, "complianceStatus"))
        control_status_by_acronym[acronym] = pkg_status_norm

    # ---------- scan test results for mismatches ------------------------------
    conflicting_acronyms: set[str] = set()

    for trow in test_rows:
        tr_status_norm = norm_status(ci_get(trow, "complianceStatus"))

        # Try common test result fields that point to which control/AP was tested
        tested_control = (
            (ci_get(trow, "control")
             or ci_get(trow, "controlAcronym")
             or ci_get(trow, "assessmentProcedure")
             or "")
        ).strip()

        if not tested_control:
            continue

        pkg_status_norm = control_status_by_acronym.get(tested_control)
        if not pkg_status_norm:
            # No package-level record for this acronym → skip
            continue

        # Conflict rules:
        # - test says "nc" but package says "c"
        # - test says "c"  but package says "nc"
        if (tr_status_norm == "nc" and pkg_status_norm == "c") or (
            tr_status_norm == "c" and pkg_status_norm == "nc"
        ):
            conflicting_acronyms.add(tested_control)

    # ---------- results -------------------------------------------------------
    if not conflicting_acronyms:
        tr = TestResult(
            test_number=98,
            name=test_name,
            result=Result.CONCERN,
            message=(
                "No control/test-result compliance conflicts detected; "
                "manual verification in eMASS still required."
            ),
        )
        status.add(tr)
        logger.warning("[T98] No conflicts detected; advising manual review.")
        return tr

    bad_list = sorted(conflicting_acronyms)
    tr = TestResult(
        test_number=98,
        name=test_name,
        result=Result.FAIL,
        message=(
            "Conflicts detected between control package status and test "
            "results: " + ", ".join(bad_list)
        ),
    )
    status.add(tr)
    logger.error("[T98] Conflicts: %s", bad_list)
    return tr



def test_99(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 99 — No “Conflicted Findings”

    Purpose
    -------
    Confirm there are no “conflicted controls/findings,” defined as:
      • a control marked Compliant (C) while any associated test result is Non-Compliant (NC), or
      • a control marked Non-Compliant (NC) while any associated test result is Compliant (C).

    This is effectively the same mismatch signal as Test 98, but the legacy checklist
    framed it as “Conflicted Findings” and treated a clean result as PASS.

    Data source in new model
    ------------------------
    ctx.controls: Controls
      ctx.controls.data -> list[dict] of controls
        - expects fields like "acronym", "complianceStatus"
    ctx.test_results: TestResults
      ctx.test_results.data -> list[dict] of test result rows
        - expects fields like "complianceStatus", "control" / "controlAcronym" / "assessmentProcedure"

    Behavior
    --------
    1. Build a map of control acronym -> normalized compliance status ("c", "nc", etc.).
    2. For each test result row:
         - extract its control acronym
         - normalize the test row's compliance status
         - if one says "c" and the other says "nc", that's a conflict.
    3. Outcomes:
         - FAIL if datasets missing
         - FAIL if any conflicts found
         - PASS if no conflicts
    """

    test_name = "Test 99: No conflicted findings"
    logger.debug("Running %s", test_name)

    # -------- helpers ---------------------------------------------------------
    def ci_get(d: dict, key: str):
        """Case-insensitive dict get. Returns None if missing/not a dict."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def norm_status(value: object) -> str:
        """
        Normalize compliance status text:
        - "c", "compliant" -> "c"
        - "nc", "non-compliant", etc. -> "nc"
        Everything else passes through lowercased.
        """
        s = (str(value or "")).strip().lower()
        if s in {"c", "compliant"}:
            return "c"
        if s in {"nc", "non-compliant", "non compliant", "noncompliant"}:
            return "nc"
        return s

    # -------- load structured datasets ---------------------------------------
    controls_block = getattr(ctx, "controls", None)
    tests_block = getattr(ctx, "test_results", None)

    control_rows: list[dict] = []
    if controls_block and isinstance(controls_block.data, list):
        control_rows = controls_block.data

    test_rows: list[dict] = []
    if tests_block and isinstance(tests_block.data, list):
        test_rows = tests_block.data

    if not control_rows:
        tr = TestResult(
            test_number=99,
            name=test_name,
            result=Result.FAIL,
            message="Controls dataset not available.",
        )
        status.add(tr)
        logger.error("[T99] Controls dataset missing.")
        return tr

    if not test_rows:
        tr = TestResult(
            test_number=99,
            name=test_name,
            result=Result.FAIL,
            message="Test results dataset not available.",
        )
        status.add(tr)
        logger.error("[T99] Test results dataset missing.")
        return tr

    # -------- build control status map ---------------------------------------
    # control_status_by_acronym["AC-2"] -> "c" / "nc" / etc.
    control_status_by_acronym: dict[str, str] = {}
    for c_row in control_rows:
        acronym = (ci_get(c_row, "acronym") or "").strip()
        if not acronym:
            continue
        pkg_status = norm_status(ci_get(c_row, "complianceStatus"))
        control_status_by_acronym[acronym] = pkg_status

    # -------- detect conflicts -----------------------------------------------
    conflicts: set[str] = set()

    for t_row in test_rows:
        tr_status_norm = norm_status(ci_get(t_row, "complianceStatus"))

        tested_control = (
            (ci_get(t_row, "control")
             or ci_get(t_row, "controlAcronym")
             or ci_get(t_row, "assessmentProcedure")
             or "")
        ).strip()
        if not tested_control:
            continue

        pkg_status_norm = control_status_by_acronym.get(tested_control)
        if not pkg_status_norm:
            continue  # no package-level record to compare against

        # Same mismatch logic as Test 98:
        #   Control C vs TR NC  OR  Control NC vs TR C  => conflict
        if (tr_status_norm == "nc" and pkg_status_norm == "c") or (
            tr_status_norm == "c" and pkg_status_norm == "nc"
        ):
            conflicts.add(tested_control)

    # -------- report ----------------------------------------------------------
    if not conflicts:
        tr = TestResult(
            test_number=99,
            name=test_name,
            result=Result.PASS,
            message="No conflicted findings detected (no C↔NC mismatches).",
        )
        status.add(tr)
        logger.info("[T99] PASS — no conflicts found between control status and test results.")
        return tr

    bad_list = sorted(conflicts)
    tr = TestResult(
        test_number=99,
        name=test_name,
        result=Result.FAIL,
        message=(
            "Conflicted findings detected (control/test-result mismatch): "
            + ", ".join(bad_list)
        ),
    )
    status.add(tr)
    logger.error("[T99] FAIL — Conflicts: %s", bad_list)
    return tr


def test_100(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 100 — No “Unmapped Findings”

    Purpose
    -------
    Detect whether there are any "unmapped findings" (e.g. scanner findings,
    such as ACAS plugin output, that are not tied to a control/CCI in eMASS).

    Reality / Limitation
    --------------------
    The data needed to automatically determine this is not provided in the
    structured context we ingest (controls, test results, POA&M items, etc.).
    The original checklist treats this as a manual review item.

    Behavior
    --------
    - Always return CONCERN, instructing the reviewer to manually verify
      unmapped findings against ACAS / scan outputs.

    Inputs
    ------
    ctx: SystemContext (not actually used, since this check cannot be automated)
    status: ATOStatus accumulator
    """

    test_name = "Test 100: No unmapped findings"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=100,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "Automated check unavailable: eMASS / provided payloads do not expose "
            "unmapped scanner findings. Manually verify that all ACAS/findings "
            "are mapped to CCIs / controls in eMASS."
        ),
    )
    status.add(tr)
    logger.warning("[T100] CONCERN — unmapped findings cannot be verified from available data.")
    return tr


def test_101(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 101 — Record contains benchmark technical data (Existing or Expired ATO ONLY)

    Purpose
    -------
    Determine whether the eMASS record includes benchmark technical data.

    Scope notes from source:
    - For Sentinel inheritance checks: N/A for *new* systems seeking Sentinel CCP inheritance.
    - For SSP review: only required for authorized / approved systems (Existing or Expired ATO),
      not for pre-authorization packages.

    Automation reality
    ------------------
    The available structured data in SystemContext (controls, findings, POA&M, etc.)
    does not include the "benchmark technical data" reference that auditors expect.
    The original script flags this as requiring a manual check.

    Behavior
    --------
    - Always returns CONCERN and instructs manual verification against the authoritative
      package in eMASS / Sentinel CCP artifacts.

    Inputs
    ------
    ctx: SystemContext (not directly used here)
    status: ATOStatus accumulator
    """

    test_name = "Test 101: Benchmark technical data present"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=101,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "Automated check unavailable: benchmark technical data is not exposed in the "
            "provided eMASS/API payloads. Manually verify benchmark technical data is "
            "included for this (Existing or Expired ATO) package."
        ),
    )
    status.add(tr)
    logger.warning("[T101] CONCERN — benchmark technical data not available in payloads; manual check required.")
    return tr



def test_102(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 102 — STIGs imported for every STIG applied in Categorization (Existing or Expired ATO ONLY)

    Purpose
    -------
    Check for gaps between STIGs marked as "applied" in Categorization and STIGs
    actually imported into the record.

    Reality / Data availability
    ---------------------------
    The eMASS data surfaced into SystemContext does not expose a reliable
    mapping of:
      • Which STIGs were "applied" in Categorization, vs.
      • Which STIG checklists / uploads were actually imported.
    The legacy script flags this as not automatable.

    Behavior
    --------
    - Always returns CONCERN and instructs manual verification in eMASS:
      confirm that each STIG listed as applied in Categorization has a
      corresponding imported STIG checklist.

    Inputs
    ------
    ctx: SystemContext (not directly used)
    status: ATOStatus accumulator
    """

    test_name = "Test 102: STIGs imported for all applied STIGs"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=102,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "Automated check unavailable: the payloads do not expose linkage between "
            "Categorization 'applied' STIGs and imported STIG artifacts. "
            "Manually verify all applied STIGs were imported."
        ),
    )
    status.add(tr)
    logger.warning(
        "[T102] CONCERN — missing API linkage between applied vs imported STIGs; manual verification required."
    )
    return tr


def test_103(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 103 — STIGs imported that are *not* documented as a requirement (Existing or Expired ATO ONLY)

    Purpose
    -------
    Identify STIGs that were imported into the package but are not actually
    documented as required in Categorization. This can indicate scope drift or
    incorrect attachments.

    Data availability
    -----------------
    The data we have in SystemContext does not include a reliable mapping between:
      • The STIGs "required" / applied in Categorization, and
      • The STIG checklists actually imported/attached.
    The original script marks this as not automatable.

    Behavior
    --------
    - Always returns CONCERN and instructs manual verification in eMASS:
      confirm there are no STIG checklists imported that aren't actually
      required for this system.

    Inputs
    ------
    ctx: SystemContext (not directly used for automation)
    status: ATOStatus accumulator
    """

    test_name = "Test 103: Imported STIGs not documented as requirements"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=103,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "Automated check unavailable: payloads do not expose applied-vs-imported STIG "
            "crosswalk. Manually verify there are no imported STIGs that are not "
            "documented as required in Categorization."
        ),
    )
    status.add(tr)

    logger.warning(
        "[T103] CONCERN — cannot verify imported vs documented STIG parity via available data."
    )
    return tr

def test_104(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 104 — STIG/SRG technical data is current per DISA Version | Release

    Purpose
    -------
    Determine whether the record contains current STIG/SRG technical data and that
    all applicable STIGs/SRGs are aligned with the latest DISA Version | Release.

    Data availability
    -----------------
    The eMASS data available in SystemContext does not include:
      • authoritative DISA STIG/SRG version metadata, or
      • a reliable mapping between imported STIG/SRG artifacts and those versions.
    The legacy script marks this check as not automatable.

    Behavior
    --------
    - Always returns CONCERN and instructs manual verification:
      confirm that the STIG/SRG checklists in the package match the latest
      approved DISA Version | Release.

    Returns
    -------
    TestResult with Result.CONCERN.
    """
    test_name = "Test 104: STIG/SRG technical data is current"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=104,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "Automated check unavailable: eMASS payloads do not expose STIG/SRG version "
            "metadata or DISA release alignment. Manually verify checklist versions "
            "match the current DISA Version | Release."
        ),
    )
    status.add(tr)

    logger.warning(
        "[T104] CONCERN — STIG/SRG version parity with DISA cannot be verified via available data."
    )
    return tr

"""
Test 105: Are STIGs imported and in compliance with NETCOM Assets Module TTP section 2.3? *Existing or Expired ATO ONLY*
REMOVED
"""
def test_106(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 106 — ACAS scans within 30 days for 100% of devices (or covered by AO exceptions).

    Purpose:
        Validate that all devices have an ACAS scan within the past 30 days
        (per TASKORD 20-0020), by inspecting the structured Findings dataset
        for ACAS-derived scan results tied to this system.

    Inputs (nested models only, no raw JSON):
        - ctx.findings: Findings       -> preferred primary source
        - ctx.fixtures.findings: Findings (optional) -> fallback if needed

        Each Findings.data row is treated as a dict with (case-insensitive) keys:
            - "System ID" / "system_id"
            - "Scan Type" / "scan_type"
            - "Last Scan Date" / "last_scan_date"
            - "hostname"

    Behavior (parity with PowerShell Test 106):
        - Filter Findings.data to rows where System ID == ctx.system_id.
        - From those rows, keep only ones whose Scan Type contains "ACAS"
          (case-insensitive).
        - If no such ACAS rows exist:
              result = FAIL
              message = "FAIL: No ACAS scan data has been found."
        - Otherwise, compute a 30-day cutoff (epoch seconds) and mark a device
          as stale if:
              * Last Scan Date is null
              * Last Scan Date is "-"
              * Last Scan Date (numeric) < cutoff
        - If no stale devices:
              result = PASS
              message = "PASS: All ACAS scans are within 30 days."
        - If one or more stale devices:
              result = FAIL
              message = "FAIL: N device(s) lack recent ACAS scans: host1, host2, ..."
    """
    test_name = "Test 106: ACAS scans within last 30 days"
    logger.debug("Running %s for system_id=%s", test_name, ctx.system_id)

    # ---------- helpers ------------------------------------------------------
    def ci_get(row: dict, key: str) -> Any:
        """Case-insensitive dict get; returns None if key not present."""
        if not isinstance(row, dict):
            return None
        target = key.lower()
        for k, v in row.items():
            if str(k).lower() == target:
                return v
        return None

    def to_epoch_seconds(raw_value: Any) -> int | None:
        """Best-effort conversion of a value into epoch seconds, or None if invalid."""
        if raw_value is None:
            return None
        if isinstance(raw_value, (int, float)):
            return int(raw_value)

        s = str(raw_value).strip()
        if not s or s == "-":
            return None
        try:
            return int(float(s))
        except Exception:
            return None

    # ---------- load findings from nested models (no raw JSON) ---------------
    findings_block = getattr(ctx, "findings", None)
    rows: list[dict] = []

    if findings_block is not None and isinstance(findings_block.data, list):
        rows = findings_block.data

    # Fallback to fixtures if primary findings are empty
    if not rows and getattr(ctx, "fixtures", None) is not None:
        fixtures_findings = getattr(ctx.fixtures, "findings", None)
        if fixtures_findings is not None and isinstance(fixtures_findings.data, list):
            rows = fixtures_findings.data

    sys_id_str = str(ctx.system_id)

    scoped_rows: list[dict] = []
    for row in rows:
        row_sys_id = ci_get(row, "system_id") or ci_get(row, "System ID")
        if row_sys_id is None:
            continue
        if str(row_sys_id) != sys_id_str:
            continue

        scan_type_raw = ci_get(row, "scan_type") or ci_get(row, "Scan Type") or ""
        scan_type_norm = str(scan_type_raw).strip().lower()
        if "acas" in scan_type_norm:
            scoped_rows.append(row)

    # ---------- parity: no ACAS data branch ---------------------------------
    if not scoped_rows:
        # PowerShell: "FAIL: No ACAS scan data has been found."
        message = "FAIL: No ACAS scan data has been found."
        tr = TestResult(
            test_number=106,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(tr)
        logger.error("[T106] %s (system_id=%s)", message, ctx.system_id)
        return tr

    # ---------- 30-day freshness check ---------------------------------------
    thirty_days_seconds = 30 * 24 * 60 * 60
    now_epoch = int(_time.time())
    thirty_days_ago_epoch = now_epoch - thirty_days_seconds

    stale_hosts: list[str] = []
    for row in scoped_rows:
        last_scan_raw = ci_get(row, "last_scan_date") or ci_get(row, "Last Scan Date")
        last_scan_epoch = to_epoch_seconds(last_scan_raw)

        if last_scan_epoch is None or last_scan_epoch < thirty_days_ago_epoch:
            hostname = ci_get(row, "hostname") or "<unknown-host>"
            stale_hosts.append(str(hostname))

    # ---------- parity: PASS / FAIL messages ---------------------------------
    if not stale_hosts:
        # PowerShell: "PASS: All ACAS scans are within 30 days."
        message = "PASS: All ACAS scans are within 30 days."
        tr = TestResult(
            test_number=106,
            name=test_name,
            result=Result.PASS,
            message=message,
        )
        status.add(tr)
        logger.info("[T106] %s (system_id=%s)", message, ctx.system_id)
        return tr

    # PowerShell: "FAIL: N device(s) lack recent ACAS scans: host1, host2"
    host_list = ", ".join(stale_hosts)
    message = f"FAIL: {len(stale_hosts)} device(s) lack recent ACAS scans: {host_list}"
    tr = TestResult(
        test_number=106,
        name=test_name,
        result=Result.FAIL,
        message=message,
    )
    status.add(tr)
    logger.error("[T106] %s (system_id=%s)", message, ctx.system_id)
    return tr



#107 Was skipped in powershell

def test_108(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 108 — Findings older than 30 days have an associated POA&M

    Purpose
    -------
    Ensure any vulnerability that remains open > 30 days from first observed
    has an associated POA&M entry documenting mitigation.

    Behavior
    --------
    For each finding in this system:
      - Ignore if it's closed (Status like "Closed", "Mitigated", etc.).
      - Compute age from its first-observed timestamp.
      - If age > 30 days:
          * Check whether its "Security Check" appears in any POA&M row
            under "Security Checks".
          * If not, flag it.

    PASS if no >30-day open findings are missing POA&M coverage.
    FAIL if any are missing POA&M.
    (Missing/undatable findings are skipped, same spirit as legacy script.)

    Data (new world)
    ----------------
    ctx.findings: Findings
        .data: List[Dict[str, Any]] rows with fields like:
            - "system_id" / "System ID"
            - "security_check" / "Security Check"
            - "first_seen_date" / "First Discovered" / "First Observed" / "First Seen"
            - "status" / "Status"
    ctx.system_poam_dashboard: SystemPOAMDashboard
        .data: List[Dict[str, Any]] rows with fields like:
            - "system_id" / "System ID"
            - "security_checks" / "Security Checks"

    Notes
    -----
    - Time fields are expected to be epoch seconds (int/float/str). "-" or blank means unknown.
    - We only consider findings whose system_id matches ctx.system_id.
    """
    test_name = "Test 108: >30-day open findings have POA&M"
    logger.debug("Running %s", test_name)

    # ----------------- helpers -----------------
    def ci_get(d: dict, key: str):
        """Case-insensitive dict get; None if not found or not a dict."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def to_epoch_seconds(val) -> int | None:
        """
        Convert common timestamp formats to epoch seconds.
        Accepts:
          - int / float (assumed epoch seconds)
          - numeric-ish strings
        Returns None for "-", "", None, or unparsable values.
        """
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return int(val)
        s = str(val).strip()
        if not s or s == "-":
            return None
        try:
            return int(float(s))
        except Exception:
            return None

    def is_closed(status_val: object) -> bool:
        """Rough 'closed' detector like legacy script."""
        s = (str(status_val or "")).strip().lower()
        return s in {
            "closed",
            "resolved",
            "mitigated",
            "accepted",
            "risk accepted",
        }

    # Pull structured datasets from context
    findings_block = getattr(ctx, "findings", None)
    poam_block = getattr(ctx, "system_poam_dashboard", None)

    findings_rows: list[dict] = []
    if findings_block and isinstance(findings_block.data, list):
        findings_rows = findings_block.data

    poam_rows: list[dict] = []
    if poam_block and isinstance(poam_block.data, list):
        poam_rows = poam_block.data

    # Scope rows to this system
    sys_id_str = str(ctx.system_id)

    scoped_findings = []
    for f in findings_rows:
        row_sys_id = ci_get(f, "system_id") or ci_get(f, "System ID")
        if row_sys_id is None:
            continue
        if str(row_sys_id) == sys_id_str:
            scoped_findings.append(f)

    scoped_poam = []
    for p in poam_rows:
        row_sys_id = ci_get(p, "system_id") or ci_get(p, "System ID")
        # POA&M items sometimes don't repeat system_id per-row, so if missing, we keep them anyway.
        if row_sys_id is None or str(row_sys_id) == sys_id_str:
            scoped_poam.append(p)

    # Build lookup: all "Security Checks" values from POA&M rows, case-insensitive
    poam_checks_ci: set[str] = set()
    for p in scoped_poam:
        checks_val = ci_get(p, "security_checks") or ci_get(p, "Security Checks")
        if not checks_val:
            continue
        # May be comma- or semicolon-delimited
        parts = [chunk.strip().lower() for chunk in str(checks_val).replace(";", ",").split(",") if chunk.strip()]
        if parts:
            poam_checks_ci.update(parts)
        else:
            poam_checks_ci.add(str(checks_val).strip().lower())

    # Threshold: older than 30 days
    now_epoch = int(_time.time())
    thirty_days_seconds = 30 * 24 * 60 * 60
    cutoff_epoch = now_epoch - thirty_days_seconds

    missing_poam: list[str] = []

    for f in scoped_findings:
        # Is it still open?
        if is_closed(ci_get(f, "status") or ci_get(f, "Status")):
            continue

        # Figure out first-observed timestamp
        first_obs_raw = (
            ci_get(f, "first_seen_date")
            or ci_get(f, "First Discovered")
            or ci_get(f, "First Observed")
            or ci_get(f, "First Seen")
        )
        first_obs_epoch = to_epoch_seconds(first_obs_raw)
        if first_obs_epoch is None:
            # Can't age it → skip (mirrors legacy "if we can't date it, we don't fail it here")
            continue
        if first_obs_epoch > cutoff_epoch:
            # Not older than 30 days
            continue

        # Map by "Security Check"
        sec_check_val = (
            ci_get(f, "security_check")
            or ci_get(f, "Security Check")
            or ""
        )
        sec_check_norm = str(sec_check_val).strip().lower()

        if not sec_check_norm:
            # No key to match against POA&M → treat as missing POA&M coverage
            missing_poam.append("<unknown-security-check>")
            continue

        if sec_check_norm not in poam_checks_ci:
            missing_poam.append(str(sec_check_val).strip() or "<unknown-security-check>")

    if not missing_poam:
        tr = TestResult(
            test_number=108,
            name=test_name,
            result=Result.PASS,
            message="All findings older than 30 days have an associated POA&M (or are closed).",
        )
        status.add(tr)
        logger.info(
            "[T108] PASS — all >30-day open findings mapped to POA&M for system_id=%s",
            ctx.system_id,
        )
        return tr

    msg = (
        "Findings >30 days without a matching POA&M (by Security Check): "
        + ", ".join(sorted(set(missing_poam)))
    )
    tr = TestResult(
        test_number=108,
        name=test_name,
        result=Result.FAIL,
        message=msg,
    )
    status.add(tr)
    logger.error("[T108] FAIL — %s", msg)
    return tr


def test_109(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 109 — Code analysis required for GOTS / Gov-developed / Open Source software

    Purpose
    -------
    If the system includes Government-developed (GOTS) or Open Source (OSS) software,
    the control baseline must reflect appropriate code analysis controls:
      - SA-11(1) when source code is available
      - SA-11(8) when source code is not available
      - SI-2      when source code dependencies are available

    Outcomes (mirrors legacy semantics)
    -----------------------------------
    - N/A
        No GOTS/OSS software discovered in this system.
    - FAIL
        GOTS/OSS software discovered, but NONE of the required controls appear
        with implementation status "Implemented".
    - CONCERN
        GOTS/OSS software discovered AND at least one required control appears
        implemented. Manual verification is still required.

    Data (new world)
    ----------------
    Software inventory:
        ctx.software_details_dashboard: SoftwareDetailsDashboard | None
            .data: list[dict], with per-row fields:
                - "software_type"
                - "software_name"
                - "system_id"
    Controls baseline:
        ctx.controls: Controls | None
            .data: list[dict], with per-row fields:
                - "acronym"
                - "implementationstatus"

    Notes
    -----
    - Matching rows are limited to ctx.system_id.
    - String comparisons are case-insensitive.
    """

    test_name = "Test 109: Code analysis required for GOTS/OSS software"
    logger.debug("Running %s", test_name)

    # -------- helpers --------------------------------------------------------
    def ci_get(d: dict, key: str):
        """Case-insensitive getter for dict-like rows."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def is_gots_or_oss(sw_type: object) -> bool:
        """
        Heuristic to classify software as GOTS or OSS.
        We treat:
          - 'GOTS'
          - 'Government Off-The-Shelf'
          - 'Open Source'
          - 'OSS'
        as in-scope.
        """
        s = (str(sw_type or "")).strip().lower()
        return (
            "gots" in s
            or "government" in s and "off-the-shelf" in s
            or "open source" in s
            or "oss" in s
        )

    # -------- pull software rows (scoped) ------------------------------------
    sw_block = getattr(ctx, "software_details_dashboard", None)
    sw_rows: list[dict] = []
    if sw_block and isinstance(sw_block.data, list):
        sw_rows = sw_block.data

    system_id_str = str(ctx.system_id)

    relevant_software_names: list[str] = []
    for row in sw_rows:
        row_sys_id = ci_get(row, "system_id")
        # some dumps might use "System ID"
        if row_sys_id is None:
            row_sys_id = ci_get(row, "System ID")
        if row_sys_id is not None and str(row_sys_id) != system_id_str:
            continue  # not this system

        sw_type = ci_get(row, "software_type") or ci_get(row, "Software Type")
        if not is_gots_or_oss(sw_type):
            continue

        sw_name = (
            ci_get(row, "software_name")
            or ci_get(row, "Software Name")
            or ci_get(row, "title")
            or "<unnamed>"
        )
        relevant_software_names.append(str(sw_name).strip())

    # If no GOTS/OSS software → N/A (1:1 with legacy)
    if not relevant_software_names:
        tr = TestResult(
            test_number=109,
            name=test_name,
            result=Result.NA,
            message="No GOTS or OSS software identified in this system's inventory.",
        )
        status.add(tr)
        logger.info(
            "[T109] N/A — No GOTS/OSS detected for system_id=%s",
            ctx.system_id,
        )
        return tr

    # -------- pull controls baseline -----------------------------------------
    ctrl_block = getattr(ctx, "controls", None)
    ctrl_rows: list[dict] = []
    if ctrl_block and isinstance(ctrl_block.data, list):
        ctrl_rows = ctrl_block.data

    required_control_acronyms = {"sa-11(1)", "sa-11(8)", "si-2"}
    implemented_hits: set[str] = set()

    for c in ctrl_rows:
        acronym = (ci_get(c, "acronym") or "").strip()
        impl_status = (ci_get(c, "implementationstatus") or "").strip().lower()
        if not acronym:
            continue
        if impl_status != "implemented":
            continue
        if acronym.lower() in required_control_acronyms:
            implemented_hits.add(acronym.upper())

    # If we did not find any implemented required controls → FAIL
    if not implemented_hits:
        msg = (
            "GOTS/OSS software detected but required secure code analysis controls "
            "do not appear implemented (expected one of: SA-11(1), SA-11(8), SI-2). "
            "Software detected: "
            + ", ".join(sorted(relevant_software_names))
        )
        tr = TestResult(
            test_number=109,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error("[T109] FAIL — %s", msg)
        return tr

    # Otherwise, we found at least one implemented required control → CONCERN
    msg = (
        "GOTS/OSS software detected and at least one required control appears "
        "Implemented (" + ", ".join(sorted(implemented_hits)) + "). "
        "Manual verification required to confirm applicability and completeness."
    )
    tr = TestResult(
        test_number=109,
        name=test_name,
        result=Result.CONCERN,
        message=msg,
    )
    status.add(tr)
    logger.warning("[T109] CONCERN — %s", msg)
    return tr



def test_110(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 110 — Traceability between Resources Module and HW/SW lists

    Purpose
    -------
    Confirm every device in the Resources Module can be traced to entries in the
    Hardware and Software inventories (matching things like hostname, firmware
    version, and physical location).

    Legacy reality
    --------------
    The original script flags this as CONCERN because eMASS doesn't expose a
    Resources Module dataset through the API, and there's no reliable join key
    back to hardware_details / software_details.

    We keep that behavior 1:1:
      - We do NOT attempt to infer or approximate the mapping.
      - We always return CONCERN and direct the reviewer to do a manual check.

    Outcomes
    --------
    - CONCERN : eMASS API does not expose Resources↔HW/SW linkage for automated validation.
    """

    test_name = "Test 110: Resources ↔ HW/SW traceability"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=110,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "Resources Module ↔ Hardware/Software traceability cannot be verified via "
            "available data. eMASS does not expose a Resources dataset or linkage keys. "
            "Manual review required."
        ),
    )
    status.add(tr)
    logger.warning("[T110] CONCERN — Resources↔HW/SW linkage not available via API.")
    return tr

def test_111(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 111 — Required hardware fields populated for each component

    Purpose
    -------
    Verify that each hardware asset entry includes the required metadata:
      • Component Type
      • Machine Name (Asset Name)
      • IP Address (if applicable; still treated as required in the legacy script)
      • Virtual Asset
      • Manufacturer
      • Model Number
      • Serial Number (if applicable; still treated as required in the legacy script)
      • OS/iOS/FW Version
      • Location

    Legacy behavior
    ---------------
    - PASS if no asset is missing required fields.
    - FAIL if any asset is missing one or more required fields.
    - If there are zero hardware rows, legacy logic passes (nothing missing).
      We intentionally preserve that behavior.

    Data source in new model
    ------------------------
    Prefer structured dashboard data when present:
      ctx.hardware_details_dashboard.data : Optional[List[Dict[str, Any]]]

    Fallback (older raw exports):
      ctx.hardware.data
      ctx.fxtures.hardware_details.data  (if present in fixtures)

    Expected per-row fields (case-insensitive):
      "System ID"
      "Component Type"
      "Asset Name"
      "Asset IP Address"
      "Virtual Asset"
      "Manufacturer"
      "Model Number"
      "Serial Number"
      "OS/iOS/FW Version"
      "Location"
    """

    test_name = (
        "Test 111: Required HW fields — component type, machine name, IP, virtual "
        "asset, manufacturer, model, serial, OS/FW, location"
    )
    logger.debug("Running %s", test_name)

    # ---------- helpers ----------
    def ci_get(d: dict, key: str):
        """Case-insensitive getter from a dict-like row."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def missing_or_dash(v: object) -> bool:
        """True if value is missing/blank/'-' (matches PowerShell semantics)."""
        if v is None:
            return True
        s = str(v).strip()
        return s == "" or s == "-"

    # ---------- gather candidate hardware rows ----------
    # Priority order:
    #   1. ctx.hardware_details_dashboard.data
    #   2. ctx.hardware.data
    #   3. ctx.fixtures.hardware_details.data (if available)
    hw_rows_all: list[dict] = []

    dash = getattr(ctx, "hardware_details_dashboard", None)
    if dash and isinstance(dash.data, list) and dash.data:
        hw_rows_all = dash.data
    elif getattr(ctx, "hardware", None) and isinstance(ctx.hardware.data, list) and ctx.hardware.data:
        hw_rows_all = ctx.hardware.data
    else:
        fixtures_obj = getattr(ctx, "fixtures", None)
        if fixtures_obj:
            hdd = getattr(fixtures_obj, "hardware_details", None)
            if hdd and isinstance(hdd.data, list) and hdd.data:
                hw_rows_all = hdd.data

    # filter rows down to this system_id
    hw_rows = [
        r for r in hw_rows_all
        if str(ci_get(r, "System ID")) == str(ctx.system_id)
    ]

    # ---------- evaluate ----------
    incomplete_assets: list[str] = []

    for asset in hw_rows:
        missing_fields: list[str] = []

        # required fields mapped 1:1 to legacy labels
        field_map = {
            "Component Type":           ci_get(asset, "Component Type"),
            "Machine Name":             ci_get(asset, "Asset Name"),
            "IP Address":               ci_get(asset, "Asset IP Address"),
            "Virtual Asset":            ci_get(asset, "Virtual Asset"),
            "Manufacturer":             ci_get(asset, "Manufacturer"),
            "Model Number":             ci_get(asset, "Model Number"),
            "Serial Number":            ci_get(asset, "Serial Number"),
            "OS/iOS/FW Version":        ci_get(asset, "OS/iOS/FW Version"),
            "Location":                 ci_get(asset, "Location"),
        }

        for label, value in field_map.items():
            if missing_or_dash(value):
                missing_fields.append(label)

        if missing_fields:
            asset_name = ci_get(asset, "Asset Name") or "<unnamed>"
            sys_id = ci_get(asset, "System ID") or ctx.system_id
            incomplete_assets.append(
                f"{asset_name} (ID: {sys_id}) missing: {', '.join(missing_fields)}"
            )

    # Legacy semantics: empty hw_rows is still considered PASS
    if not incomplete_assets:
        msg = "All hardware components have the required fields populated."
        tr = TestResult(
            test_number=111,
            name=test_name,
            result=Result.PASS,
            message=msg,
        )
        status.add(tr)
        logger.info("[T111] %s (assets_checked=%d for system_id=%s)", msg, len(hw_rows), ctx.system_id)
        return tr

    msg = "Missing fields in Assets → " + " | ".join(incomplete_assets)
    tr = TestResult(
        test_number=111,
        name=test_name,
        result=Result.FAIL,
        message=msg,
    )
    status.add(tr)
    logger.error("[T111] %s", msg)
    return tr



def test_112(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 112 — Component types appear in the “System Authorization Boundary” artifact

    Purpose
    -------
    Ensure every component type listed in HW/SW inventory is represented
    (at least at the type/class level) in the System Authorization Boundary diagram.

    Legacy behavior
    ---------------
    The original PowerShell marks this test as CONCERN because:
    - The eMASS API does not expose machine-readable contents of the boundary diagram.
    - Verifying coverage would require manually inspecting the uploaded diagram (or OCR).

    We preserve that behavior exactly.

    Outcome
    -------
    - CONCERN: eMASS API does not provide the data needed to verify diagram coverage.
    """

    test_name = "Test 112: Component types represented in Authorization Boundary diagram"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=112,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "eMASS API does not expose diagram contents; OCR/manual verification is "
            "required to confirm component types are present on the Authorization Boundary."
        ),
    )
    status.add(tr)
    logger.warning("[T112] Insufficient data (no OCR) to automate verification.")
    return tr

def test_113(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 113 — OS/iOS/FW versions in Boundary diagram match SW inventory

    Purpose
    -------
    Validate that every OS / iOS / firmware version shown on the System Authorization
    Boundary artifact is represented in the software inventory (software name + version).

    Legacy behavior
    ---------------
    The original script returns CONCERN because the eMASS API does not expose
    machine-readable contents of the Authorization Boundary diagram/artifact.
    Verifying version alignment would require OCR or manual review.

    Outcome
    -------
    - CONCERN: Automated verification not possible (requires OCR/manual review).
    """
    test_name = (
        "Test 113: OS/iOS/FW versions in Authorization Boundary match SW inventory"
    )
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=113,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "Automated check not possible: eMASS API does not include Authorization "
            "Boundary diagram contents. Use OCR or manual review to confirm OS/iOS/FW "
            "versions align with software name+version in inventory."
        ),
    )
    status.add(tr)
    logger.warning("[T113] Cannot verify without OCR/text from artifact.")
    return tr



def test_114(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 114 — POC identified for each Hardware asset

    Purpose
    -------
    Ensure every hardware component has complete Point of Contact (POC) details and
    a recent review date (≤ 1 year old), mirroring the legacy PowerShell logic.

    Required fields per asset (case-insensitive / best-effort mapping)
    ------------------------------------------------------------------
    - POC Office/Organization
    - POC First Name
    - POC Last Name
    - POC Phone Number
    - POC Email
    - Date Reviewed / Updated (epoch seconds; must be within last 365 days)

    Behavior (1:1 with original script)
    -----------------------------------
    - PASS if all assets have all required POC fields AND the review date is present
      and within the last 365 days.
    - FAIL otherwise, listing each offending asset and which fields are missing/stale.
    - NOTE: As with the PowerShell, if there are zero hardware rows, this passes
      (because no violations were detected).

    Data source in new model
    ------------------------
    ctx.hardware_details_dashboard: HardwareDetailsDashboard | None
      - .data: Optional[List[Dict[str, Any]]]

    We also make a best effort to read POC/contact fields out of each row's dict
    because these are not first-class fields in HardwareDetailsDashboard today.
    """

    test_name = "Test 114: Hardware POC details present and current"
    logger.debug("Running %s", test_name)

    # ---------- helpers ----------
    def ci_get(d: dict, key: str):
        """Case-insensitive getter for dict-like rows."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def first_present(d: dict, *candidates: str):
        """Try multiple possible field names, return the first non-None/non-empty-ish."""
        for c in candidates:
            v = ci_get(d, c)
            if v is not None and str(v).strip() not in ("", "-"):
                return v
        # fall back to raw first candidate even if blank, to preserve semantics in messaging
        return ci_get(d, candidates[0])

    def is_missing(value: object) -> bool:
        """True if missing/blank/'-' (matching legacy semantics)."""
        if value is None:
            return True
        s = str(value).strip()
        return s == "" or s == "-"

    def to_int(v) -> int | None:
        """Best-effort int conversion; return None if not parseable."""
        try:
            return int(v)
        except Exception:
            return None

    # ---------- gather data ----------
    hw_block = getattr(ctx, "hardware_details_dashboard", None)
    hw_rows = []
    if hw_block and isinstance(hw_block.data, list):
        hw_rows = hw_block.data

    # 365-day cutoff
    now_epoch = int(_time.time())
    cutoff_epoch = now_epoch - (365 * 24 * 3600)

    offenders: list[str] = []

    for asset in hw_rows:
        missing_fields: list[str] = []

        # Try to identify the asset name for reporting
        asset_name = (
            first_present(
                asset,
                "Asset Name",
                "host_name",
                "Host Name",
                "hostname",
                "fqdn",
                "FQDN",
                "nickname",
                "Nickname",
            )
            or "<unnamed>"
        )

        # We'll also include system_id/device identifier if present for clarity
        sys_id = first_present(asset, "System ID", "system_id", "systemid") or ctx.system_id

        # Pull POC fields using the legacy labels; if  ingestion normalizes these
        # later into snake_case, add those names to the candidate lists.
        poc_office = first_present(asset, "POC Office/Organization", "poc_office_organization")
        poc_first = first_present(asset, "POC First Name", "poc_first_name")
        poc_last = first_present(asset, "POC Last Name", "poc_last_name")
        poc_phone = first_present(asset, "POC Phone Number", "poc_phone_number", "phone")
        poc_email = first_present(asset, "POC Email", "poc_email", "email")

        # Date Reviewed / Updated might appear as epoch seconds, review/update date,
        # last_scan_date, etc. We prefer explicit review/update fields if present.
        reviewed_raw = (
            ci_get(asset, "Date Reviewed / Updated")
            or ci_get(asset, "date_reviewed_updated")
            or ci_get(asset, "last_reviewed")
            or ci_get(asset, "last_scan_date")
        )
        reviewed_epoch = to_int(reviewed_raw)

        if is_missing(poc_office):
            missing_fields.append("POC Office/Organization")
        if is_missing(poc_first):
            missing_fields.append("POC First Name")
        if is_missing(poc_last):
            missing_fields.append("POC Last Name")
        if is_missing(poc_phone):
            missing_fields.append("POC Phone Number")
        if is_missing(poc_email):
            missing_fields.append("POC Email")

        # Review date required and must be within 1 year
        if reviewed_epoch is None or reviewed_epoch <= cutoff_epoch:
            missing_fields.append("Review Date ≤1yr")

        if missing_fields:
            offenders.append(
                f"{asset_name} (ID: {sys_id}) missing: {', '.join(missing_fields)}"
            )

    if not offenders:
        msg = "All hardware components have POC details and recent review dates."
        tr = TestResult(
            test_number=114,
            name=test_name,
            result=Result.PASS,
            message=msg,
        )
        status.add(tr)
        logger.info("[T114] %s (assets_checked=%d)", msg, len(hw_rows))
        return tr

    msg = "Missing POC fields or stale review date → " + " | ".join(offenders)
    tr = TestResult(
        test_number=114,
        name=test_name,
        result=Result.FAIL,
        message=msg,
    )
    status.add(tr)
    logger.error("[T114] %s", msg)
    return tr



def test_115(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 115 — POA&M exists for End-of-Life (EoL) hardware in the boundary

    Purpose
    -------
    Determine whether any EoL hardware inside the authorization boundary has a
    corresponding POA&M entry with a remediation timeline.

    Legacy behavior
    ---------------
    The upstream PowerShell marks this test as CONCERN because the eMASS API
    snapshot did not expose:
      - a reliable hardware End-of-Life indicator, and
      - a deterministic mapping from that asset to a POA&M line item.

    We preserve that behavior. We don't attempt to infer EoL status from
    firmware dates or lifecycle hints because that would go beyond 1:1 parity.

    Outcome
    -------
    - CONCERN : Automated verification not possible with available data.
    """

    test_name = "Test 115: POA&M for End-of-Life Hardware"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=115,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "Automated EoL hardware ↔ POA&M correlation is not available in the "
            "current structured data. Manual verification required (check boundary "
            "hardware against POA&M remediation items)."
        ),
    )
    status.add(tr)
    logger.warning(
        "[T115] Not enough structured data to verify EoL hardware POA&M coverage."
    )
    return tr


def test_116(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 116 — Software entries have required fields

    Purpose
    -------
    Ensure every software entry has the required fields populated:
      • Software Type
      • Software Vendor
      • Software Name
      • Software Version

    Behavior (1:1 with original)
    ----------------------------
    - PASS if all software rows contain non-empty values (not '-', not blank)
      for each required field.
    - FAIL otherwise; list each offending entry and the missing fields.

    Inputs (post-port, preferred)
    -----------------------------
    ctx.software_details_dashboard.data : List[dict]-like rows
        Keys may look like either legacy export headers
        ("Software Type", "Software Vendor", ...) or normalized snake_case
        ("software_type", "software_vendor", ...).

    Transitional fallback (legacy world)
    ------------------------------------
    ctx.raw.software_details or ctx.raw.software : List[dict]
        • "System ID"
        • "Software Type"
        • "Software Vendor"
        • "Software Name"
        • "Software Version"
    """
    test_name = "Test 116: Software entries have Type/Vendor/Name/Version"
    logger.debug("Running %s", test_name)

    # ---------- helpers ----------
    def ci_get(d: dict, key: str):
        """
        Case-insensitive dict lookup; also tolerates snake_case vs. title case.
        We'll try both the exact key and some common variants.
        """
        if not isinstance(d, dict):
            return None

        # direct case-insensitive match
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v

        # fallback: snake_case <-> title case bridges
        # e.g. "Software Type" <-> "software_type"
        snake_variant = (
            key.lower()
            .replace(" ", "_")
            .replace("/", "_")
            .replace("-", "_")
        )
        title_variant = (
            key.replace("_", " ")
               .replace("/", " ")
               .replace("-", " ")
        )

        for k, v in d.items():
            k_norm = str(k).lower().replace(" ", "_").replace("/", "_").replace("-", "_")
            if k_norm == snake_variant:
                return v
            if k_norm == snake_variant.replace("software_", "software_"):  # no-op but keeps symmetry
                return v
            # also check titleized norm
            if k_norm == title_variant.lower().replace(" ", "_"):
                return v

        return None

    def is_missing(value: object) -> bool:
        """Missing if None, empty string, or literal '-' (PowerShell parity)."""
        if value is None:
            return True
        s = str(value).strip()
        return s == "" or s == "-"

    def collect_sw_rows() -> list[dict]:
        """
        Preferred source: ctx.software_details_dashboard.data
        Fallbacks: ctx.software_details_dashboard (if it's already a list of dicts),
        then ctx.raw.software_details / ctx.raw.software (legacy).
        """
        rows: list[dict] = []

        # 1. Strongly-typed dashboard model path
        sdd = getattr(ctx, "software_details_dashboard", None)
        if sdd is not None:
            data_attr = getattr(sdd, "data", None)
            if isinstance(data_attr, list) and data_attr:
                rows = data_attr
            elif isinstance(sdd, list) and sdd:
                # extremely defensive: if someone stuffed list-of-dicts directly
                rows = sdd  # type: ignore[assignment]

        # 2. Legacy raw fallback if still available in the runtime ctx
        if not rows:
            raw_obj = getattr(ctx, "raw", None)
            if raw_obj is not None:
                legacy = (
                    getattr(raw_obj, "software_details", None)
                    or getattr(raw_obj, "software", None)
                    or []
                )
                if isinstance(legacy, list):
                    rows = legacy

        # Scope rows to this system_id if a System ID field is present.
        filtered: list[dict] = []
        for r in rows:
            sys_id_val = ci_get(r, "System ID")
            if sys_id_val is None:
                # assume already scoped to this system
                filtered.append(r)
            else:
                if str(sys_id_val) == str(ctx.system_id):
                    filtered.append(r)

        return filtered

    # ---------- gather data ----------
    sw_rows = collect_sw_rows()

    REQUIRED_FIELDS = [
        "Software Type",
        "Software Vendor",
        "Software Name",
        "Software Version",
    ]

    missing_entries: list[str] = []

    # ---------- evaluate ----------
    for row in sw_rows:
        missing_fields = [field for field in REQUIRED_FIELDS if is_missing(ci_get(row, field))]

        if missing_fields:
            sw_name = ci_get(row, "Software Name") or ci_get(row, "software_name") or "<unnamed>"
            # Try to surface a useful system ID / context for debugging
            sys_id = ci_get(row, "System ID") or ci_get(row, "system_id") or ctx.system_id
            missing_entries.append(
                f"{sw_name} (ID: {sys_id}) missing: {', '.join(missing_fields)}"
            )

    # ---------- result ----------
    if not missing_entries:
        msg = "All software entries have required fields populated."
        tr = TestResult(
            test_number=116,
            name=test_name,
            result=Result.PASS,
            message=msg,
        )
        status.add(tr)
        logger.info("[T116] %s (entries_checked=%d)", msg, len(sw_rows))
        return tr

    msg = (
        "Missing required fields in Software entries → "
        + " | ".join(missing_entries)
    )
    tr = TestResult(
        test_number=116,
        name=test_name,
        result=Result.FAIL,
        message=msg,
    )
    status.add(tr)
    logger.error("[T116] %s", msg)
    return tr


def test_117(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 117 — ACAS-detected software appears in the Software Baseline

    Purpose
    -------
    Validate that all software discovered by ACAS scans is represented in the
    system's Software Baseline.

    Parity with source script
    -------------------------
    The original PowerShell emits CONCERN because the eMASS API payload available
    here does not expose a reliable ACAS ↔ baseline crosswalk (no authoritative
    ACAS software inventory that can be joined to the system's declared baseline).
    We preserve that behavior exactly.

    Outcome
    -------
    - CONCERN: Automated verification not possible with current data.
    """
    test_name = "Test 117: ACAS software ↔ baseline coverage"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=117,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "ACAS-to-Software Baseline mapping not available in current API snapshot; "
            "manual verification required."
        ),
    )
    status.add(tr)
    logger.warning("[T117] Insufficient data to compare ACAS findings to software baseline.")
    return tr



def test_118(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 118 — Software entries have an identified POC

    Purpose
    -------
    Ensure each software record has complete Point-of-Contact (POC) details in
    the “General Information” section.

    Required fields (case-insensitive)
    ----------------------------------
    - POC Office/Organization
    - POC First Name
    - POC Last Name
    - POC Phone Number
    - POC Email
    - Date Reviewed / Updated  → must exist and be within the last year (epoch seconds)

    Behavior
    --------
    - PASS if all software entries include the fields above (not blank, not "-")
      and the review date is within one year.
    - FAIL otherwise; list each offending entry and which fields are missing/stale.

    Data source in new model
    ------------------------
    ctx.software_details_dashboard: SoftwareDetailsDashboard | None
      ctx.software_details_dashboard.data: Optional[List[Dict[str, Any]]]

    We expect (case-insensitive) keys like:
      • "Software Name"
      • "POC Office/Organization"
      • "POC First Name"
      • "POC Last Name"
      • "POC Phone Number"
      • "POC Email"
      • "Date Reviewed / Updated" (epoch seconds)
      • "System ID" (may appear as string or int)
    """
    test_name = "Test 118: Software POC identified"
    logger.debug("Running %s", test_name)

    # ---------- helpers ----------
    def ci_get(d: dict, key: str):
        """Case-insensitive dict lookup; None if missing or row not a dict."""
        if not isinstance(d, dict):
            return None
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return None

    def is_missing(v: object) -> bool:
        """
        Treat None / "" / "-" as missing.
        Mirrors the PowerShell semantics used in hardware POC (Test 114)
        and software required fields (Test 116).
        """
        if v is None:
            return True
        s = str(v).strip()
        return s == "" or s == "-"

    def to_int(v) -> int | None:
        """Best-effort int conversion, else None."""
        try:
            return int(v)
        except Exception:
            return None

    # ---------- gather data ----------
    sw_dash = getattr(ctx, "software_details_dashboard", None)
    rows = []
    if sw_dash and isinstance(sw_dash.data, list):
        rows = sw_dash.data

    # Time window for "within 1 year"
    one_year_seconds = 365 * 24 * 60 * 60
    now_epoch = int(_time.time())
    cutoff_epoch = now_epoch - one_year_seconds

    offenders: list[str] = []

    REQUIRED_POC_FIELDS = [
        "POC Office/Organization",
        "POC First Name",
        "POC Last Name",
        "POC Phone Number",
        "POC Email",
    ]

    for row in rows:
        missing_fields: list[str] = []

        # Required POC identity/contact fields
        for field in REQUIRED_POC_FIELDS:
            if is_missing(ci_get(row, field)):
                missing_fields.append(field)

        # Date Reviewed / Updated must exist and be <= 365 days old
        reviewed_raw = ci_get(row, "Date Reviewed / Updated")
        reviewed_epoch = to_int(reviewed_raw)
        if reviewed_epoch is None or reviewed_epoch < cutoff_epoch:
            missing_fields.append("Review Date ≤1yr")

        if missing_fields:
            sw_name = ci_get(row, "Software Name") or "<unnamed software>"
            sys_id = ci_get(row, "System ID") or ctx.system_id
            offenders.append(
                f"{sw_name} (ID: {sys_id}) missing: {', '.join(missing_fields)}"
            )

    # ---------- result ----------
    if not offenders:
        msg = (
            "All software entries have complete POC details and a review within one year."
        )
        tr = TestResult(
            test_number=118,
            name=test_name,
            result=Result.PASS,
            message=msg,
        )
        status.add(tr)
        logger.info("[T118] %s (entries_checked=%d)", msg, len(rows))
        return tr

    msg = "Missing Software POC → " + " | ".join(offenders)
    tr = TestResult(
        test_number=118,
        name=test_name,
        result=Result.FAIL,
        message=msg,
    )
    status.add(tr)
    logger.error("[T118] %s", msg)
    return tr


def test_119(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 119 — POA&M exists for End-of-Life (EoL) software within the authorization boundary

    Purpose
    -------
    Determine whether any End-of-Life software identified inside the system’s
    authorization boundary has a corresponding POA&M entry documenting planned
    remediation/replacement.

    Parity with source script
    -------------------------
    The original PowerShell implementation always returns **CONCERN** because
    validating EoL software inside the *authorization boundary* requires reading
    the boundary diagram/document, which is not available through the current
    eMASS API data (no OCR or structured extraction). We preserve that behavior.

    Outcome
    -------
    - CONCERN : Automated verification not possible with current inputs; manual review required.

    Notes
    -----
    If in the future the artifact text (e.g., PDF) is OCR’d and parsed into
    structured data, this test should:
      1) extract the set of software in-boundary from the artifact,
      2) find any entries flagged EoL/EoS,
      3) verify each has a matching POA&M item with dates/mitigations.
    """
    test_name = "Test 119: POA&M for EoL software in authorization boundary"
    logger.debug("Running %s", test_name)

    tr = TestResult(
        test_number=119,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "Cannot verify EoL software inside authorization boundary using current "
            "API snapshot; requires OCR/parsed boundary artifact. Perform manual review."
        ),
    )
    status.add(tr)
    logger.warning(
        "[T119] Insufficient data (no OCR/structured boundary parsing). Marking as CONCERN."
    )
    return tr


def test_120(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 120 — POC information provided under "General POA&M Information".

    Purpose
    -------
    Validate that each POA&M item (non-inherited) includes basic POC identity:
      • pocFirstName
      • pocLastName
    We treat a value as missing if it's None, empty, or "-".
    This mirrors the PowerShell logic.

    Behavior
    --------
    For each POA&M row associated with this system:
      - Skip inherited items (isInherited == True).
      - Require non-missing pocFirstName and pocLastName.
      - On first failure, FAIL and report that POA&M item's ID.

    Outcomes
    --------
    - PASS : All applicable POA&M items have valid first/last names (or there
             are no POA&M rows at all).
    - FAIL : A POA&M item is missing first or last name; we include its ID.

    Notes
    -----
    • The legacy commentary says this might warrant CONCERN due to API gaps,
      but the actual script logic is straight PASS/FAIL. We preserve that.
    • Keys are matched case-insensitively.
    """
    test_name = "Test 120: POC info present in POA&M 'General Information'"
    logger.debug("Running %s", test_name)

    # ----- helpers -----------------------------------------------------------
    def ci_get(d: dict, key: str, default=None):
        """Case-insensitive dict getter."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def is_missing(v: object) -> bool:
        """True if value is None, empty, or '-' (PowerShell semantics)."""
        if v is None:
            return True
        s = str(v).strip()
        return s == "" or s == "-"

    # ----- load POA&M rows ---------------------------------------------------
    poam_rows_all = (
        getattr(ctx, "system_poam_dashboard", None)
        and getattr(ctx.system_poam_dashboard, "data", None)
    ) or getattr(ctx, "system_poam_details", None) or []
    # Fallback to raw-style list if present
    if not poam_rows_all:
        poam_rows_all = (
            getattr(ctx, "raw", None)
            and (
                getattr(ctx.raw, "system_poam_details", None)
                or getattr(ctx.raw, "poam_details", None)
                or getattr(ctx.raw, "poam", None)
            )
        ) or []

    # Filter rows to just this system_id when possible
    poam_rows: list[dict] = []
    for row in poam_rows_all:
        sys_id_val = ci_get(row, "System ID") or ci_get(row, "system_id")
        if sys_id_val is None or str(sys_id_val) == str(ctx.system_id):
            poam_rows.append(row)

    # ----- evaluate ----------------------------------------------------------
    offending_id = None

    for row in poam_rows:
        # Skip inherited POA&M items if flagged
        if ci_get(row, "isInherited", False) is True:
            continue

        first = ci_get(row, "pocFirstName")
        last = ci_get(row, "pocLastName")

        if is_missing(first) or is_missing(last):
            offending_id = ci_get(row, "displayPoamId") or ci_get(row, "id") or "<unknown>"
            logger.error(
                "[T120] Missing POC first/last name for POA&M ID %s (system_id=%s)",
                offending_id,
                ctx.system_id,
            )
            break

    # ----- result ------------------------------------------------------------
    if offending_id is not None:
        tr = TestResult(
            test_number=120,
            name=test_name,
            result=Result.FAIL,
            message=f"POC first/last name missing for POA&M ID: {offending_id}.",
        )
        status.add(tr)
        return tr

    tr = TestResult(
        test_number=120,
        name=test_name,
        result=Result.PASS,
        message=(
            "All applicable POA&M entries include POC first/last names "
            "(or there were no POA&M items to validate)."
        ),
    )
    status.add(tr)
    logger.info(
        "[T120] PASS — all POA&M items have POC first/last names (system_id=%s, rows_checked=%d)",
        ctx.system_id,
        len(poam_rows),
    )
    return tr


def test_121(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 121 — “Point of Contact” information provided in each POA&M record.

    Purpose
    -------
    Ensure every relevant (non-inherited) POA&M row includes a Point of Contact
    (POC) with both first and last name populated.

    What we check
    -------------
    For each POA&M row for this system (skipping inherited rows):
      • pocFirstName is present, non-empty, and not "-"
      • pocLastName  is present, non-empty, and not "-"
    On the first failure we stop and report that POA&M row's ID.

    Rationale
    ---------
    Mirrors the original PowerShell logic operating on a non-inherited subset.

    Outcomes
    --------
    - PASS : All non-inherited POA&M entries have valid POC info (or there are no rows).
    - FAIL : First offending POA&M ID is reported.
    """
    test_name = "Test 121: POC information present in each non-inherited POA&M record"
    logger.debug("Running %s", test_name)

    # ---------- helpers ----------
    def ci_get(d: dict, key: str, default=None):
        """Case-insensitive dict getter tolerant of column drift."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def is_missing(value: object) -> bool:
        """True if value is None, empty string, or '-'."""
        if value is None:
            return True
        s = str(value).strip()
        return s == "" or s == "-"

    # ---------- load POA&M dataset ----------
    # Try structured dashboard view first
    poam_rows_all = (
        getattr(ctx, "system_poam_dashboard", None)
        and getattr(ctx.system_poam_dashboard, "data", None)
    ) or getattr(ctx, "system_poam_details", None) or []

    # Fallback to raw if needed
    if not poam_rows_all:
        poam_rows_all = (
            getattr(ctx, "raw", None)
            and (
                getattr(ctx.raw, "system_poam_details", None)
                or getattr(ctx.raw, "poam_details", None)
                or getattr(ctx.raw, "poam", None)
            )
        ) or []

    # Filter rows to this system when possible
    poam_rows: list[dict] = []
    for row in poam_rows_all:
        sys_id_val = ci_get(row, "System ID") or ci_get(row, "system_id")
        if sys_id_val is None or str(sys_id_val) == str(ctx.system_id):
            poam_rows.append(row)

    # ---------- evaluate ----------
    offending_id = None

    for row in poam_rows:
        # Only check non-inherited items
        if ci_get(row, "isInherited", False) is True:
            continue

        first = ci_get(row, "pocFirstName")
        last = ci_get(row, "pocLastName")

        if is_missing(first) or is_missing(last):
            offending_id = (
                ci_get(row, "displayPoamId")
                or ci_get(row, "id")
                or "<unknown>"
            )
            logger.error(
                "[T121] Missing POC info for POA&M ID %s (system_id=%s)",
                offending_id,
                ctx.system_id,
            )
            break

    # ---------- result ----------
    if offending_id is not None:
        tr = TestResult(
            test_number=121,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Some non-inherited POA&M entries are missing POC fields; "
                f"first failure at POA&M ID: {offending_id}."
            ),
        )
        status.add(tr)
        return tr

    tr = TestResult(
        test_number=121,
        name=test_name,
        result=Result.PASS,
        message=(
            "All non-inherited POA&M entries include POC first/last name "
            "(or there were no applicable POA&M rows)."
        ),
    )
    status.add(tr)
    logger.info(
        "[T121] PASS — all POA&M rows have POC info (system_id=%s, rows_checked=%d)",
        ctx.system_id,
        len(poam_rows),
    )
    return tr


def test_122(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 122 — All POA&M entries are mapped to an applicable security control.

    Purpose
    -------
    Validate that every POA&M row is explicitly tied to a security control
    (e.g., "AC-2", "RA-5") so remediation work is traceable to a baseline
    requirement.

    What we check
    -------------
    For each POA&M row in the current system:
      • controlAcronym exists
      • controlAcronym is non-empty and not "-"

    Notes
    -----
    - Mirrors the original PowerShell `$filteredPoamData` logic, which checks
      ALL POA&M rows (inherited or not). Do not filter by `isInherited`.
    - Case-insensitive field access is used to tolerate column drift
      ("controlAcronym" vs "Control Acronym", etc.).

    Outcomes
    --------
    - PASS : All rows have a valid control acronym (or there are no rows).
    - FAIL : First offending POA&M entry is reported by its display ID.
    """
    test_name = (
        "Test 122: All POA&M entries are mapped to the applicable security control"
    )
    logger.debug("Running %s", test_name)

    # ---------- helpers ----------
    def ci_get(d: dict, key: str, default=None):
        """Case-insensitive getter tolerant of column drift."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def is_missing(value: object) -> bool:
        """True if value is None, empty string, or '-'."""
        if value is None:
            return True
        s = str(value).strip()
        return s == "" or s == "-"

    # ---------- load POA&M dataset ----------
    poam_rows_all = (
        getattr(ctx, "system_poam_dashboard", None)
        and getattr(ctx.system_poam_dashboard, "data", None)
    ) or getattr(ctx, "system_poam_details", None) or []

    # Fallback to raw if nothing structured is attached
    if not poam_rows_all:
        poam_rows_all = (
            getattr(ctx, "raw", None)
            and (
                getattr(ctx.raw, "system_poam_details", None)
                or getattr(ctx.raw, "poam_details", None)
                or getattr(ctx.raw, "poam", None)
            )
        ) or []

    # Filter down to this system where possible. We accept rows with no System ID
    # (PowerShell wasn't super strict about this either).
    poam_rows: list[dict] = []
    for row in poam_rows_all:
        sys_id_val = ci_get(row, "System ID") or ci_get(row, "system_id")
        if sys_id_val is None or str(sys_id_val) == str(ctx.system_id):
            poam_rows.append(row)

    # ---------- evaluate rows ----------
    offending_id = None

    for row in poam_rows:
        control = (
            ci_get(row, "controlAcronym")
            or ci_get(row, "Control Acronym")
            or ci_get(row, "control_acronym")
        )

        if is_missing(control):
            offending_id = (
                ci_get(row, "displayPoamId")
                or ci_get(row, "displaypoamId")
                or ci_get(row, "id")
                or "<unknown>"
            )
            logger.error(
                "[T122] Missing/invalid control mapping for POA&M ID %s (system_id=%s)",
                offending_id,
                ctx.system_id,
            )
            break

    # ---------- produce result ----------
    if offending_id is not None:
        tr = TestResult(
            test_number=122,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Missing or invalid security control mapping in POA&M ID: "
                f"{offending_id}."
            ),
        )
        status.add(tr)
        return tr

    tr = TestResult(
        test_number=122,
        name=test_name,
        result=Result.PASS,
        message="All POA&M entries have valid security control mappings.",
    )
    status.add(tr)
    logger.info(
        "[T122] PASS — all POA&M rows mapped to controls (system_id=%s, rows_checked=%d)",
        ctx.system_id,
        len(poam_rows),
    )
    return tr


def test_123(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 123 — POA&M status and control status do not conflict.

    Purpose
    -------
    Detect inconsistencies between POA&M records and the control/compliance
    state recorded elsewhere for the same system.

    Legacy rules (mirrors the original PowerShell logic)
    ----------------------------------------------------
    For each POA&M entry (skipping inherited rows):
      1) If POA&M `status` == "Ongoing" AND either `controlAcronym` or `cci`
         text *contains* "Compliant" → conflict.
      2) If POA&M `status` in {"Ongoing", "Risk Accepted"} AND either
         `controlAcronym` or `cci` text *contains* "Compliant" → conflict.
         (Yes, this overlaps rule #1. We intentionally keep both to stay
          faithful to the source.)

    Then:
      3) For each Non-Compliant control in the control dataset, verify there
         exists at least one POA&M whose `controlAcronym` string contains that
         control acronym. If not, flag a conflict.

    Notes
    -----
    • We treat "NC" / "Non-Compliant" (any case, extra spaces, hyphen optional)
      as Non-Compliant.
    • Case-insensitive field lookup because exports drift.
    • We try structured context first, then fall back to ctx.raw.
    """
    test_name = "Test 123: POA&M status and control status do not conflict."
    logger.debug("Running %s", test_name)

    # ---------- helpers ----------
    def ci_get(d: dict, key: str, default=None):
        """Case-insensitive getter; returns default when key not present."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def text_contains(val, needle: str) -> bool:
        """True if string value contains `needle` (case-insensitive)."""
        if val is None:
            return False
        return needle.lower() in str(val).lower()

    def norm_status(s: object) -> str:
        """
        Normalize a compliance status down to 'nc' (non-compliant),
        'c' (compliant), or raw lowercase string.
        """
        v = (str(s or "")).strip().lower()
        if v in {"c", "compliant"}:
            return "c"
        if v in {"nc", "non-compliant", "non compliant", "noncompliant"}:
            return "nc"
        return v

    # ---------- load POA&M rows ----------
    # Preferred structured path
    poam_rows_all = []
    if getattr(ctx, "system_poam_dashboard", None):
        poam_rows_all = getattr(ctx.system_poam_dashboard, "data", None) or []

    # Fallback(s)
    if not poam_rows_all:
        poam_rows_all = (
            getattr(ctx, "system_poam_details", None)
            or (
                getattr(ctx, "raw", None)
                and (
                    getattr(ctx.raw, "system_poam_details", None)
                    or getattr(ctx.raw, "poam_details", None)
                    or getattr(ctx.raw, "poam", None)
                )
            )
            or []
        )

    # Filter to this system_id when possible
    poam_rows: list[dict] = []
    for row in poam_rows_all:
        sys_id_val = ci_get(row, "System ID") or ci_get(row, "system_id")
        if sys_id_val is None or str(sys_id_val) == str(ctx.system_id):
            poam_rows.append(row)

    # ---------- load control rows ----------
    control_rows_all = []
    if getattr(ctx, "controls", None):
        control_rows_all = getattr(ctx.controls, "data", None) or []

    if not control_rows_all:
        control_rows_all = (
            getattr(ctx, "raw", None)
            and (
                getattr(ctx.raw, "controls", None)
                or getattr(ctx.raw, "controls_data", None)
                or getattr(ctx.raw, "controls_catalog", None)
            )
        ) or []

    control_rows: list[dict] = []
    for row in control_rows_all:
        sys_id_val = ci_get(row, "System ID") or ci_get(row, "systemid") or ci_get(row, "system_id")
        if sys_id_val is None or str(sys_id_val) == str(ctx.system_id):
            control_rows.append(row)

    # ---------- rule evaluation ----------
    conflicts: list[str] = []

    # Rules 1 & 2: internal POA&M consistency
    for row in poam_rows:
        # skip inherited POA&M entries
        if bool(ci_get(row, "isInherited", False)):
            continue

        poam_status = (ci_get(row, "status", "") or "").strip()
        control_acronym_text = ci_get(row, "controlAcronym", "") or ci_get(row, "Control Acronym", "") or ""
        cci_text = ci_get(row, "cci", "") or ""

        disp_id = (
            ci_get(row, "displayPoamId")
            or ci_get(row, "displaypoamId")
            or ci_get(row, "displayPOAMId")
            or ci_get(row, "id")
            or "<unknown POA&M ID>"
        )

        # Rule 1
        if poam_status == "Ongoing" and (
            text_contains(control_acronym_text, "Compliant")
            or text_contains(cci_text, "Compliant")
        ):
            conflicts.append(f"{disp_id} (Ongoing but marked Compliant)")

        # Rule 2
        if poam_status in {"Ongoing", "Risk Accepted"} and (
            text_contains(control_acronym_text, "Compliant")
            or text_contains(cci_text, "Compliant")
        ):
            conflicts.append(f"{disp_id} (Risk Accepted/Ongoing but marked Compliant)")

    # Rule 3: every Non-Compliant control must have at least one POA&M
    # whose controlAcronym references that control acronym
    # Build set of NC control acronyms
    nc_control_acronyms: set[str] = set()
    for ctrl in control_rows:
        c_status_norm = norm_status(ci_get(ctrl, "complianceStatus") or ci_get(ctrl, "compliancestatus"))
        if c_status_norm == "nc":
            acronym_val = (
                ci_get(ctrl, "acronym")
                or ci_get(ctrl, "controlAcronym")
                or ci_get(ctrl, "Control Acronym")
                or ""
            )
            acronym_val = str(acronym_val).strip()
            if acronym_val:
                nc_control_acronyms.add(acronym_val)

    if nc_control_acronyms:
        # Build a list of POA&M controlAcronym strings to match against
        poam_control_texts = [
            str(
                ci_get(p, "controlAcronym")
                or ci_get(p, "Control Acronym")
                or ""
            )
            for p in poam_rows
        ]

        for ctrl_acr in nc_control_acronyms:
            if not any(ctrl_acr in poam_text for poam_text in poam_control_texts):
                conflicts.append(
                    f"Control {ctrl_acr} — Non-Compliant control with no POA&M"
                )

    # ---------- finalize ----------
    if conflicts:
        # de-dupe while preserving order-ish
        seen = set()
        unique_conflicts = []
        for cmsg in conflicts:
            if cmsg not in seen:
                seen.add(cmsg)
                unique_conflicts.append(cmsg)

        msg = "Conflicts found: " + "; ".join(unique_conflicts)
        tr = TestResult(
            test_number=123,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error("[T123] %s (system_id=%s)", msg, ctx.system_id)
        return tr

    tr = TestResult(
        test_number=123,
        name=test_name,
        result=Result.PASS,
        message="No conflicts between POA&M status and control status.",
    )
    status.add(tr)
    logger.info(
        "[T123] PASS — POA&M status aligns with control status (system_id=%s, poams_checked=%d, controls_checked=%d)",
        ctx.system_id,
        len(poam_rows),
        len(control_rows),
    )
    return tr


def test_124(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 124 — 'Vulnerability Description' present except for Not Applicable POA&Ms

    Purpose
    -------
    Ensure each POA&M record includes a non-empty Vulnerability Description
    that demonstrates understanding of the vulnerability, with the single
    exception of POA&Ms whose overall status is "Not Applicable".

    What we check (mirrors legacy PowerShell semantics)
    ---------------------------------------------------
    For each POA&M row (no inheritance filtering):
      • If `status` == "Not Applicable" → skip row.
      • Else, require `vulnerabilityDescription` to be present and non-empty
        (not None, not "", not "-").
      • On the first missing description, FAIL and report that POA&M's ID.

    Outcomes
    --------
    - PASS : All eligible POA&M rows include a Vulnerability Description.
    - FAIL : First POA&M missing a description is reported by its ID.
    """
    test_name = "Test 124: 'Vulnerability Description' present except for Not Applicable POA&Ms"
    logger.debug("Running %s", test_name)

    # ---------- helpers ----------
    def ci_get(d: dict, key: str, default=None):
        """Case-insensitive dict getter."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def is_blank(val: object) -> bool:
        """Treat None, empty string, or single dash '-' as blank."""
        if val is None:
            return True
        s = str(val).strip()
        return s == "" or s == "-"

    # ---------- load POA&M rows ----------
    # Prefer structured dashboard data if present
    poam_rows_all = []
    if getattr(ctx, "system_poam_dashboard", None):
        poam_rows_all = getattr(ctx.system_poam_dashboard, "data", None) or []

    # Fallbacks if dashboard data not populated
    if not poam_rows_all:
        poam_rows_all = (
            getattr(ctx, "system_poam_details", None)
            or (
                getattr(ctx, "raw", None)
                and (
                    getattr(ctx.raw, "system_poam_details", None)
                    or getattr(ctx.raw, "poam_details", None)
                    or getattr(ctx.raw, "poam", None)
                )
            )
            or []
        )

    # Scope rows to this system_id when possible, but include rows
    # that don't advertise system ID (same behavior we used in 120+)
    poam_rows: list[dict] = []
    for row in poam_rows_all:
        sys_id_val = ci_get(row, "System ID") or ci_get(row, "system_id")
        if sys_id_val is None or str(sys_id_val) == str(ctx.system_id):
            poam_rows.append(row)

    # ---------- evaluate ----------
    for row in poam_rows:
        status_text = (ci_get(row, "status", "") or "").strip().lower()

        # Skip "Not Applicable" POA&Ms (they are exempt)
        if status_text == "not applicable":
            continue

        vuln_desc = (
            ci_get(row, "vulnerabilityDescription")
            or ci_get(row, "Vulnerability Description")
        )

        if is_blank(vuln_desc):
            failed_poam_id = (
                ci_get(row, "poamId")
                or ci_get(row, "POAM Id")
                or ci_get(row, "POA&M ID")
                or ci_get(row, "displayPoamId")
                or ci_get(row, "displaypoamId")
                or "<unknown POA&M ID>"
            )

            tr = TestResult(
                test_number=124,
                name=test_name,
                result=Result.FAIL,
                message=f"Missing Vulnerability Description for POA&M ID: {failed_poam_id}.",
            )
            status.add(tr)
            logger.error(
                "[T124] FAIL — Missing Vulnerability Description for POA&M ID %s (system_id=%s)",
                failed_poam_id,
                ctx.system_id,
            )
            return tr

    # ---------- pass ----------
    tr = TestResult(
        test_number=124,
        name=test_name,
        result=Result.PASS,
        message="All eligible POA&M entries include a Vulnerability Description.",
    )
    status.add(tr)
    logger.info(
        "[T124] PASS — All eligible POA&M entries have Vulnerability Descriptions (system_id=%s, poams_checked=%d)",
        ctx.system_id,
        len(poam_rows),
    )
    return tr


def test_125(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 125 — Mitigations are present (when required) and plausibly specific

    Purpose
    -------
    Validate that POA&M records in a state that *requires mitigations* include a
    non-empty Mitigations entry. This mirrors the legacy PowerShell logic:
    we only assert presence/emptiness (not narrative quality), and we fail fast
    on the first offending POA&M.

    Scope
    -----
    • Rows with `status` equal to "Ongoing" or "Risk Accepted" MUST include
      a non-blank `mitigations` field.
    • All other statuses are skipped.

    Blank definition (PowerShell parity)
    ------------------------------------
    Consider `mitigations` blank if it is:
      - None
      - ""
      - "-"
      - "not applicable" (case-insensitive)

    Outcomes
    --------
    - FAIL    : First POA&M in required status is missing/blank mitigations.
    - CONCERN : All required rows have text, but human review is still required
                for sufficiency/specificity. (We intentionally do not return PASS.)

    Notes
    -----
    - Case-insensitive dict access is used for resilience to column drift.
    - We stop at the first failure (mirrors `break` in PowerShell).
    """
    test_name = "Test 125: Mitigations present for 'Ongoing' or 'Risk Accepted' POA&Ms"
    logger.debug("Running %s", test_name)

    # ---------- helpers ----------
    def ci_get(d: dict, key: str, default=None):
        """Case-insensitive dict getter."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def is_blank_mitigation(val: object) -> bool:
        """
        Blank if None, empty, '-', or 'not applicable' (case-insensitive).
        """
        if val is None:
            return True
        s = str(val).strip()
        if s == "" or s == "-":
            return True
        return s.lower() == "not applicable"

    # ---------- load POA&M rows ----------
    poam_rows_all = []
    if getattr(ctx, "system_poam_dashboard", None):
        poam_rows_all = getattr(ctx.system_poam_dashboard, "data", None) or []

    if not poam_rows_all:
        poam_rows_all = (
            getattr(ctx, "system_poam_details", None)
            or (
                getattr(ctx, "raw", None)
                and (
                    getattr(ctx.raw, "system_poam_details", None)
                    or getattr(ctx.raw, "poam_details", None)
                    or getattr(ctx.raw, "poam", None)
                )
            )
            or []
        )

    # Filter rows for this system_id when present in the row;
    # include rows with no system id (same leniency as earlier tests)
    poam_rows: list[dict] = []
    for row in poam_rows_all:
        sys_id_val = ci_get(row, "System ID") or ci_get(row, "system_id")
        if sys_id_val is None or str(sys_id_val) == str(ctx.system_id):
            poam_rows.append(row)

    # ---------- evaluate ----------
    for row in poam_rows:
        status_text = (ci_get(row, "status", "") or "").strip()
        if status_text not in {"Ongoing", "Risk Accepted"}:
            continue  # Only these require mitigations text

        mitigations_val = ci_get(row, "mitigations")

        if is_blank_mitigation(mitigations_val):
            poam_id = (
                ci_get(row, "poamId")
                or ci_get(row, "displayPoamId")
                or ci_get(row, "displaypoamId")
                or ci_get(row, "POA&M ID")
                or "<unknown POA&M ID>"
            )

            tr = TestResult(
                test_number=125,
                name=test_name,
                result=Result.FAIL,
                message=f"Missing or invalid mitigations for POA&M ID: {poam_id}.",
            )
            status.add(tr)

            logger.error(
                "[T125] FAIL — Missing/blank mitigations for POA&M ID %s (status=%s, system_id=%s)",
                poam_id,
                status_text,
                ctx.system_id,
            )
            return tr

    # If we got here, every required POA&M row had non-blank mitigations.
    # We still mark CONCERN, not PASS, because content quality still needs human review.
    tr = TestResult(
        test_number=125,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "All required POA&M entries in status Ongoing / Risk Accepted "
            "have mitigation text. Manual verification of specificity is still required."
        ),
    )
    status.add(tr)

    logger.warning(
        "[T125] CONCERN — Mitigations present for all required POA&M entries; "
        "manual quality review still required (system_id=%s, poams_checked=%d)",
        ctx.system_id,
        len(poam_rows),
    )
    return tr


def test_126(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 126 — POA&M Severity aligns with NETCOM Risk Analysis guidance.

    Parity with source PowerShell:
    - Consider only POA&Ms whose `status` is "Ongoing" or "Risk Accepted".
    - For those rows:
        1. `severity` must be present (non-empty).
        2. `severity` must equal `residualRiskLevel`.
        3. `severity` must NOT be *lower* than the highest residual risk level
           seen across all in-scope POA&Ms.
    - Any violation -> FAIL, listing offending POA&M IDs.
    - Otherwise -> PASS.

    Data source preference:
    - First: ctx.system_poam_dashboard.data  (structured, modeled path)
    - Fallback: ctx.raw_payloads.system_poam_details  (only if the first is missing)
    """

    test_name = (
        "Test 126: Severity matches NETCOM guidance for 'Ongoing'/'Risk Accepted' POA&Ms"
    )

    # ------------------------------------------------------------------
    # Local helper: get POA&M rows from the context.
    # We keep it inside the function so this test is a single drop-in unit.
    # ------------------------------------------------------------------
    def _get_poams_from_context(system_ctx: SystemContext) -> list[dict]:
        """
        Return a list of POA&M-like dicts for this system.

        Order of preference:
          1. system_ctx.system_poam_dashboard.data  (modeled JSON structure)
          2. system_ctx.raw_payloads.system_poam_details  (legacy/raw dumps)

        If neither exists, return an empty list.
        """
        # 1) structured / modeled location
        dashboard = getattr(system_ctx, "system_poam_dashboard", None)
        if dashboard is not None:
            data = getattr(dashboard, "data", None)
            if isinstance(data, list):
                return data

        # 2) last-resort raw
        raw = getattr(system_ctx, "raw_payloads", None)
        if raw is not None:
            raw_poams = getattr(raw, "system_poam_details", None)
            if isinstance(raw_poams, list):
                return raw_poams

        # 3) nothing available
        return []

    # ------------------------------------------------------------------
    # Utility helpers (case-insensitive getter, label normalization, etc.)
    # ------------------------------------------------------------------
    def ci_get(row: dict, key: str, default=None):
        """
        Case-insensitive dict getter.

        eMASS exports are messy and may have field names like 'ResidualRiskLevel',
        'residualrisklevel', 'residualRiskLevel', etc. This helper collapses that.
        """
        if not isinstance(row, dict):
            return default
        wanted = key.lower()
        for k, v in row.items():
            if str(k).lower() == wanted:
                return v
        return default

    def normalize_risk_label(value: object) -> str:
        """
        Normalize common risk labels to canonical forms so we can compare them.

        We explicitly accept 'Medium' as 'Moderate', because that shows up in
        some eMASS datasets.
        """
        text = str(value or "").strip()
        canonical_map = {
            "very low": "Very Low",
            "low": "Low",
            "moderate": "Moderate",
            "medium": "Moderate",
            "high": "High",
            "very high": "Very High",
        }
        return canonical_map.get(text.lower(), text)

    # Strict order for comparisons — index is the "strength"
    risk_scale = ["Very Low", "Low", "Moderate", "High", "Very High"]

    def risk_index(label: str) -> int:
        """
        Map a canonical label to its index in the risk scale.
        Unknown labels return -1 so we can treat them as invalid.
        """
        try:
            return risk_scale.index(label)
        except ValueError:
            return -1

    def is_in_scope_status(status_text: str) -> bool:
        """
        Only 'Ongoing' and 'Risk Accepted' POA&Ms are in scope for this test.
        """
        return status_text in {"Ongoing", "Risk Accepted"}

    # ------------------------------------------------------------------
    # 1) Load POA&Ms
    # ------------------------------------------------------------------
    poam_rows = _get_poams_from_context(ctx)

    # ------------------------------------------------------------------
    # 2) First pass — find the highest residual risk among in-scope rows
    # ------------------------------------------------------------------
    highest_residual_label = "Very Low"
    highest_residual_idx = risk_index(highest_residual_label)

    for row in poam_rows:
        status_text = str(ci_get(row, "status", "") or "").strip()
        if not is_in_scope_status(status_text):
            continue

        residual = normalize_risk_label(ci_get(row, "residualRiskLevel"))
        residual_idx = risk_index(residual)

        # Track the highest one we actually saw
        if residual_idx > highest_residual_idx:
            highest_residual_label = residual
            highest_residual_idx = residual_idx

    # ------------------------------------------------------------------
    # 3) Second pass — validate each in-scope POA&M against that high-water mark
    # ------------------------------------------------------------------
    offenders: list[str] = []

    for row in poam_rows:
        status_text = str(ci_get(row, "status", "") or "").strip()
        if not is_in_scope_status(status_text):
            continue

        # Try several ID-ish fields; eMASS is inconsistent
        poam_id = (
            ci_get(row, "poamId")
            or ci_get(row, "displayPoamId")
            or ci_get(row, "POA&M ID")
            or "<unknown POA&M ID>"
        )

        severity = normalize_risk_label(ci_get(row, "severity"))
        residual = normalize_risk_label(ci_get(row, "residualRiskLevel"))

        # (1) Severity must exist
        if not severity:
            offenders.append(
                f"{poam_id} (Severity: NULL, Residual Risk: {residual or 'NULL'})"
            )
            continue

        # (2) Severity must equal residual
        if severity != residual:
            offenders.append(
                f"{poam_id} (Severity: {severity}, Residual Risk: {residual or 'NULL'})"
            )
            continue

        # (3) Severity cannot be lower than the highest residual we saw
        sev_idx = risk_index(severity)
        if sev_idx == -1 or highest_residual_idx == -1:
            # unknown label(s) -> bad data
            offenders.append(
                f"{poam_id} (Unrecognized risk label(s): Severity='{severity}', HighestResidual='{highest_residual_label}')"
            )
            continue

        if sev_idx < highest_residual_idx:
            offenders.append(
                f"{poam_id} (Severity too low: {severity}; expected ≥ {highest_residual_label})"
            )

    # ------------------------------------------------------------------
    # 4) Emit TestResult
    # ------------------------------------------------------------------
    if offenders:
        tr = TestResult(
            test_number=126,
            name=test_name,
            result=Result.FAIL,
            message="Incorrect severity levels for POA&Ms: " + ", ".join(offenders),
        )
        status.add(tr)
        return tr

    tr = TestResult(
        test_number=126,
        name=test_name,
        result=Result.PASS,
        message="All POA&Ms follow NETCOM Risk Analysis Severity guidance.",
    )
    status.add(tr)
    return tr


def test_127(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 127 — 'Relevance of Threat' matches NETCOM Risk Analysis guidance
    for POA&M records whose status is 'Ongoing' or 'Risk Accepted'.

    This is a direct, defensive port of the original PowerShell you shared.
    It enforces three rules on in-scope POA&Ms:

    1. Presence rule (→ CONCERN if no hard FAILs):
       - If `relevanceOfThreat` is blank/missing, we can't fully validate it,
         so we flag that POA&M for manual review.

    2. Allowed-label rule (→ FAIL):
       - If `relevanceOfThreat` is present but *not* in the canonical NETCOM set
         ["Very Low", "Low", "Moderate", "High", "Very High"], we fail.

    3. High-water-mark rule (→ FAIL):
       - The relevance must NOT be *lower* than either the POA&M's severity
         or impact (after normalization). This mirrors
         `IndexOf(relevance) -lt Max(IndexOf(severity), IndexOf(impact)))`
         from  PowerShell.

    Data source preference (to avoid "raw" if we can help it):
      1. ctx.system_poam_dashboard.data     ←  modeled, structured path
      2. ctx.fixtures.poam_dashboard.data   ← older/synthetic fixtures
      3. ctx.raw_payloads.system_poam_details  ← last resort

    If we truly have no POA&M data, we return PASS ("nothing to validate").
    """

    test_name = "Test 127: 'Relevance of Threat' matches NETCOM Risk Analysis guidance"

    # ---------------------------------------------------------------------
    # Canonical NETCOM risk order — must stay in sync with Test 126
    # ---------------------------------------------------------------------
    RISK_SCALE = ["Very Low", "Low", "Moderate", "High", "Very High"]
    IN_SCOPE_STATUSES = {"Ongoing", "Risk Accepted"}

    # ---------------------------------------------------------------------
    # Local helpers (kept inside so the test is drop-in / self-contained)
    # ---------------------------------------------------------------------
    def _risk_index(label: str) -> int:
        """Map a canonical label to its index; unknowns → -1."""
        try:
            return RISK_SCALE.index(label)
        except ValueError:
            return -1

    def _normalize_risk_label(value: object) -> str:
        """
        Normalize common spellings to our canonical labels.
        eMASS likes to send 'Medium' sometimes → we treat it as 'Moderate'.
        """
        text = str(value or "").strip()
        mapping = {
            "very low": "Very Low",
            "low": "Low",
            "moderate": "Moderate",
            "medium": "Moderate",
            "high": "High",
            "very high": "Very High",
        }
        return mapping.get(text.lower(), text)

    def _ci_get(row: dict, *keys: str):
        """Case-insensitive getter that tries multiple candidate keys."""
        if not isinstance(row, dict):
            return None
        lowered = {str(k).lower(): v for k, v in row.items()}
        for key in keys:
            val = lowered.get(key.lower())
            if val is not None:
                return val
        return None

    def _load_poams(system_ctx: SystemContext) -> list[dict]:
        """
        Best-effort POA&M loader that prefers modeled data and only
        falls back to raw if we truly don't have structured POA&Ms.
        """
        # 1) Structured dashboard (new world)
        dash = getattr(system_ctx, "system_poam_dashboard", None)
        if dash is not None:
            dash_data = getattr(dash, "data", None)
            if isinstance(dash_data, list):
                return dash_data

        # 2) Fixtures (older/synthetic)
        fixtures = getattr(system_ctx, "fixtures", None)
        if fixtures is not None:
            poam_dash = getattr(fixtures, "poam_dashboard", None)
            if poam_dash is not None:
                fx_data = getattr(poam_dash, "data", None)
                if isinstance(fx_data, list):
                    return fx_data

        # 3) Raw payloads (last resort)
        raw = getattr(system_ctx, "raw_payloads", None)
        if raw is not None:
            raw_data = getattr(raw, "system_poam_details", None)
            if isinstance(raw_data, list):
                return raw_data

        # Nothing found
        return []

    # ---------------------------------------------------------------------
    # 1) Get POA&Ms
    # ---------------------------------------------------------------------
    poam_rows = _load_poams(ctx)

    # No POA&Ms at all → PASS (matches  "empty package" behavior)
    if not poam_rows:
        tr = TestResult(
            test_number=127,
            name=test_name,
            result=Result.PASS,
            message="No POA&M entries to validate.",
        )
        status.add(tr)
        return tr

    # ---------------------------------------------------------------------
    # 2) Walk rows and apply the 3 rules
    # ---------------------------------------------------------------------
    invalid_poams: list[str] = []  # hard FAILs
    concern_poams: list[str] = []  # missing relevance -> CONCERN if no FAILs

    for row in poam_rows:
        # Filter to only Ongoing / Risk Accepted
        status_text = str(
            _ci_get(row, "status", "poamItemStatus", "poam_item_status") or ""
        ).strip()
        if status_text not in IN_SCOPE_STATUSES:
            continue

        # Try a bunch of ID-ish fields so we always have something to print
        poam_id = (
            _ci_get(
                row,
                "poamId",
                "displayPoamId",
                "displaypoamId",
                "POA&M ID",
                "id",
                "condition_id",
            )
            or "<unknown POA&M ID>"
        )

        # Pull fields (case-insensitive)
        relevance_raw = _ci_get(
            row,
            "relevanceOfThreat",
            "relevance_of_threat",
            "relevanceofthreat",
        )
        severity_raw = _ci_get(row, "severity", "raw_severity")
        impact_raw = _ci_get(row, "impact", "impact_description")

        # Normalize
        relevance = _normalize_risk_label(relevance_raw)
        severity = _normalize_risk_label(severity_raw)
        impact = _normalize_risk_label(impact_raw)

        # 2.1) Presence rule → CONCERN if missing
        if not relevance:
            concern_poams.append(poam_id)
            continue

        # 2.2) Allowed-label rule → FAIL if relevance not in canonical list
        relevance_idx = _risk_index(relevance)
        if relevance_idx == -1:
            invalid_poams.append(
                f"{poam_id} (Relevance of Threat: '{relevance}')"
            )
            continue

        # 2.3) High-water-mark rule → relevance >= max(severity, impact)
        severity_idx = _risk_index(severity)
        impact_idx = _risk_index(impact)
        expected_floor = max(severity_idx, impact_idx)
        # If both severity/impact are unknown, expected_floor = -1 -> won't fail.
        if relevance_idx < expected_floor:
            invalid_poams.append(
                (
                    f"{poam_id} (Relevance too low: {relevance}; "
                    f"expected ≥ {severity or 'N/A'} or {impact or 'N/A'})"
                )
            )

    # ---------------------------------------------------------------------
    # 3) Emit final result (FAIL > CONCERN > PASS)
    # ---------------------------------------------------------------------
    if invalid_poams:
        # Hard failure, but we can still surface "needs manual review" ones
        msg = (
            "Incorrect 'Relevance of Threat' values: " + ", ".join(invalid_poams)
        )
        if concern_poams:
            msg += (
                ". Missing values (manual review required): "
                + ", ".join(concern_poams)
            )
        tr = TestResult(
            test_number=127,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        return tr

    if concern_poams:
        tr = TestResult(
            test_number=127,
            name=test_name,
            result=Result.CONCERN,
            message=(
                "Some POA&Ms have missing 'Relevance of Threat' values "
                "(manual verification required): " + ", ".join(concern_poams)
            ),
        )
        status.add(tr)
        return tr

    tr = TestResult(
        test_number=127,
        name=test_name,
        result=Result.PASS,
        message="All applicable POA&Ms follow NETCOM 'Relevance of Threat' guidance.",
    )
    status.add(tr)
    return tr


def test_128(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 128 — 'Likelihood' matches NETCOM Risk Analysis guidance
    for POA&Ms with status 'Ongoing' or 'Risk Accepted'.

    This is a defensive, self-contained port of the PowerShell you shared.
    It enforces three rules:

    1. Presence rule (→ CONCERN if no hard FAILs):
       - If `likelihood` is missing/blank on an in-scope POA&M, we flag it for
         manual review but do not fail the entire test if there are no hard failures.

    2. Allowed-label rule (→ FAIL):
       - If `likelihood` is present but not in the canonical ordered NETCOM set
         ["Very Low", "Low", "Moderate", "High", "Very High"]
         (with "Medium" normalized to "Moderate"), we FAIL.

    3. High-water-mark rule (→ FAIL):
       - likelihood must not be *lower* than either `relevanceOfThreat`
         (or `relevance_of_threat`) or `impact`, after normalization.
         This matches the PS line:
            IndexOf(likelihood) -lt Max(IndexOf(relevance), IndexOf(impact))
    """

    test_name = (
        "Test 128: 'Likelihood' matches NETCOM Risk Analysis guidance for "
        "'Ongoing'/'Risk Accepted' POA&Ms"
    )

    # -------------------------------------------------------------------------
    # Canonical scale — keep in sync with 126 and 127
    # -------------------------------------------------------------------------
    RISK_SCALE = ["Very Low", "Low", "Moderate", "High", "Very High"]
    IN_SCOPE_STATUSES = {"Ongoing", "Risk Accepted"}

    # -------------------------------------------------------------------------
    # Local helpers (inside so the test is self-contained)
    # -------------------------------------------------------------------------
    def _risk_index(label: str) -> int:
        """Return index in the canonical risk scale; unknown → -1."""
        try:
            return RISK_SCALE.index(label)
        except ValueError:
            return -1

    def _normalize_label(raw: object) -> str:
        """
        Normalize common eMASS variants to our canonical labels.
        e.g. 'medium' → 'Moderate'.
        """
        s = str(raw or "").strip()
        mapping = {
            "very low": "Very Low",
            "low": "Low",
            "moderate": "Moderate",
            "medium": "Moderate",
            "high": "High",
            "very high": "Very High",
        }
        return mapping.get(s.lower(), s)

    def _ci_get(row: dict, *keys: str):
        """Case-insensitive getter that tries multiple key spellings."""
        if not isinstance(row, dict):
            return None
        lowered = {str(k).lower(): v for k, v in row.items()}
        for key in keys:
            val = lowered.get(key.lower())
            if val is not None:
                return val
        return None

    def _load_poams(context: SystemContext) -> list[dict]:
        """
        Best-effort POA&M loader that PREFERs modeled data and only
        falls back to raw when nothing else is present.
        Order:
          1. ctx.system_poam_dashboard.data
          2. ctx.fixtures.poam_dashboard.data
          3. ctx.raw_payloads.system_poam_details
        """
        # 1) structured dashboard
        dash = getattr(context, "system_poam_dashboard", None)
        if dash is not None:
            dash_data = getattr(dash, "data", None)
            if isinstance(dash_data, list):
                return dash_data

        # 2) fixtures (older / synthetic)
        fixtures = getattr(context, "fixtures", None)
        if fixtures is not None:
            fx_poam_dash = getattr(fixtures, "poam_dashboard", None)
            if fx_poam_dash is not None:
                fx_data = getattr(fx_poam_dash, "data", None)
                if isinstance(fx_data, list):
                    return fx_data

        # 3) raw payloads (last resort)
        raw = getattr(context, "raw_payloads", None)
        if raw is not None:
            raw_poams = getattr(raw, "system_poam_details", None)
            if isinstance(raw_poams, list):
                return raw_poams

        return []

    # -------------------------------------------------------------------------
    # 1) Gather POA&M rows
    # -------------------------------------------------------------------------
    poam_rows = _load_poams(ctx)

    # No POA&Ms at all → PASS (don't block the checklist)
    if not poam_rows:
        tr = TestResult(
            test_number=128,
            name=test_name,
            result=Result.PASS,
            message="No POA&M entries to validate.",
        )
        status.add(tr)
        return tr

    # -------------------------------------------------------------------------
    # 2) Walk in-scope rows and evaluate
    # -------------------------------------------------------------------------
    invalid_poams: list[str] = []  # → FAIL
    concern_poams: list[str] = []  # → CONCERN (only if no FAILs)

    for row in poam_rows:
        # scope check
        status_text = str(
            _ci_get(row, "status", "poamItemStatus", "poam_item_status") or ""
        ).strip()
        if status_text not in IN_SCOPE_STATUSES:
            continue

        # get something user-searchable
        poam_id = (
            _ci_get(
                row,
                "poamId",
                "displayPoamId",
                "displaypoamId",
                "POA&M ID",
                "id",
                "condition_id",
            )
            or "<unknown POA&M ID>"
        )

        # pull/normalize fields
        likelihood_raw = _ci_get(row, "likelihood")
        relevance_raw = _ci_get(
            row,
            "relevanceOfThreat",
            "relevance_of_threat",
            "relevanceofthreat",
        )
        impact_raw = _ci_get(row, "impact", "impact_description")

        likelihood = _normalize_label(likelihood_raw)
        relevance = _normalize_label(relevance_raw)
        impact = _normalize_label(impact_raw)

        # 2a) presence rule
        if not likelihood:
            concern_poams.append(poam_id)
            continue

        # 2b) allowed-label rule
        likelihood_idx = _risk_index(likelihood)
        if likelihood_idx == -1:
            invalid_poams.append(f"{poam_id} (Likelihood: '{likelihood}')")
            continue

        # 2c) high-water-mark rule → likelihood >= max(relevance, impact)
        relevance_idx = _risk_index(relevance)
        impact_idx = _risk_index(impact)
        expected_floor = max(relevance_idx, impact_idx)
        # if both relevance and impact are unknown, floor = -1 → tolerated
        if likelihood_idx < expected_floor:
            invalid_poams.append(
                f"{poam_id} (Likelihood too low: {likelihood}; expected ≥ {relevance or 'N/A'} or {impact or 'N/A'})"
            )

    # -------------------------------------------------------------------------
    # 3) Emit final result — FAIL > CONCERN > PASS
    # -------------------------------------------------------------------------
    if invalid_poams:
        message = (
            "Some POA&Ms have incorrect 'Likelihood' values: "
            + ", ".join(invalid_poams)
        )
        if concern_poams:
            message += (
                ". Missing values (manual review): " + ", ".join(concern_poams)
            )
        tr = TestResult(
            test_number=128,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(tr)
        return tr

    if concern_poams:
        tr = TestResult(
            test_number=128,
            name=test_name,
            result=Result.CONCERN,
            message=(
                "Some POA&Ms have missing 'Likelihood' values (manual verification required): "
                + ", ".join(concern_poams)
            ),
        )
        status.add(tr)
        return tr

    tr = TestResult(
        test_number=128,
        name=test_name,
        result=Result.PASS,
        message="All applicable POA&Ms follow NETCOM 'Likelihood' guidance.",
    )
    status.add(tr)
    return tr


def test_129(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 129 — POA&M 'Impact' matches the system's Impact Level
    for POA&Ms with status 'Ongoing' or 'Risk Accepted'.

    This is a defensive port of the PowerShell logic you shared. It does:
      1. Resolve the system's impact level from several plausible places.
      2. If we *can't* determine system impact → CONCERN (same as PS).
      3. Load POA&M rows from the "new world" context (dashboard → fixtures → raw).
      4. For every in-scope POA&M (Ongoing / Risk Accepted):
            - skip if POA&M impact is blank/"-"
            - otherwise normalize and compare to system impact
            - mismatch → FAIL and collect POA&M IDs
      5. Emit FAIL > CONCERN > PASS, using keyword args for TestResult
         so Pydantic doesn't choke.
    """

    test_name = (
        "Test 129: 'Impact' matches System 'Impact Level' for 'Ongoing'/'Risk Accepted' POA&Ms"
    )
    IN_SCOPE_STATUSES = {"Ongoing", "Risk Accepted"}

    # -------------------------------------------------------------------------
    # Helpers (kept inside so the test is self-contained)
    # -------------------------------------------------------------------------
    def normalize_impact(raw: object) -> str:
        """
        Normalize impact labels to canonical values.
        Accepts:
          - "", None, "-" → ""
          - "medium" → "Moderate"
          - case-insensitive for low/moderate/high
        """
        s = str(raw or "").strip()
        if not s or s == "-":
            return ""
        mapping = {
            "low": "Low",
            "moderate": "Moderate",
            "medium": "Moderate",
            "high": "High",
        }
        return mapping.get(s.lower(), s)

    def ci_get(row: dict, *keys: str):
        """Case-insensitive dict getter that tries multiple key names."""
        if not isinstance(row, dict):
            return None
        lowered = {str(k).lower(): v for k, v in row.items()}
        for key in keys:
            val = lowered.get(key.lower())
            if val is not None:
                return val
        return None

    def resolve_system_impact(c: SystemContext) -> str:
        """
        Try to find the system's impact in the same spirit as the PS script:
        take the first non-empty impact-like value we can find, in priority order.
        """
        # 1) top-level (most convenient)
        top = normalize_impact(getattr(c, "impact", None))
        if top:
            return top

        # 2) system_details_dashboard
        sdd = getattr(c, "system_details_dashboard", None)
        if sdd is not None:
            sdd_impact = normalize_impact(getattr(sdd, "impact", None))
            if sdd_impact:
                return sdd_impact

        # 3) system_info
        sinfo = getattr(c, "system_info", None)
        if sinfo is not None:
            si_impact = normalize_impact(getattr(sinfo, "impact", None))
            if si_impact:
                return si_impact

        # 4) raw_payloads.system_status_details (common PS-style source)
        raw = getattr(c, "raw_payloads", None)
        if raw is not None:
            ssd = getattr(raw, "system_status_details", None)
            if isinstance(ssd, list):
                for row in ssd:
                    row_impact = normalize_impact(ci_get(row, "impact"))
                    if row_impact:
                        return row_impact

        # 5) fixtures.system_details_dashboard
        fixtures = getattr(c, "fixtures", None)
        if fixtures is not None:
            f_sdd = getattr(fixtures, "system_details_dashboard", None)
            if f_sdd is not None:
                f_impact = normalize_impact(getattr(f_sdd, "impact", None))
                if f_impact:
                    return f_impact

        # nothing usable
        return ""

    def load_poams(c: SystemContext) -> list[dict]:
        """
        Best-effort POA&M loader that PREFERS structured/modelled data.
        Note:  SystemContext doesn't actually define a top-level
        `system_poam_details`, so we START with the dashboard.
        Order:
          1. ctx.system_poam_dashboard.data
          2. ctx.fixtures.poam_dashboard.data
          3. ctx.raw_payloads.system_poam_details
        """
        # 1) dashboard
        spd = getattr(c, "system_poam_dashboard", None)
        if spd is not None and isinstance(getattr(spd, "data", None), list):
            return list(spd.data)

        # 2) fixtures
        fixtures = getattr(c, "fixtures", None)
        if fixtures is not None:
            f_poam_dash = getattr(fixtures, "poam_dashboard", None)
            if f_poam_dash is not None and isinstance(getattr(f_poam_dash, "data", None), list):
                return list(f_poam_dash.data)

        # 3) raw payloads
        raw = getattr(c, "raw_payloads", None)
        if raw is not None and isinstance(getattr(raw, "system_poam_details", None), list):
            return list(raw.system_poam_details)

        return []

    # -------------------------------------------------------------------------
    # 1) Resolve the system impact FIRST (like the PS did)
    # -------------------------------------------------------------------------
    system_impact = resolve_system_impact(ctx)

    if not system_impact:
        # PS: if no system impact, we return CONCERN even if POA&M data exists
        tr = TestResult(
            test_number=129,
            name=test_name,
            result=Result.CONCERN,
            message="System Impact Level is missing or undefined. Unable to verify POA&M impact consistency.",
        )
        status.add(tr)
        return tr

    # -------------------------------------------------------------------------
    # 2) Load POA&M rows
    # -------------------------------------------------------------------------
    poam_rows = load_poams(ctx)

    # If there are no POA&Ms at all, with a known system impact → PASS
    if not poam_rows:
        tr = TestResult(
            test_number=129,
            name=test_name,
            result=Result.PASS,
            message="No POA&M entries to validate.",
        )
        status.add(tr)
        return tr

    # -------------------------------------------------------------------------
    # 3) Evaluate in-scope POA&Ms
    # -------------------------------------------------------------------------
    mismatched_poams: list[str] = []

    for row in poam_rows:
        status_text = str(
            ci_get(row, "status", "poamItemStatus", "poam_item_status") or ""
        ).strip()
        if status_text not in IN_SCOPE_STATUSES:
            continue  # not Ongoing/Risk Accepted → ignore

        # identifier for human debugging
        poam_id = (
            ci_get(
                row,
                "poamId",
                "displayPoamId",
                "displaypoamId",
                "POA&M ID",
                "id",
                "condition_id",
            )
            or "<unknown POA&M ID>"
        )

        poam_impact = normalize_impact(ci_get(row, "impact", "impact_description"))

        # PS skipped POA&Ms with no impact
        if not poam_impact:
            continue

        if poam_impact != system_impact:
            mismatched_poams.append(
                f"{poam_id} (System: {system_impact}, Found: {poam_impact})"
            )

    # -------------------------------------------------------------------------
    # 4) Emit final result
    # -------------------------------------------------------------------------
    if mismatched_poams:
        tr = TestResult(
            test_number=129,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Some 'Ongoing'/'Risk Accepted' POA&Ms have an impact that does not "
                "match the system's impact level. Affected POA&Ms: "
                + ", ".join(mismatched_poams)
            ),
        )
        status.add(tr)
        return tr

    tr = TestResult(
        test_number=129,
        name=test_name,
        result=Result.PASS,
        message="All applicable POA&Ms have an impact level matching the system's impact level.",
    )
    status.add(tr)
    return tr

def test_130(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 130 — Residual Risk values match recommended values (NIST 800-30 Rev. 1)

    For every POA&M we can find, compute the expected residual risk from a fixed
    NIST-style matrix (likelihood × impact → residual). If the actual residual
    risk differs, the record must have a justification (impactDescription /
    recommendations / mitigations / etc.). Otherwise → FAIL.
    """
    test_name = "Test 130: Residual Risk aligns with NIST 800-30 Rev. 1 Table I-2"

    # -------------------------------------------------------------------------
    # helpers
    # -------------------------------------------------------------------------
    def ci_get(d: dict, *keys: str):
        """Case-insensitive, multi-key dict getter."""
        if not isinstance(d, dict):
            return None
        lower = {str(k).lower(): v for k, v in d.items()}
        for key in keys:
            val = lower.get(key.lower())
            if val is not None:
                return val
        return None

    def normalize_level(v: object) -> str:
        """Map common variants to canonical NIST-ish labels."""
        s = str(v or "").strip()
        if not s or s == "-":
            return ""
        mapping = {
            "very low": "Very Low",
            "low": "Low",
            "moderate": "Moderate",
            "medium": "Moderate",  # treat Medium == Moderate
            "high": "High",
            "very high": "Very High",
        }
        return mapping.get(s.lower(), s)

    def load_poams(c: SystemContext) -> list[dict]:
        """
        Pull POA&M rows from any of the supported “new world” surfaces.
        Prefer dashboard → fixtures → raw, since ctx rarely has a top-level
        system_poam_details.
        """
        # 1) dashboard
        dash = getattr(c, "system_poam_dashboard", None)
        if dash is not None and getattr(dash, "data", None):
            return list(dash.data)

        # 2) fixtures
        fixtures = getattr(c, "fixtures", None)
        if fixtures is not None:
            f_dash = getattr(fixtures, "poam_dashboard", None)
            if f_dash is not None and getattr(f_dash, "data", None):
                return list(f_dash.data)

        # 3) raw payloads
        raw = getattr(c, "raw_payloads", None)
        if raw is not None and getattr(raw, "system_poam_details", None):
            return list(raw.system_poam_details)

        # 4) legacy / flat (if it ever appears)
        poams = getattr(c, "system_poam_details", None)
        if poams:
            return list(poams)

        return []

    # -------------------------------------------------------------------------
    # NIST-style matrix (Likelihood x Impact -> Residual)
    # -------------------------------------------------------------------------
    risk_matrix: dict[str, dict[str, str]] = {
        "Very High": {
            "Very Low": "Very Low",
            "Low": "Low",
            "Moderate": "Moderate",
            "High": "High",
            "Very High": "Very High",
        },
        "High": {
            "Very Low": "Very Low",
            "Low": "Low",
            "Moderate": "Moderate",
            "High": "Moderate",
            "Very High": "High",
        },
        "Moderate": {
            "Very Low": "Very Low",
            "Low": "Low",
            "Moderate": "Moderate",
            "High": "Moderate",
            "Very High": "Moderate",
        },
        "Low": {
            "Very Low": "Very Low",
            "Low": "Very Low",
            "Moderate": "Low",
            "High": "Low",
            "Very High": "Moderate",
        },
        "Very Low": {
            "Very Low": "Very Low",
            "Low": "Very Low",
            "Moderate": "Very Low",
            "High": "Low",
            "Very High": "Low",
        },
    }

    poam_rows = load_poams(ctx)

    # No POA&Ms → PASS (same semantics as 128/129)
    if not poam_rows:
        tr = TestResult(
            test_number=130,
            name=test_name,
            result=Result.PASS,
            message="No POA&M entries to validate.",
        )
        status.add(tr)
        return tr

    offenders: list[str] = []

    # -------------------------------------------------------------------------
    # Iterate and validate
    # -------------------------------------------------------------------------
    for row in poam_rows:
        likelihood = normalize_level(
            ci_get(row, "likelihood", "recommended_likelihood")
        )
        impact = normalize_level(ci_get(row, "impact"))
        residual = normalize_level(
            ci_get(
                row,
                "residualRiskLevel",
                "residual_risk",
                "recommended_residual_risk",
                "residual_risk_level",
            )
        )

        # justification-ish fields
        justification = str(
            ci_get(
                row,
                "impactDescription",
                "impact_description",
                "mitigations",
                "recommendations",
            )
            or ""
        ).strip()

        # PS behavior: skip incomplete rows
        if not likelihood or not impact or not residual:
            continue

        expected = risk_matrix.get(likelihood, {}).get(impact)
        if not expected:
            # unknown combo → be lenient (don't fail the whole test)
            continue

        if residual != expected and not justification:
            poam_id = (
                ci_get(
                    row,
                    "poamId",
                    "displayPoamId",
                    "displaypoamId",
                    "POA&M ID",
                    "id",
                    "condition_id",
                )
                or "<unknown POA&M ID>"
            )
            offenders.append(f"{poam_id} (Expected: {expected}, Found: {residual})")

    # -------------------------------------------------------------------------
    # Emit result
    # -------------------------------------------------------------------------
    if offenders:
        tr = TestResult(
            test_number=130,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Residual risk deviates from recommended values without justification. "
                "Affected POA&Ms: " + ", ".join(offenders)
            ),
        )
        status.add(tr)
        return tr

    tr = TestResult(
        test_number=130,
        name=test_name,
        result=Result.PASS,
        message="All POA&Ms have correct residual risk levels or documented justification for deviations.",
    )
    status.add(tr)
    return tr

def test_132(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 132 — POA&M 'Ongoing' records have realistic, relevant milestones with sensible dates.
    PS parity: start PASS, downgrade to FAIL for bad dates, and then
    (yes) can downgrade to CONCERN if milestone patterns are bad.
    """

    test_name = (
        "Test 132: Ongoing POA&Ms list key events/steps with realistic completion dates"
    )

    # ------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------
    def ci_get(d: dict, *keys: str, default=None):
        """Case-insensitive getter that can try multiple keys."""
        if not isinstance(d, dict):
            return default
        lower = {str(k).lower(): v for k, v in d.items()}
        for k in keys:
            v = lower.get(str(k).lower())
            if v is not None:
                return v
        return default

    def to_epoch_seconds(v) -> float | None:
        """
        eMASS often gives us epoch seconds (int) or a string of that.
        If it's missing / "-", return None.
        """
        if v is None or v == "" or v == "-":
            return None
        try:
            return float(v)
        except Exception:
            return None

    def load_poams(c: SystemContext) -> list[dict]:
        """
        New-world tolerant POA&M loader.
        Order:
          1) ctx.system_poam_dashboard.data
          2) ctx.fixtures.poam_dashboard.data
          3) ctx.raw_payloads.system_poam_details
          4) (optional) ctx.system_poam_details IF it ever exists
        """
        # 1) dashboard
        dash = getattr(c, "system_poam_dashboard", None)
        if dash is not None and getattr(dash, "data", None):
            return list(dash.data)

        # 2) fixtures
        fixtures = getattr(c, "fixtures", None)
        if fixtures is not None:
            f_dash = getattr(fixtures, "poam_dashboard", None)
            if f_dash is not None and getattr(f_dash, "data", None):
                return list(f_dash.data)

        # 3) raw payloads (you actually have this in  model)
        raw = getattr(c, "raw_payloads", None)
        if raw is not None and getattr(raw, "system_poam_details", None):
            return list(raw.system_poam_details)

        # 4) legacy / in case you later add it
        if hasattr(c, "system_poam_details"):
            legacy = getattr(c, "system_poam_details") or []
            return list(legacy)

        return []

    # ------------------------------------------------------------
    # constants (same as PS)
    # ------------------------------------------------------------
    ONE_YEAR_SECONDS = 365 * 24 * 60 * 60
    CCSD_GRACE_SECONDS = 180 * 24 * 60 * 60

    good_words_regex = re.compile(
        r"(test|implement|review|schedule|ccb|deployment|mitigation|patch|upgrade|monthly|weekly|biweekly|develop|patching|replace)",
        flags=re.IGNORECASE,
    )
    final_milestone_regex = re.compile(r"(contractual|final milestone)", flags=re.IGNORECASE)

    poams = load_poams(ctx)

    # no POA&Ms → PASS
    if not poams:
        tr = TestResult(
            test_number=132,
            name=test_name,
            result=Result.PASS,
            message="PASS: No POA&M entries to evaluate.",
        )
        status.add(tr)
        return tr

    # PS style: start PASS
    overall_result: Result = Result.PASS
    offenders: list[str] = []

    for row in poams:
        # skip inherited
        is_inherited = bool(
            ci_get(row, "isInherited", "isinherited", "remote_inheritance_instance", default=False)
        )
        if is_inherited:
            continue

        # status can be `status` (raw) or `poam_item_status` (dashboard)
        status_val = str(
            ci_get(row, "status", "poam_item_status", default="") or ""
        ).strip()
        if status_val.lower() != "ongoing":
            continue

        poam_id = (
            ci_get(row, "poamId", "displayPoamId", "displaypoamId", "POA&M ID", "id", "condition_id")
            or "<unknown POA&M ID>"
        )

        # milestones are usually a list
        milestones = ci_get(row, "milestones", default=[]) or []
        if not isinstance(milestones, list):
            milestones = []

        unique_dates: dict[float, int] = {}
        has_valid_steps = False
        final_milestone_identified = False
        all_dates_same = True
        final_completion_date: float | None = None

        if milestones:
            for ms in milestones:
                date_val = to_epoch_seconds(
                    ci_get(ms, "scheduledCompletionDate", "scheduled_completion_date")
                )
                desc = str(ci_get(ms, "description", default="") or "")

                if date_val is not None:
                    # track unique dates
                    if date_val not in unique_dates:
                        unique_dates[date_val] = 1
                    else:
                        unique_dates[date_val] += 1

                    # "good" milestone content
                    if good_words_regex.search(desc):
                        has_valid_steps = True

                    # latest date
                    if final_completion_date is None or date_val > final_completion_date:
                        final_completion_date = date_val

            # are dates all the same?
            if len(unique_dates) > 1:
                all_dates_same = False

            # final milestone identified?
            last_desc = str(ci_get(milestones[-1], "description", default="") or "")
            if final_milestone_regex.search(last_desc):
                final_milestone_identified = True
        else:
            # no milestones at all → will trigger CONCERN logic below
            all_dates_same = True
            has_valid_steps = False
            final_milestone_identified = False

        # row-level dates
        created_date = to_epoch_seconds(
            ci_get(row, "createdDate", "created_date")
        )
        ccsd_expiration = to_epoch_seconds(
            ci_get(row, "ccsdExpirationDate", "ccsd_expiration_date")
        )

        # ------------------------------------------------------------
        # FAIL checks (done BEFORE concern, matching PS order)
        # ------------------------------------------------------------
        if final_completion_date is not None and created_date is not None:
            if final_completion_date - created_date > ONE_YEAR_SECONDS:
                overall_result = Result.FAIL
                offenders.append(f"{poam_id} (Over 1 year)")

        if final_completion_date is not None and ccsd_expiration is not None:
            ccsd_deadline = ccsd_expiration + CCSD_GRACE_SECONDS
            if final_completion_date > ccsd_deadline:
                overall_result = Result.FAIL
                offenders.append(f"{poam_id} (CCSD Exceeded)")

        # ------------------------------------------------------------
        # CONCERN checks — PS can override FAIL → CONCERN
        # ------------------------------------------------------------
        if all_dates_same or (not has_valid_steps) or (not final_milestone_identified):
            overall_result = Result.CONCERN
            offenders.append(f"{poam_id} (Bad Milestones)")

    # ------------------------------------------------------------
    # finalize
    # ------------------------------------------------------------
    if overall_result == Result.PASS:
        tr = TestResult(
            test_number=132,
            name=test_name,
            result=Result.PASS,
            message="PASS: All 'Ongoing' POA&Ms have realistic milestones and valid completion dates.",
        )
    elif overall_result == Result.FAIL:
        tr = TestResult(
            test_number=132,
            name=test_name,
            result=Result.FAIL,
            message=(
                "FAIL: Some 'Ongoing' POA&Ms have unrealistic completion dates. Affected: "
                + ", ".join(offenders)
                if offenders
                else "FAIL: Some 'Ongoing' POA&Ms have unrealistic completion dates."
            ),
        )
    else:  # CONCERN
        tr = TestResult(
            test_number=132,
            name=test_name,
            result=Result.CONCERN,
            message=(
                "CONCERN: Some 'Ongoing' POA&Ms have unrealistic milestones or completion dates. "
                "Affected: " + ", ".join(offenders)
                if offenders
                else "CONCERN: Some 'Ongoing' POA&Ms have unrealistic milestones or completion dates."
            ),
        )

    status.add(tr)
    return tr

def test_133(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 133 — Ongoing POA&Ms with past-due milestones must have new future milestones and an explanation.

    Overview
    --------
    This test enforces forward momentum on open POA&M items. If an *Ongoing* POA&M
    shows a milestone in the past, the record must also show:
      1. at least one milestone scheduled in the future, and
      2. an explanation / rationale for the miss (usually in `comments`).

    Data sources (in priority order)
    --------------------------------
    1. ctx.system_poam_dashboard.data          ← current, structured
    2. ctx.fixtures.poam_dashboard.data        ← fixture-backed
    3. ctx.raw_payloads.system_poam_details    ← raw eMASS payload fallback
    4. ctx.system_poam_details (if ever present on ctx) ← legacy/back-compat

    Behavior
    --------
    - PASS if there are no POA&Ms OR every Ongoing POA&M that has a past milestone
      also has a future milestone AND an explanation.
    - FAIL otherwise.

    Logging
    -------
    Emits docker-friendly, T-numbered lines like:
        [T133] FAIL — Ongoing POA&Ms missing new milestones and/or explanations: <ids>
        [T133] PASS — All Ongoing POA&Ms with past milestones have follow-up milestones and explanations.
        [T133] INFO — No POA&M data available to evaluate.

    This matches the style:
        [T104] CONCERN — STIG/SRG version parity with DISA cannot be verified via available data.
        [T110] CONCERN — Resources↔HW/SW linkage not available via API.
        ...
    """
    test_name = (
        "Test 133: Ongoing POA&Ms with past milestones must have new future milestones and explanations"
    )

    # ---------------------------------------------------------------------
    # nested helpers — self-contained
    # ---------------------------------------------------------------------
    def load_poams_from_context(context: SystemContext) -> List[Dict[str, Any]]:
        """
        Best-effort loader for POA&M records from the various places we know the
        data can live in our SystemContext.

        Priority:
            1. context.system_poam_dashboard.data
            2. context.fixtures.poam_dashboard.data
            3. context.raw_payloads.system_poam_details
            4. context.system_poam_details  (legacy / defensive)
        """
        # 1) primary structured dashboard
        dashboard = getattr(context, "system_poam_dashboard", None)
        if dashboard is not None and getattr(dashboard, "data", None):
            return list(dashboard.data)

        # 2) fixture-backed structured view
        fixtures = getattr(context, "fixtures", None)
        if fixtures is not None:
            fx_dash = getattr(fixtures, "poam_dashboard", None)
            if fx_dash is not None and getattr(fx_dash, "data", None):
                return list(fx_dash.data)

        # 3) raw payloads (last-ish resort)
        raw_payloads = getattr(context, "raw_payloads", None)
        if raw_payloads is not None and getattr(raw_payloads, "system_poam_details", None):
            return list(raw_payloads.system_poam_details)

        # 4) legacy attr (only if present)
        if hasattr(context, "system_poam_details"):
            maybe = getattr(context, "system_poam_details") or []
            if isinstance(maybe, list):
                return list(maybe)

        return []

    def ci_get(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        """
        Case-insensitive getter. First matching key wins.
        """
        if not isinstance(d, dict):
            return default
        lower_map = {str(k).lower(): v for k, v in d.items()}
        for key in keys:
            val = lower_map.get(str(key).lower())
            if val is not None:
                return val
        return default

    def to_epoch_seconds(value: Any) -> float | None:
        """
        Normalize eMASS-style timestamps that may arrive as strings, ints, '-', or ''.
        """
        if value in (None, "", "-"):
            return None
        try:
            return float(value)
        except Exception:
            return None

    # ---------------------------------------------------------------------
    # actual test logic
    # ---------------------------------------------------------------------
    now_epoch = time.time()
    poam_rows = load_poams_from_context(ctx)

    # If there is literally no POA&M data, we do what the PS script effectively did:
    # mark as PASS but explain why.
    if not poam_rows:
        logger.info("[T133] PASS — No POA&M data available to evaluate.")
        tr = TestResult(
            test_number=133,
            name=test_name,
            result=Result.PASS,
            message="PASS: No POA&M data available to evaluate.",
        )
        status.add(tr)
        return tr

    failing_poam_ids: List[str] = []

    for row in poam_rows:
        # Status can show up as "status" (API/raw) or "poam_item_status" (dashboard)
        status_val = str(
            ci_get(row, "status", "poam_item_status", default="") or ""
        ).strip()

        # We only care about Ongoing entries
        if status_val.lower() != "ongoing":
            continue

        # Normalize POA&M ID — there are several ways to spell this in the data
        poam_id = ci_get(
            row,
            "poamId",
            "displayPoamId",
            "displaypoamId",
            "POA&M ID",
            "id",
            "condition_id",
            default="<unknown POA&M ID>",
        )

        # Milestones can be a true list or can be "dashboardy" single fields
        milestones = ci_get(row, "milestones", default=[])
        if not isinstance(milestones, list):
            milestones = []

        # If no milestones list, try to synthesize one from the dashboard fields
        if not milestones:
            dash_date = ci_get(
                row,
                "milestone_scheduled_completion_date",
                "scheduled_completion_date",
                default=None,
            )
            dash_desc = ci_get(
                row,
                "latest_milestone_description",
                "milestone_description",
                default=None,
            )
            if dash_date is not None or dash_desc is not None:
                milestones = [
                    {
                        "scheduledCompletionDate": dash_date,
                        "description": dash_desc or "",
                    }
                ]

        has_past_ms = False
        has_future_ms = False

        for ms in milestones:
            sched = to_epoch_seconds(
                ci_get(ms, "scheduledCompletionDate", "scheduled_completion_date", default=None)
            )
            if sched is None:
                continue
            if sched < now_epoch:
                has_past_ms = True
            elif sched > now_epoch:
                has_future_ms = True

        # Explanation can be in several places — prefer "comments"
        comments = str(
            ci_get(row, "comments", "poam_item_review_status", default="") or ""
        ).strip()
        has_explanation = bool(comments)

        # Rule core:
        # If we have ANY past milestone → we MUST have both a future milestone AND an explanation.
        if has_past_ms and (not has_future_ms or not has_explanation):
            failing_poam_ids.append(str(poam_id))

    # ---------------------------------------------------------------------
    # finalize
    # ---------------------------------------------------------------------
    if failing_poam_ids:
        logger.warning(
            "[T133] FAIL — Ongoing POA&Ms missing new milestones and/or explanations: %s",
            ", ".join(failing_poam_ids),
        )
        tr = TestResult(
            test_number=133,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Ongoing POA&Ms with past milestones are missing a future milestone and/or an explanation. "
                f"Affected POA&Ms: {', '.join(failing_poam_ids)}"
            ),
        )
        status.add(tr)
        return tr

    logger.info(
        "[T133] PASS — All Ongoing POA&Ms with past milestones have follow-up milestones and explanations."
    )
    tr = TestResult(
        test_number=133,
        name=test_name,
        result=Result.PASS,
        message="All Ongoing POA&Ms with past milestones include future milestones and explanations.",
    )
    status.add(tr)
    return tr


def test_134(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 134 — All expired POA&Ms must have a pending extension.

    Intent
    ------
    A POA&M whose overall scheduled completion date is in the past but that
    does NOT show a pending extension indicates stalled remediation. This test
    finds those and flags them.

    Data sources (priority)
    -----------------------
    1. ctx.system_poam_dashboard.data          ← current, structured
    2. ctx.fixtures.poam_dashboard.data        ← fixture-backed
    3. ctx.raw_payloads.system_poam_details    ← raw eMASS payload
    4. ctx.system_poam_details                 ← legacy/back-compat (if present)

    Logging
    -------
    Emits docker-friendly lines like:
        [T134] PASS — All expired POA&Ms have a pending extension.
        [T134] FAIL — Expired POA&Ms missing pending extensions: 123, 456
        [T134] INFO — No POA&M data available to evaluate.

    Args:
        ctx (SystemContext): Fully-populated system snapshot.
        status (ATOStatus): Aggregator for test results.

    Returns:
        TestResult: PASS if every expired POA&M has a pending extension; otherwise FAIL.
    """

    test_name = "Test 134: All expired POA&Ms are pending an extension"

    # ------------------------------------------------------------------
    # nested helpers — keeps the test self-contained
    # ------------------------------------------------------------------
    def load_poams_from_context(context: SystemContext) -> List[Dict[str, Any]]:
        """
        Best-effort POA&M loader that knows all the places POA&M data can land.

        Priority:
            1. context.system_poam_dashboard.data
            2. context.fixtures.poam_dashboard.data
            3. context.raw_payloads.system_poam_details
            4. context.system_poam_details (legacy, if present)
        """
        # 1) structured dashboard at top-level
        dash = getattr(context, "system_poam_dashboard", None)
        if dash is not None and getattr(dash, "data", None):
            return list(dash.data)

        # 2) fixture-backed structured view
        fixtures = getattr(context, "fixtures", None)
        if fixtures is not None:
            fx_dash = getattr(fixtures, "poam_dashboard", None)
            if fx_dash is not None and getattr(fx_dash, "data", None):
                return list(fx_dash.data)

        # 3) raw payloads — eMASS dump we kept around
        raw_payloads = getattr(context, "raw_payloads", None)
        if raw_payloads is not None and getattr(raw_payloads, "system_poam_details", None):
            return list(raw_payloads.system_poam_details)

        # 4) legacy / defensive
        if hasattr(context, "system_poam_details"):
            maybe = getattr(context, "system_poam_details") or []
            if isinstance(maybe, list):
                return list(maybe)

        return []

    def ci_get(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        """
        Case-insensitive, multi-key dictionary getter.
        First matching key wins.
        """
        if not isinstance(d, dict):
            return default
        lower_map = {str(k).lower(): v for k, v in d.items()}
        for key in keys:
            val = lower_map.get(str(key).lower())
            if val is not None:
                return val
        return default

    def to_epoch_seconds(value: Any) -> float | None:
        """
        Normalize common eMASS timestamp patterns (str/int/'-'/'').
        Returns None if unparseable.
        """
        if value in (None, "", "-"):
            return None
        try:
            return float(value)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # actual test
    # ------------------------------------------------------------------
    now_epoch = time.time()
    poam_rows = load_poams_from_context(ctx)

    # No POA&M data at all → treat as PASS (same spirit as  PS script)
    if not poam_rows:
        logger.info("[T134] INFO — No POA&M data available to evaluate.")
        tr = TestResult(
            test_number=134,
            name=test_name,
            result=Result.PASS,
            message="PASS: No POA&M data available to evaluate.",
        )
        status.add(tr)
        return tr

    expired_missing_extension: List[str] = []

    for row in poam_rows:
        # Scheduled completion can be spelled a few ways depending on source:
        # - scheduledCompletionDate          (raw eMASS)
        # - scheduled_completion_date        (dashboard)
        # - completion_date                  (sometimes used in dashboards)
        sched = to_epoch_seconds(
            ci_get(
                row,
                "scheduledCompletionDate",
                "scheduled_completion_date",
                "completion_date",
                default=None,
            )
        )
        if sched is None:
            continue

        # expired?
        if sched < now_epoch:
            # Pending extension can also be spelled multiple ways:
            # - pendingExtensionDate           (raw)
            # - pending_extension_date         (dashboard)
            pending_ext = to_epoch_seconds(
                ci_get(
                    row,
                    "pendingExtensionDate",
                    "pending_extension_date",
                    "extension_date",  # some exports just have 'extension_date'
                    default=None,
                )
            )
            if pending_ext is None:
                poam_id = ci_get(
                    row,
                    "displayPoamId",
                    "poamId",
                    "id",
                    "condition_id",
                    "POA&M ID",
                    default="<unknown POA&M ID>",
                )
                expired_missing_extension.append(str(poam_id))

    # ------------------------------------------------------------------
    # finalize
    # ------------------------------------------------------------------
    if expired_missing_extension:
        logger.warning(
            "[T134] FAIL — Expired POA&Ms missing pending extensions: %s",
            ", ".join(expired_missing_extension),
        )
        tr = TestResult(
            test_number=134,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Some expired POA&Ms do not have a pending extension: "
                + ", ".join(expired_missing_extension)
            ),
        )
        status.add(tr)
        return tr

    logger.info("[T134] PASS — All expired POA&Ms have a pending extension.")
    tr = TestResult(
        test_number=134,
        name=test_name,
        result=Result.PASS,
        message="All expired POA&Ms have a pending extension.",
    )
    status.add(tr)
    return tr


def test_135(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 135 — 'Source Identifying Vulnerability' present for Ongoing/Risk Accepted POA&Ms.

    Purpose
    -------
    For every POA&M that is actively being worked (Ongoing) or has been Risk Accepted,
    require a non-empty source-identifying field so we know where the vuln came from.

    Data sources (priority)
    -----------------------
    1. ctx.system_poam_dashboard.data
    2. ctx.fixtures.poam_dashboard.data
    3. ctx.raw_payloads.system_poam_details
    4. ctx.system_poam_details (legacy/back-compat, if present)

    Behavior
    --------
    - If no POA&M data at all → PASS (same spirit as the PS script).
    - Else, check only rows whose status is Ongoing or Risk Accepted.
    - First missing/invalid source → FAIL + that POA&M id.
    - Otherwise → PASS.
    """

    test_name = (
        "Test 135: 'Source Identifying Vulnerability' provided for Ongoing/Risk Accepted POA&Ms"
    )

    # ------------------------------------------------------------------
    # nested helpers (keeps the test portable)
    # ------------------------------------------------------------------
    def load_poams_from_context(context: SystemContext) -> List[Dict[str, Any]]:
        """
        Best-effort POA&M loader that mirrors the other tests (133/134) so we
        don't explode on missing attrs.
        """
        # 1) top-level dashboard
        dash = getattr(context, "system_poam_dashboard", None)
        if dash is not None and getattr(dash, "data", None):
            return list(dash.data)

        # 2) fixtures version
        fixtures = getattr(context, "fixtures", None)
        if fixtures is not None:
            fx_dash = getattr(fixtures, "poam_dashboard", None)
            if fx_dash is not None and getattr(fx_dash, "data", None):
                return list(fx_dash.data)

        # 3) raw payloads
        raw_payloads = getattr(context, "raw_payloads", None)
        if raw_payloads is not None and getattr(raw_payloads, "system_poam_details", None):
            return list(raw_payloads.system_poam_details)

        # 4) legacy/back-compat
        if hasattr(context, "system_poam_details"):
            maybe = getattr(context, "system_poam_details") or []
            if isinstance(maybe, list):
                return list(maybe)

        return []

    def ci_get(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        """
        Case-insensitive, multi-key getter.
        """
        if not isinstance(d, dict):
            return default
        lower_map = {str(k).lower(): v for k, v in d.items()}
        for key in keys:
            v = lower_map.get(str(key).lower())
            if v is not None:
                return v
        return default

    # ------------------------------------------------------------------
    # actual test logic
    # ------------------------------------------------------------------
    poams = load_poams_from_context(ctx)

    # No data → PASS (that's how  PS behaves)
    if not poams:
        logger.info("[T135] PASS — No POA&M data available to evaluate.")
        tr = TestResult(
            test_number=135,
            name=test_name,
            result=Result.PASS,
            message="PASS: No POA&M data available to evaluate.",
        )
        status.add(tr)
        return tr

    failed_id: str | None = None

    for row in poams:
        # status can be raw "status" or dashboard "poam_item_status"
        status_val = (ci_get(row, "status", "poam_item_status", default="") or "").strip()
        status_val_lower = status_val.lower()

        if status_val_lower not in ("ongoing", "risk accepted"):
            continue

        # source can be spelled a few ways
        source_val = (ci_get(
            row,
            "sourceIdentifyingVulnerability",
            "source_identifying_vulnerability",
            "source_identifyingvulnerability",
            "source",   # some dashboards just give 'source'
            default="",
        ) or "").strip()

        if not source_val or source_val == "-":
            failed_id = str(
                ci_get(row, "displayPoamId", "poamId", "id", "condition_id", default="<unknown POA&M ID>")
            )
            break

    if failed_id:
        logger.warning(
            "[T135] FAIL — No Source Identifying Vulnerability for POA&M: %s",
            failed_id,
        )
        tr = TestResult(
            test_number=135,
            name=test_name,
            result=Result.FAIL,
            message=f"Missing 'Source Identifying Vulnerability' for POA&M: {failed_id}.",
        )
        status.add(tr)
        return tr

    logger.info(
        "[T135] PASS — All Ongoing/Risk Accepted POA&Ms include 'Source Identifying Vulnerability'."
    )
    tr = TestResult(
        test_number=135,
        name=test_name,
        result=Result.PASS,
        message="All Ongoing/Risk Accepted POA&Ms include 'Source Identifying Vulnerability'.",
    )
    status.add(tr)
    return tr

def test_136(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Validate that all risk-accepted POA&M records include a meaningful justification.

    This test enforces the programmatic equivalent of the eMASS / RMF guidance that any
    POA&M item whose **Status** is “Risk Accepted” must contain a substantive rationale
    in the **Recommendations** field. The rationale must be long enough to convey intent
    (we use a 6-word minimum, matching the original PowerShell rule), since single-word
    or empty recommendations do not provide traceability for auditors, AOs, or package
    reviewers.

    Data sources
    ------------
    The function tolerates multiple eMASS shapes and attempts to load POA&M data from
    these locations, in order:
      1. `ctx.system_poam_dashboard.data` (parsed/dashboard form)
      2. `ctx.fixtures.poam_dashboard.data` (fixture-backed dashboard form)
      3. `ctx.raw_payloads.system_poam_details` (raw list of POA&M dicts)
      4. `ctx.system_poam_details` (legacy/back-compat attribute if present)

    If none of the above sources are present or contain data, the test exits with PASS,
    on the assumption that the current system snapshot simply did not include POA&M
    records and we should not fail the package for missing upstream data.

    Matching behavior
    -----------------
    - The POA&M **status** value is resolved case-insensitively and across common key
      variants, e.g. `"status"` and `"poam_item_status"`.
    - A record is **in-scope** if and only if the status resolves to `"risk accepted"`.
    - For in-scope records, the **Recommendations** text is collected from common key
      variants, prioritizing `"recommendations"`, but falling back to adjacent
      description fields when necessary.
    - The recommendation text is split on whitespace and must contain **at least 6
      words**. Anything shorter is considered insufficient justification and will fail
      the test immediately.
    - On the first failure, the function reports the best available POA&M identifier
      (prefers `poamId`, then `displayPoamId`, then common dashboard IDs) so the caller
      can trace the exact offending row.

    Args:
        ctx (SystemContext):
            Fully materialized system snapshot containing one or more POA&M sources.
            Partial/dirty data is allowed; the function will degrade gracefully across
            dashboard, fixture, raw, and legacy shapes.
        status (ATOStatus):
            Aggregated test state for the current run. This function appends a single
            `TestResult` instance to `status.results` and updates the appropriate
            PASS/FAIL counters.

    Returns:
        TestResult:
            - `Result.PASS` when:
                * No POA&M data is available, or
                * All POA&M records with status “Risk Accepted” have a recommendation
                  containing ≥ 6 words.
            - `Result.FAIL` when:
                * At least one “Risk Accepted” POA&M record is missing or has an
                  underspecified recommendation. The returned `TestResult.message`
                  includes the offending POA&M ID whenever one was present in the
                  source data.

    Notes:
        - This check is intentionally “fail fast”: as soon as an underspecified
          recommendation is found, the function returns. This mirrors the original
          PowerShell behavior and keeps CI/test-runner output focused on the first
          actionable defect.
        - The word-count threshold (6) is a pragmatic heuristic — it’s not intended to
          judge writing quality, only to ensure the field contains more than a short
          placeholder like “accept risk” or “approved.”

    Examples:
        - PASS:
            * POA&M status = “Risk Accepted”, recommendations = “Implementation cost
              exceeds mission benefit at this time.”
        - FAIL:
            * POA&M status = “Risk Accepted”, recommendations = “accept risk”
    """
    test_name = (
        "Test 136: Risk-accepted POA&Ms include justification in 'Recommendations'"
    )

    # ------------------------------------------------------------
    # shared POA&M loader (same pattern as we used for 135)
    # ------------------------------------------------------------
    def load_poams_from_context(context: SystemContext) -> List[Dict[str, Any]]:
        # 1) top-level dashboard
        dash = getattr(context, "system_poam_dashboard", None)
        if dash is not None and getattr(dash, "data", None):
            return list(dash.data)

        # 2) fixtures version
        fixtures = getattr(context, "fixtures", None)
        if fixtures is not None:
            fx_dash = getattr(fixtures, "poam_dashboard", None)
            if fx_dash is not None and getattr(fx_dash, "data", None):
                return list(fx_dash.data)

        # 3) raw payloads
        raw_payloads = getattr(context, "raw_payloads", None)
        if raw_payloads is not None and getattr(raw_payloads, "system_poam_details", None):
            return list(raw_payloads.system_poam_details)

        # 4) legacy/back-compat
        if hasattr(context, "system_poam_details"):
            maybe = getattr(context, "system_poam_details") or []
            if isinstance(maybe, list):
                return list(maybe)

        return []

    def ci_get(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        """
        Case-insensitive multi-key getter.
        """
        if not isinstance(d, dict):
            return default
        lower_map = {str(k).lower(): v for k, v in d.items()}
        for key in keys:
            v = lower_map.get(str(key).lower())
            if v is not None:
                return v
        return default

    poams = load_poams_from_context(ctx)

    # No POA&M data at all → treat as PASS (mirrors the PS "we didn't see anything" behavior)
    if not poams:
        logger.info("[T136] PASS — No POA&M data available to evaluate.")
        tr = TestResult(
            test_number=136,
            name=test_name,
            result=Result.PASS,
            message="PASS: No POA&M data available to evaluate.",
        )
        status.add(tr)
        return tr

    failed_id: str | None = None

    for row in poams:
        # status could be "status" (raw) or "poam_item_status" (dashboard)
        status_val = (
            ci_get(row, "status", "poam_item_status", default="") or ""
        ).strip()
        if status_val.lower() != "risk accepted":
            continue

        # recommendations can be "recommendations" (raw/dashboard) or occasionally
        # something like "latest_milestone_description" in some exports; but OG PS
        # logic used .recommendations so we prioritize that.
        recs = (
            ci_get(
                row,
                "recommendations",
                "recommendation",
                "latest_milestone_description",  # fallback, just in case
                default="",
            )
            or ""
        ).strip()

        word_count = len(recs.split()) if recs else 0

        if word_count < 6:
            failed_id = str(
                ci_get(
                    row,
                    "poamId",
                    "displayPoamId",
                    "id",
                    "condition_id",
                    default="<unknown POA&M ID>",
                )
            )
            break

    if failed_id:
        logger.warning(
            "[T136] FAIL — Risk acceptance without sufficient justification: %s",
            failed_id,
        )
        tr = TestResult(
            test_number=136,
            name=test_name,
            result=Result.FAIL,
            message=(
                f"Risk acceptance lacks sufficient justification in 'Recommendations' "
                f"for POA&M: {failed_id}."
            ),
        )
        status.add(tr)
        return tr

    logger.info(
        "[T136] PASS — All Risk Accepted POA&Ms contain a minimally sufficient justification."
    )
    tr = TestResult(
        test_number=136,
        name=test_name,
        result=Result.PASS,
        message="All Risk Accepted POA&Ms include a minimally sufficient justification in 'Recommendations'.",
    )
    status.add(tr)
    return tr



def test_137(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 137 — Completed POA&Ms include evidence of closure.

    Purpose
    -------
    Port of the original PowerShell check:
    - Find POA&M items that are marked "Completed".
    - For each completed item, verify some kind of evidence/artifact is present.
    - If *any* completed item has no evidence → FAIL (first one wins).
    - If we saw completed items and all had something → CONCERN (manual review still needed).
    - If we didn't see any completed items → CONCERN (nothing to auto-verify).

    We have to do this against multiple possible sources because eMASS exports are
    not consistent. So we try, in order:
      1. ctx.system_poam_dashboard.data
      2. ctx.fixtures.poam_dashboard.data
      3. ctx.raw_payloads.system_poam_details
      4. ctx.system_poam_details (legacy/ad-hoc)

    Args:
        ctx: Current system context (already scoped to one system).
        status: Running ATO status aggregator.

    Returns:
        TestResult: Final outcome of the test.
    """
    test_number = 137
    test_name = "Test 137: Completed POA&Ms have evidence validating closure"

    def ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict getter."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    # ------------------------------------------------------------
    # unified POA&M loader (same shape as  136/138 style)
    # ------------------------------------------------------------
    poams: List[Dict[str, Any]] = []

    if getattr(ctx, "system_poam_dashboard", None) and ctx.system_poam_dashboard.data:
        logger.debug("[T137] using ctx.system_poam_dashboard.data for system_id=%s", ctx.system_id)
        poams = ctx.system_poam_dashboard.data or []

    elif getattr(ctx, "fixtures", None):
        fixtures_poam = getattr(ctx.fixtures, "poam_dashboard", None)
        if fixtures_poam and fixtures_poam.data:
            logger.debug("[T137] using ctx.fixtures.poam_dashboard.data for system_id=%s", ctx.system_id)
            poams = fixtures_poam.data or []

    elif getattr(ctx, "raw_payloads", None) and ctx.raw_payloads.system_poam_details:
        logger.debug("[T137] using ctx.raw_payloads.system_poam_details for system_id=%s", ctx.system_id)
        poams = ctx.raw_payloads.system_poam_details or []

    elif hasattr(ctx, "system_poam_details"):
        logger.debug("[T137] using ctx.system_poam_details for system_id=%s", ctx.system_id)
        poams = getattr(ctx, "system_poam_details") or []

    # ------------------------------------------------------------
    # core check
    # ------------------------------------------------------------
    failed_id: Optional[str] = None
    found_completed = False

    for row in poams:
        # eMASS likes a few different names for this
        status_val = (
            ci_get(row, "status", "")
            or ci_get(row, "poam_item_status", "")
            or ci_get(row, "poamItemStatus", "")
            or ""
        ).strip()

        if status_val.lower() != "completed":
            continue

        found_completed = True

        # artifacts/evidence can be a string, list, dict, "-", ""
        artifacts = (
            ci_get(row, "artifacts")
            or ci_get(row, "artifact_attachments")
            or ci_get(row, "attachments")
        )

        if isinstance(artifacts, str):
            artifacts = artifacts.strip()

        missing = (
            artifacts is None
            or artifacts == []
            or artifacts == {}
            or (isinstance(artifacts, str) and artifacts in {"", "-"})
        )
        if missing:
            failed_id = str(
                ci_get(row, "displayPoamId")
                or ci_get(row, "poamId")
                or ci_get(row, "id")
                or "<unknown POA&M ID>"
            )
            logger.warning(
                "[T137] FAIL — completed POA&M missing artifacts for system_id=%s: %s",
                ctx.system_id,
                failed_id,
            )
            break

    # ------------------------------------------------------------
    # result mapping (same intent as PS)
    # ------------------------------------------------------------
    if failed_id:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=(
                "Completed POA&M lacks evidence of closure (artifacts missing): "
                f"POA&M {failed_id}."
            ),
        )
        status.add(tr)
        return tr

    if found_completed:
        msg = (
            "All completed POA&Ms include some evidence; manual review still recommended "
            "for sufficiency."
        )
    else:
        msg = "No completed POA&Ms found; nothing to verify automatically."

    logger.info(
        "[T137] CONCERN — %s (system_id=%s)",
        msg,
        ctx.system_id,
    )

    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.CONCERN,
        message=msg,
    )
    status.add(tr)
    return tr

def test_138(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 138 — False Positives/False Negatives listed in CM-6.5

    Purpose
    -------
    Surface that the current eMASS payloads wired into this engine do not expose
    a reliable field to validate whether CM-6.5 false positives/false negatives
    have been documented. Because of that, the check cannot be automated here.

    Behavior
    --------
    - Always returns CONCERN with guidance to perform manual validation.
    - This mirrors the PowerShell intent of "we can't see it -> tell the assessor."

    Outcomes
    --------
    - CONCERN: Manual verification required.
    """
    test_name = "Test 138: False Positives/False Negatives listed in CM-6.5"
    tr = TestResult(
        test_number=138,
        name=test_name,
        result=Result.CONCERN,
        message=(
            "CM-6.5 FP/FN documentation is not exposed in the available eMASS payloads; "
            "perform manual verification in the source system."
        ),
    )
    status.add(tr)
    return tr

def test_139(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 139 — STIG-related POA&Ms correctly closed when no assets are affected.

    Purpose
    -------
    For POA&Ms that cite STIG as the source, ensure items with **no affected
    assets** (e.g., “No Resources Affected”) are marked **Completed**.

    Behavior (parity with PowerShell)
    ---------------------------------
    - Look at STIG-sourced POA&Ms.
    - If a STIG POA&M reports no affected assets, it should be Completed.
    - If none are STIG → CONCERN.
    - If some should be Completed but aren’t → CONCERN.
    - Otherwise → PASS.
    """
    test_name = (
        "Test 139: STIG-related POA&Ms with no affected assets are marked 'Completed'"
    )

    def ci_get(d: dict, key: str, default=None):
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    # 1) Prefer the raw payloads (this is where you're actually hanging the list)
    if ctx.raw_payloads and ctx.raw_payloads.system_poam_details is not None:
        poams = ctx.raw_payloads.system_poam_details
    # 2) Fallback: some eMASS exports push POA&Ms into the dashboard `.data`
    elif ctx.system_poam_dashboard and ctx.system_poam_dashboard.data:
        poams = ctx.system_poam_dashboard.data
    else:
        poams = []

    stig_found_ids: list[str] = []
    should_be_completed_but_not: list[str] = []
    correctly_completed: list[str] = []

    for row in poams:
        src = (ci_get(row, "sourceIdentifyingVulnerability", "") or "").strip()
        if "stig" not in src.lower():
            continue

        poam_id = str(
            ci_get(row, "poamId")
            or ci_get(row, "displayPoamId")
            or ci_get(row, "id")
            or "<unknown POA&M ID>"
        )
        stig_found_ids.append(poam_id)

        resources = ci_get(row, "resources")
        resources_str = (resources or "").strip() if isinstance(resources, str) else resources

        no_affected_assets = (
            resources is None
            or resources == []
            or resources == {}
            or (isinstance(resources_str, str) and (
                resources_str == "" or "no resources affected" in resources_str.lower()
            ))
        )

        if no_affected_assets:
            status_val = (ci_get(row, "status", "") or ci_get(row, "poam_item_status", "") or "").strip()
            if status_val == "Completed":
                correctly_completed.append(poam_id)
            else:
                should_be_completed_but_not.append(poam_id)

    # No STIG POA&Ms at all → CONCERN (same shape as PS)
    if not stig_found_ids:
        tr = TestResult(
            test_number=139,
            name=test_name,
            result=Result.CONCERN,
            message="No STIG-related POA&Ms found; manual verification recommended.",
        )
        status.add(tr)
        return tr

    # Some STIG POA&Ms report no assets but are not completed → CONCERN
    if should_be_completed_but_not:
        tr = TestResult(
            test_number=139,
            name=test_name,
            result=Result.CONCERN,
            message=(
                "Some STIG-related POA&Ms report no affected assets but are not marked "
                "'Completed': " + ", ".join(should_be_completed_but_not) + "."
            ),
        )
        status.add(tr)
        return tr

    # Otherwise → PASS
    tr = TestResult(
        test_number=139,
        name=test_name,
        result=Result.PASS,
        message=(
            "All STIG-related POA&Ms with no affected assets/findings are correctly marked 'Completed'."
        ),
    )
    status.add(tr)
    return tr



#Skip Test 140(COMMENTED OUT IN POWERSHELL. So, we skip it here.

def test_141(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 141 — No new 'High' / 'Very High' residual risk since last authorization

    Logic (faithful to PS)
    ----------------------
    Iterate POA&Ms:
      1. If mitigations is missing / "-" / empty -> CONCERN (stop)
      2. Else if severity is "High" or "Very High" (or contains it) -> FAIL (stop)
      3. Else keep going
    If we finish the loop with no hits -> PASS
    """
    test_name = (
        "Test 141: No new 'High'/'Very High' residual risk since last authorization"
    )

    def ci_get(d: dict, key: str, default=None):
        """Case-insensitive dict get."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    # --- get POA&Ms from the same places as 139 ---
    if ctx.raw_payloads and ctx.raw_payloads.system_poam_details is not None:
        poams = ctx.raw_payloads.system_poam_details
    elif ctx.system_poam_dashboard and ctx.system_poam_dashboard.data:
        poams = ctx.system_poam_dashboard.data
    else:
        poams = []

    overall_result: Result = Result.PASS
    offender_poam_id: str | None = None

    for row in poams:
        # mitigation text
        mitigations_raw = ci_get(row, "mitigations", "")
        mitigations_str = (mitigations_raw or "").strip()

        # severity: try a couple of common keys
        severity_raw = (
            ci_get(row, "severity")
            or ci_get(row, "residual_risk")
            or ci_get(row, "residualRisk")
            or ci_get(row, "residualRiskLevel")
            or ci_get(row, "raw_severity")
            or ""
        )
        severity_str = (severity_raw or "").strip()

        poam_id = str(
            ci_get(row, "displayPoamId")
            or ci_get(row, "poamId")
            or ci_get(row, "id")
            or "<unknown POA&M ID>"
        )

        # Branch 1: missing / placeholder mitigations -> CONCERN
        if mitigations_str == "" or mitigations_str == "-":
            overall_result = Result.CONCERN
            offender_poam_id = poam_id
            break

        # Branch 2: high / very high -> FAIL
        s = severity_str.lower()
        # mimic PS: /(high|very high)/i with a loose check
        if "very high" in s or s == "high" or s.endswith(" high") or s.startswith("high"):
            overall_result = Result.FAIL
            offender_poam_id = poam_id
            break
        if s == "very high":
            overall_result = Result.FAIL
            offender_poam_id = poam_id
            break

    # Build message
    if overall_result == Result.CONCERN:
        msg = (
            "CONCERN: One or more POA&Ms are missing mitigation details or contain "
            f"placeholder mitigation text. Example POA&M {offender_poam_id}."
        )
    elif overall_result == Result.FAIL:
        msg = (
            "FAIL: At least one POA&M reports High or Very High residual risk that "
            f"appears unacceptable for current authorization. Example POA&M {offender_poam_id}."
        )
    else:
        msg = "PASS: All POA&Ms have mitigation details and none report High/Very High residual risk."

    tr = TestResult(
        test_number=141,
        name=test_name,
        result=overall_result,
        message=msg,
    )
    status.add(tr)
    return tr


def test_141(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 141 — No new 'High' / 'Very High' residual risk since last authorization

    Logic (faithful to PS)
    ----------------------
    Iterate POA&Ms:
      1. If mitigations is missing / "-" / empty -> CONCERN (stop)
      2. Else if severity is "High" or "Very High" (or contains it) -> FAIL (stop)
      3. Else keep going
    If we finish the loop with no hits -> PASS
    """
    test_name = (
        "Test 141: No new 'High'/'Very High' residual risk since last authorization"
    )

    def ci_get(d: dict, key: str, default=None):
        """Case-insensitive dict get."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    # --- get POA&Ms from the same places as 139 ---
    if ctx.raw_payloads and ctx.raw_payloads.system_poam_details is not None:
        poams = ctx.raw_payloads.system_poam_details
    elif ctx.system_poam_dashboard and ctx.system_poam_dashboard.data:
        poams = ctx.system_poam_dashboard.data
    else:
        poams = []

    overall_result: Result = Result.PASS
    offender_poam_id: str | None = None

    for row in poams:
        # mitigation text
        mitigations_raw = ci_get(row, "mitigations", "")
        mitigations_str = (mitigations_raw or "").strip()

        # severity: try a couple of common keys
        severity_raw = (
            ci_get(row, "severity")
            or ci_get(row, "residual_risk")
            or ci_get(row, "residualRisk")
            or ci_get(row, "residualRiskLevel")
            or ci_get(row, "raw_severity")
            or ""
        )
        severity_str = (severity_raw or "").strip()

        poam_id = str(
            ci_get(row, "displayPoamId")
            or ci_get(row, "poamId")
            or ci_get(row, "id")
            or "<unknown POA&M ID>"
        )

        # Branch 1: missing / placeholder mitigations -> CONCERN
        if mitigations_str == "" or mitigations_str == "-":
            overall_result = Result.CONCERN
            offender_poam_id = poam_id
            break

        # Branch 2: high / very high -> FAIL
        s = severity_str.lower()
        # mimic PS: /(high|very high)/i with a loose check
        if "very high" in s or s == "high" or s.endswith(" high") or s.startswith("high"):
            overall_result = Result.FAIL
            offender_poam_id = poam_id
            break
        if s == "very high":
            overall_result = Result.FAIL
            offender_poam_id = poam_id
            break

    # Build message
    if overall_result == Result.CONCERN:
        msg = (
            "CONCERN: One or more POA&Ms are missing mitigation details or contain "
            f"placeholder mitigation text. Example POA&M {offender_poam_id}."
        )
    elif overall_result == Result.FAIL:
        msg = (
            "FAIL: At least one POA&M reports High or Very High residual risk that "
            f"appears unacceptable for current authorization. Example POA&M {offender_poam_id}."
        )
    else:
        msg = "PASS: All POA&Ms have mitigation details and none report High/Very High residual risk."

    tr = TestResult(
        test_number=141,
        name=test_name,
        result=overall_result,
        message=msg,
    )
    status.add(tr)
    return tr



def test_143(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 143 — CONOPs (Concept of Operations) artifact present.

    Context
    -------
    For Major Acquisition Programs (ACAT II & III & SIS/CRN), a CONOPs (Concept
    of Operations) document is required. In PowerShell, this was implemented as:
      - Search artifacts for anything whose name/filename matches "CONOP".
      - If found: CONCERN (we found something but can't verify signature/auth).
      - If not found: FAIL.

    We mirror that logic exactly.

    We are *not* attempting to determine:
    - Whether the system is ACAT II/III/etc.
    - Whether the CONOPs is the correct/approved version.
    - Whether it's actually signed.

    Inputs
    ------
    ctx.artifact_details : list[dict] | None
        Materialized artifact detail rows for this system. Expected keys include
        "Artifact Name" and "Filename". We imitate the `Get-ArtifactInfo`
        behavior by fuzzy matching "CONOP" case-insensitive.

    Behavior
    --------
    - If one or more artifacts match "CONOP":
        Result = CONCERN
        Message = we found possible CONOPs, but require manual verification.
    - Else:
        Result = FAIL
        Message = no CONOP found.

    Returns
    -------
    TestResult
        CONCERN or FAIL as described above.
    """

    test_number = 143
    test_name = "Test 143: CONOPs present"

    def ci_get(d: dict, key: str, default=None):
        """Case-insensitive dict get helper."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def matches_conops(artifact_row: dict) -> bool:
        """
        True if this artifact row looks like a CONOPs doc.
        PowerShell logic: match '*CONOP*' against Artifact Name OR filename.
        We'll do case-insensitive substring 'conop'.
        """
        art_name = str(ci_get(artifact_row, "Artifact Name", "") or "")
        fname = str(ci_get(artifact_row, "Filename", "") or "")
        needle = "conop"
        return (needle in art_name.lower()) or (needle in fname.lower())

    artifacts = ctx.artifact_details or []
    matching_artifacts: list[str] = []

    for row in artifacts:
        if matches_conops(row):
            # capture something human-friendly for debug text
            art_name = ci_get(row, "Artifact Name") or ci_get(row, "Filename") or "<unnamed>"
            matching_artifacts.append(str(art_name))

    if matching_artifacts:
        # PowerShell branch:
        # Yellow CONCERN: "CONOP Found, but cannot be verified signed. Please download..."
        msg = (
            "CONCERN: CONOP artifact(s) found but signature/approval cannot be "
            "verified automatically. Manual review required. "
            f"Artifacts: {', '.join(matching_artifacts)}"
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.CONCERN,
            message=msg,
        )
        status.add(tr)
        return tr

    # else → FAIL: "No CONOP Found."
    msg = "FAIL: No CONOP artifact found for this system."
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.FAIL,
        message=msg,
    )
    status.add(tr)
    return tr



def test_144(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 144 — Ensure a PPS List artifact exists (PowerShell-parity, Python-style).

    Purpose
    -------
    The original PowerShell test did this:
    - Look for artifacts whose name matched "*PPS*".
    - If it found any → **CONCERN**: "PPS List Found, but cannot be verified signed..."
    - If it found none → **FAIL**: "No PPS List Found."

    We preserve exactly that behavior, but we read artifacts from the
    *structured* fields on `SystemContext` first, and only fall back to raw
    payloads if the structured data is missing.

    Read order (highest → lowest fidelity):
        1. ctx.artifact_details.data
        2. ctx.artifact_details (single object)
        3. ctx.artifact_summary.data
        4. ctx.raw_payloads.artifact_details    ← last resort

    Args:
        ctx: Fully-populated system snapshot.
        status: Running test-status accumulator to append this result to.

    Returns:
        TestResult: CONCERN if a PPS-like artifact is present; FAIL otherwise.
    """
    test_number = 144
    test_name = "Test 144: PPS List present"

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict get.

        We have to do this because eMASS exports love to give you
        'Artifact Name' *and* 'artifact_name' on different days.
        """
        if not isinstance(d, dict):
            return default
        key_l = key.lower()
        for k, v in d.items():
            if str(k).lower() == key_l:
                return v
        return default

    def iter_artifact_rows() -> Iterable[Dict[str, Any]]:
        """Yield artifact rows from the *nested* SystemContext structure.

        This is the part  runner will hit most of the time.
        We only touch the raw payload at the very end.
        """
        # 1) Structured: ctx.artifact_details.data  (preferred)
        if ctx.artifact_details and getattr(ctx.artifact_details, "data", None):
            for row in ctx.artifact_details.data:  # type: ignore[attr-defined]
                if isinstance(row, dict):
                    yield row

        # 2) Structured: ctx.artifact_details as a single object
        elif ctx.artifact_details:
            # Single artifact entry shaped by Pydantic
            yield ctx.artifact_details.model_dump(exclude_none=True)

        # 3) Structured: ctx.artifact_summary.data
        if ctx.artifact_summary and getattr(ctx.artifact_summary, "data", None):
            for row in ctx.artifact_summary.data:  # type: ignore[attr-defined]
                if isinstance(row, dict):
                    yield row

        # 4) (Optional) fixtures — if you later hang it off ctx
        fixtures = getattr(ctx, "fixtures", None)
        if fixtures is not None:
            # fixtures.artifact_details
            fad = getattr(fixtures, "artifact_details", None)
            if fad is not None:
                data = getattr(fad, "data", None)
                if data:
                    for row in data:
                        if isinstance(row, dict):
                            yield row

        # 5) LAST RESORT: raw payloads
        if ctx.raw_payloads and ctx.raw_payloads.artifact_details:
            for row in ctx.raw_payloads.artifact_details:
                if isinstance(row, dict):
                    yield row

    def is_pps_like(artifact_row: Dict[str, Any]) -> bool:
        """Return True if this artifact looks like a PPS List.

        PowerShell basically did: `-like "*PPS*"` on artifact name / filename.
        We'll do that as a case-insensitive substring on the usual fields.
        """
        needle = "pps"
        name_val = (
            ci_get(artifact_row, "Artifact Name", "")
            or ci_get(artifact_row, "artifact_name", "")
            or ""
        )
        file_val = (
            ci_get(artifact_row, "Filename", "")
            or ci_get(artifact_row, "filename", "")
            or ""
        )
        return needle in str(name_val).lower() or needle in str(file_val).lower()

    # ------------------------------------------------------------------ #
    # core logic (PowerShell parity)
    # ------------------------------------------------------------------ #
    matching: List[str] = []

    for row in iter_artifact_rows():
        if is_pps_like(row):
            label = (
                ci_get(row, "Artifact Name")
                or ci_get(row, "artifact_name")
                or ci_get(row, "Filename")
                or ci_get(row, "filename")
                or "<unnamed artifact>"
            )
            matching.append(str(label))

    if matching:
        # Yellow branch from PS
        msg = (
            "CONCERN: PPS List artifact(s) found but signature/approval cannot be "
            "auto-verified. Manual review required. "
            f"Artifacts: {', '.join(matching)}"
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.CONCERN,
            message=msg,
        )
        status.add(tr)
        return tr

    # Red branch from PS
    msg = "FAIL: No PPS List artifact found for this system."
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.FAIL,
        message=msg,
    )
    status.add(tr)
    return tr


def test_145(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Validate SOP artifact presence (PS parity, structured-first).

    Overview
    --------
    This test mirrors the original PowerShell behavior:

    - Search this system's artifacts for strings that indicate SOPs
      (``"SOP"`` or ``"Standard Operating Procedure"``).
    - If **any** SOP-like artifact is present, we do **not** attempt to
      auto-verify signature, currency (≤ 365 days), or mapping to controls.
      Instead we return **CONCERN** and tell a human to review.
    - If **no** SOP-like artifact is found, we return **FAIL**.

    The reason for returning **CONCERN** on presence is that the actual
    compliance requirement is richer than what we can prove from eMASS
    metadata alone (must be signed by current authority, must be current,
    must be the right SOP for the right control set). This matches the
    original PS script’s “we found it, but go look at it” flow.

    This version is “modernized” in that it prefers the structured,
    Pydantic-backed surfaces on ``SystemContext`` and only then falls
    back to the raw payload list.

    Args:
        ctx (SystemContext): Fully-populated system snapshot. We expect
            SOP-like artifacts to appear primarily under
            ``ctx.artifact_details.data``, but we will also check
            ``ctx.artifact_summary.data``, optional ``ctx.fixtures``,
            and finally ``ctx.raw_payloads.artifact_details``.
        status (ATOStatus): Aggregator that collects test outcomes and
            maintains PASS/FAIL/CONCERN counts.

    Returns:
        TestResult: A single test result object representing this check.

    Notes:
        - This function is intentionally conservative: *any* hit becomes
          a manual-review CONCERN.
        - Logging is included at INFO/DEBUG so operators can trace
          where artifacts were sourced from and which ones matched.
    """
    test_number = 145
    test_name = (
        "Test 145: SOPs present, signed by current authority, "
        "reviewed within 365 days"
    )

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict lookup.

        Args:
            d: Source dict, typically one artifact row.
            key: Field name to look up (e.g. ``"Artifact Name"``).
            default: Value to return if not found.

        Returns:
            Value found under a case-insensitive match, or ``default``.
        """
        if not isinstance(d, dict):
            return default
        wanted = key.lower()
        for k, v in d.items():
            if str(k).lower() == wanted:
                return v
        return default

    def iter_artifact_rows() -> Iterable[Dict[str, Any]]:
        """Yield artifact-like rows from highest- to lowest-fidelity source.

        Order:
            1. ``ctx.artifact_details.data``  (structured, per-system)
            2. ``ctx.artifact_details``       (single structured row)
            3. ``ctx.artifact_summary.data``  (less detailed, still structured)
            4. ``ctx.fixtures.artifact_details.data`` (if present)
            5. ``ctx.raw_payloads.artifact_details``  (raw JSON list)

        Yields:
            Dict[str, Any]: One artifact row at a time.
        """
        # 1) structured per-system artifacts
        if ctx.artifact_details and getattr(ctx.artifact_details, "data", None):
            logger.debug(
                "test_145: using ctx.artifact_details.data for system_id=%s",
                ctx.system_id,
            )
            for row in ctx.artifact_details.data:  # type: ignore[attr-defined]
                if isinstance(row, dict):
                    yield row
        # 2) single structured artifact_details object
        elif ctx.artifact_details:
            logger.debug(
                "test_145: using ctx.artifact_details (single row) for system_id=%s",
                ctx.system_id,
            )
            yield ctx.artifact_details.model_dump(exclude_none=True)

        # 3) structured artifact summary rows
        if ctx.artifact_summary and getattr(ctx.artifact_summary, "data", None):
            logger.debug(
                "test_145: using ctx.artifact_summary.data for system_id=%s",
                ctx.system_id,
            )
            for row in ctx.artifact_summary.data:  # type: ignore[attr-defined]
                if isinstance(row, dict):
                    yield row

        # 4) fixtures (optional)
        fixtures = getattr(ctx, "fixtures", None)
        if fixtures is not None:
            fad = getattr(fixtures, "artifact_details", None)
            if fad is not None:
                data = getattr(fad, "data", None)
                if data:
                    logger.debug(
                        "test_145: using ctx.fixtures.artifact_details.data for system_id=%s",
                        ctx.system_id,
                    )
                    for row in data:
                        if isinstance(row, dict):
                            yield row

        # 5) raw payloads as last resort
        if ctx.raw_payloads and ctx.raw_payloads.artifact_details:
            logger.debug(
                "test_145: using ctx.raw_payloads.artifact_details for system_id=%s",
                ctx.system_id,
            )
            for row in ctx.raw_payloads.artifact_details:
                if isinstance(row, dict):
                    yield row

    def is_sop_artifact(row: Dict[str, Any]) -> bool:
        """Return True if this artifact row looks like an SOP."""
        name_val = (
            ci_get(row, "Artifact Name", "")
            or ci_get(row, "artifact_name", "")
            or ""
        )
        file_val = (
            ci_get(row, "Filename", "")
            or ci_get(row, "filename", "")
            or ""
        )
        combined = f"{name_val} {file_val}".lower()
        return (
            "sop" in combined
            or "standard operating procedure" in combined
        )

    # ------------------------------------------------------------------ #
    # core logic
    # ------------------------------------------------------------------ #
    sop_candidates: List[str] = []
    inspected_count = 0

    for art in iter_artifact_rows():
        inspected_count += 1
        if is_sop_artifact(art):
            label = (
                ci_get(art, "Artifact Name")
                or ci_get(art, "artifact_name")
                or ci_get(art, "Filename")
                or ci_get(art, "filename")
                or "<unnamed SOP>"
            )
            logger.info(
                "test_145: SOP-like artifact matched for system_id=%s: %s",
                ctx.system_id,
                label,
            )
            sop_candidates.append(str(label))

    logger.debug(
        "test_145: inspected %d artifact rows for system_id=%s",
        inspected_count,
        ctx.system_id,
    )

    if sop_candidates:
        msg = (
            "CONCERN: SOP artifacts found, but mapping to controls, verifying the "
            "current appointed authority signature, and confirming last review "
            "≤ 365 days cannot be automated. Manual review required. "
            f"SOP candidates: {', '.join(sop_candidates)}"
        )
        logger.info(
            "test_145: CONCERN for system_id=%s — %d SOP candidates found",
            ctx.system_id,
            len(sop_candidates),
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.CONCERN,
            message=msg,
        )
        status.add(tr)
        return tr

    # no SOPs at all → FAIL
    msg = (
        "FAIL: No SOP / Standard Operating Procedure artifacts were identified "
        "for this system."
    )
    logger.warning(
        "test_145: FAIL for system_id=%s — no SOP-like artifacts found",
        ctx.system_id,
    )
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.FAIL,
        message=msg,
    )
    status.add(tr)
    return tr

def test_146(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Validate presence of responsibility / service-boundary artifacts (PS parity).

    Overview
    --------
    This is the Pythonic port of the original PowerShell check:

    - Search this system’s artifacts for documents that typically define
      shared responsibility, hosting, or boundary agreements:
        * MOU
        * MOA
        * SLA
        * CRM (Customer Responsibility Matrix)
        * "Cloud Service Provider"
        * "Cybersecurity Service Provider"
    - If **any** such artifact is present → **CONCERN**:
        we found candidate boundary docs, but we cannot auto-verify currency,
        signatures, or role applicability.
    - If **none** are present → **FAIL**:
        the system isn’t carrying the expected boundary/responsibility docs.

    Why CONCERN on presence?
    ------------------------
    The real requirement is richer than just “file is there.” It normally
    wants:
      - correct *kind* of agreement,
      - signed by the right party,
      - current / in-force,
      - mapped to the hosting / inherited environment.
    We can’t prove those from eMASS metadata alone, so we follow the PS
    approach and tell a human to review.

    This version is “new world” in that it:
      1. Reads from the **nested** Pydantic surfaces on `SystemContext`
         first (structured data),
      2. Only then falls back to `ctx.raw_payloads.artifact_details`,
      3. Normalizes field names case-insensitively.

    Args:
        ctx (SystemContext): Snapshot of a single eMASS system. Expected to
            have artifact information in `ctx.artifact_details.data`,
            `ctx.artifact_summary.data`, optional `ctx.fixtures`, or, as a last
            resort, `ctx.raw_payloads.artifact_details`.
        status (ATOStatus): Running accumulator for test results. This function
            will append the newly created result.

    Returns:
        TestResult: A single test result reflecting the PS-parity outcome
        (CONCERN on presence, otherwise FAIL).

    Notes:
        - We do **not** implement the “not applicable for cARMY/DISA hosted
          cloud” nuance the old comment mentioned — the PS didn’t, so we don’t.
        - Logging uses the existing `[T###] ...` style, so you get traceability
          consistent with tests 95–117.
    """
    test_number = 146
    test_name = (
        "Test 146: MOUs/MOAs/SLAs/CRM/CSP-CSSP responsibility docs attached"
    )

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Return value from `d` using case-insensitive key match."""
        if not isinstance(d, dict):
            return default
        look_for = key.lower()
        for k, v in d.items():
            if str(k).lower() == look_for:
                return v
        return default

    def iter_artifact_rows() -> Iterable[Dict[str, Any]]:
        """Yield artifact-like rows from structured → raw, highest fidelity first.

        Order:
            1. ctx.artifact_details.data
            2. ctx.artifact_details (single row)
            3. ctx.artifact_summary.data
            4. ctx.fixtures.artifact_details.data   (if present)
            5. ctx.raw_payloads.artifact_details    (last resort)
        """
        # 1) primary structured artifacts
        if ctx.artifact_details and getattr(ctx.artifact_details, "data", None):
            logger.debug(
                "[T146] using ctx.artifact_details.data for system_id=%s",
                ctx.system_id,
            )
            for row in ctx.artifact_details.data:  # type: ignore[attr-defined]
                if isinstance(row, dict):
                    yield row
        # 2) single structured artifact_details
        elif ctx.artifact_details:
            logger.debug(
                "[T146] using ctx.artifact_details (single row) for system_id=%s",
                ctx.system_id,
            )
            yield ctx.artifact_details.model_dump(exclude_none=True)

        # 3) artifact summary
        if ctx.artifact_summary and getattr(ctx.artifact_summary, "data", None):
            logger.debug(
                "[T146] using ctx.artifact_summary.data for system_id=%s",
                ctx.system_id,
            )
            for row in ctx.artifact_summary.data:  # type: ignore[attr-defined]
                if isinstance(row, dict):
                    yield row

        # 4) fixtures (optional, same shape)
        fixtures = getattr(ctx, "fixtures", None)
        if fixtures is not None:
            fad = getattr(fixtures, "artifact_details", None)
            if fad is not None:
                data = getattr(fad, "data", None)
                if data:
                    logger.debug(
                        "[T146] using ctx.fixtures.artifact_details.data for system_id=%s",
                        ctx.system_id,
                    )
                    for row in data:
                        if isinstance(row, dict):
                            yield row

        # 5) raw payloads (JSON list)
        if ctx.raw_payloads and ctx.raw_payloads.artifact_details:
            logger.debug(
                "[T146] using ctx.raw_payloads.artifact_details for system_id=%s",
                ctx.system_id,
            )
            for row in ctx.raw_payloads.artifact_details:
                if isinstance(row, dict):
                    yield row

    def is_responsibility_artifact(row: Dict[str, Any]) -> bool:
        """Return True if this artifact looks like MOU/MOA/SLA/CRM/CSP/CSSP."""
        name_val = (
            ci_get(row, "Artifact Name", "")
            or ci_get(row, "artifact_name", "")
            or ""
        )
        file_val = (
            ci_get(row, "Filename", "")
            or ci_get(row, "filename", "")
            or ""
        )
        haystack = f"{name_val} {file_val}".lower()

        keywords = (
            "mou",
            "moa",
            "sla",
            "crm",
            "cloud service provider",
            "cybersecurity service provider",
        )
        return any(term in haystack for term in keywords)

    # ------------------------------------------------------------------ #
    # core logic
    # ------------------------------------------------------------------ #
    matching_docs: List[str] = []
    inspected = 0

    for art in iter_artifact_rows():
        inspected += 1
        if is_responsibility_artifact(art):
            label = (
                ci_get(art, "Artifact Name")
                or ci_get(art, "artifact_name")
                or ci_get(art, "Filename")
                or ci_get(art, "filename")
                or "<unnamed responsibility doc>"
            )
            matching_docs.append(str(label))
            logger.info(
                "[T146] matched responsibility artifact for system_id=%s: %s",
                ctx.system_id,
                label,
            )

    logger.debug(
        "[T146] inspected %d artifact rows for system_id=%s",
        inspected,
        ctx.system_id,
    )

    if matching_docs:
        message = (
            "CONCERN: Responsibility / boundary documents were found "
            "(e.g. MOU, MOA, SLA, CRM, CSP/CSSP agreements), but automated "
            "validation of signatures, recency, and applicability is not "
            "available from current data sources. Manual verification required. "
            f"Documents: {', '.join(matching_docs)}"
        )
        logger.info(
            "[T146] CONCERN — responsibility docs present for system_id=%s: %s",
            ctx.system_id,
            ", ".join(matching_docs),
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.CONCERN,
            message=message,
        )
        status.add(tr)
        return tr

    # no responsibility docs at all → FAIL
    message = (
        "FAIL: No MOU/MOA/SLA/CRM/CSP/CSSP responsibility documents were "
        "identified for this system."
    )
    logger.warning(
        "[T146] FAIL — no responsibility/boundary documents found for system_id=%s",
        ctx.system_id,
    )
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.FAIL,
        message=message,
    )
    status.add(tr)
    return tr


def test_147(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Check for PKI Waiver artifacts (PS parity, structured-first).

    Overview
    --------
    This is a straight port of the original PowerShell logic:

    - Search this system's artifacts for "PKI Waiver".
    - If we find at least one → **CONCERN** ("PKI Waiver found, but we can't
      confirm applicability/authority/currency").
    - If we do **not** find any → **CONCERN** ("No PKI Waiver found, but we
      also can't confirm whether this system needed one").

    In other words, this test **always returns CONCERN**. The PowerShell
    comment even said this should be nested under applicability checks
    (e.g. only for NETCOM / SIS-CRN / specific mission owners), but those
    checks never got implemented — so we preserve that behavior.

    Modernization
    -------------
    1. Read from the nested Pydantic surfaces on `SystemContext` first
       (`ctx.artifact_details.data`, `ctx.artifact_summary.data`,
       optional `ctx.fixtures`).
    2. Only fall back to `ctx.raw_payloads.artifact_details` if the structured
       parts are empty.
    3. Case-insensitive field access for "Artifact Name" / "artifact_name" and
       "Filename" / "filename".
    4. Logging matches the suite pattern:
         - `[T147] using ...`
         - `[T147] found PKI Waiver ...`
         - `[T147] CONCERN — ...`

    Args:
        ctx (SystemContext): Authoritative snapshot of one eMASS system,
            including structured artifact surfaces and (optionally) raw JSON
            payloads for trace/debug.
        status (ATOStatus): Running accumulator of test results. This function
            appends its result.

    Returns:
        TestResult: Always `Result.CONCERN`. The message distinguishes between
        “found” and “not found”.

    Notes:
        - We do **not** implement "skip if system not applicable" because the
          PowerShell did not.
        - This test is intentionally conservative — it only tells the human
          reviewer what was and wasn’t present.
    """
    test_number = 147
    test_name = "Test 147: PKI Waiver present (if applicable)"

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Return value from `d` using a case-insensitive key match."""
        if not isinstance(d, dict):
            return default
        needle = key.lower()
        for k, v in d.items():
            if str(k).lower() == needle:
                return v
        return default

    def iter_artifact_rows() -> Iterable[Dict[str, Any]]:
        """Yield artifact-like rows from structured → raw, highest fidelity first.

        Order:
            1. ctx.artifact_details.data
            2. ctx.artifact_details (single row)
            3. ctx.artifact_summary.data
            4. ctx.fixtures.artifact_details.data   (if present)
            5. ctx.raw_payloads.artifact_details    (last resort)
        """
        # 1) main structured list
        if ctx.artifact_details and getattr(ctx.artifact_details, "data", None):
            logger.debug(
                "[T147] using ctx.artifact_details.data for system_id=%s",
                ctx.system_id,
            )
            for row in ctx.artifact_details.data:  # type: ignore[attr-defined]
                if isinstance(row, dict):
                    yield row
        # 2) single structured artifact_details
        elif ctx.artifact_details:
            logger.debug(
                "[T147] using ctx.artifact_details (single row) for system_id=%s",
                ctx.system_id,
            )
            yield ctx.artifact_details.model_dump(exclude_none=True)

        # 3) artifact summary list
        if ctx.artifact_summary and getattr(ctx.artifact_summary, "data", None):
            logger.debug(
                "[T147] using ctx.artifact_summary.data for system_id=%s",
                ctx.system_id,
            )
            for row in ctx.artifact_summary.data:  # type: ignore[attr-defined]
                if isinstance(row, dict):
                    yield row

        # 4) fixtures (optional)
        fixtures = getattr(ctx, "fixtures", None)
        if fixtures is not None:
            fad = getattr(fixtures, "artifact_details", None)
            if fad is not None:
                data = getattr(fad, "data", None)
                if data:
                    logger.debug(
                        "[T147] using ctx.fixtures.artifact_details.data for system_id=%s",
                        ctx.system_id,
                    )
                    for row in data:
                        if isinstance(row, dict):
                            yield row

        # 5) raw payloads
        if ctx.raw_payloads and ctx.raw_payloads.artifact_details:
            logger.debug(
                "[T147] using ctx.raw_payloads.artifact_details for system_id=%s",
                ctx.system_id,
            )
            for row in ctx.raw_payloads.artifact_details:
                if isinstance(row, dict):
                    yield row

    def looks_like_pki_waiver(row: Dict[str, Any]) -> bool:
        """Return True if artifact name/filename contains 'PKI Waiver'."""
        name_val = (
            ci_get(row, "Artifact Name", "")
            or ci_get(row, "artifact_name", "")
            or ""
        )
        file_val = (
            ci_get(row, "Filename", "")
            or ci_get(row, "filename", "")
            or ""
        )
        haystack = f"{name_val} {file_val}".lower()
        # PS used exactly "PKI Waiver" — keep parity.
        return "pki waiver" in haystack

    # ------------------------------------------------------------------ #
    # core logic
    # ------------------------------------------------------------------ #
    inspected = 0
    pki_hits: List[str] = []

    for art in iter_artifact_rows():
        inspected += 1
        if looks_like_pki_waiver(art):
            label = (
                ci_get(art, "Artifact Name")
                or ci_get(art, "artifact_name")
                or ci_get(art, "Filename")
                or ci_get(art, "filename")
                or "<unnamed PKI Waiver>"
            )
            pki_hits.append(str(label))
            logger.info(
                "[T147] found PKI Waiver candidate for system_id=%s: %s",
                ctx.system_id,
                label,
            )

    logger.debug(
        "[T147] inspected %d artifact rows for system_id=%s",
        inspected,
        ctx.system_id,
    )

    if pki_hits:
        # same as PS: CONCERN if found
        msg = (
            "CONCERN: PKI Waiver artifact(s) located, but automated validation of "
            "applicability, approval authority, and currency is not implemented. "
            "Manual review required. "
            f"Artifacts: {', '.join(pki_hits)}"
        )
        logger.info(
            "[T147] CONCERN — PKI Waiver artifacts present for system_id=%s: %s",
            ctx.system_id,
            ", ".join(pki_hits),
        )
    else:
        # same as PS: still CONCERN if not found
        msg = (
            "CONCERN: No PKI Waiver artifact found. This may be acceptable if the "
            "system does not require a waiver, but applicability logic (e.g. by "
            "owning org or enclave) is not implemented. Manual review required."
        )
        logger.warning(
            "[T147] CONCERN — no PKI Waiver artifact found for system_id=%s",
            ctx.system_id,
        )

    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.CONCERN,
        message=msg,
    )
    status.add(tr)
    return tr

def test_148(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Check for HBSS Waiver / HBSS-related artifacts (PS parity, structured-first).

    Overview
    --------
    This is a direct, modernized port of the original PowerShell logic:

    - Look through the system's artifacts for **either**:
        • "HBSS Waiver"
        • "Host Based Security System"
    - If we find at least one match → **CONCERN** ("HBSS Waiver Found.")
    - If we do **not** find any → **CONCERN** ("No HBSS Waiver Found.")
    - There is **no PASS** branch in the original script because the missing,
      harder logic (applicability, HBSS compliance, STIG alignment) was never
      implemented.

    Modernization
    -------------
    1. We read from the structured Pydantic surfaces on `SystemContext` **first**:
       `ctx.artifact_details.data`, then `ctx.artifact_details`, then
       `ctx.artifact_summary.data`, then optional `ctx.fixtures.*`.
    2. Only if those surfaces are empty do we fall back to
       `ctx.raw_payloads.artifact_details`.
    3. Field access is case-insensitive for "Artifact Name" / "artifact_name" and
       "Filename" / "filename".
    4. Logging matches the suite style:
         - `[T148] using ...`
         - `[T148] found HBSS Waiver candidate ...`
         - `[T148] CONCERN — ...`

    Behavior (PS parity)
    --------------------
    The PowerShell comments said, essentially:
    - “This should be nested to ensure the system is APPLICABLE”
    - “If you are HBSS compliant, we can skip this check (WIP)”
    That logic never shipped. We preserve that behavior: **always CONCERN**.

    Args:
        ctx (SystemContext): Authoritative snapshot of one eMASS system, with
            structured artifact/evidence surfaces and optional raw payloads.
        status (ATOStatus): Running test accumulator; this function appends a
            single `TestResult`.

    Returns:
        TestResult: Always `Result.CONCERN`. The message distinguishes between
        “HBSS waiver artifact(s) found” vs “No HBSS waiver artifact found”.

    Notes:
        - This test is intentionally conservative. It just tells the human
          reviewer what we *saw*, not whether the system *needed* the waiver.
        - A future version can short-circuit to N/A if we can prove HBSS
          compliant from scan/STIG data.
    """
    test_number = 148
    test_name = "Test 148: HBSS Waiver present (if applicable)"

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Return value from dict using a case-insensitive key match."""
        if not isinstance(d, dict):
            return default
        needle = key.lower()
        for k, v in d.items():
            if str(k).lower() == needle:
                return v
        return default

    def iter_artifact_rows() -> Iterable[Dict[str, Any]]:
        """Yield artifact-like rows from highest-fidelity → lowest-fidelity.

        Order:
            1. ctx.artifact_details.data
            2. ctx.artifact_details (single)
            3. ctx.artifact_summary.data
            4. ctx.fixtures.artifact_details.data
            5. ctx.raw_payloads.artifact_details
        """
        # 1) main structured list
        if ctx.artifact_details and getattr(ctx.artifact_details, "data", None):
            logger.debug(
                "[T148] using ctx.artifact_details.data for system_id=%s",
                ctx.system_id,
            )
            for row in ctx.artifact_details.data:  # type: ignore[attr-defined]
                if isinstance(row, dict):
                    yield row
        # 2) single structured artifact_details
        elif ctx.artifact_details:
            logger.debug(
                "[T148] using ctx.artifact_details (single row) for system_id=%s",
                ctx.system_id,
            )
            yield ctx.artifact_details.model_dump(exclude_none=True)

        # 3) artifact_summary.data
        if ctx.artifact_summary and getattr(ctx.artifact_summary, "data", None):
            logger.debug(
                "[T148] using ctx.artifact_summary.data for system_id=%s",
                ctx.system_id,
            )
            for row in ctx.artifact_summary.data:  # type: ignore[attr-defined]
                if isinstance(row, dict):
                    yield row

        # 4) fixtures (optional)
        fixtures = getattr(ctx, "fixtures", None)
        if fixtures is not None:
            fad = getattr(fixtures, "artifact_details", None)
            if fad is not None:
                data = getattr(fad, "data", None)
                if data:
                    logger.debug(
                        "[T148] using ctx.fixtures.artifact_details.data for system_id=%s",
                        ctx.system_id,
                    )
                    for row in data:
                        if isinstance(row, dict):
                            yield row

        # 5) raw payloads (last resort)
        if ctx.raw_payloads and ctx.raw_payloads.artifact_details:
            logger.debug(
                "[T148] using ctx.raw_payloads.artifact_details for system_id=%s",
                ctx.system_id,
            )
            for row in ctx.raw_payloads.artifact_details:
                if isinstance(row, dict):
                    yield row

    def looks_like_hbss_waiver(row: Dict[str, Any]) -> bool:
        """Return True if name/filename looks like an HBSS waiver."""
        name_val = (
            ci_get(row, "Artifact Name", "")
            or ci_get(row, "artifact_name", "")
            or ""
        )
        file_val = (
            ci_get(row, "Filename", "")
            or ci_get(row, "filename", "")
            or ""
        )
        haystack = f"{name_val} {file_val}".lower()
        keywords = (
            "hbss waiver",
            "host based security system",
        )
        return any(kw in haystack for kw in keywords)

    # ------------------------------------------------------------------ #
    # core logic
    # ------------------------------------------------------------------ #
    inspected = 0
    hbss_hits: List[str] = []

    for art in iter_artifact_rows():
        inspected += 1
        if looks_like_hbss_waiver(art):
            label = (
                ci_get(art, "Artifact Name")
                or ci_get(art, "artifact_name")
                or ci_get(art, "Filename")
                or ci_get(art, "filename")
                or "<unnamed HBSS waiver>"
            )
            hbss_hits.append(str(label))
            logger.info(
                "[T148] found HBSS Waiver candidate for system_id=%s: %s",
                ctx.system_id,
                label,
            )

    logger.debug(
        "[T148] inspected %d artifact rows for system_id=%s",
        inspected,
        ctx.system_id,
    )

    if hbss_hits:
        # PS branch: waiver(s) found → CONCERN
        message = (
            "CONCERN: HBSS Waiver / Host Based Security System artifact(s) located, "
            "but automated validation of requirement, approval authority, and host "
            "coverage is not implemented. Manual review required. "
            f"Artifacts: {', '.join(hbss_hits)}"
        )
        logger.info(
            "[T148] CONCERN — HBSS Waiver artifacts present for system_id=%s: %s",
            ctx.system_id,
            ", ".join(hbss_hits),
        )
    else:
        # PS branch: still CONCERN if not found
        message = (
            "CONCERN: No HBSS Waiver artifact found. This may be acceptable if the "
            "system is fully HBSS-compliant, but automated HBSS/STIG applicability "
            "checks are not implemented. Manual review required."
        )
        logger.warning(
            "[T148] CONCERN — no HBSS Waiver artifact found for system_id=%s",
            ctx.system_id,
        )

    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.CONCERN,
        message=message,
    )
    status.add(tr)
    return tr



def test_149(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Check that the system has a PIA signed within the last 3 years.

    Overview
    --------
    This is a structured, pythonic port of the original PowerShell test:

    - Compute a cutoff timestamp = now - 1095 days.
    - Walk all artifact sources for the system (structured first, raw last).
    - Identify artifacts that *look* like PIAs by name or filename:
        • contains "pia"
        • contains "privacy impact assessment"
    - For PIA-like artifacts, read the signed date (multiple field names supported)
      and treat it as epoch seconds.
    - If any PIA-like artifact has a signed date >= cutoff → PASS.
    - Otherwise → FAIL.

    Parity Notes
    ------------
    - The PS script mentions an NSS exception (NSS w/o PII), but it does *not*
      implement it. We also do *not* implement it here.
    - We preserve the PASS/FAIL shape: no CONCERN branch.

    Args:
        ctx (SystemContext): Single-system snapshot containing artifact surfaces
            (`artifact_details`, `artifact_summary`, optionally fixtures and raw payloads).
        status (ATOStatus): Aggregator to which we append the resulting TestResult.

    Returns:
        TestResult: PASS if we found ≥1 PIA signed in the last 3 years; otherwise FAIL.
    """
    test_number = 149
    test_name = "Test 149: Check if system has PIA < 3 years old"

    # ------------------------------------------------------------------ #
    # helper fns
    # ------------------------------------------------------------------ #
    def ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Return a value from a dict using a case-insensitive key match."""
        if not isinstance(d, dict):
            return default
        needle = key.lower()
        for k, v in d.items():
            if str(k).lower() == needle:
                return v
        return default

    def iter_artifact_rows() -> Iterable[Dict[str, Any]]:
        """Yield artifact rows from highest-fidelity sources to lowest.

        Order:
            1. ctx.artifact_details.data          (Pydantic -> list[dict])
            2. ctx.artifact_details                (single artifact_details model)
            3. ctx.artifact_summary.data
            4. ctx.fixtures.artifact_details.data  (if present)
            5. ctx.raw_payloads.artifact_details   (raw eMASS JSON list)
        """
        # 1) structured details list
        if ctx.artifact_details and getattr(ctx.artifact_details, "data", None):
            logger.debug("[T149] using ctx.artifact_details.data for system_id=%s", ctx.system_id)
            for row in ctx.artifact_details.data:  # type: ignore[attr-defined]
                if isinstance(row, dict):
                    yield row
        # 2) single structured details
        elif ctx.artifact_details:
            logger.debug("[T149] using single ctx.artifact_details for system_id=%s", ctx.system_id)
            yield ctx.artifact_details.model_dump(exclude_none=True)

        # 3) artifact summary
        if ctx.artifact_summary and getattr(ctx.artifact_summary, "data", None):
            logger.debug("[T149] using ctx.artifact_summary.data for system_id=%s", ctx.system_id)
            for row in ctx.artifact_summary.data:  # type: ignore[attr-defined]
                if isinstance(row, dict):
                    yield row

        # 4) fixtures
        fixtures = getattr(ctx, "fixtures", None)
        if fixtures is not None:
            f_ad = getattr(fixtures, "artifact_details", None)
            if f_ad is not None and getattr(f_ad, "data", None):
                logger.debug("[T149] using ctx.fixtures.artifact_details.data for system_id=%s", ctx.system_id)
                for row in f_ad.data:  # type: ignore[attr-defined]
                    if isinstance(row, dict):
                        yield row

        # 5) raw payloads
        if ctx.raw_payloads and ctx.raw_payloads.artifact_details:
            logger.debug("[T149] using ctx.raw_payloads.artifact_details for system_id=%s", ctx.system_id)
            for row in ctx.raw_payloads.artifact_details:
                if isinstance(row, dict):
                    yield row

    def is_pia_like(row: Dict[str, Any]) -> bool:
        """Return True if the artifact name/filename suggests it's a PIA."""
        name_val = (
            ci_get(row, "name", "")
            or ci_get(row, "Artifact Name", "")
            or ci_get(row, "artifact_name", "")
            or ""
        )
        file_val = (
            ci_get(row, "filename", "")
            or ci_get(row, "Filename", "")
            or ""
        )
        haystack = f"{name_val} {file_val}".lower()
        return (
            "pia" in haystack
            or "privacy impact assessment" in haystack
        )

    def parse_signed_epoch(row: Dict[str, Any]) -> Optional[float]:
        """Parse 'Signed Date' from various shapes into epoch seconds.

        Supports:
            - "Signed Date" (PS export)
            - "signed_date" (Pydantic field)
            - artifact_details.signed_date in ISO-ish string form
        """
        # common PS / CSV key
        raw_val = (
            ci_get(row, "Signed Date")
            or ci_get(row, "signed_date")
            or ci_get(row, "signedDate")
        )
        if raw_val in (None, "", "-"):
            return None

        # try straight epoch first
        try:
            return float(raw_val)
        except (TypeError, ValueError):
            pass

        # try to parse datetime-like string to epoch
        try:
            dt = datetime.fromisoformat(str(raw_val))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # core logic
    # ------------------------------------------------------------------ #
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=1095)
    cutoff_epoch = cutoff_dt.timestamp()

    inspected = 0
    fresh_pias: List[str] = []

    for art in iter_artifact_rows():
        inspected += 1
        if not is_pia_like(art):
            continue

        signed_epoch = parse_signed_epoch(art)
        if signed_epoch is None:
            logger.debug(
                "[T149] PIA-like artifact missing signed date for system_id=%s: %s",
                ctx.system_id,
                art,
            )
            continue

        if signed_epoch >= cutoff_epoch:
            # collect a display label
            label = (
                ci_get(art, "filename")
                or ci_get(art, "Filename")
                or ci_get(art, "name")
                or ci_get(art, "Artifact Name")
                or "<unnamed PIA>"
            )
            fresh_pias.append(str(label))
            logger.info(
                "[T149] found valid PIA (>= cutoff) for system_id=%s: %s",
                ctx.system_id,
                label,
            )

    logger.debug(
        "[T149] inspected %d artifact rows for system_id=%s (cutoff=%s)",
        inspected,
        ctx.system_id,
        cutoff_dt.isoformat(),
    )

    if not fresh_pias:
        message = (
            "FAIL: No PIA documents have been found signed within the last three years. "
            "Verify whether the system is NSS and contains PII before granting an exemption."
        )
        logger.warning(
            "[T149] FAIL — no recent PIA found for system_id=%s (inspected=%d)",
            ctx.system_id,
            inspected,
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=message,
        )
        status.add(tr)
        return tr

    message = "PASS: The PIA document(s) found: " + ", ".join(fresh_pias)
    logger.info(
        "[T149] PASS — recent PIA(s) found for system_id=%s: %s",
        ctx.system_id,
        ", ".join(fresh_pias),
    )
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=message,
    )
    status.add(tr)
    return tr



def test_150(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 150 — Ensure system has SCA-V / SCA-O / SAR evidence.

    Purpose
    -------
    Mirrors the original PowerShell test:

    - Build the search terms: {"SCA-V", "SCA-O", "SAR"}.
    - Look through the system's artifact details.
    - If *any* artifact name or filename contains one of those terms
      (case-insensitive) → **PASS**.
    - Otherwise → **CONCERN** (manual review).

    Differences from PowerShell
    ---------------------------
    The PS script called an internal helper (`Get-ArtifactInfo`) on a
    pre-filtered JSON blob. In this Python port we don't have that helper,
    so we:
      1. Walk all the known artifact locations on the context
         (ctx.artifact_details.data, ctx.fixtures.artifact_details.data,
          ctx.raw_payloads.artifact_details).
      2. Perform the same substring match the PS would have done.

    Args:
        ctx: Resolved, system-scoped context object for this test run.
        status: Shared ATO status accumulator (collects all TestResults).

    Returns:
        TestResult: PASS if any SCA-V/SCA-O/SAR artifact is found,
        otherwise CONCERN (never FAILS).
    """
    test_number = 150
    test_name = "Test 150: Ensure system has SCA-V / SCA-O / SAR"

    # -----------------------------
    # helpers
    # -----------------------------
    def ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Return d[key] in a case-insensitive way."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def iter_artifact_rows() -> Iterable[Dict[str, Any]]:
        """Yield raw artifact rows from all plausible places on the context.

        We do this because eMASS exports are not stable across environments
        and we want this test to be resilient.
        """
        # 1) canonical place on the current context
        if getattr(ctx, "artifact_details", None):
            # ctx.artifact_details is an ArtifactDetails model, real rows are under .data
            data = getattr(ctx.artifact_details, "data", None)
            if data:
                logger.debug("[T150] using ctx.artifact_details.data for system_id=%s", ctx.system_id)
                for row in data:
                    yield row

        # 2) fixture-style mounting (older runs)
        if getattr(ctx, "fixtures", None):
            fixtures_art = getattr(ctx.fixtures, "artifact_details", None)
            if fixtures_art and getattr(fixtures_art, "data", None):
                logger.debug("[T150] using ctx.fixtures.artifact_details.data for system_id=%s", ctx.system_id)
                for row in fixtures_art.data:  # type: ignore[attr-defined]
                    yield row

        # 3) raw payloads (sometimes this is just a list[dict])
        if getattr(ctx, "raw_payloads", None) and ctx.raw_payloads.artifact_details:
            logger.debug("[T150] using ctx.raw_payloads.artifact_details for system_id=%s", ctx.system_id)
            for row in ctx.raw_payloads.artifact_details:
                yield row

    def looks_like_target(row: Dict[str, Any]) -> bool:
        """Return True if row's name/filename suggests SCA-V/SCA-O/SAR."""
        name_val = str(
            ci_get(row, "Artifact Name")
            or ci_get(row, "artifact_name")
            or ci_get(row, "name")
            or ""
        ).lower()

        file_val = str(
            ci_get(row, "Filename")
            or ci_get(row, "filename")
            or ""
        ).lower()

        needles = ("sca-v", "sca-o", "sar")
        return any(n in name_val or n in file_val for n in needles)

    # -----------------------------
    # core logic (1:1 intent with PS)
    # -----------------------------
    matched: List[str] = []

    for art in iter_artifact_rows():
        if not isinstance(art, dict):
            continue

        if looks_like_target(art):
            # collect a displayable name
            display = (
                ci_get(art, "Filename")
                or ci_get(art, "filename")
                or ci_get(art, "Artifact Name")
                or ci_get(art, "artifact_name")
                or ci_get(art, "name")
                or "<unnamed>"
            )
            matched.append(str(display))

    if matched:
        msg = (
            f"PASS: SCA-V / SCA-O / SAR artifact(s) found for system {ctx.system_id}: "
            + ", ".join(matched)
        )
        logger.info("[T150] %s", msg)
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.PASS,
            message=msg,
        )
        status.add(tr)
        return tr

    # mirrors PS: no artifacts → CONCERN, not FAIL
    msg = (
        "CONCERN: No SCA-V / SCA-O / SAR artifacts were found. "
        "Manual review recommended to confirm assessment evidence."
    )
    logger.warning("[T150] %s (system_id=%s)", msg, ctx.system_id)
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.CONCERN,
        message=msg,
    )
    status.add(tr)
    return tr

def test_151(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """
    Test 151: Ensure system has SCA-V / SCA-O Recommendation Memo.

    Purpose
    -------
    Check whether the system has an uploaded recommendation memo from
    assessors (SCA-V or SCA-O). The PowerShell version treats the presence
    of any such artifact as PASS and anything else as CONCERN.

    What we check (1:1 with PowerShell)
    -----------------------------------
    - Search all artifact details for names/filenames containing:
        • "SCA-O Recommendation Memo"
        • "SCA-V Recommendation Memo"
        • "Recommendation Memo"
    - If ANY match is found → PASS.
    - Otherwise → CONCERN.

    Notes
    -----
    • The PowerShell script logs CONCERN when missing, not FAIL.
    • There is no date freshness check or signature validation.
    • We assume ctx.artifact_details is already filtered to this system.

    Outcomes
    --------
    - PASS    : Found at least one likely recommendation memo.
    - CONCERN : None found, manual review required.
    """
    test_name = (
        "Test 151: Ensure system has SCA-V / SCA-O Recommendation Memo"
    )

    def ci_get(d: Dict[str, Any], key: str, default=None):
        """
        Case-insensitive dict lookup.
        """
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def artifact_matches_terms(row: Dict[str, Any], terms: List[str]) -> bool:
        """
        Return True if the artifact's name or filename contains ANY of the
        provided term substrings (case-insensitive).
        Mirrors how Get-ArtifactInfo was used in PowerShell.
        """
        name_val = str(
            ci_get(row, "Artifact Name")
            or ci_get(row, "name")
            or ""
        ).lower()
        file_val = str(
            ci_get(row, "Filename")
            or ci_get(row, "filename")
            or ""
        ).lower()

        for term in terms:
            t = term.lower()
            if t in name_val or t in file_val:
                return True
        return False

    artifacts = ctx.artifact_details or []
    search_terms = [
        "SCA-O Recommendation Memo",
        "SCA-V Recommendation Memo",
        "Recommendation Memo",
    ]

    matching: List[str] = []
    for art in artifacts:
        if artifact_matches_terms(art, search_terms):
            label = (
                ci_get(art, "Filename")
                or ci_get(art, "filename")
                or ci_get(art, "Artifact Name")
                or ci_get(art, "name")
                or "<unnamed>"
            )
            matching.append(str(label))

    if matching:
        tr = TestResult(
            151,
            test_name,
            Result.PASS,
            "PASS: SCA-V / SCA-O Recommendation Memo found: "
            + ", ".join(matching),
        )
        status.add(tr)
        return tr

    tr = TestResult(
        151,
        test_name,
        Result.CONCERN,
        (
            "CONCERN: No SCA-V or SCA-O Recommendation Memo found. "
            "Manual review required to confirm if such a memo exists."
        ),
    )
    status.add(tr)
    return tr


def test_151(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 151 — Ensure system has SCA-V / SCA-O Recommendation Memo.

    Purpose
    -------
    Mirror the PowerShell behavior:
      - Look through the system’s artifacts.
      - If **any** artifact looks like “SCA-O Recommendation Memo”, “SCA-V Recommendation Memo”,
        or just “Recommendation Memo”, we consider the test **PASS**.
      - If none match, we emit **CONCERN** (PowerShell logged CONCERN here, not a hard FAIL).

    Why we have to do more than PowerShell
    --------------------------------------
    The PS script called `Get-ArtifactInfo` on a pre-filtered JSON blob. In Python we might have:
      1. `ctx.artifact_details.data` (canonical, typed),
      2. `ctx.fixtures.artifact_details.data` (older / fixture-style),
      3. `ctx.raw_payloads.artifact_details` (raw list[dict] straight from API).

    We walk **all** of them so the test stays stable even when the upstream ingestion changes.

    Args:
        ctx: System-scoped context with structured and raw eMASS payloads.
        status: Shared accumulator for all ATO test results.

    Returns:
        TestResult: PASS if we found ≥1 recommendation memo artifact, else CONCERN.
    """
    test_number = 151
    test_name = "Test 151: Ensure system has SCA-V / SCA-O Recommendation Memo"

    # PS-equivalent search terms
    search_terms = [
        "SCA-O Recommendation Memo",
        "SCA-V Recommendation Memo",
        "Recommendation Memo",
    ]

    def ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict lookup."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def iter_artifact_rows() -> Iterable[Dict[str, Any]]:
        """Yield raw artifact rows from every plausible source on the context."""
        # 1) canonical / typed path
        if getattr(ctx, "artifact_details", None):
            data = getattr(ctx.artifact_details, "data", None)
            if data:
                logger.debug("[T151] using ctx.artifact_details.data for system_id=%s", ctx.system_id)
                for row in data:
                    yield row

        # 2) fixture-style path
        if getattr(ctx, "fixtures", None):
            fixtures_art = getattr(ctx.fixtures, "artifact_details", None)
            if fixtures_art and getattr(fixtures_art, "data", None):
                logger.debug("[T151] using ctx.fixtures.artifact_details.data for system_id=%s", ctx.system_id)
                for row in fixtures_art.data:  # type: ignore[attr-defined]
                    yield row

        # 3) raw payloads path (this one is usually already a list[dict])
        if getattr(ctx, "raw_payloads", None) and ctx.raw_payloads.artifact_details:
            logger.debug("[T151] using ctx.raw_payloads.artifact_details for system_id=%s", ctx.system_id)
            for row in ctx.raw_payloads.artifact_details:
                yield row

    def artifact_matches_terms(row: Dict[str, Any]) -> bool:
        """Return True if this artifact’s name or filename contains ANY target term."""
        name_val = str(
            ci_get(row, "Artifact Name")
            or ci_get(row, "artifact_name")
            or ci_get(row, "name")
            or ""
        ).lower()
        file_val = str(
            ci_get(row, "Filename")
            or ci_get(row, "filename")
            or ""
        ).lower()

        for term in search_terms:
            t = term.lower()
            if t in name_val or t in file_val:
                return True
        return False

    matches: List[str] = []

    for art in iter_artifact_rows():
        if not isinstance(art, dict):
            continue
        if artifact_matches_terms(art):
            label = (
                ci_get(art, "Filename")
                or ci_get(art, "filename")
                or ci_get(art, "Artifact Name")
                or ci_get(art, "artifact_name")
                or ci_get(art, "name")
                or "<unnamed>"
            )
            matches.append(str(label))

    # -----------------------------
    # same outcomes as PowerShell
    # -----------------------------
    if matches:
        msg = "PASS: SCA-V / SCA-O Recommendation Memo found: " + ", ".join(matches)
        logger.info("[T151] %s (system_id=%s)", msg, ctx.system_id)
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.PASS,
            message=msg,
        )
        status.add(tr)
        return tr

    # PS used CONCERN text but incremented the fail counter — we keep the semantic CONCERN result.
    msg = (
        "CONCERN: No SCA-V or SCA-O Recommendation Memo found. "
        "Manual review required to confirm assessor documentation."
    )
    logger.warning("[T151] %s (system_id=%s)", msg, ctx.system_id)
    tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.CONCERN,
            message=msg,
    )
    status.add(tr)
    return tr


def test_152(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 152 — Ensure system has Nessus/ACAS assessment scan results.

    Purpose
    -------
    This is the lightweight predecessor to Test 153. The original PowerShell
    script only verified **presence** of a Nessus/ACAS-style artifact — it did
    **not** validate file extension, age, or scan depth.

    We keep that intent:
      - Look through artifacts for **any** of:
          • "Nessus"
          • "ACAS"
          • "Assessment Scan Results"
      - If at least one artifact's name/filename contains one of those terms → PASS
      - Otherwise → FAIL

    Why it’s slightly more defensive here
    -------------------------------------
    In PowerShell, `Get-ArtifactInfo` was handed a pre-filtered JSON object.
    In Python,  ingestion can surface artifacts in multiple places, so we
    walk all plausible sources on the `SystemContext` to make this test robust
    across exports.

    Args:
        ctx: Canonical system snapshot containing artifacts (possibly in several
             sub-containers).
        status: Shared test-aggregator. This function appends its `TestResult`
                to it.

    Returns:
        TestResult: PASS if we found a matching artifact, otherwise FAIL.
    """
    test_number = 152
    test_name = "Test 152: Ensure system has Nessus/ACAS Assessment Scan Results"

    # PowerShell search terms
    search_terms: List[str] = ["Nessus", "ACAS", "Assessment Scan Results"]

    def ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict lookup.

        We do this instead of hard-coding only "Filename" because eMASS exports
        aren’t perfectly consistent and we want the test to be tolerant.
        """
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def iter_artifacts() -> Iterable[Dict[str, Any]]:
        """Yield artifact rows from every plausible source on the context.

        We support three shapes:
        1) ctx.artifact_details.data           ← typed model
        2) ctx.fixtures.artifact_details.data  ← fixture container
        3) ctx.raw_payloads.artifact_details   ← raw list[dict]

        We also guard for the case where `ctx.artifact_details` is
        **already** a list of dicts (some pipelines do that).
        """
        # 1) canonical typed path
        ad = getattr(ctx, "artifact_details", None)
        if ad is not None:
            # could be a Pydantic object with .data
            data = getattr(ad, "data", None)
            if data:
                logger.debug("[T152] using ctx.artifact_details.data (system_id=%s)", ctx.system_id)
                for row in data:
                    yield row
            # or it could already be a list[dict]
            elif isinstance(ad, list):
                logger.debug("[T152] using ctx.artifact_details list (system_id=%s)", ctx.system_id)
                for row in ad:
                    yield row

        # 2) fixtures path
        fixtures = getattr(ctx, "fixtures", None)
        if fixtures is not None:
            fixtures_ad = getattr(fixtures, "artifact_details", None)
            if fixtures_ad is not None and getattr(fixtures_ad, "data", None):
                logger.debug("[T152] using ctx.fixtures.artifact_details.data (system_id=%s)", ctx.system_id)
                for row in fixtures_ad.data:  # type: ignore[attr-defined]
                    yield row

        # 3) raw payloads path
        if getattr(ctx, "raw_payloads", None) and ctx.raw_payloads.artifact_details:
            logger.debug("[T152] using ctx.raw_payloads.artifact_details (system_id=%s)", ctx.system_id)
            for row in ctx.raw_payloads.artifact_details:
                yield row

    def artifact_matches(row: Dict[str, Any]) -> bool:
        """Return True if artifact name or filename contains any search term."""
        name_val = str(
            ci_get(row, "Artifact Name")
            or ci_get(row, "artifact_name")
            or ci_get(row, "name")
            or ""
        ).lower()
        file_val = str(
            ci_get(row, "Filename")
            or ci_get(row, "filename")
            or ""
        ).lower()

        for term in search_terms:
            t = term.lower()
            if t in name_val or t in file_val:
                return True
        return False

    matching_labels: List[str] = []

    for art in iter_artifacts():
        if not isinstance(art, dict):
            continue

        if not artifact_matches(art):
            continue

        label = (
            ci_get(art, "Filename")
            or ci_get(art, "filename")
            or ci_get(art, "Artifact Name")
            or ci_get(art, "artifact_name")
            or "<unnamed>"
        )
        matching_labels.append(str(label))

    if matching_labels:
        msg = (
            "PASS: Nessus/ACAS assessment scan result artifact(s) found: "
            + ", ".join(matching_labels)
        )
        logger.info("[T152] %s (system_id=%s)", msg, ctx.system_id)
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.PASS,
            message=msg,
        )
        status.add(tr)
        return tr

    # No matching artifact found → FAIL (same semantics as PS)
    msg = "FAIL: No Nessus/ACAS assessment scan results found."
    logger.warning("[T152] %s (system_id=%s)", msg, ctx.system_id)
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.FAIL,
        message=msg,
    )
    status.add(tr)
    return tr


def test_153(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 153 — Ensure system has recent Nessus/ACAS scan results.

    Purpose
    -------
    Mirror the PowerShell script:
      - Look through artifacts for "Nessus", "ACAS", or "Assessment Scan Results".
      - Require the file to be in **.nessus** or **.csv** format (PDFs don’t count).
      - Require the artifact to be **recent** (last 30 days).
      - If any artifact satisfies **both** format + recency → PASS.
      - Otherwise → FAIL.

    Why this looks a bit more complex than PowerShell
    -------------------------------------------------
    PS called `Get-ArtifactInfo` with a pre-filtered JSON object.
    In Python you may receive artifacts in multiple places:
      1. `ctx.artifact_details.data`
      2. `ctx.fixtures.artifact_details.data`
      3. `ctx.raw_payloads.artifact_details` (already a `list[dict]`)
    We walk all of them so the test doesn't break when ingestion changes.

    Args:
        ctx: Structured system context containing artifact metadata.
        status: Shared test accumulator. We append our result here.

    Returns:
        TestResult: PASS if we found ≥1 recent .nessus/.csv Nessus/ACAS artifact;
                    otherwise FAIL.
    """
    test_number = 153
    test_name = (
        "Test 153: Ensure system has recent Nessus/ACAS scan results "
        "in .nessus or .csv, ≤30 days old"
    )

    # PS search terms
    search_terms = ["Nessus", "ACAS", "Assessment Scan Results"]

    # Build the 30-day cutoff like PS does
    now_epoch = datetime.now(timezone.utc).timestamp()
    thirty_days_seconds = 30 * 86400
    cutoff_epoch = now_epoch - thirty_days_seconds

    def ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict lookup."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def iter_artifacts() -> Iterable[Dict[str, Any]]:
        """Yield artifact rows from every plausible source on the context."""
        # 1) canonical path
        if getattr(ctx, "artifact_details", None):
            data = getattr(ctx.artifact_details, "data", None)
            if data:
                logger.debug("[T153] using ctx.artifact_details.data for system_id=%s", ctx.system_id)
                for row in data:
                    yield row

        # 2) fixture path
        if getattr(ctx, "fixtures", None):
            fixtures_art = getattr(ctx.fixtures, "artifact_details", None)
            if fixtures_art and getattr(fixtures_art, "data", None):
                logger.debug("[T153] using ctx.fixtures.artifact_details.data for system_id=%s", ctx.system_id)
                for row in fixtures_art.data:  # type: ignore[attr-defined]
                    yield row

        # 3) raw payloads path
        if getattr(ctx, "raw_payloads", None) and ctx.raw_payloads.artifact_details:
            logger.debug("[T153] using ctx.raw_payloads.artifact_details for system_id=%s", ctx.system_id)
            for row in ctx.raw_payloads.artifact_details:
                yield row

    def artifact_matches_terms(row: Dict[str, Any]) -> bool:
        """True if artifact name or filename mentions any of the Nessus/ACAS terms."""
        name_val = str(
            ci_get(row, "Artifact Name")
            or ci_get(row, "artifact_name")
            or ci_get(row, "name")
            or ""
        ).lower()
        file_val = str(
            ci_get(row, "Filename")
            or ci_get(row, "filename")
            or ""
        ).lower()

        for term in search_terms:
            t = term.lower()
            if t in name_val or t in file_val:
                return True
        return False

    def parse_last_modified_epoch(row: Dict[str, Any]) -> Optional[float]:
        """Try to coerce 'Last Modified' to epoch seconds, like the PS script."""
        raw_val = ci_get(row, "Last Modified")
        if raw_val in (None, "", "-"):
            return None
        try:
            return float(raw_val)
        except (TypeError, ValueError):
            return None

    def is_recent(epoch_seconds: float) -> bool:
        """Check if artifact timestamp is within the last 30 days."""
        return epoch_seconds >= cutoff_epoch

    def has_valid_extension(filename: str) -> bool:
        """Match the PS regex '\\.nessus$|\\.csv$' using a lowercase endswith."""
        fl = filename.lower()
        return fl.endswith(".nessus") or fl.endswith(".csv")


    passing_artifacts: List[str] = []

    for art in iter_artifacts():
        if not isinstance(art, dict):
            continue

        # Must be a Nessus/ACAS-ish artifact
        if not artifact_matches_terms(art):
            continue

        last_modified_epoch = parse_last_modified_epoch(art)
        filename_val = (
            ci_get(art, "Filename")
            or ci_get(art, "filename")
            or ""
        )

        if last_modified_epoch is None or not filename_val:
            continue

        if is_recent(last_modified_epoch) and has_valid_extension(filename_val):
            # Human readable timestamp in *local* time, like PS did
            dt_human = (
                datetime.fromtimestamp(last_modified_epoch, tz=timezone.utc)
                .astimezone()
                .strftime("%m/%d/%Y %I:%M:%S %p")
            )
            passing_artifacts.append(f"{filename_val} (Last Modified {dt_human})")
            # PS breaks on first pass — we can break too to match behavior exactly.
            break

    if passing_artifacts:
        msg = (
            "PASS: Found recent Nessus/ACAS scan result(s) in acceptable format: "
            + "; ".join(passing_artifacts)
        )
        logger.info("[T153] %s (system_id=%s)", msg, ctx.system_id)
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.PASS,
            message=msg,
        )
        status.add(tr)
        return tr

    # If we get here, we didn't find a valid/ recent .nessus/.csv
    msg = (
        "FAIL: No valid Nessus/ACAS scan results were found within the last 30 days "
        "in .nessus or .csv format."
    )
    logger.error("[T153] %s (system_id=%s)", msg, ctx.system_id)
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.FAIL,
        message=msg,
    )
    status.add(tr)
    return tr


def test_154(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 154 — Ensure system has all self-assessment .ckls completed.

    Purpose
    -------
    The original PowerShell check didn’t (and couldn’t) verify actual CKL
    completion because eMASS didn’t expose the underlying checklist contents.
    Instead, it just emitted a concern saying: “this needs manual review.”

    We mirror that 1:1 in Python:
      - Always return CONCERN
      - Tell the operator/manual reviewer why
      - Log in our normal test style so it’s obvious in Kibana/ELK

    Args:
        ctx: Current system context. Kept for interface consistency even though
             this test does not currently inspect artifacts.
        status: Aggregator that collects all test results.

    Returns:
        TestResult: Always a CONCERN result explaining that CKL completion
        cannot be validated from the current dataset.
    """
    test_number = 154
    test_name = "Test 154: Ensure system has all self-assessment .ckls completed"

    message = (
        "CONCERN: eMASS / current dataset does not expose self-assessment "
        "checklist (.ckl) completion details. Manual review required."
    )

    logger.warning("[T154] %s (system_id=%s)", message, getattr(ctx, "system_id", "unknown"))

    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.CONCERN,
        message=message,
    )
    status.add(tr)
    return tr


def test_155(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 155 — Check for deployment/fielding guidance artifacts.

    Purpose
    -------
    The original PowerShell logic looked for artifacts like:
      - "Fielding Guide"
      - "Fielding Manual"
      - "Deployment Guide"
      - "Deployment Manual"
    …but regardless of whether they were found, it **always** reported
    a CONCERN because applicability is mission-/program-/role-dependent
    (e.g. CSSP, SIS, CRN). We mirror that 1:1.

    Behavior
    --------
    - If we find *any* matching artifact name/filename:
        → CONCERN: present, manual review required
    - If we find *none*:
        → CONCERN: not present, manual review required
    - There is no PASS path today.

    Args:
        ctx: Current system context; may hold artifacts as a list or a
             pydantic model with `.data`.
        status: Aggregator to which we append the result.

    Returns:
        TestResult: Always CONCERN, with a message indicating whether
        something was found.
    """
    test_number = 155
    test_name = (
        "Test 155: Check for Fielding/Deployment guides identifying "
        "receiving unit responsibilities"
    )

    # --- pull artifacts in a tolerant way (list or model-with-.data) ---
    raw_artifacts = ctx.artifact_details
    if isinstance(raw_artifacts, list):
        artifacts: List[Dict[str, Any]] = raw_artifacts
    elif hasattr(raw_artifacts, "data") and isinstance(raw_artifacts.data, list):
        artifacts = raw_artifacts.data  # type: ignore[assignment]
    else:
        artifacts = []

    search_terms = [
        "Fielding Guide",
        "Fielding Manual",
        "Deployment Guide",
        "Deployment Manual",
    ]

    def ci_get(d: Dict[str, Any], key: str, default: Optional[Any] = None) -> Optional[Any]:
        """Case-insensitive dict lookup."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def artifact_matches_terms(row: Dict[str, Any], terms: List[str]) -> bool:
        """Return True if artifact name OR filename contains any term (CI)."""
        name_val = str(
            ci_get(row, "Artifact Name")
            or ci_get(row, "name")
            or ""
        ).lower()
        file_val = str(
            ci_get(row, "Filename")
            or ci_get(row, "filename")
            or ""
        ).lower()

        for term in terms:
            t = term.lower()
            if t in name_val or t in file_val:
                return True
        return False

    matching: List[str] = []
    for art in artifacts:
        if artifact_matches_terms(art, search_terms):
            label = (
                ci_get(art, "Filename")
                or ci_get(art, "filename")
                or ci_get(art, "Artifact Name")
                or ci_get(art, "name")
                or "<unnamed>"
            )
            matching.append(str(label))

    if matching:
        message = (
            "CONCERN: Fielding / Deployment guidance artifacts present: "
            + ", ".join(matching)
            + ". Manual review required to confirm applicability and "
              "receiving-unit responsibilities."
        )
        logger.warning(
            "[T155] Deployment/Fielding artifacts present (%d) for system_id=%s",
            len(matching),
            getattr(ctx, "system_id", "unknown"),
        )
    else:
        message = (
            "CONCERN: No Fielding / Deployment guidance artifacts found. "
            "Manual review required to determine if such documentation is "
            "required for this system (e.g. SIS/CRN/CSSP role)."
        )
        logger.warning(
            "[T155] No deployment/fielding artifacts found for system_id=%s",
            getattr(ctx, "system_id", "unknown"),
        )

    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.CONCERN,
        message=message,
    )
    status.add(tr)
    return tr



def test_156(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 156 — Prior NETCOM / SCA-V / independent validation evidence.

    Purpose
    -------
    The original PowerShell script checked whether the system already had
    documentation from:
      - a NETCOM Control Assessor,
      - an "Independent Validation", or
      - an SCA-V team.
    If **any** such artifact was present, it marked the test as **PASS** and
    printed the artifact(s). Otherwise it marked the test as **CONCERN**.
    There was no explicit FAIL path.

    We mirror that behavior 1:1, but in a Pythonic way that works with our
    pydantic models and mixed artifact shapes.

    Behavior
    --------
    1. Pull artifacts from `ctx.artifact_details`:
       - if it's a list, use it as-is;
       - if it's a pydantic `ArtifactDetails` with `.data`, use `.data`;
       - else, assume no artifacts.
    2. Case-insensitive match on name/filename against:
         - "Control Assessor"
         - "Independent Validation"
         - "SCA-V"
    3. If **any** match → PASS (with list of hits).
       Else → CONCERN (manual review).

    Args:
        ctx: Current system context, holding artifact metadata.
        status: ATOStatus aggregator to which we append this test result.

    Returns:
        TestResult: PASS if any relevant artifacts exist, else CONCERN.
    """
    test_number = 156
    test_name = (
        "Test 156: Previous NETCOM Control Assessor recommendation or "
        "independent validation present"
    )

    # --- normalize artifact shape (list vs. ArtifactDetails(data=[...])) ---
    raw_artifacts = ctx.artifact_details
    if isinstance(raw_artifacts, list):
        artifacts: List[Dict[str, Any]] = raw_artifacts
    elif hasattr(raw_artifacts, "data") and isinstance(raw_artifacts.data, list):
        artifacts = raw_artifacts.data  # type: ignore[assignment]
    else:
        artifacts = []

    search_terms = [
        "Control Assessor",
        "Independent Validation",
        "SCA-V",
    ]

    def ci_get(d: Dict[str, Any], key: str, default: Optional[Any] = None) -> Optional[Any]:
        """Return value from dict using case-insensitive key lookup."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def artifact_matches_terms(row: Dict[str, Any], terms: List[str]) -> bool:
        """Return True if artifact name or filename contains any search term."""
        name_val = str(
            ci_get(row, "Artifact Name")
            or ci_get(row, "name")
            or ""
        ).lower()
        file_val = str(
            ci_get(row, "Filename")
            or ci_get(row, "filename")
            or ""
        ).lower()

        for term in terms:
            t = term.lower()
            if t in name_val or t in file_val:
                return True
        return False

    matching: List[str] = []
    for art in artifacts:
        if artifact_matches_terms(art, search_terms):
            label = (
                ci_get(art, "Filename")
                or ci_get(art, "filename")
                or ci_get(art, "Artifact Name")
                or ci_get(art, "name")
                or "<unnamed>"
            )
            matching.append(str(label))

    system_id = getattr(ctx, "system_id", "unknown")

    if matching:
        # PowerShell: PASS when ANY relevant artifact exists
        message = (
            "PASS: Found evidence of prior assessment/validation: "
            + ", ".join(matching)
            + "."
        )
        logger.info(
            "[T156] Found %d validation artifact(s) for system_id=%s: %s",
            len(matching),
            system_id,
            ", ".join(matching),
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.PASS,
            message=message,
        )
        status.add(tr)
        return tr

    # PowerShell: CONCERN when none found
    message = (
        "CONCERN: No artifacts indicating a NETCOM Control Assessor "
        "recommendation, SCA-V, or independent validation were found. "
        "Manual review required."
    )
    logger.warning(
        "[T156] No control-assessor / independent-validation artifacts found "
        "for system_id=%s",
        system_id,
    )
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.CONCERN,
        message=message,
    )
    status.add(tr)
    return tr



def test_157(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 157 — Terms and Conditions Approval Workflow exists.

    Purpose
    -------
    Mirror the original PowerShell check that ensured a system had a
    "Terms and Conditions Approval Workflow". In PS, this was a straight
    PASS/FAIL test based on whether the workflow was present.

    Data sources we support
    -----------------------
    Because our Python `SystemContext` can hold workflow info in several places,
    we look in this order and merge:
      1. `ctx.raw_payloads.workflows_instances` (raw list from ingest)
      2. `ctx.workflows.data` (structured pydantic `Workflows`)
      3. `ctx.workflow_dashboard.data` (sometimes present as another view)

    Behavior
    --------
    - If ANY row looks like "Terms and Conditions Approval Workflow"
      (case-insensitive substring in name/workflow/packageName),
      → PASS and surface its package name if available.
    - Otherwise → FAIL.

    Args:
        ctx: SystemContext for the current system.
        status: ATOStatus aggregator to append the result to.

    Returns:
        TestResult: PASS if workflow found, else FAIL.
    """
    test_number = 157
    test_name = "Test 157: Terms and Conditions Approval Workflow is present"
    target = "terms and conditions approval workflow"
    system_id = getattr(ctx, "system_id", "unknown")

    # --- 1) collect workflow rows from all the plausible places ---
    workflows: List[Dict[str, Any]] = []

    # a) raw payloads ( original code was trying to read this but from ctx.* directly)
    rp = getattr(ctx, "raw_payloads", None)
    if rp is not None and getattr(rp, "workflows_instances", None):
        if isinstance(rp.workflows_instances, list):
            workflows.extend(rp.workflows_instances)

    # b) structured `ctx.workflows` (pydantic Workflows model)
    wf_model = getattr(ctx, "workflows", None)
    if wf_model is not None:
        wf_data = getattr(wf_model, "data", None)
        if isinstance(wf_data, list):
            workflows.extend(wf_data)

    # c) sometimes there's workflow data on the dashboard
    wf_dash = getattr(ctx, "workflow_dashboard", None)
    if wf_dash is not None:
        dash_data = getattr(wf_dash, "data", None)
        if isinstance(dash_data, list):
            workflows.extend(dash_data)

    def ci_get(d: Dict[str, Any], key: str, default: Optional[Any] = None) -> Optional[Any]:
        """Return dict value using case-insensitive key lookup."""
        if not isinstance(d, dict):
            return default
        key_l = key.lower()
        for k, v in d.items():
            if str(k).lower() == key_l:
                return v
        return default

    def is_terms_and_conditions_workflow(row: Dict[str, Any]) -> bool:
        """Heuristic match against common workflow fields."""
        candidates = [
            ci_get(row, "name", ""),
            ci_get(row, "workflow", ""),
            ci_get(row, "packageName", ""),
            ci_get(row, "packagename", ""),
            ci_get(row, "title", ""),
        ]
        return any(
            isinstance(val, str) and target in val.strip().lower()
            for val in candidates
        )

    found_row: Optional[Dict[str, Any]] = None
    for wf in workflows:
        if not isinstance(wf, dict):
            # some ingest paths could have strings/ids — ignore those
            continue
        if is_terms_and_conditions_workflow(wf):
            found_row = wf
            break

    if found_row is None:
        # PowerShell: FAIL branch
        msg = (
            "FAIL: No 'Terms and Conditions Approval Workflow' was found for this system."
        )
        logger.warning("[T157] %s system_id=%s", msg, system_id)
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        return tr

    # PowerShell: PASS branch
    pkg_name = (
        ci_get(found_row, "packageName")
        or ci_get(found_row, "packagename")
        or ci_get(found_row, "name")
        or "<unnamed package>"
    )
    msg = (
        "PASS: 'Terms and Conditions Approval Workflow' found: "
        f"{pkg_name}"
    )
    logger.info(
        "[T157] Found terms-and-conditions workflow for system_id=%s: %s",
        system_id,
        pkg_name,
    )
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=msg,
    )
    status.add(tr)
    return tr

def test_158(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 158 — disallowed inheritance (Sentinel / DoD Tier1 / Army Tier2 CCP).

    Purpose
    -------
    Port the original PowerShell check:

      1. Pull the system's association/inheritance rows.
      2. Look for associations whose **Associated System ID** is either
         `"3915"` or `"2315"`.
      3. Then (this is the odd part) the PS script does this:
            if ($null -eq $badinheritance) { FAIL } else { PASS }
         i.e. **no bad entries → FAIL**, **some bad entries → PASS**.
         We intentionally keep this inversion to stay 1:1 with the current
         behavior so you can diff Python vs. PowerShell runs.

    Data sources
    ------------
    Because in our Python model associations can show up in a couple of places,
    we normalize them from:
      - `ctx.raw_payloads.associations_details` (preferred, raw list)
      - `ctx.associations.data` (structured pydantic model)
      - `ctx.associations` itself, if it looks like a dict with a matching
        system id

    Matching rules
    --------------
    - We match associated system ID strings **exactly** against:
        {"3915", "2315"}
    - We also filter rows to the current system:
        row["System ID"] == ctx.system_id   (case-insensitive lookup)

    Returns
    -------
    TestResult
        - FAIL: if **no** disallowed inheritances were found
        - PASS: if **at least one** disallowed inheritance was found
          (this keeps the original PS inversion)
    """
    test_number = 158
    test_name = (
        "Test 158: Receiving inheritance from 'Army Sentinel CCP' / "
        "DoD Tier1 CCP / Army Tier 2 CCP removed"
    )
    system_id = getattr(ctx, "system_id", None)

    # ------------------------
    # helpers
    # ------------------------
    def ci_get(d: Dict[str, Any], key: str, default: Optional[Any] = None) -> Optional[Any]:
        """Case-insensitive dict lookup."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    # ------------------------
    # 1) collect associations from every place we store them
    # ------------------------
    associations: List[Dict[str, Any]] = []

    # a) raw payload list (this is what  failing code tried to read)
    rp = getattr(ctx, "raw_payloads", None)
    if rp is not None:
        raw_list = getattr(rp, "associations_details", None)
        if isinstance(raw_list, list):
            associations.extend(raw_list)

    # b) structured Associations model
    assoc_model = getattr(ctx, "associations", None)
    if assoc_model is not None:
        # could be a list under .data
        assoc_data = getattr(assoc_model, "data", None)
        if isinstance(assoc_data, list):
            associations.extend(assoc_data)
        else:
            # sometimes it's just one association shaped like a dict
            if isinstance(assoc_model, dict):
                associations.append(assoc_model)  # type: ignore[arg-type]

    # at this point `associations` is just a flat list of dicts (maybe empty)

    # ------------------------
    # 2) filter to this system (like the PS `| where { $_."System ID" -eq $systemID }`)
    # ------------------------
    filtered_rows: List[Dict[str, Any]] = []
    for row in associations:
        if not isinstance(row, dict):
            continue
        row_sys_id = ci_get(row, "System ID") or ci_get(row, "system_id")
        # if system_id is None, we just accept all rows
        if system_id is None or str(row_sys_id).strip() == str(system_id).strip():
            filtered_rows.append(row)

    # ------------------------
    # 3) apply the disallowed inheritance check
    # ------------------------
    forbidden_ids = {"3915", "2315"}
    bad_inheritance: List[str] = []

    for assoc in filtered_rows:
        assoc_sys_id = ci_get(assoc, "Associated System ID") or ci_get(assoc, "associated_system_id")
        if not assoc_sys_id:
            continue
        assoc_sys_id_s = str(assoc_sys_id).strip()
        if assoc_sys_id_s in forbidden_ids:
            bad_inheritance.append(assoc_sys_id_s)

    # ------------------------
    # 4) reproduce the *inverted* PowerShell logic
    # ------------------------
    if not bad_inheritance:
        # PS branch:
        # if ($null -eq $badinheritance) { FAIL ... }
        msg = (
            "FAIL: The system is inheriting from system ID 3915 or 2315: "
            f"{', '.join(bad_inheritance) if bad_inheritance else 'None'} "
            "(note: behavior mirrors legacy PowerShell, which flags the "
            "absence of these rows as a failure)."
        )
        logger.warning("[T158] %s system_id=%s", msg, system_id)
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        return tr

    # else branch (PS): PASS
    msg = (
        "PASS: The not allowed inheritances are not present "
        f"(found rows referencing: {', '.join(bad_inheritance)}). "
        "This mirrors legacy PowerShell logic, which treats presence as PASS."
    )
    logger.info(
        "[T158] %s system_id=%s", msg, system_id
    )
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=msg,
    )
    status.add(tr)
    return tr


def test_159(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Validate required inheritance relationships for the system.

    This test is a Pythonic, model-aware port of the original PowerShell
    script:

    - Always require the **AMC Policy Record** (Associated System ID `4642`)
    - If the system is **cloud**, also require **Army CCP Cloud** (ID `5050`)
    - If the system is **not cloud**, require **Army CCP policy** (ID `3915`)
    - Produce **PASS** only when the applicable set is present
    - Produce **FAIL** with a targeted message otherwise

    We modernize this to work with the current Pydantic models by pulling
    associations from:
      1. `ctx.raw_payloads.associations_details` (raw eMASS list)
      2. `ctx.associations.data` (structured array)
      3. `ctx.associations` itself, when it looks like a single association

    Args:
        ctx: Current system context, including raw payloads and structured views.
        status: Running ATO status accumulator.

    Returns:
        A `TestResult` marked PASS or FAIL, also pushed into `status`.
    """
    test_number = 159
    test_name = (
        "Test 159: Required inheritance (AMC PR, CCP cloud/non-cloud) is established"
    )
    system_id = getattr(ctx, "system_id", None)

    # -------------------------------------------------------------------------
    # small helpers
    # -------------------------------------------------------------------------
    def ci_get(d: Dict[str, Any], key: str, default: Optional[Any] = None) -> Optional[Any]:
        """Case-insensitive dict lookup."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def infer_is_cloud(ctx: SystemContext) -> bool:
        """Best-effort inference of the 'cloud' flag from multiple model surfaces."""
        # 1) top-level
        if ctx.cloud_computing is not None:
            return bool(ctx.cloud_computing)

        # 2) system_info
        si = getattr(ctx, "system_info", None)
        if si is not None and getattr(si, "cloudcomputing", None) is not None:
            return bool(si.cloudcomputing)

        # 3) system_details_dashboard (stringy sometimes)
        sdd = getattr(ctx, "system_details_dashboard", None)
        if sdd is not None and getattr(sdd, "cloud_computing", None) is not None:
            val = sdd.cloud_computing
            # normalize stringy "True"/"False"
            sval = str(val).strip().lower()
            if sval in {"true", "yes", "y", "1"}:
                return True
            if sval in {"false", "no", "n", "0"}:
                return False
            return bool(val)

        return False

    logger.info("[T159] Starting test — system_id=%s", system_id)

    # -------------------------------------------------------------------------
    # 1) Collect association rows from ALL known locations
    # -------------------------------------------------------------------------
    associations: List[Dict[str, Any]] = []

    # a) raw payloads
    raw_payloads = getattr(ctx, "raw_payloads", None)
    if raw_payloads is not None:
        raw_assoc = getattr(raw_payloads, "associations_details", None)
        if isinstance(raw_assoc, list):
            associations.extend(raw_assoc)

    # b) structured Associations model (list under .data)
    assoc_model = getattr(ctx, "associations", None)
    if assoc_model is not None:
        assoc_data = getattr(assoc_model, "data", None)
        if isinstance(assoc_data, list):
            associations.extend(assoc_data)
        else:
            # sometimes it's effectively a single association
            # convert to dict and add
            try:
                associations.append(assoc_model.dict(exclude_none=True))
            except Exception:
                # last ditch: ignore
                pass

    # -------------------------------------------------------------------------
    # 2) Filter to this system (PS did: ... | where { $_.'System ID' -eq $systemID })
    # -------------------------------------------------------------------------
    filtered: List[Dict[str, Any]] = []
    for row in associations:
        if not isinstance(row, dict):
            continue
        row_sys_id = ci_get(row, "System ID") or ci_get(row, "system_id")
        if system_id is None or (row_sys_id is not None and str(row_sys_id).strip() == str(system_id).strip()):
            filtered.append(row)

    logger.debug(
        "[T159] Collected %d association rows (filtered for system_id=%s)",
        len(filtered),
        system_id,
    )

    # -------------------------------------------------------------------------
    # 3) Scan once, bucket by Associated System ID
    #    (PowerShell did 3 foreaches, we do 1 for efficiency)
    # -------------------------------------------------------------------------
    AMC_ID = "4642"      # AMC Policy Record
    CCP_CLOUD_ID = "5050"  # Army CCP Cloud policy
    CCP_ID = "3915"      # Army CCP policy (non-cloud)

    has_amc = False
    has_ccp_cloud = False
    has_ccp = False

    for assoc in filtered:
        assoc_sid = ci_get(assoc, "Associated System ID") or ci_get(assoc, "associated_system_id")
        if not assoc_sid:
            continue
        assoc_sid_str = str(assoc_sid).strip()
        if assoc_sid_str == AMC_ID:
            has_amc = True
        elif assoc_sid_str == CCP_CLOUD_ID:
            has_ccp_cloud = True
        elif assoc_sid_str == CCP_ID:
            has_ccp = True

    # -------------------------------------------------------------------------
    # 4) Apply original PowerShell branching
    # -------------------------------------------------------------------------
    # 4.1 AMC is always required
    if not has_amc:
        msg = (
            "FAIL: The system is missing the AMC Policy Record "
            f"(no inheritance from Associated System ID {AMC_ID})."
        )
        logger.warning("[T159] %s system_id=%s", msg, system_id)
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        return tr

    # 4.2 cloud vs non-cloud
    is_cloud = infer_is_cloud(ctx)
    logger.debug("[T159] Cloud inference for system_id=%s → %s", system_id, is_cloud)

    if is_cloud:
        # cloud: must also have 5050
        if not has_ccp_cloud:
            msg = (
                "FAIL: Cloud system is missing the Army CCP Cloud policy record "
                f"(no inheritance from Associated System ID {CCP_CLOUD_ID})."
            )
            logger.warning("[T159] %s system_id=%s", msg, system_id)
            tr = TestResult(
                test_number=test_number,
                name=test_name,
                result=Result.FAIL,
                message=msg,
            )
            status.add(tr)
            return tr

        msg = (
            "PASS: Cloud system has AMC Policy Record "
            f"({AMC_ID}) and Army CCP Cloud Policy Record ({CCP_CLOUD_ID})."
        )
        logger.info("[T159] %s system_id=%s", msg, system_id)
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.PASS,
            message=msg,
        )
        status.add(tr)
        return tr

    # non-cloud: must have 3915
    if not has_ccp:
        msg = (
            "FAIL: Non-cloud system is missing the Army CCP policy record "
            f"(no inheritance from Associated System ID {CCP_ID})."
        )
        logger.warning("[T159] %s system_id=%s", msg, system_id)
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        return tr

    msg = (
        "PASS: Non-cloud system has AMC Policy Record "
        f"({AMC_ID}) and Army CCP Policy Record ({CCP_ID})."
    )
    logger.info("[T159] %s system_id=%s", msg, system_id)
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=msg,
    )
    status.add(tr)
    return tr


def test_160(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Validate cloud inheritance from the Army Enterprise Cloud CCP (ID 5050).

    This is a Pythonic port of the original PowerShell:

    - If the system is **not** cloud → **N/A**
    - If the system **is** cloud:
        - if **no** association row has `Associated System ID == "5050"` → **FAIL**
        - otherwise → **PASS**

    Modernization notes
    -------------------
     current Pydantic layout does **not** expose `ctx.associations_details`
    as a top-level field. The raw list lives at
    `ctx.raw_payloads.associations_details`, and there can also be structured
    associations on `ctx.associations.data`. This test therefore:
      1. Collects from `ctx.raw_payloads.associations_details` (if present)
      2. Collects from `ctx.associations.data` (if present)
      3. Falls back to treating `ctx.associations` as a single association
         and appends it as a dict
      4. Filters to the current `ctx.system_id`

    Cloud is inferred from:
      - `ctx.cloud_computing`
      - `ctx.system_info.cloudcomputing`
      - `ctx.system_details_dashboard.cloud_computing` (stringy)

    Args:
        ctx: Rich system snapshot, including raw payloads.
        status: Shared ATO execution status accumulator.

    Returns:
        TestResult: PASS, FAIL, or NA.
    """
    test_number = 160
    test_name = (
        "Test 160: Cloud system inherits from Army Enterprise Cloud CCP (5050)"
    )
    system_id = getattr(ctx, "system_id", None)

    def ci_get(d: Dict[str, Any], key: str, default: Optional[Any] = None) -> Optional[Any]:
        """Case-insensitive dict lookup."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def infer_is_cloud(ctx: SystemContext) -> bool:
        """Best-effort 'is cloud?' inference across known surfaces."""
        # 1) top-level boolean
        if ctx.cloud_computing is not None:
            return bool(ctx.cloud_computing)

        # 2) system_info.cloudcomputing
        si = getattr(ctx, "system_info", None)
        if si is not None and getattr(si, "cloudcomputing", None) is not None:
            return bool(si.cloudcomputing)

        # 3) system_details_dashboard.cloud_computing (often stringy)
        sdd = getattr(ctx, "system_details_dashboard", None)
        if sdd is not None and getattr(sdd, "cloud_computing", None) is not None:
            val = sdd.cloud_computing
            sval = str(val).strip().lower()
            if sval in {"true", "yes", "y", "1"}:
                return True
            if sval in {"false", "no", "n", "0"}:
                return False
            return bool(val)

        return False

    logger.info("[T160] Starting test — system_id=%s", system_id)

    # -------------------------------------------------------------------------
    # 1) Collect associations from all known locations
    # -------------------------------------------------------------------------
    associations: List[Dict[str, Any]] = []

    # a) raw payloads
    raw_payloads = getattr(ctx, "raw_payloads", None)
    if raw_payloads is not None:
        raw_assoc = getattr(raw_payloads, "associations_details", None)
        if isinstance(raw_assoc, list):
            associations.extend(raw_assoc)

    # b) structured associations model
    assoc_model = getattr(ctx, "associations", None)
    if assoc_model is not None:
        assoc_data = getattr(assoc_model, "data", None)
        if isinstance(assoc_data, list):
            associations.extend(assoc_data)
        else:
            # sometimes it's a single object
            try:
                associations.append(assoc_model.dict(exclude_none=True))
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # 2) Filter to this system (mimic PS: inheritancedatasorted for this system)
    # -------------------------------------------------------------------------
    filtered: List[Dict[str, Any]] = []
    for row in associations:
        if not isinstance(row, dict):
            continue
        row_sys_id = ci_get(row, "System ID") or ci_get(row, "system_id")
        if system_id is None:
            filtered.append(row)
        else:
            if row_sys_id is not None and str(row_sys_id).strip() == str(system_id).strip():
                filtered.append(row)

    logger.debug(
        "[T160] Collected %d association rows after filtering to system_id=%s",
        len(filtered),
        system_id,
    )

    # -------------------------------------------------------------------------
    # 3) Cloud branch / N/A branch
    # -------------------------------------------------------------------------
    is_cloud = infer_is_cloud(ctx)
    logger.debug("[T160] Cloud inference for system_id=%s → %s", system_id, is_cloud)

    if not is_cloud:
        msg = "N/A: The system is not a cloud system."
        logger.info("[T160] %s system_id=%s", msg, system_id)
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.NA,
            message=msg,
        )
        status.add(tr)
        return tr

    # -------------------------------------------------------------------------
    # 4) Cloud: must have Army CCP Cloud policy (Associated System ID 5050)
    # -------------------------------------------------------------------------
    CCP_CLOUD_ID = "5050"
    has_ccp_cloud = False

    for assoc in filtered:
        assoc_sid = (
            ci_get(assoc, "Associated System ID")
            or ci_get(assoc, "associated_system_id")
        )
        if not assoc_sid:
            continue
        if str(assoc_sid).strip() == CCP_CLOUD_ID:
            has_ccp_cloud = True
            break

    if not has_ccp_cloud:
        msg = (
            "FAIL: Cloud system is missing the Army CCP Cloud policy record "
            f"(no inheritance from Associated System ID {CCP_CLOUD_ID})."
        )
        logger.warning("[T160] %s system_id=%s", msg, system_id)
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        return tr

    msg = (
        "PASS: Cloud system inherits from the Army CCP Cloud provider "
        f"(Associated System ID {CCP_CLOUD_ID} present). Hybrid controls acceptable."
    )
    logger.info("[T160] %s system_id=%s", msg, system_id)
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=msg,
    )
    status.add(tr)
    return tr
def test_161(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Report inability to verify inherited CCIs ↔ STIG mappings (hybrid allowed).

    Source / PowerShell behavior
    ----------------------------
    The original PowerShell did **not** implement this check. It printed a yellow
    message saying the eMASS API does not have the data and set the result to
    CONCERN.

    We preserve that 1:1:
      - we **always** return CONCERN
      - we **always** emit a message pointing at missing eMASS/API fields
      - we **still** accept `ctx` so the signature is uniform with other tests

    Args:
        ctx: Current system context. (Not used — API doesn’t expose what we need.)
        status: Aggregator that receives the created `TestResult`.

    Returns:
        TestResult: Always `CONCERN`.
    """
    test_number = 161
    test_name = (
        "Test 161: Inherited CCIs mapped to STIG requirements (hybrid controls allowed)"
    )
    system_id = getattr(ctx, "system_id", None)

    logger.info(
        "[T161] Starting test — system_id=%s (API does not expose CCI→STIG for inherited controls)",
        system_id,
    )

    msg = (
        "CONCERN: eMASS / source API does not expose sufficient data to confirm whether "
        "inherited CCIs have associated STIG coverage (hybrid controls excepted). "
        "Manual review is required."
    )

    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.CONCERN,
        message=msg,
    )
    status.add(tr)

    logger.warning("[T161] %s system_id=%s", msg, system_id)

    return tr


def test_162(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Check for inherited **critical** controls that are Non-Compliant (NC).

    Source / PowerShell behavior
    ----------------------------
    Original PS walked `$criticalcontrolinfodata` and did:
      - if `isInherited == "True"` **and** `complianceStatus == "NC"`, collect its `acronym`
      - if any were collected → **FAIL**
      - else → **PASS**

    Notes / assumptions
    -------------------
    - We assume `ctx.critical_control_info` (or equivalent) is a list of dict-like
      objects that match the PS shape:
        • isInherited
        • complianceStatus
        • acronym
    - If we **cannot** find such data, we return **CONCERN** (modern safety) and log it.
      PS never hit this path because its variable was already populated.

    Args:
        ctx: Current system context (eMASS snapshot, may or may not have the critical list).
        status: Aggregator for test results.

    Returns:
        TestResult: PASS if none are inherited+NC, FAIL if one or more, CONCERN if no data.
    """
    test_number = 162
    test_name = (
        "Test 162: Inherited critical controls are not Non-Compliant (NC)"
    )
    system_id = getattr(ctx, "system_id", None)

    logger.info(
        "[T162] Starting test — system_id=%s", system_id
    )

    # --- 1) get the data, following  assumption from the comment ---
    # Primary expected location ( code):
    critical_rows = getattr(ctx, "critical_control_info", None)

    # If it’s missing or empty, we *could* try other places, but  model
    # doesn’t actually define a field for it, so we fail gracefully.
    if not critical_rows:
        msg = (
            "CONCERN: No `critical_control_info` dataset was found on the context; "
            "unable to evaluate inherited critical controls for NC status."
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.CONCERN,
            message=msg,
        )
        status.add(tr)
        logger.warning("[T162] %s system_id=%s", msg, system_id)
        return tr

    # --- 2) helper — case-insensitive lookup like PS ---
    def ci_get(d: Dict[str, Any], key: str, default=None) -> Any:
        """Case-insensitive dict lookup (PowerShell-ish)."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    noncompliant_inherited: List[str] = []

    for row in critical_rows:
        is_inherited_val = str(ci_get(row, "isInherited", "")).strip().lower()
        compliance_val = str(ci_get(row, "complianceStatus", "")).strip().upper()
        acronym_val = ci_get(row, "acronym", "<unknown>")

        if is_inherited_val == "true" and compliance_val == "NC":
            noncompliant_inherited.append(str(acronym_val))

    # --- 3) decide result, add to status, log in our style ---
    if noncompliant_inherited:
        msg = (
            "FAIL: The following inherited *critical* controls are Non-Compliant (NC): "
            + ", ".join(noncompliant_inherited)
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error(
            "[T162] Found inherited NC critical controls: %s system_id=%s",
            ", ".join(noncompliant_inherited),
            system_id,
        )
        return tr

    # PASS path
    msg = "PASS: No inherited critical controls are marked Non-Compliant (NC)."
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=msg,
    )
    status.add(tr)
    logger.info("[T162] %s system_id=%s", msg, system_id)
    return tr


def test_163(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Validate that Cybersecurity Service Provider (CSSP) inheritance exists
    and matches the system's hosting (cloud vs non-cloud).

    PowerShell parity
    -----------------
    Original PS walked `$inheritancedatasorted` twice:
      1. collect cloud CSSP IDs in {5206, 2555, 2409}
      2. collect non-cloud CSSP IDs in {367}
      3. if `$cloud -like "True"` → require at least one cloud ID
         else → require at least one non-cloud ID

    Our Python version:
      - We treat `ctx.cloud_computing` (or system dashboards) as `$cloud`.
      - We treat the raw list at `ctx.raw_payloads.associations_details` as
        `$inheritancedatasorted` when present.
      - We fall back to `ctx.associations.data` or `ctx.associations` if the raw
        list isn’t there.
      - If **no** association data is present, we return CONCERN (PS wouldn’t
        have hit that, but Python can).

    Args:
        ctx: Current system context built from eMASS exports.
        status: Running ATOStatus aggregator to append this test's result.

    Returns:
        TestResult: PASS/FAIL mirroring the PowerShell behavior, or CONCERN
        if we can’t see inheritance data.
    """
    # PS constants, lifted straight over
    CLOUD_CSSP_IDS = {"5206", "2555", "2409"}
    NONCLOUD_CSSP_IDS = {"367"}
    test_number = 163
    test_name = (
        "Test 163: CSSP inheritance present and aligned with hosting model"
    )
    system_id = getattr(ctx, "system_id", None)

    logger.info("[T163] Starting CSSP inheritance check system_id=%s", system_id)

    # ------------------------------------------------------------------
    # 1) Gather association rows from *any* place they can reasonably be
    # ------------------------------------------------------------------
    associations: Sequence[Dict[str, Any]] = ()

    # Preferred: raw payloads (this is where you said it really lives)
    if ctx.raw_payloads and ctx.raw_payloads.associations_details:
        associations = ctx.raw_payloads.associations_details
        logger.debug(
            "[T163] Using associations from ctx.raw_payloads.associations_details "
            "(count=%d) system_id=%s",
            len(associations),
            system_id,
        )
    # Next best: structured associations with a data list
    elif ctx.associations and getattr(ctx.associations, "data", None):
        associations = ctx.associations.data or []
        logger.debug(
            "[T163] Using associations from ctx.associations.data (count=%d) "
            "system_id=%s",
            len(associations),
            system_id,
        )
    # Fallback: single structured associations object → wrap it
    elif ctx.associations:
        associations = [ctx.associations.dict()]
        logger.debug(
            "[T163] Using single associations object from ctx.associations "
            "system_id=%s",
            system_id,
        )

    # If we *still* have nothing, we can’t mirror the PS check
    if not associations:
        msg = (
            "CONCERN: No association/inheritance dataset found on context; "
            "unable to confirm CSSP inheritance for cloud/non-cloud systems."
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.CONCERN,
            message=msg,
        )
        status.add(tr)
        logger.warning("[T163] %s system_id=%s", msg, system_id)
        return tr

    # ------------------------------------------------------------------
    # 2) Figure out if this is a cloud system (be generous about sources)
    # ------------------------------------------------------------------
    def _to_bool(val: Any) -> bool:
        if isinstance(val, bool):
            return val
        if val is None:
            return False
        s = str(val).strip().lower()
        return s in {"true", "yes", "y", "1"}
    # try top-level first
    is_cloud = _to_bool(getattr(ctx, "cloud_computing", None))
    # if still falsey, try deeper (some snapshots only put it in the dashboard)
    if not is_cloud:
        if ctx.system_info and ctx.system_info.cloudcomputing is not None:
            is_cloud = _to_bool(ctx.system_info.cloudcomputing)
        elif (
            ctx.system_details_dashboard
            and ctx.system_details_dashboard.cloud_computing is not None
        ):
            is_cloud = _to_bool(ctx.system_details_dashboard.cloud_computing)

    # ------------------------------------------------------------------
    # 3) Single pass over associations: collect hits for both buckets
    # ------------------------------------------------------------------
    def ci_get(d: Dict[str, Any], key: str, default=None):
        """Case-insensitive dict lookup + graceful fallback."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    cloud_hits: List[str] = []
    noncloud_hits: List[str] = []

    for assoc in associations:
        # PS used "Associated System ID" exactly; our raw export may lower/underscore it
        assoc_id_raw = (
            ci_get(assoc, "Associated System ID")
            or ci_get(assoc, "associated_system_id")
            or ci_get(assoc, "associatedsystemid")
            or ""
        )
        assoc_id = str(assoc_id_raw).strip()

        if not assoc_id:
            continue

        if assoc_id in CLOUD_CSSP_IDS:
            cloud_hits.append(assoc_id)

        if assoc_id in NONCLOUD_CSSP_IDS:
            noncloud_hits.append(assoc_id)

    # ------------------------------------------------------------------
    # 4) Mirror the PS branching
    # ------------------------------------------------------------------
    if is_cloud:
        # Cloud path
        if not cloud_hits:
            msg = (
                "FAIL: Cloud system is missing CSSP inheritance; "
                "no known cloud CSSP provider association IDs found."
            )
            tr = TestResult(
                test_number=test_number,
                name=test_name,
                result=Result.FAIL,
                message=msg,
            )
            status.add(tr)
            logger.error(
                "[T163] Cloud CSSP missing (expected one of %s) system_id=%s",
                ", ".join(sorted(CLOUD_CSSP_IDS)),
                system_id,
            )
            return tr

        msg = (
            "PASS: Cloud system has CSSP inheritance via provider ID(s): "
            + ", ".join(cloud_hits)
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.PASS,
            message=msg,
        )
        status.add(tr)
        logger.info("[T163] %s system_id=%s", msg, system_id)
        return tr

    # Non-cloud path
    if not noncloud_hits:
        msg = (
            "FAIL: Non-cloud system is missing CSSP inheritance; "
            "no known non-cloud CSSP provider association IDs found."
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error(
            "[T163] Non-cloud CSSP missing (expected ID %s) system_id=%s",
            ", ".join(sorted(NONCLOUD_CSSP_IDS)),
            system_id,
        )
        return tr

    msg = (
        "PASS: Non-cloud system has CSSP inheritance via provider ID(s): "
        + ", ".join(noncloud_hits)
    )
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=msg,
    )
    status.add(tr)
    logger.info("[T163] %s system_id=%s", msg, system_id)
    return tr


def test_164(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Validate that a **cloud** production system inherits from an approved
    C5ISR / CSO provider.

    PowerShell parity
    -----------------
    Original script:
      - iterate `$inheritancedatasorted`
      - collect associations whose "Associated System ID" is in:
            {4894, 5035, 3694, 3696, 3692, 3695, 3697}
      - if `$cloud -like "True"`:
            - if none → FAIL
            - else    → PASS
        else:
            - N/A

    Our Python version:
      - Treat `ctx.raw_payloads.associations_details` as the canonical
        `$inheritancedatasorted` if present.
      - Fall back to `ctx.associations.data` or a single `ctx.associations`.
      - Detect cloud from multiple sources (top-level, SystemInfo, Dashboard).
      - If cloud but we literally have **no** association data, we emit
        **CONCERN** because we can’t prove or disprove inheritance.

    Args:
        ctx: Hydrated system context for this test run.
        status: Aggregator of all test results.

    Returns:
        TestResult: PASS, FAIL, NA, or CONCERN (see above).
    """
    test_number = 164
    test_name = (
        "Test 164: Cloud system has established inheritance with approved C5ISR/CSO"
    )
    system_id = getattr(ctx, "system_id", None)

    logger.info("[T164] Starting C5ISR inheritance check system_id=%s", system_id)

    # ------------------------------------------------------------------
    # 1) Pull associations from *wherever* the runner stashed them
    # ------------------------------------------------------------------
    associations: Sequence[Dict[str, Any]] = ()

    if ctx.raw_payloads and ctx.raw_payloads.associations_details:
        associations = ctx.raw_payloads.associations_details
        logger.debug(
            "[T164] Using associations from ctx.raw_payloads.associations_details "
            "(count=%d) system_id=%s",
            len(associations),
            system_id,
        )
    elif ctx.associations and getattr(ctx.associations, "data", None):
        associations = ctx.associations.data or []
        logger.debug(
            "[T164] Using associations from ctx.associations.data (count=%d) "
            "system_id=%s",
            len(associations),
            system_id,
        )
    elif ctx.associations:
        # single object, wrap it so downstream code can iterate
        associations = [ctx.associations.dict()]
        logger.debug(
            "[T164] Using single associations object from ctx.associations "
            "system_id=%s",
            system_id,
        )

    # ------------------------------------------------------------------
    # 2) Determine if this is a cloud system (be generous)
    # ------------------------------------------------------------------
    def _to_bool(val: Any) -> bool:
        if isinstance(val, bool):
            return val
        if val is None:
            return False
        s = str(val).strip().lower()
        return s in {"true", "yes", "y", "1"}

    is_cloud = _to_bool(getattr(ctx, "cloud_computing", None))

    if not is_cloud and ctx.system_info and ctx.system_info.cloudcomputing is not None:
        is_cloud = _to_bool(ctx.system_info.cloudcomputing)
    if (
        not is_cloud
        and ctx.system_details_dashboard
        and ctx.system_details_dashboard.cloud_computing is not None
    ):
        is_cloud = _to_bool(ctx.system_details_dashboard.cloud_computing)

    # ------------------------------------------------------------------
    # 3) If it’s *not* cloud, we match PS exactly → N/A
    # ------------------------------------------------------------------
    if not is_cloud:
        msg = "N/A: System is not marked as a cloud system."
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.NA,
            message=msg,
        )
        status.add(tr)
        logger.info("[T164] %s system_id=%s", msg, system_id)
        return tr

    # from this point on we know it's a cloud system
    # PS would now scan $inheritancedatasorted

    # ------------------------------------------------------------------
    # 4) Cloud but we have no associations at all → we can’t prove it
    # ------------------------------------------------------------------
    if not associations:
        msg = (
            "CONCERN: Cloud system but no association/inheritance dataset was "
            "found on the context; unable to confirm C5ISR / CSO inheritance."
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.CONCERN,
            message=msg,
        )
        status.add(tr)
        logger.warning("[T164] %s system_id=%s", msg, system_id)
        return tr

    # ------------------------------------------------------------------
    # 5) Single pass over associations to find approved C5ISR providers
    # ------------------------------------------------------------------
    def ci_get(d: Dict[str, Any], key: str, default=None):
        """Case-insensitive dict lookup (handles snake vs space vs casing)."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    c5isr_hits: List[str] = []
    for assoc in associations:
        assoc_id_raw = (
            ci_get(assoc, "Associated System ID")
            or ci_get(assoc, "associated_system_id")
            or ci_get(assoc, "associatedsystemid")
            or ""
        )
        assoc_id = str(assoc_id_raw).strip()
        if not assoc_id:
            continue
        if assoc_id in C5ISR_PROVIDER_IDS:
            c5isr_hits.append(assoc_id)

    # ------------------------------------------------------------------
    # 6) Mirror PS decision tree
    # ------------------------------------------------------------------
    if not c5isr_hits:
        msg = (
            "FAIL: Cloud system is missing C5ISR / CSO inheritance; "
            "no approved provider association found."
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error(
            "[T164] C5ISR inheritance missing (expected one of %s) system_id=%s",
            ", ".join(sorted(C5ISR_PROVIDER_IDS)),
            system_id,
        )
        return tr

    msg = (
        "PASS: Cloud system has C5ISR / CSO inheritance via provider ID(s): "
        + ", ".join(c5isr_hits)
    )
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=msg,
    )
    status.add(tr)
    logger.info("[T164] %s system_id=%s", msg, system_id)
    return tr

def test_165(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Validate that manually inherited controls (not covered by a policy record)
    are documented with MOU/MOA/SLA artifacts.

    PowerShell behavior
    -------------------
    Original script only printed:
        "CONCERN: The eMASS API does not have data for this test."
    and marked the test as CONCERN.

    Why we keep it
    --------------
    The actual requirement would need:
      - control inheritance view,
      - policy / AP association for those controls,
      - and artifact evidence tying the manual inheritance to an agreement.
     current eMASS export / API surface does **not** provide that
    correlation, so we cannot deterministically pass/fail.

    So we preserve PS intent 1:1 → always CONCERN.

    Args:
        ctx: Hydrated system context for the system under test.
        status: Aggregator that tracks all test outcomes.

    Returns:
        TestResult: Always Result.CONCERN with an explanatory message.
    """
    test_number = 165
    test_name = (
        "Test 165: Manual inheritance documented for controls not in policy record"
    )
    system_id = getattr(ctx, "system_id", None)

    logger.info(
        "[T165] Starting manual inheritance check (data not exposed) system_id=%s",
        system_id,
    )

    msg = (
        "CONCERN: eMASS API/export does not expose the data needed to verify that "
        "manually inherited controls are backed by MOU/MOA/SLA. Manual review required."
    )

    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.CONCERN,
        message=msg,
    )
    status.add(tr)

    logger.warning("[T165] %s system_id=%s", msg, system_id)
    return tr

def test_166(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Validate that APMS-listed dependencies are present in eMASS Associations.

    PowerShell behavior (original)
    ------------------------------
    - Read first APMS row:
        * "Parent System Name"
        * "Child System Name"
    - Build one list: parent + child.
    - For each item in that list, scan eMASS associations
      (field: "Associated System Acronym") for a *substring* match.
    - If APMS had no parent/child → N/A.
    - If all APMS deps matched → PASS.
    - If any APMS dep did not match → FAIL.
    - Else → CONCERN.

    Why defensive in Python
    -----------------------
     SystemContext does *not* expose `associations_details` directly.
    That lives under `ctx.raw_payloads.associations_details`, while some
    systems only hydrate `ctx.associations` (with `.data`). So we merge
    both sources and treat missing data as an empty list.

    Args:
        ctx: Hydrated system context (APMS snapshot + raw payloads).
        status: Aggregator for all test outcomes.

    Returns:
        TestResult: PASS | FAIL | NA | CONCERN, preserving PS semantics.
    """
    test_number = 166
    test_name = "Test 166: APMS dependencies are documented in eMASS Associations"
    system_id = getattr(ctx, "system_id", None)

    logger.info(
        "[T166] Starting APMS↔eMASS association alignment check system_id=%s",
        system_id,
    )

    # ---------- helpers ----------
    def ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict lookup.

        Args:
            d: Source dictionary.
            key: Key to look up.
            default: Value to return if key not found.

        Returns:
            Any: Value if found (by case-insensitive key), else default.
        """
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    # ---------- Step 1: pull APMS deps ----------
    apms_row: Dict[str, Any] = ctx.apms_first_row_raw or {}

    parent_raw = ci_get(apms_row, "Parent System Name")
    child_raw = ci_get(apms_row, "Child System Name")

    # PowerShell does N/A *before* matching if both are None/"".
    no_parents = parent_raw is None or str(parent_raw).strip() == ""
    no_children = child_raw is None or str(child_raw).strip() == ""
    if no_parents and no_children:
        msg = (
            "N/A: APMS does not list any parent/child system dependencies for this system."
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.NA,
            message=msg,
        )
        status.add(tr)
        logger.info("[T166] %s system_id=%s", msg, system_id)
        return tr

    # Build APMS associations list like PS: $APMSParentSystems + $APMSChildSystems
    apms_associations: List[str] = []

    def _push_if_valid(val: Any) -> None:
        if val is None:
            return
        s = str(val).strip()
        if s and s != "-":
            apms_associations.append(s)

    _push_if_valid(parent_raw)
    _push_if_valid(child_raw)

    logger.debug(
        "[T166] APMS associations collected=%s system_id=%s",
        apms_associations,
        system_id,
    )

    # ---------- Step 2: get eMASS association rows ----------
    # Source 1: raw payloads
    raw_assoc: List[Dict[str, Any]] = []
    if getattr(ctx, "raw_payloads", None) and ctx.raw_payloads.associations_details:
        raw_assoc = ctx.raw_payloads.associations_details

    # Source 2: parsed object
    parsed_assoc: List[Dict[str, Any]] = []
    if getattr(ctx, "associations", None):
        # ctx.associations might be a single object *or* have a .data list
        if getattr(ctx.associations, "data", None):
            parsed_assoc = ctx.associations.data  # type: ignore[assignment]
        else:
            # single association object → make it a list of dicts
            parsed_assoc = [ctx.associations.dict(exclude_none=True)]

    # Merge, preserving order: raw first (usually more complete)
    emass_assocs: List[Dict[str, Any]] = []
    if raw_assoc:
        emass_assocs.extend(raw_assoc)
    if parsed_assoc:
        emass_assocs.extend(parsed_assoc)

    logger.debug(
        "[T166] eMASS associations found=%d system_id=%s",
        len(emass_assocs),
        system_id,
    )

    # ---------- Step 3: match logic (powerShell-style) ----------
    match_hits: List[str] = []
    missing_deps: List[str] = []

    def get_assoc_acronym(row: Dict[str, Any]) -> str:
        acr = ci_get(row, "Associated System Acronym", "") or ci_get(
            row, "associated_system_acronym", ""
        )
        return str(acr).strip()

    for apms_item in apms_associations:
        apms_item_lower = apms_item.lower()
        local_hit = False

        for assoc in emass_assocs:
            acr = get_assoc_acronym(assoc)
            if not acr:
                continue
            # PowerShell: -like "*$acr*"
            acr_lower = acr.lower()
            if acr_lower and acr_lower in apms_item_lower:
                match_hits.append(acr)
                local_hit = True

        if not local_hit:
            missing_deps.append(apms_item)

    logger.debug(
        "[T166] match_hits=%s missing_deps=%s system_id=%s",
        match_hits,
        missing_deps,
        system_id,
    )

    # ---------- Step 4: decide outcome (exact PS rules) ----------
    if not missing_deps and match_hits:
        msg = (
            "PASS: The dependencies in APMS match eMASS associations for this system."
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.PASS,
            message=msg,
        )
        status.add(tr)
        logger.info("[T166] %s system_id=%s", msg, system_id)
        return tr

    if missing_deps:
        msg = (
            "FAIL: APMS lists dependent/related systems that do not appear in eMASS "
            "associations: " + ", ".join(missing_deps)
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.warning("[T166] %s system_id=%s", msg, system_id)
        return tr

    # Ambiguous / partial data
    msg = (
        "CONCERN: APMS and eMASS association alignment could not be determined from the "
        "available data (no matches, no explicit misses)."
    )
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.CONCERN,
        message=msg,
    )
    status.add(tr)
    logger.warning("[T166] %s system_id=%s", msg, system_id)
    return tr



def test_167(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Verify that eMASS associations explicitly document external systems.

    Overview
    --------
    This test mirrors the original PowerShell behavior:

    - Iterate the eMASS association rows (`$inheritancedatasorted` in PS).
    - Count rows where `"External System"` is `"Yes"` (case-insensitive).
    - If the count is **0** → CONCERN.
    - If the count is **> 0** → PASS (and report the count).

    Why we’re defensive here
    ------------------------
    In the Python model, associations don’t live at `ctx.associations_details`;
    they typically arrive as **raw payloads** under
    `ctx.raw_payloads.associations_details`, and sometimes as a parsed object
    in `ctx.associations` (with an optional `.data` list). We normalize both
    so this test works regardless of the ingestion path.

    Args:
        ctx: Current system snapshot (APMS, eMASS, associations, raw payloads).
        status: Aggregator for test results.

    Returns:
        TestResult: PASS if at least one external system is documented,
        otherwise CONCERN.
    """
    test_number = 167
    test_name = "Test 167: Documented 'External Systems' listed as needed"
    system_id = getattr(ctx, "system_id", None)

    logger.info("[T167] Starting external-systems documentation check system_id=%s", system_id)

    # ---------- helpers ----------

    def ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Return value for `key` in dict `d` using case-insensitive lookup."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    # ---------- gather association rows (raw → parsed) ----------
    associations: List[Dict[str, Any]] = []

    # 1) primary: raw payloads
    if getattr(ctx, "raw_payloads", None) and ctx.raw_payloads.associations_details:
        associations.extend(ctx.raw_payloads.associations_details)

    # 2) secondary: parsed object on ctx.associations
    if getattr(ctx, "associations", None):
        # Could be a single association, or an object with .data
        if getattr(ctx.associations, "data", None):
            associations.extend(ctx.associations.data)  # type: ignore[arg-type]
        else:
            # single object → treat as 1-row list
            associations.append(ctx.associations.dict(exclude_none=True))

    logger.debug(
        "[T167] Normalized associations rows=%d system_id=%s",
        len(associations),
        system_id,
    )

    # ---------- core logic (PowerShell parity) ----------
    external_count = 0

    for assoc in associations:
        # PS column: "External System"
        # model field: external_system
        ext_val = ci_get(assoc, "External System")
        if ext_val is None:
            # try model-style snake_case from Associations(...)
            ext_val = ci_get(assoc, "external_system")

        if isinstance(ext_val, str):
            if ext_val.strip().lower() == "yes":
                external_count += 1
        elif isinstance(ext_val, bool):
            if ext_val:
                external_count += 1

    # ---------- decide result ----------
    if external_count == 0:
        # PS: "CONCERN: There are zero external systems documented"
        msg = (
            "CONCERN: There are zero external systems documented in eMASS associations. "
            "Manual verification may be required to confirm whether external interfaces exist."
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.CONCERN,
            message=msg,
        )
        status.add(tr)
        logger.warning("[T167] %s system_id=%s", msg, system_id)
        return tr

    # PS: "PASS: Number of external systems documented: X"
    msg = (
        f"PASS: {external_count} external system(s) documented in associations for this system."
    )
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=msg,
    )
    status.add(tr)
    logger.info("[T167] %s system_id=%s", msg, system_id)
    return tr



def test_168(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Verify that the PAC ISO/PM role is populated for this system.

    Parity with PowerShell
    ----------------------
    The original PowerShell did:
    1. GET `/api/system-roles/pac?role=ISO%2FP`
    2. Filter `.data` to the current `$SystemID`
    3. Walk `roles.users` and collect `"First Last"`
    4. If none → **FAIL**, else → **PASS** (print names)

    Our offline pipeline
    --------------------
    - We treat ``ctx.raw_payloads.user_assignments_details`` as the JSON array
      the PS script would have received.
    - We filter rows to ``row.systemId == ctx.system_id`` (string-safe compare).
    - We normalize the ``roles`` field which can be:
        * a single dict
        * a list of dicts
    - We accept role names like:
        * ``"ISO/P"``
        * ``"ISO/PM"``
        * ``"ISO / PM"``
        * anything that looks like ISO + PM, case-insensitive
    - From matching roles we pull ``users`` and format ``"First Last"``.

    We also support a *model-era* fallback:
    - If no PAC rows yield names, but ``ctx.system_details_dashboard.iso_pm`` is
      set, we treat that as the source of truth and PASS. That keeps compatibility
      with  newer structured dashboards that already project ISO/PM.

    Args:
        ctx: System context with raw eMASS payloads + parsed dashboards.
        status: Aggregator to which the test result will be appended.

    Returns:
        TestResult: PASS if ≥1 ISO/PM user found, otherwise FAIL.
    """
    test_number = 168
    test_name = "Test 168: Correct PAC ISO/PM Present"
    system_id = getattr(ctx, "system_id", None)

    logger.info("[T168] Starting ISO/PM presence check system_id=%s", system_id)

    # ---------------------------------------------------------------------
    # helpers
    # ---------------------------------------------------------------------
    def ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict lookup."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def is_iso_pm_role(name: str) -> bool:
        """Return True if the role name looks like an ISO/PM PAC role."""
        if not name:
            return False
        s = name.strip().lower()
        if s in {"iso/p", "iso/pm"}:
            return True
        # handle things like "ISO / PM", "ISO-PM", "ISO/PM (Primary)"
        if "iso" in s and "pm" in s:
            return True
        return False

    def normalize_roles(roles_field: Any) -> List[Dict[str, Any]]:
        """Turn 'roles' (dict | list | None) into a list[dict]."""
        if roles_field is None:
            return []
        if isinstance(roles_field, dict):
            return [roles_field]
        if isinstance(roles_field, (list, tuple)):
            return [r for r in roles_field if isinstance(r, dict)]
        return []

    # ---------------------------------------------------------------------
    # 1) Gather PAC user-assignments (the thing PS called the API for)
    # ---------------------------------------------------------------------
    assignments: List[Dict[str, Any]] = []

    if getattr(ctx, "raw_payloads", None) and ctx.raw_payloads.user_assignments_details:
        # This is the one that actually exists in  RawPayloads model
        assignments.extend(ctx.raw_payloads.user_assignments_details)

    # If later you project it to top-level, this keeps us forward-compatible.
    # (Today SystemContext doesn't have ctx.user_assignments_details)
    if hasattr(ctx, "user_assignments_details"):
        # type: ignore[attr-defined]
        maybe_top = getattr(ctx, "user_assignments_details") or []
        if isinstance(maybe_top, list):
            assignments.extend(maybe_top)

    logger.debug(
        "[T168] Normalized user-assignments rows=%d system_id=%s",
        len(assignments),
        system_id,
    )

    iso_pm_names: List[str] = []

    # ---------------------------------------------------------------------
    # 2) PS-style logic over normalized rows
    # ---------------------------------------------------------------------
    for row in assignments:
        # eMASS sends 'systemId' but sometimes we see casing drift.
        row_sys_id = (
            ci_get(row, "systemId")
            or ci_get(row, "system_id")
            or ci_get(row, "SystemID")
        )
        if str(row_sys_id) != str(system_id):
            continue

        roles_field = ci_get(row, "roles")
        roles = normalize_roles(roles_field)
        if not roles:
            continue

        for role in roles:
            role_name = (
                ci_get(role, "role")
                or ci_get(role, "roleName")
                or ci_get(role, "name")
                or ""
            )
            if not is_iso_pm_role(str(role_name)):
                continue

            users_field = ci_get(role, "users") or []
            if isinstance(users_field, dict):
                users_iter: Sequence[Dict[str, Any]] = [users_field]
            else:
                users_iter = users_field  # assume list-like

            for user in users_iter:
                if not isinstance(user, dict):
                    continue
                first = ci_get(user, "firstName", "").strip()
                last = ci_get(user, "lastName", "").strip()
                full_name = (first + " " + last).strip()
                if full_name:
                    iso_pm_names.append(full_name)

    # ---------------------------------------------------------------------
    # 3) Model-era fallback: system_details_dashboard.iso_pm
    # ---------------------------------------------------------------------
    if not iso_pm_names and getattr(ctx, "system_details_dashboard", None):
        dash_iso = ctx.system_details_dashboard.iso_pm  # type: ignore[union-attr]
        if dash_iso and str(dash_iso).strip():
            # dashboard sometimes stores as "First Last, Second Last"
            dash_names = [n.strip() for n in str(dash_iso).split(",") if n.strip()]
            iso_pm_names.extend(dash_names)
            logger.debug(
                "[T168] Fallback to system_details_dashboard.iso_pm names=%s system_id=%s",
                dash_names,
                system_id,
            )

    # Deduplicate in order
    if iso_pm_names:
        unique_names = list(dict.fromkeys(iso_pm_names))
    else:
        unique_names = []

    # ---------------------------------------------------------------------
    # 4) Decide outcome (strict PS parity: none → FAIL)
    # ---------------------------------------------------------------------
    if not unique_names:
        msg = "FAIL: The ISO/PM is not provided for this system."
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error("[T168] %s system_id=%s", msg, system_id)
        return tr

    joined = ", ".join(unique_names)
    msg = f"PASS: The ISO/PMs are: {joined}"
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=msg,
    )
    status.add(tr)
    logger.info("[T168] %s system_id=%s", msg, system_id)
    return tr





def test_169(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Verify that an Organizational ISSM (O-ISSM) PAC role exists for this system.

    This is the Python analogue of the original PowerShell test:

    PowerShell behavior
    -------------------
    1. Call `GET /api/system-roles/pac?role=Organizational%20ISSM`.
    2. If the call fails → ERROR/FAIL.
    3. If it returns but has no `.data` → FAIL ("API returned no data").
    4. Filter to rows where `systemId == $SystemID`.
    5. If no matching rows or the matching row has no `roles.users` → FAIL.
    6. Else → PASS and print `First Last, ...`.

    Offline behavior (this test)
    ----------------------------
    - We treat `ctx.raw_payloads.user_assignments_details` as the already-fetched
      payload the PS script expected.
    - We do *not* simulate network failures, because data is now local.
    - We *do* keep semantics for "no array at all" → FAIL.

    Args:
        ctx: Canonical snapshot of the eMASS system, including raw payloads.
        status: Mutable ATOStatus aggregator to append this test's result.

    Returns:
        TestResult: PASS if ≥ 1 Organizational ISSM is found for this system;
        otherwise FAIL.
    """
    test_number = 169
    test_name = "Test 169: Correct PAC O-ISSM Present"
    system_id = getattr(ctx, "system_id", None)

    logger.info("[T169] Start O-ISSM presence check system_id=%s", system_id)

    def _get_pac_assignments(ctx: SystemContext) -> List[Dict[str, Any]]:
        """Return PAC/system-roles rows from any place our model might store them.

        Order of preference:
        1. ctx.raw_payloads.user_assignments_details  (actual place in  model)
        2. ctx.user_assignments_details               (future/top-level projection)
        """
        rows: List[Dict[str, Any]] = []

        # current real location
        if getattr(ctx, "raw_payloads", None):
            raw = ctx.raw_payloads.user_assignments_details  # type: ignore[assignment]
            if isinstance(raw, list):
                rows.extend(raw)

        # future-proof / forward-compat
        if hasattr(ctx, "user_assignments_details"):
            # type: ignore[attr-defined]
            maybe_top = getattr(ctx, "user_assignments_details") or []
            if isinstance(maybe_top, list):
                rows.extend(maybe_top)

        return rows
    # ---------------------------------------------------------------------
    # local helpers
    # ---------------------------------------------------------------------
    def ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict lookup."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def normalize_roles(roles_field: Any) -> List[Dict[str, Any]]:
        """Normalize 'roles' into a list of dicts."""
        if roles_field is None:
            return []
        if isinstance(roles_field, dict):
            return [roles_field]
        if isinstance(roles_field, (list, tuple)):
            return [r for r in roles_field if isinstance(r, dict)]
        return []

    def is_o_issm_role(role_name: str) -> bool:
        """Return True if the role name looks like an Organizational ISSM."""
        if not role_name:
            return False
        s = role_name.strip().lower()
        # strict
        if s == "organizational issm":
            return True
        # tolerate light drift
        if s in {"o-issm", "o issm", "org issm"}:
            return True
        # last resort: contains-based
        if "issm" in s and "org" in s:
            return True
        if "issm" in s and "organizational" in s:
            return True
        return False

    # ---------------------------------------------------------------------
    # 1) get PAC payload (this is where  current code was blowing up)
    # ---------------------------------------------------------------------
    assignments = _get_pac_assignments(ctx)

    # emulate "API returned no data"
    if not assignments:
        msg = (
            f"FAIL: No PAC role data available for system {system_id}; "
            "cannot confirm Organizational ISSM."
        )
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error("[T169] %s system_id=%s", msg, system_id)
        return tr

    logger.debug(
        "[T169] Found %d PAC rows to inspect system_id=%s",
        len(assignments),
        system_id,
    )

    # ---------------------------------------------------------------------
    # 2) PS-style filtering for this system and this role
    # ---------------------------------------------------------------------
    oissm_names: List[str] = []

    for row in assignments:
        # systemId can be 'systemId', 'system_id', or sometimes weird casing
        row_sys_id = (
            ci_get(row, "systemId")
            or ci_get(row, "system_id")
            or ci_get(row, "SystemID")
        )
        if str(row_sys_id) != str(system_id):
            continue

        roles_field = ci_get(row, "roles")
        roles = normalize_roles(roles_field)
        if not roles:
            continue

        for role in roles:
            role_name = (
                ci_get(role, "role")
                or ci_get(role, "roleName")
                or ci_get(role, "name")
                or ""
            )
            if not is_o_issm_role(str(role_name)):
                continue

            users_field = ci_get(role, "users") or []
            if isinstance(users_field, dict):
                users: Sequence[Dict[str, Any]] = [users_field]
            else:
                users = users_field  # assume list-ish

            for user in users:
                if not isinstance(user, dict):
                    continue
                first = (ci_get(user, "firstName", "") or "").strip()
                last = (ci_get(user, "lastName", "") or "").strip()
                full = (first + " " + last).strip()
                if full:
                    oissm_names.append(full)

    # dedupe, keep order
    unique_names = list(dict.fromkeys(oissm_names))

    # ---------------------------------------------------------------------
    # 3) outcome — strict PS parity
    # ---------------------------------------------------------------------
    if not unique_names:
        msg = f"FAIL: No Organizational ISSM users found for system {system_id}."
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message=msg,
        )
        status.add(tr)
        logger.error("[T169] %s system_id=%s", msg, system_id)
        return tr

    joined = ", ".join(unique_names)
    msg = f"PASS: The O-ISSMs are: {joined}"
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=msg,
    )
    status.add(tr)
    logger.info("[T169] %s system_id=%s", msg, system_id)
    return tr






def test_170(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 170 — Correct PAC P-ISSM Present.

    Validates that, for the current ``system_id``, at least one user is assigned to the
    **Program ISSM (P-ISSM)** role using **nested models only** (strictly no access to
    ``raw_payloads``). Mirrors the legacy PowerShell behavior that queried
    ``GET /api/system-roles/pac?role=Program%20ISSM`` and failed when no names were found.

    PowerShell-parity outcomes:
      * No P-ISSM names found → **FAIL** with legacy wording:
        ``"FAIL: The P-ISSM is not provided"``.
      * ≥1 name found → **PASS** with legacy wording:
        ``"PASS: The P-ISSMs are: <names>"``.

    Design notes:
      * Stays **out of** ``ctx.raw_payloads`` entirely; inspects only ``ctx.user_details.data``.
      * Robust to light schema drift (camelCase/snake_case; role as list/dict).
      * Stable de-dup preserving discovery order.
      * Emits breadcrumbs in house style: ``[T170] Running → source rows → extracted names → result``.

    Args:
      ctx: Authoritative snapshot of one eMASS system (nested models only).
      status: Aggregator that records this test’s result.

    Returns:
      TestResult: PASS if ≥1 Program ISSM assignee exists; otherwise FAIL.
    """
    test_number = 170
    test_name = "Test 170: Correct PAC P-ISSM Present"
    system_id = getattr(ctx, "system_id", None)

    logger.debug("[T170] Running %s (system_id=%s)", test_name, system_id)

    # ---------- helpers ----------
    def _ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict lookup with a safe default."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def _as_list(x: Optional[Any]) -> List[Any]:
        """Return list/tuple as list; else empty list (strings excluded)."""
        if isinstance(x, list):
            return x
        if isinstance(x, tuple):
            return list(x)
        return []

    def _normalize_roles(roles_field: Any) -> List[Dict[str, Any]]:
        """Normalize a 'roles' field into a list[dict]."""
        if roles_field is None:
            return []
        if isinstance(roles_field, dict):
            return [roles_field]
        if isinstance(roles_field, (list, tuple)):
            return [r for r in roles_field if isinstance(r, dict)]
        return []

    def _is_program_issm(role_val: Any) -> bool:
        """Loose matcher for 'Program ISSM' (tolerate case, hyphens, spacing)."""
        if not role_val:
            return False
        s = str(role_val).strip().lower()
        s = " ".join(s.split())             # collapse internal whitespace
        s = s.replace("-", " ")             # normalize hyphens to spaces
        return s == "program issm"

    # ---------- source: nested models only ----------
    if getattr(ctx, "user_details", None) and getattr(ctx.user_details, "data", None):
        rows: List[Dict[str, Any]] = [r for r in _as_list(ctx.user_details.data) if isinstance(r, dict)]
        logger.debug("[T170] Using user_details.data (rows=%d)", len(rows))
    else:
        rows = []
        logger.debug("[T170] No user_details.data available")

    # Early exit if no rows (match legacy wording exactly).
    if not rows:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The P-ISSM is not provided",
        )
        status.add(tr)
        logger.debug("[T170] Result=FAIL (no nested PAC-style data)")
        return tr

    # ---------- extraction ----------
    names: List[str] = []

    for row in rows:
        # Filter to this system when an id is present on the row; tolerate absence.
        row_sid = _ci_get(row, "systemId") or _ci_get(row, "system_id") or _ci_get(row, "SystemID")
        if system_id is not None and row_sid is not None and str(row_sid) != str(system_id):
            continue

        for role in _normalize_roles(_ci_get(row, "roles")):
            role_name = _ci_get(role, "role") or _ci_get(role, "roleName") or _ci_get(role, "name") or ""
            if not _is_program_issm(role_name):
                continue

            users_field = _ci_get(role, "users") or []
            users: Sequence[Dict[str, Any]]
            if isinstance(users_field, dict):
                users = [users_field]
            else:
                users = [u for u in _as_list(users_field) if isinstance(u, dict)]

            for user in users:
                first = str(_ci_get(user, "firstName", "") or _ci_get(user, "first_name", "")).strip()
                last = str(_ci_get(user, "lastName", "") or _ci_get(user, "last_name", "")).strip()
                full = (first + " " + last).strip() or str(_ci_get(user, "name", "")).strip()
                if full:
                    names.append(full)

    unique_names = list(dict.fromkeys(names))  # stable de-dup; preserve discovery order
    logger.debug("[T170] Extracted Program ISSM names (unique=%d): %s", len(unique_names), unique_names)

    # ---------- result ----------
    if not unique_names:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The P-ISSM is not provided",
        )
        status.add(tr)
        logger.debug("[T170] Result=FAIL (no Program ISSM assignments found)")
        return tr

    joined = ", ".join(unique_names)
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=f"PASS: The P-ISSMs are: {joined}",
    )
    status.add(tr)
    logger.debug("[T170] Result=PASS (names=%d)", len(unique_names))
    return tr




def test_171(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 171 — Correct PAC SCA-R Present.

    Validates that, for the current ``system_id``, at least one user is assigned to
    the **SCA-R** role using **nested models only** (no access to ``raw_payloads``).
    Behavior mirrors the legacy PowerShell which queried:
    ``GET /api/system-roles/pac?role=SCA-R``.

    PowerShell parity:
      * If no SCA-R names are found → **FAIL** (legacy wording):
        ``"FAIL: The SCA-R is not provided"``.
      * Else → **PASS** with legacy wording:
        ``"PASS: The SCA-Rs are: <names>"``.

    Design notes:
      * Stays out of ``ctx.raw_payloads`` entirely; inspects only ``ctx.user_details.data``.
      * Robust to light schema drift (camelCase/snake_case; role as list/dict).
      * Preserves discovery order; de-duplicates deterministically.
      * Emits breadcrumbs in house style: ``[T171] Running → source rows → extracted names → result``.

    Args:
      ctx: Authoritative snapshot of one eMASS system (nested models only).
      status: Aggregator that records this test’s result.

    Returns:
      TestResult: PASS if ≥1 SCA-R assignee exists; otherwise FAIL.
    """
    test_number = 171
    test_name = "Test 171: Correct PAC SCA-R Present"
    system_id = getattr(ctx, "system_id", None)

    logger.debug("[T171] Running %s (system_id=%s)", test_name, system_id)

    # ---------- helpers ----------
    def _ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict lookup with a safe default."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def _as_list(x: Optional[Any]) -> List[Any]:
        """Return list/tuple as list; else empty list (strings excluded)."""
        if isinstance(x, list):
            return x
        if isinstance(x, tuple):
            return list(x)
        return []

    def _normalize_roles(roles_field: Any) -> List[Dict[str, Any]]:
        """Normalize a 'roles' field into a list[dict]."""
        if roles_field is None:
            return []
        if isinstance(roles_field, dict):
            return [roles_field]
        if isinstance(roles_field, (list, tuple)):
            return [r for r in roles_field if isinstance(r, dict)]
        return []

    def _is_scar(role_val: Any) -> bool:
        """Loose matcher for 'SCA-R' (tolerate case, spaces, and hyphens)."""
        if not role_val:
            return False
        s = str(role_val).strip().lower()
        s = " ".join(s.split())          # collapse whitespace
        s = s.replace(" ", "").replace("-", "")
        return s == "scar"

    # ---------- source: nested models only ----------
    if getattr(ctx, "user_details", None) and getattr(ctx.user_details, "data", None):
        assignments: List[Dict[str, Any]] = [
            row for row in _as_list(ctx.user_details.data) if isinstance(row, dict)
        ]
        logger.debug("[T171] Using user_details.data (rows=%d)", len(assignments))
    else:
        assignments = []
        logger.debug("[T171] No user_details.data available")

    # Early exit: no rows → legacy FAIL wording.
    if not assignments:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The SCA-R is not provided",
        )
        status.add(tr)
        logger.debug("[T171] Result=FAIL (no nested role data)")
        return tr

    # ---------- extraction ----------
    names: List[str] = []

    for row in assignments:
        # Match the system ID when present on the row; tolerate absence.
        row_sid = (
            _ci_get(row, "systemId")
            or _ci_get(row, "system_id")
            or _ci_get(row, "SystemID")
        )
        if system_id is not None and row_sid is not None and str(row_sid) != str(system_id):
            continue

        for role in _normalize_roles(_ci_get(row, "roles")):
            role_name = _ci_get(role, "role") or _ci_get(role, "roleName") or _ci_get(role, "rolename") or ""
            if not _is_scar(role_name):
                continue

            users_field = _ci_get(role, "users") or []
            if isinstance(users_field, dict):
                users: Sequence[Dict[str, Any]] = [users_field]
            else:
                users = [u for u in _as_list(users_field) if isinstance(u, dict)]

            for user in users:
                first = str(_ci_get(user, "firstName", "") or _ci_get(user, "first_name", "")).strip()
                last = str(_ci_get(user, "lastName", "") or _ci_get(user, "last_name", "")).strip()
                full = (first + " " + last).strip() or str(_ci_get(user, "name", "")).strip()
                if full:
                    names.append(full)

    unique_names = list(dict.fromkeys(names))  # stable de-dup; preserve discovery order
    logger.debug("[T171] Extracted SCA-R names (unique=%d): %s", len(unique_names), unique_names)

    # ---------- result ----------
    if not unique_names:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The SCA-R is not provided",
        )
        status.add(tr)
        logger.debug("[T171] Result=FAIL (no SCA-R assignments found)")
        return tr

    joined = ", ".join(unique_names)
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=f"PASS: The SCA-Rs are: {joined}",
    )
    status.add(tr)
    logger.debug("[T171] Result=PASS (names=%d)", len(unique_names))
    return tr



def test_172(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 172 — Correct PAC SCA-A Present.

    Validates that, for the current ``system_id``, at least one user is assigned to
    the **SCA-A** role using **nested models only** (no access to ``raw_payloads``).
    Behavior mirrors the legacy PowerShell, which queried:
    ``GET /api/system-roles/pac?role=SCA-A``.

    Parity with PowerShell:
      * If no SCA-A names are found → **FAIL** (legacy wording):
        ``"FAIL: The SCA-A is not provided"``.
      * Else → **PASS** with legacy wording:
        ``"PASS: The SCA-As are: <names>"``.

    Design notes:
      * Stays out of ``ctx.raw_payloads`` entirely; inspects only ``ctx.user_details.data``.
      * Robust to light schema drift (camelCase/snake_case; role as list/dict).
      * Preserves discovery order; de-duplicates deterministically.
      * Emits breadcrumbs in house style: ``[T172] Running → source rows → extracted names → result``.

    Args:
      ctx: Authoritative snapshot of one eMASS system (nested models only).
      status: Aggregator that records this test’s result.

    Returns:
      TestResult: PASS if ≥1 SCA-A assignee exists; otherwise FAIL.
    """
    test_number = 172
    test_name = "Test 172: Correct PAC SCA-A Present"
    system_id = getattr(ctx, "system_id", None)

    logger.debug("[T172] Running %s (system_id=%s)", test_name, system_id)

    # ---------- helpers ----------
    def _ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict lookup with a safe default."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def _as_list(x: Optional[Any]) -> List[Any]:
        """Return list/tuple as list; else empty list (strings excluded)."""
        if isinstance(x, list):
            return x
        if isinstance(x, tuple):
            return list(x)
        return []

    def _normalize_roles(roles_field: Any) -> List[Dict[str, Any]]:
        """Normalize a 'roles' field into a list[dict]."""
        if roles_field is None:
            return []
        if isinstance(roles_field, dict):
            return [roles_field]
        if isinstance(roles_field, (list, tuple)):
            return [r for r in roles_field if isinstance(r, dict)]
        return []

    def _is_scaa(role_val: Any) -> bool:
        """Loose matcher for 'SCA-A' (tolerate case, spaces, and hyphens)."""
        if not role_val:
            return False
        s = str(role_val).strip().lower()
        s = " ".join(s.split())          # collapse whitespace
        s = s.replace(" ", "").replace("-", "")
        return s == "scaa"

    # ---------- source: nested models only ----------
    if getattr(ctx, "user_details", None) and getattr(ctx.user_details, "data", None):
        assignments: List[Dict[str, Any]] = [
            row for row in _as_list(ctx.user_details.data) if isinstance(row, dict)
        ]
        logger.debug("[T172] Using user_details.data (rows=%d)", len(assignments))
    else:
        assignments = []
        logger.debug("[T172] No user_details.data available")

    # Early exit: no rows → legacy FAIL wording.
    if not assignments:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The SCA-A is not provided",
        )
        status.add(tr)
        logger.debug("[T172] Result=FAIL (no nested role data)")
        return tr

    # ---------- extraction ----------
    names: List[str] = []

    for row in assignments:
        # Match the system ID when present on the row; tolerate absence.
        row_sid = (
            _ci_get(row, "systemId")
            or _ci_get(row, "system_id")
            or _ci_get(row, "SystemID")
        )
        if system_id is not None and row_sid is not None and str(row_sid) != str(system_id):
            continue

        for role in _normalize_roles(_ci_get(row, "roles")):
            role_name = _ci_get(role, "role") or _ci_get(role, "roleName") or _ci_get(role, "rolename") or ""
            if not _is_scaa(role_name):
                continue

            users_field = _ci_get(role, "users") or []
            users: Sequence[Dict[str, Any]]
            if isinstance(users_field, dict):
                users = [users_field]
            else:
                users = [u for u in _as_list(users_field) if isinstance(u, dict)]

            for user in users:
                first = str(_ci_get(user, "firstName", "") or _ci_get(user, "first_name", "")).strip()
                last = str(_ci_get(user, "lastName", "") or _ci_get(user, "last_name", "")).strip()
                full = (first + " " + last).strip() or str(_ci_get(user, "name", "")).strip()
                if full:
                    names.append(full)

    unique_names = list(dict.fromkeys(names))  # stable de-dup; preserve discovery order
    logger.debug("[T172] Extracted SCA-A names (unique=%d): %s", len(unique_names), unique_names)

    # ---------- result ----------
    if not unique_names:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The SCA-A is not provided",
        )
        status.add(tr)
        logger.debug("[T172] Result=FAIL (no SCA-A assignments found)")
        return tr

    joined = ", ".join(unique_names)
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=f"PASS: The SCA-As are: {joined}",
    )
    status.add(tr)
    logger.debug("[T172] Result=PASS (names=%d)", len(unique_names))
    return tr




def test_173(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 173 — Correct PAC AO Present.

    Validates that, for the current ``system_id``, at least one user is assigned to
    the **AO** role using **nested models only** (no access to ``raw_payloads``).
    Behavior mirrors the legacy PowerShell, which queried:
    ``GET /api/system-roles/pac?role=AO``.

    Parity with PowerShell:
      * If no AO names are found → **FAIL** with legacy wording
        ``"FAIL: The AO is not provided"``.
      * Else → **PASS** with legacy wording
        ``"PASS: The AO is: <names>"`` (singular “is” kept for diff stability).

    Design notes:
      * Stays out of ``ctx.raw_payloads`` entirely; inspects only ``ctx.user_details.data``.
      * Robust to light schema drift (camelCase/snake_case; role as list/dict).
      * Preserves discovery order; de-duplicates deterministically.
      * Emits breadcrumbs in house style: ``[T173] Running → source rows → extracted names → result``.

    Args:
      ctx: Authoritative snapshot of one eMASS system (nested models only).
      status: Aggregator that records this test’s result.

    Returns:
      TestResult: PASS if ≥1 AO assignee exists; otherwise FAIL.
    """
    test_number = 173
    test_name = "Test 173: Correct PAC AO Present"
    system_id = getattr(ctx, "system_id", None)

    logger.debug("[T173] Running %s (system_id=%s)", test_name, system_id)

    # ---------- helpers ----------
    def _ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict lookup with a safe default."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def _as_list(x: Optional[Any]) -> List[Any]:
        """Return list/tuple as list; else empty list (strings excluded)."""
        if isinstance(x, list):
            return x
        if isinstance(x, tuple):
            return list(x)
        return []

    def _normalize_roles(roles_field: Any) -> List[Dict[str, Any]]:
        """Normalize a 'roles' field into a list[dict]."""
        if roles_field is None:
            return []
        if isinstance(roles_field, dict):
            return [roles_field]
        if isinstance(roles_field, (list, tuple)):
            return [r for r in roles_field if isinstance(r, dict)]
        return []

    def _is_ao(role_val: Any) -> bool:
        """Loose matcher for 'AO' (tolerate case and extra spaces)."""
        if not role_val:
            return False
        s = " ".join(str(role_val).strip().lower().split())
        return s == "ao"

    # ---------- source: nested models only ----------
    if getattr(ctx, "user_details", None) and getattr(ctx.user_details, "data", None):
        assignments: List[Dict[str, Any]] = [
            row for row in _as_list(ctx.user_details.data) if isinstance(row, dict)
        ]
        logger.debug("[T173] Using user_details.data (rows=%d)", len(assignments))
    else:
        assignments = []
        logger.debug("[T173] No user_details.data available")

    # Early exit: no rows to examine → legacy FAIL wording.
    if not assignments:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The AO is not provided",
        )
        status.add(tr)
        logger.debug("[T173] Result=FAIL (no nested role data)")
        return tr

    # ---------- extraction ----------
    names: List[str] = []

    for row in assignments:
        # Match the system ID when present on the row; tolerate absence.
        row_sid = _ci_get(row, "systemId") or _ci_get(row, "system_id") or _ci_get(row, "SystemID")
        if system_id is not None and row_sid is not None and str(row_sid) != str(system_id):
            continue

        for role in _normalize_roles(_ci_get(row, "roles")):
            role_name = _ci_get(role, "role") or _ci_get(role, "roleName") or _ci_get(role, "rolename") or ""
            if not _is_ao(role_name):
                continue

            users_field = _ci_get(role, "users") or []
            users: Sequence[Dict[str, Any]]
            if isinstance(users_field, dict):
                users = [users_field]
            else:
                users = [u for u in _as_list(users_field) if isinstance(u, dict)]

            for user in users:
                first = str(_ci_get(user, "firstName", "") or _ci_get(user, "first_name", "")).strip()
                last = str(_ci_get(user, "lastName", "") or _ci_get(user, "last_name", "")).strip()
                full = (first + " " + last).strip() or str(_ci_get(user, "name", "")).strip()
                if full:
                    names.append(full)

    unique_names = list(dict.fromkeys(names))  # stable de-dup; preserve discovery order
    logger.debug("[T173] Extracted AO names (unique=%d): %s", len(unique_names), unique_names)

    # ---------- result ----------
    if not unique_names:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The AO is not provided",
        )
        status.add(tr)
        logger.debug("[T173] Result=FAIL (no AO assignments found)")
        return tr

    joined = ", ".join(unique_names)
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=f"PASS: The AO is: {joined}",  # Keep PS wording (“is”) for diff stability.
    )
    status.add(tr)
    logger.debug("[T173] Result=PASS (names=%d)", len(unique_names))
    return tr




def test_174(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 174 — Correct PAC AODR Present.

    Validates that, for the current ``system_id``, at least one user is assigned to
    the **AODR** role using **nested models only** (no access to ``raw_payloads``).
    Behavior mirrors the legacy PowerShell, which queried:
    ``GET /api/system-roles/pac?role=AODR``.

    Parity with PowerShell:
      * If no AODR names are found → **FAIL** with legacy wording
        ``"FAIL: The AODR is not provided"``.
      * Else → **PASS** with legacy wording
        ``"PASS: The AODRs are: <names>"`` (plural “AODRs” kept for diff stability).

    Design notes:
      * Stays out of ``ctx.raw_payloads`` entirely; inspects only ``ctx.user_details.data``.
      * Robust to light schema drift (camelCase/snake_case; role as list/dict).
      * Preserves discovery order; de-duplicates deterministically.
      * Small, local helpers; no side effects beyond logging and status aggregation.

    Args:
      ctx: Authoritative snapshot of one eMASS system (nested models only).
      status: Aggregator that records this test’s result.

    Returns:
      TestResult: PASS if ≥1 AODR assignee exists; otherwise FAIL.

    Logging:
      Emits breadcrumbs in house style:
      ``[T174] Running … → source rows → extracted names → final result``.
    """
    test_number = 174
    test_name = "Test 174: Correct PAC AODR Present"
    system_id = getattr(ctx, "system_id", None)

    logger.debug("[T174] Running %s (system_id=%s)", test_name, system_id)

    # ---------- helpers ----------
    def _ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict lookup with a safe default."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def _as_list(x: Optional[Any]) -> List[Any]:
        """Return list/tuple as list; else empty list (strings excluded)."""
        if isinstance(x, list):
            return x
        if isinstance(x, tuple):
            return list(x)
        return []

    def _normalize_roles(roles_field: Any) -> List[Dict[str, Any]]:
        """Normalize a 'roles' field into a list[dict]."""
        if roles_field is None:
            return []
        if isinstance(roles_field, dict):
            return [roles_field]
        if isinstance(roles_field, (list, tuple)):
            return [r for r in roles_field if isinstance(r, dict)]
        return []

    def _is_aodr(role_val: Any) -> bool:
        """Loose matcher for 'AODR' (tolerate case and extra spaces)."""
        if not role_val:
            return False
        s = " ".join(str(role_val).strip().lower().split())
        return s == "aodr"

    # ---------- source: nested models only ----------
    if getattr(ctx, "user_details", None) and getattr(ctx.user_details, "data", None):
        assignments: List[Dict[str, Any]] = [
            row for row in _as_list(ctx.user_details.data) if isinstance(row, dict)
        ]
        logger.debug("[T174] Using user_details.data (rows=%d)", len(assignments))
    else:
        assignments = []
        logger.debug("[T174] No user_details.data available")

    # If no rows at all, return legacy FAIL wording.
    if not assignments:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The AODR is not provided",
        )
        status.add(tr)
        logger.debug("[T174] Result=FAIL (no nested role data)")
        return tr

    # ---------- extraction ----------
    names: List[str] = []

    for row in assignments:
        # Match the system ID when present on the row; tolerate absence.
        row_sid = _ci_get(row, "systemId") or _ci_get(row, "system_id") or _ci_get(row, "SystemID")
        if system_id is not None and row_sid is not None and str(row_sid) != str(system_id):
            continue

        for role in _normalize_roles(_ci_get(row, "roles")):
            role_name = _ci_get(role, "role") or _ci_get(role, "roleName") or _ci_get(role, "rolename") or ""
            if not _is_aodr(role_name):
                continue

            users_field = _ci_get(role, "users") or []
            users: Sequence[Dict[str, Any]]
            if isinstance(users_field, dict):
                users = [users_field]
            else:
                users = [u for u in _as_list(users_field) if isinstance(u, dict)]

            for user in users:
                first = str(_ci_get(user, "firstName", "") or _ci_get(user, "first_name", "")).strip()
                last = str(_ci_get(user, "lastName", "") or _ci_get(user, "last_name", "")).strip()
                full = (first + " " + last).strip() or str(_ci_get(user, "name", "")).strip()
                if full:
                    names.append(full)

    unique_names = list(dict.fromkeys(names))  # stable de-dup; preserve discovery order
    logger.debug("[T174] Extracted AODR names (unique=%d): %s", len(unique_names), unique_names)

    # ---------- result ----------
    if not unique_names:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The AODR is not provided",
        )
        status.add(tr)
        logger.debug("[T174] Result=FAIL (no AODR assignments found)")
        return tr

    joined = ", ".join(unique_names)
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=f"PASS: The AODRs are: {joined}",
    )
    status.add(tr)
    logger.debug("[T174] Result=PASS (names=%d)", len(unique_names))
    return tr



def test_175(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 175 — Correct PAC Network AO Present.

    Validates that, for the current ``system_id``, at least one user is assigned to
    the **Network AO** role using **nested models only** (no access to ``raw_payloads``).
    Behavior mirrors the legacy PowerShell, which queried:
    ``GET /api/system-roles/pac?role=Network%20AO``.

    Parity with PowerShell:
      * If no Network AO names are found for this system → **FAIL** with
        ``"The Network AO is not provided"``.
      * Else → **PASS** listing the names (comma-delimited). We keep the legacy wording
        that uses “is” even when multiple names exist.

    Design:
      * Stays out of ``ctx.raw_payloads`` entirely; inspects only ``ctx.user_details.data``.
      * Robust to light schema drift (camelCase/snake_case; role as list/dict).
      * Preserves discovery order; de-duplicates deterministically.

    Args:
      ctx: Authoritative snapshot for one system (nested models only).
      status: Aggregator that records this test’s result.

    Returns:
      TestResult: PASS if ≥1 Network AO assignee exists; otherwise FAIL.

    Logging:
      Emits breadcrumbs in house style:
      ``[T175] Running … → source rows → extracted names → final result``.
    """
    test_number = 175
    test_name = "Test 175: Correct PAC Network AO Present"
    system_id = getattr(ctx, "system_id", None)

    logger.debug("[T175] Running %s (system_id=%s)", test_name, system_id)

    # ---------- helpers ----------
    def _ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict lookup with a safe default."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def _as_list(x: Optional[Any]) -> List[Any]:
        """Return list/tuple as list; else empty list (strings excluded)."""
        if isinstance(x, list):
            return x
        if isinstance(x, tuple):
            return list(x)
        return []

    def _normalize_roles(roles_field: Any) -> List[Dict[str, Any]]:
        """Normalize a 'roles' field into a list[dict]."""
        if roles_field is None:
            return []
        if isinstance(roles_field, dict):
            return [roles_field]
        if isinstance(roles_field, (list, tuple)):
            return [r for r in roles_field if isinstance(r, dict)]
        return []

    def _is_network_ao(role_val: Any) -> bool:
        """Loose matcher for 'Network AO' (tolerate case and extra spaces)."""
        if not role_val:
            return False
        s = " ".join(str(role_val).strip().lower().split())
        return s == "network ao"

    # ---------- source: nested models only ----------
    if getattr(ctx, "user_details", None) and getattr(ctx.user_details, "data", None):
        assignments: List[Dict[str, Any]] = [
            row for row in _as_list(ctx.user_details.data) if isinstance(row, dict)
        ]
        logger.debug("[T175] Using user_details.data (rows=%d)", len(assignments))
    else:
        assignments = []
        logger.debug("[T175] No user_details.data available")

    # Short-circuit if no source rows at all (legacy wording)
    if not assignments:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The Network AO is not provided",
        )
        status.add(tr)
        logger.debug("[T175] Result=FAIL (no nested role data)")
        return tr

    # ---------- extraction ----------
    names: List[str] = []

    for row in assignments:
        # Match the system ID when present on the row; tolerate absence.
        row_sid = _ci_get(row, "systemId") or _ci_get(row, "system_id") or _ci_get(row, "SystemID")
        if system_id is not None and row_sid is not None and str(row_sid) != str(system_id):
            continue

        for role in _normalize_roles(_ci_get(row, "roles")):
            role_name = _ci_get(role, "role") or _ci_get(role, "roleName") or _ci_get(role, "rolename") or ""
            if not _is_network_ao(role_name):
                continue

            users_field = _ci_get(role, "users") or []
            users: Sequence[Dict[str, Any]]
            if isinstance(users_field, dict):
                users = [users_field]
            else:
                users = [u for u in _as_list(users_field) if isinstance(u, dict)]

            for user in users:
                first = str(_ci_get(user, "firstName", "") or _ci_get(user, "first_name", "")).strip()
                last = str(_ci_get(user, "lastName", "") or _ci_get(user, "last_name", "")).strip()
                full = (first + " " + last).strip() or str(_ci_get(user, "name", "")).strip()
                if full:
                    names.append(full)

    unique_names = list(dict.fromkeys(names))  # stable de-dup; preserve discovery order
    logger.debug("[T175] Extracted Network AO names (unique=%d): %s", len(unique_names), unique_names)

    # ---------- result ----------
    if not unique_names:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The Network AO is not provided",
        )
        status.add(tr)
        logger.debug("[T175] Result=FAIL (no Network AO assignments found)")
        return tr

    joined = ", ".join(unique_names)
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        # Keep PS wording ("is") even if multiple names, to match legacy output.
        message=f"PASS: The Network AO is: {joined}",
    )
    status.add(tr)
    logger.debug("[T175] Result=PASS (names=%d)", len(unique_names))
    return tr


def test_176(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 176 — Correct PAC Network AODR Present.

    Validate that, for the current ``system_id``, at least one user is assigned to the
    **Network AODR** role using **nested models only** (strictly no access to
    ``raw_payloads``). This mirrors the legacy PowerShell behavior that queried
    ``GET /api/system-roles/pac?role=Network%20AODR`` and failed when no names were found.

    PowerShell parity:
      * No Network AODR names found → **FAIL** with legacy wording:
        ``"FAIL: The Network AODR is not provided"``.
      * ≥1 name found → **PASS** with legacy wording:
        ``"PASS: The Network AODR is: <names>"`` (note the singular “is” even for multiples).

    Design notes:
      * Stays **out of** ``ctx.raw_payloads`` entirely; inspects only ``ctx.user_details.data``.
      * Tolerates light schema drift (camelCase/snake_case; role as dict/list).
      * Stable, deterministic de-dup preserving discovery order.
      * Emits breadcrumbs in our house style:
        ``[T176] Running → source rows → extracted names → result``.

    Args:
        ctx: Authoritative snapshot of one eMASS system (nested models only).
        status: Aggregator that records this test’s result.

    Returns:
        TestResult: PASS if ≥1 Network AODR assignee exists; otherwise FAIL.
    """
    test_number = 176
    test_name = "Test 176: Correct PAC Network AODR Present"
    system_id = getattr(ctx, "system_id", None)

    logger.debug("[T176] Running %s (system_id=%s)", test_name, system_id)

    # ---------- helpers ----------
    def _ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict lookup with a safe default."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def _as_list(x: Optional[Any]) -> List[Any]:
        """Return list/tuple as list; else empty list (strings excluded)."""
        if isinstance(x, list):
            return x
        if isinstance(x, tuple):
            return list(x)
        return []

    def _normalize_roles(roles_field: Any) -> List[Dict[str, Any]]:
        """Normalize a 'roles' field into a list[dict]."""
        if roles_field is None:
            return []
        if isinstance(roles_field, dict):
            return [roles_field]
        if isinstance(roles_field, (list, tuple)):
            return [r for r in roles_field if isinstance(r, dict)]
        return []

    def _is_network_aodr(role_val: Any) -> bool:
        """Loose matcher for 'Network AODR' (tolerate case/hyphens/extra spaces)."""
        if not role_val:
            return False
        s = str(role_val).strip().lower()
        s = " ".join(s.replace("-", " ").split())  # normalize separators/whitespace
        return s == "network aodr"

    # ---------- source: nested models only ----------
    if getattr(ctx, "user_details", None) and getattr(ctx.user_details, "data", None):
        rows: List[Dict[str, Any]] = [r for r in _as_list(ctx.user_details.data) if isinstance(r, dict)]
        logger.debug("[T176] Using user_details.data (rows=%d)", len(rows))
    else:
        rows = []
        logger.debug("[T176] No user_details.data available")

    # If there is no nested PAC-style data at all, match legacy failure wording.
    if not rows:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The Network AODR is not provided",
        )
        status.add(tr)
        logger.debug("[T176] Result=FAIL (no nested role data)")
        return tr

    # ---------- extraction ----------
    names: List[str] = []

    for row in rows:
        # Respect row-level system id if present; tolerate absence.
        row_sid = _ci_get(row, "systemId") or _ci_get(row, "system_id") or _ci_get(row, "SystemID")
        if system_id is not None and row_sid is not None and str(row_sid) != str(system_id):
            continue

        for role in _normalize_roles(_ci_get(row, "roles")):
            role_name = _ci_get(role, "role") or _ci_get(role, "roleName") or _ci_get(role, "rolename") or ""
            if not _is_network_aodr(role_name):
                continue

            users_field = _ci_get(role, "users") or []
            users: Sequence[Dict[str, Any]]
            if isinstance(users_field, dict):
                users = [users_field]
            else:
                users = [u for u in _as_list(users_field) if isinstance(u, dict)]

            for user in users:
                first = str(_ci_get(user, "firstName", "") or _ci_get(user, "first_name", "")).strip()
                last = str(_ci_get(user, "lastName", "") or _ci_get(user, "last_name", "")).strip()
                full = (first + " " + last).strip() or str(_ci_get(user, "name", "")).strip()
                if full:
                    names.append(full)

    unique_names = list(dict.fromkeys(names))  # stable de-dup; preserve discovery order
    logger.debug("[T176] Extracted Network AODR names (unique=%d): %s", len(unique_names), unique_names)

    # ---------- result ----------
    if not unique_names:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The Network AODR is not provided",
        )
        status.add(tr)
        logger.debug("[T176] Result=FAIL (no Network AODR assignments found)")
        return tr

    joined = ", ".join(unique_names)
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=f"PASS: The Network AODR is: {joined}",
    )
    status.add(tr)
    logger.debug("[T176] Result=PASS (names=%d)", len(unique_names))
    return tr


def test_177(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 177 — Correct CAC ISO/PM/ISSO Present.

    Validate that, for the current ``system_id``, at least one user is assigned to the
    **ISO/PM/ISSO** role using **nested models only** (strictly no access to
    ``raw_payloads``). This mirrors the legacy PowerShell behavior that queried:
    ``GET /api/system-roles/cac?role=ISO%2FPM%2FISSO`` and failed when no names were found.

    PowerShell parity:
      * No ISO/PM/ISSO names found → **FAIL** with legacy wording:
        ``"FAIL: The CAC ISO/PM/ISSO is not provided"``.
      * ≥1 name found → **PASS** with legacy wording:
        ``"PASS: The CAC ISO/PM/ISSO is: <names>"`` (note the singular “is” even for multiples).

    Design notes:
      * Stays **out of** ``ctx.raw_payloads`` entirely; inspects only ``ctx.user_details.data``.
      * Tolerates light schema drift (camelCase/snake_case; role as dict/list).
      * Stable, deterministic de-dup preserving discovery order.
      * Emits breadcrumbs in our house style:
        ``[T177] Running → source rows → extracted names → result``.

    Args:
        ctx: Authoritative snapshot of one eMASS system (nested models only).
        status: Aggregator that records this test’s result.

    Returns:
        TestResult: PASS if ≥1 ISO/PM/ISSO assignee exists; otherwise FAIL.
    """
    test_number = 177
    test_name = "Test 177: Correct CAC ISO/PM/ISSO Present"
    system_id = getattr(ctx, "system_id", None)

    logger.debug("[T177] Running %s (system_id=%s)", test_name, system_id)

    # ---------- helpers ----------
    def _ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict lookup with a safe default."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def _as_list(x: Optional[Any]) -> List[Any]:
        """Return list/tuple as list; else empty list (strings excluded)."""
        if isinstance(x, list):
            return x
        if isinstance(x, tuple):
            return list(x)
        return []

    def _normalize_roles(roles_field: Any) -> List[Dict[str, Any]]:
        """Normalize a 'roles' field into a list[dict]."""
        if roles_field is None:
            return []
        if isinstance(roles_field, dict):
            return [roles_field]
        if isinstance(roles_field, (list, tuple)):
            return [r for r in roles_field if isinstance(r, dict)]
        return []

    def _is_iso_pm_isso(role_val: Any) -> bool:
        """Loose matcher for 'ISO/PM/ISSO' tolerant of hyphens/slashes/space/case."""
        if not role_val:
            return False
        s = str(role_val).strip().lower()
        s = " ".join(s.replace("-", " ").replace("/", " ").split())
        return s == "iso pm isso"

    # ---------- source: nested models only ----------
    rows: List[Dict[str, Any]] = []
    if getattr(ctx, "user_details", None) and getattr(ctx.user_details, "data", None):
        rows = [r for r in _as_list(ctx.user_details.data) if isinstance(r, dict)]
        logger.debug("[T177] Using user_details.data (rows=%d)", len(rows))
    else:
        logger.debug("[T177] No user_details.data available")

    # If there is no nested CAC-style role data at all, match legacy failure wording.
    if not rows:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The CAC ISO/PM/ISSO is not provided",
        )
        status.add(tr)
        logger.debug("[T177] Result=FAIL (no nested role data)")
        return tr

    # ---------- extraction ----------
    names: List[str] = []

    for row in rows:
        # Respect row-level system id if present; tolerate absence.
        row_sid = (
            _ci_get(row, "systemId")
            or _ci_get(row, "system_id")
            or _ci_get(row, "SystemID")
        )
        if system_id is not None and row_sid is not None and str(row_sid) != str(system_id):
            continue

        for role in _normalize_roles(_ci_get(row, "roles")):
            role_name = (
                _ci_get(role, "role")
                or _ci_get(role, "roleName")
                or _ci_get(role, "name")
                or ""
            )
            if not _is_iso_pm_isso(role_name):
                continue

            users_field = _ci_get(role, "users") or []
            users: Sequence[Dict[str, Any]]
            if isinstance(users_field, dict):
                users = [users_field]
            else:
                users = [u for u in _as_list(users_field) if isinstance(u, dict)]

            for user in users:
                first = str(_ci_get(user, "firstName", "") or _ci_get(user, "first_name", "")).strip()
                last = str(_ci_get(user, "lastName", "") or _ci_get(user, "last_name", "")).strip()
                full = (first + " " + last).strip() or str(_ci_get(user, "name", "")).strip()
                if full:
                    names.append(full)

    unique_names = list(dict.fromkeys(names))  # stable de-dup; preserve discovery order
    logger.debug("[T177] Extracted ISO/PM/ISSO names (unique=%d): %s", len(unique_names), unique_names)

    # ---------- result ----------
    if not unique_names:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The CAC ISO/PM/ISSO is not provided",
        )
        status.add(tr)
        logger.debug("[T177] Result=FAIL (no ISO/PM/ISSO assignments found)")
        return tr

    joined = ", ".join(unique_names)
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=f"PASS: The CAC ISO/PM/ISSO is: {joined}",
    )
    status.add(tr)
    logger.debug("[T177] Result=PASS (names=%d)", len(unique_names))
    return tr



def test_178(ctx: SystemContext, status: ATOStatus) -> TestResult:
    """Test 178 — Correct CAC SCA-V Present.

    Validate that, for the current ``system_id``, at least one user is assigned to
    the **SCA-V** role using **nested models only** (strictly no access to
    ``raw_payloads``). Mirrors the legacy PowerShell behavior:

        GET /api/system-roles/cac?role=SCA%2DV

    PowerShell parity:
      * No SCA-V names found → **FAIL** with legacy wording:
        ``"FAIL: The CAC SCA-V is not provided"``.
      * ≥1 name found → **PASS** with legacy wording:
        ``"PASS: The CAC SCA-V is: <names>"`` (use singular “is” even for multiples).

    Design notes:
      * Reads only ``ctx.user_details.data`` (nested model).
      * Tolerates light schema drift (camelCase/snake_case; role as dict/list).
      * Preserves discovery order; deterministic de-dup.
      * Logs breadcrumbs in house style:
        ``[T178] Running → source rows → extracted names → result``.

    Args:
        ctx: Authoritative snapshot of one eMASS system (nested models only).
        status: Aggregator that records this test’s result.

    Returns:
        TestResult: PASS if ≥1 SCA-V assignee exists; otherwise FAIL.
    """
    test_number = 178
    test_name = "Test 178: Correct CAC SCA-V Present"
    system_id = getattr(ctx, "system_id", None)

    logger.debug("[T178] Running %s (system_id=%s)", test_name, system_id)

    # ---------- helpers ----------
    def _ci_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
        """Case-insensitive dict lookup with a safe default."""
        if not isinstance(d, dict):
            return default
        lk = key.lower()
        for k, v in d.items():
            if str(k).lower() == lk:
                return v
        return default

    def _as_list(x: Optional[Any]) -> List[Any]:
        """Return list/tuple as list; else empty list (strings excluded)."""
        if isinstance(x, list):
            return x
        if isinstance(x, tuple):
            return list(x)
        return []

    def _normalize_roles(roles_field: Any) -> List[Dict[str, Any]]:
        """Normalize a 'roles' field into a list[dict]."""
        if roles_field is None:
            return []
        if isinstance(roles_field, dict):
            return [roles_field]
        if isinstance(roles_field, (list, tuple)):
            return [r for r in roles_field if isinstance(r, dict)]
        return []

    def _is_scav(role_val: Any) -> bool:
        """Loose matcher for 'SCA-V' tolerant of hyphen/space/case."""
        if not role_val:
            return False
        s = " ".join(str(role_val).strip().lower().replace("-", " ").split())
        return s == "sca v"

    # ---------- source: nested models only ----------
    rows: List[Dict[str, Any]] = []
    if getattr(ctx, "user_details", None) and getattr(ctx.user_details, "data", None):
        rows = [r for r in _as_list(ctx.user_details.data) if isinstance(r, dict)]
        logger.debug("[T178] Using user_details.data (rows=%d)", len(rows))
    else:
        logger.debug("[T178] No user_details.data available")

    # If there is no nested CAC-style role data at all, match legacy failure wording.
    if not rows:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The CAC SCA-V is not provided",
        )
        status.add(tr)
        logger.debug("[T178] Result=FAIL (no nested role data)")
        return tr

    # ---------- extraction ----------
    names: List[str] = []

    for row in rows:
        # Respect row-level system id if present; tolerate absence.
        row_sid = (
            _ci_get(row, "systemId")
            or _ci_get(row, "system_id")
            or _ci_get(row, "SystemID")
        )
        if system_id is not None and row_sid is not None and str(row_sid) != str(system_id):
            continue

        for role in _normalize_roles(_ci_get(row, "roles")):
            role_name = (
                _ci_get(role, "role")
                or _ci_get(role, "roleName")
                or _ci_get(role, "name")
                or ""
            )
            if not _is_scav(role_name):
                continue

            users_field = _ci_get(role, "users") or []
            users: Sequence[Dict[str, Any]]
            if isinstance(users_field, dict):
                users = [users_field]
            else:
                users = [u for u in _as_list(users_field) if isinstance(u, dict)]

            for user in users:
                first = str(_ci_get(user, "firstName", "") or _ci_get(user, "first_name", "")).strip()
                last  = str(_ci_get(user, "lastName", "")  or _ci_get(user, "last_name", "")).strip()
                full  = (first + " " + last).strip() or str(_ci_get(user, "name", "")).strip()
                if full:
                    names.append(full)

    unique_names = list(dict.fromkeys(names))  # stable de-dup; preserve discovery order
    logger.debug("[T178] Extracted SCA-V names (unique=%d): %s", len(unique_names), unique_names)

    # ---------- result ----------
    if not unique_names:
        tr = TestResult(
            test_number=test_number,
            name=test_name,
            result=Result.FAIL,
            message="FAIL: The CAC SCA-V is not provided",
        )
        status.add(tr)
        logger.debug("[T178] Result=FAIL (no SCA-V assignments found)")
        return tr

    joined = ", ".join(unique_names)
    tr = TestResult(
        test_number=test_number,
        name=test_name,
        result=Result.PASS,
        message=f"PASS: The CAC SCA-V is: {joined}",
    )
    status.add(tr)
    logger.debug("[T178] Result=PASS (names=%d)", len(unique_names))
    return tr


def run_all_tests(context: SystemContext) -> ATOStatus:
    """
    Discover and execute all test functions defined in this module.

    This delegates to the shared helper `run_discovered_tests` to:
      - find all `test_*` functions that accept (ctx, status),
      - sort them numerically by their test number,
      - execute each with exception safety,
      - and aggregate results in an ATOStatus.

    Returns:
        ATOStatus: Aggregated results for this module's tests.
    """
    logger.info("Running all tests in module %s", __name__)
    return run_discovered_tests(__name__, context)




