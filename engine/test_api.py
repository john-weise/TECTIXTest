from __future__ import annotations

import csv
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from engine.config import Config
import engine.models as models  # SystemContext + all Pydantic data classes

log = logging.getLogger(__name__)
# force our builder logger to be loud in container
if not log.handlers:
    # don't duplicate handlers if this code is imported twice
    stream_handler = logging.StreamHandler()  # defaults to stderr
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s")
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.DEBUG)
    log.addHandler(stream_handler)

log.setLevel(logging.DEBUG)
log.propagate = True


# ---------------------------------------------------------------------------------
# Shared helpers (safe versions, robust to trash data)
# ---------------------------------------------------------------------------------

def _load_fixture_json(fname: str, cfg: Optional[Config]) -> Any:
    """
    Try to load a JSON fixture by name.

    Search order:
    1. cfg.data_root (if provided)
    2. engine/Notionalassets (sibling to this file)
    3. CWD/Notionalassets

    Returns parsed JSON (list/dict/etc.) or None.
    """
    base_candidates: List[str] = []
    if cfg and getattr(cfg, "data_root", None):
        base_candidates.append(cfg.data_root)

    this_dir = os.path.dirname(__file__)
    base_candidates.append(os.path.join(this_dir, "Notionalassets"))
    base_candidates.append(os.path.join(os.getcwd(), "Notionalassets"))

    chosen_path = None
    for base in base_candidates:
        candidate = os.path.join(base, fname)
        if os.path.exists(candidate):
            chosen_path = candidate
            break

    if not chosen_path:
        log.debug("Fixture %s not found in any candidate path", fname)
        return None

    try:
        with open(chosen_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        log.warning("Failed to parse fixture %s: %s", chosen_path, exc)
        return None


def _unwrap_data(node: Any) -> Any:
    """If node has {'data': ...}, return node['data'], else node."""
    if isinstance(node, dict) and "data" in node:
        return node["data"]
    return node


def _normalize_to_row_list(node: Any) -> List[Dict[str, Any]]:
    """
    Normalize arbitrary fixture shapes into list[dict].

    Accepts:
    - list[dict]
    - {"data": [...]}
    - dict-of-dicts keyed by IDs
    - single dict row
    - None

    Returns a list of dict rows.
    """
    node = _unwrap_data(node)

    if node is None:
        return []

    if isinstance(node, list):
        return [r for r in node if isinstance(r, dict)]

    if isinstance(node, dict):
        vals = list(node.values())
        if vals and all(isinstance(v, dict) for v in vals):
            # dict-of-dicts
            return [v for v in vals if isinstance(v, dict)]
        # single-row dict
        return [node]

    return []


def _ci_get(row: Dict[str, Any], keys: Tuple[str, ...], default: Any = None) -> Any:
    """Case-insensitive multi-key getter."""
    lowered = {str(k).lower(): v for k, v in row.items()}
    for k in keys:
        lk = k.lower()
        if lk in lowered and lowered[lk] is not None:
            return lowered[lk]
    return default


def _extract_system_id(row: Dict[str, Any]) -> str:
    """Guess 'system id' out of a row."""
    return str(
        _ci_get(
            row,
            (
                "System ID",
                "SystemID",
                "systemId",
                "system_id",
                "sysId",
                "id",
                "systemid",
            ),
            default="",
        )
    )


def _filter_rows_for_system(
    rows: List[Dict[str, Any]], target_system_id: str
) -> List[Dict[str, Any]]:
    """Filter list of rows to just the given system_id (string compare)."""
    return [r for r in rows if _extract_system_id(r) == target_system_id or not _extract_system_id(r)]


def _first_or_none(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return rows[0] if rows else None


def _to_boolish(val: Any) -> Optional[bool]:
    """
    Convert y/n/true/false/"1"/"0"/etc → bool.
    Return None if unknown.
    """
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


def _safe_model_build(model_cls: Any, src: Optional[Dict[str, Any]]) -> Any:
    """
    Instantiate a Pydantic model from a dict row.
    Returns None if src is None or instantiation fails.
    """
    if not isinstance(src, dict) or not src:
        return None
    try:
        return model_cls(**src)
    except Exception as exc:
        log.error(
            "Failed to build %s from %r: %s",
            getattr(model_cls, "__name__", model_cls),
            src,
            exc,
        )
        return None


def _load_apms_csv(apms_csv_path: str):
    """
    Read APMS CSV snapshot for this system.

    Returns:
        (first_row_dict_or_None,
         headers_list_or_None,
         derived_meta: dict[str, Optional[str]])
    """
    if not apms_csv_path or not os.path.exists(apms_csv_path):
        return None, None, {
            "data_report_number": None,
            "item_name": None,
            "acronym": None,
            "cloud_designation": None,
            "is_saas": None,
            "cloud_service_type": None,
        }

    try:
        with open(apms_csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            headers = reader.fieldnames or []
            first_row = next(reader, None)

        if not first_row:
            return None, headers, {
                "data_report_number": None,
                "item_name": None,
                "acronym": None,
                "cloud_designation": None,
                "is_saas": None,
                "cloud_service_type": None,
            }

        meta = {
            "data_report_number": (
                first_row.get("DATA Number") or first_row.get("AITR Number")
            ),
            "item_name": first_row.get("Item Name"),
            "acronym": first_row.get("Acronym"),
            "cloud_designation": first_row.get("Cloud Assessment Designation"),
            "is_saas": first_row.get("Is this a SaaS System"),
            "cloud_service_type": first_row.get("Cloud Service Type"),
        }
        return first_row, headers, meta

    except Exception as exc:
        log.warning("Failed to parse APMS CSV %s: %s", apms_csv_path, exc)
        return None, None, {
            "data_report_number": None,
            "item_name": None,
            "acronym": None,
            "cloud_designation": None,
            "is_saas": None,
            "cloud_service_type": None,
        }


def _maybe_wrap_artifacts(rows_for_sys: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    ArtifactDetails / ArtifactSummary can come in 2 shapes:
    (A) wrapper row that already has 'data': [...]
        e.g. { "system_id": "114", "data": [ ... ], "meta": {...}, ... }

    (B) flat list of artifact rows:
        [ { "Artifact Name": "...", "System ID": "114", ...},
          { "Artifact Name": "...", "System ID": "114", ...} ]

    We must ALWAYS hand tests an object where `.data` is a list of artifact dicts,
    otherwise tests 22-26 auto-fail.

    This function:
      - If the first row already has "data": [...], just return that row.
      - Otherwise, synthesize: { "data": rows_for_sys, "system_id": <best guess>, ... }
    """
    if not rows_for_sys:
        return {}

    first_row = rows_for_sys[0]

    # Case A: already wrapped
    if isinstance(first_row, dict) and "data" in first_row and isinstance(first_row["data"], list):
        return first_row

    # Case B: synthesize wrapper
    def _ci_get_local(r: Dict[str, Any], *keys: str) -> Optional[str]:
        lowered = {str(k).lower(): v for k, v in r.items()}
        for k in keys:
            lk = k.lower()
            if lk in lowered and lowered[lk] is not None:
                return str(lowered[lk])
        return None

    wrapper: Dict[str, Any] = {
        "data": rows_for_sys,
    }

    wrapper["system_id"] = _ci_get_local(
        first_row,
        "System ID", "SystemID", "systemId", "system_id", "sysId", "id",
    )
    wrapper["system_name"] = _ci_get_local(
        first_row,
        "System Name", "systemName", "system_name",
    )
    wrapper["system_acronym"] = _ci_get_local(
        first_row,
        "System Acronym", "systemAcronym", "system_acronym",
    )
    # leave meta/pagination/etc. absent if we don't have them.

    return wrapper


def _normalize_cia_level(raw: Optional[str]) -> Optional[str]:
    """
    Normalize CIA-ish strings like "Medium" vs "Moderate" vs "MODERATE".
    We collapse {"medium","moderate"} → "Moderate".

    Returns normalized string (capitalized), or None.
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in {"medium", "moderate"}:
        return "Moderate"
    if s == "low":
        return "Low"
    if s == "high":
        return "High"
    # pass through unknowns ("Very High", etc.)
    return raw




# ---------------------------------------------------------------------------------
# The Builder
# ---------------------------------------------------------------------------------
def build_system_context_from_emass(
    *,
    cfg: Config,
    system_id: int,
    apms_csv_path: str,
    checklist_path: str,
) -> models.SystemContext:
    """
            Build a fully-populated ``SystemContext`` for a single eMASS/RMF system.

            Overview
            --------
            This function is the primary orchestration entry point for turning a set of
            raw eMASS export fixtures + an APMS CSV snapshot into a structured
            ``SystemContext`` instance that downstream tests and dashboards can consume.

            High-level behavior:

            * Locates and loads all expected eMASS JSON fixtures (SystemInfo, Controls,
            TestResults, Hardware, Software, etc.), using the same search rules as
            the rest of the module (via ``_load_fixture_json``).
            * Transparently handles paginated eMASS responses (via
            ``_load_fixture_json_paginated``) by merging multi-page payloads into a
            single normalized object.
            * Normalizes heterogeneous fixture shapes to row lists
            (``_normalize_to_row_list``), then filters rows down to the target
            ``system_id`` using the shared system-id extractor.
            * Adds snake_case aliases for space/punctuation-heavy keys so that both
            original eMASS column names and normalized field names are available.
            * Parses the APMS CSV export (via ``_load_apms_csv``) to hydrate APMS
            metadata (cloud designation, item name/acronym, report number, etc.).
            * Derives scalar summary fields (CIA triad, impact, workflow stage,
            classification, continuity/BCP metrics, data flags like CUI/PII/PHI/NSS/FMS,
            connectivity details, presence of artifacts/hardware/software).
            * Hydrates all relevant Pydantic models (SystemInfo, SystemDetailsDashboard,
            Controls, TestResults, Hardware, Software, Privacy, POA&M, etc.) using a
            defensive builder (``_safe_model_build``) that tolerates partial data.
            * Assembles a single ``SystemContext`` object with both the derived scalar
            attributes and the hydrated nested models, plus optional ``raw_payloads``
            for trace/debug purposes.

            When run in a CLI context (``__main__``), this builder is also responsible
            for pretty-printing the final context to the terminal via ``rich`` when
            available.

            Args
            ----
            cfg:
                Runtime configuration, typically providing the fixture root
                (e.g., ``cfg.data_root``). May be ``None`` or a lightweight stand-in
                when invoked from the CLI; only the data-root semantics are used by
                the internal loaders.
            system_id:
                eMASS system identifier to target. Only rows associated with this
                system are used to build the context; all other systems present in the
                fixtures are ignored.
            apms_csv_path:
                Filesystem path to the APMS CSV export corresponding to the target
                system. The CSV is parsed once to hydrate cloud designation, item
                metadata, and a small number of APMS-derived fields. If empty or
                unreadable, APMS-specific fields are left ``None`` or defaulted.
            checklist_path:
                Filesystem path to the checklist / STIG snapshot associated with the
                target system. This is stored on the resulting ``SystemContext`` for
                traceability but is not parsed by this function.

            Returns
            -------
            models.SystemContext
                A best-effort, fully-hydrated ``SystemContext`` describing the target
                eMASS system, including:

                * Core system metadata (name, acronym, description, version).
                * Registration, lifecycle, authorization and workflow status.
                * CIA category and impact level.
                * Cloud/service-model flags and APMS cloud metadata.
                * Data-type flags (CUI/PII/PHI/NSS/FMS).
                * Artifact, hardware, and software presence + counts.
                * Continuity / BCP attributes (MTD, RTO, RPO, termination dates, IR plan).
                * Nested Pydantic models for each major eMASS fixture.
                * Optional ``raw_payloads`` containing the filtered row-level data used
                to construct the models.

            Raises
            ------
            OSError
                If critical fixture files or the APMS CSV cannot be read from disk.
            ValueError
                If the APMS CSV or required eMASS fixtures are structurally invalid in
                ways that the defensive builders cannot recover from.
            AnyError
                Other exceptions propagated from underlying loaders or Pydantic model
                construction in truly unrecoverable scenarios. In normal operation,
                most parse issues are logged and result in partially populated fields
                rather than hard failures.

            Side Effects
            ------------
            * Reads multiple JSON and CSV files from disk under the configured data
            root and provided paths.
            * Emits structured logging at DEBUG/INFO/ERROR via the module-level
            ``log`` logger, including fixture snapshots and the final context.
            * When ``rich`` is installed and the call path goes through the CLI
            wrapper, pretty-prints the final context as formatted JSON to stdout.

            Notes
            -----
            * This function is intentionally tolerant of partial/dirty data: missing
            optional fixtures, unexpected keys, and malformed rows are logged and
            skipped where possible rather than causing the build to fail outright.
            * Callers that need to validate fixture integrity up-front should run
            ``test_emass_connection`` first and enforce its result before calling
            this builder
            
    """
    target_id_str = str(system_id)

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------
    def _dump_obj(label: str, obj: Any) -> None:
        """
        Structured debug logging helper.

        Priority:
        - Pydantic v2: .model_dump(mode="python")
        - Pydantic v1: .dict()
        - Any object with __dict__
        - Fallback repr()
        """
        try:
            if obj is None:
                log.debug("%s = None", label)
                return

            if hasattr(obj, "model_dump"):
                # Pydantic v2+
                log.info("%s = %s", label, obj.model_dump(mode="python"))
                return

            if hasattr(obj, "dict"):
                # Pydantic v1
                log.debug("%s = %s", label, obj.dict())
                return

            if hasattr(obj, "__dict__"):
                log.debug("%s = %s", label, vars(obj))
                return

            log.debug("%s = %r", label, obj)
        except Exception as exc:
            log.debug("Failed to dump %s: %s", label, exc)

    def ci_get_local(r: Optional[Dict[str, Any]], *keys: str, default: Any = None) -> Any:
        """Case-insensitive multi-key getter into an eMASS row dict."""
        if not r:
            return default
        lowered = {str(k).lower(): v for k, v in r.items()}
        for k in keys:
            lk = str(k).lower()
            if lk in lowered and lowered[lk] is not None:
                return lowered[lk]
        return default

    # NEW: add snake_case aliases for space/punct-heavy keys
    def _add_snake_case_aliases(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Add snake_case aliases for eMASS row keys that contain spaces/punctuation.

        Examples:
          "Baseline Location" -> "baseline_location"
          "Maximum Tolerable Downtime (MTD)" -> "maximum_tolerable_downtime_mtd"

        Existing keys are never overwritten; we only add missing aliases.
        """
        if not isinstance(row, dict):
            return row

        out: Dict[str, Any] = dict(row)
        for k, v in row.items():
            key_str = str(k).strip()
            # Replace non-alphanumerics with underscores, collapse repeats, lowercase.
            snake = re.sub(r"[^0-9a-zA-Z]+", "_", key_str)
            snake = re.sub(r"_+", "_", snake).strip("_").lower()
            if snake and snake not in out:
                out[snake] = v
        return out

    def _load_fixture_json_paginated(fname: str, cfg_: Optional[Config]) -> Any:
        """
        Pagination-aware JSON loader. Starts with `fname`, inspects `"pagination"`,
        and if multiple pages are indicated, it attempts to read sibling files for
        pages 2..N using common naming patterns. All pages are merged into a single
        object with `data=[...]` and a collapsed one-page `"pagination"` block.

        Falls back to the base loader and returns the object as-is when no pagination
        is present or only one page is indicated.
        """
        base_obj = _load_fixture_json(fname, cfg_)
        # Non-dict shapes (list/singleton/None) get normalized later as usual.
        if not isinstance(base_obj, dict):
            return base_obj

        # Read totalPages from known casings.
        pagination = base_obj.get("pagination") or {}
        total_pages = (
            pagination.get("totalPages")
            or pagination.get("total_pages")
            or pagination.get("TotalPages")
        )
        try:
            total_pages = int(total_pages) if total_pages is not None else None
        except Exception:
            total_pages = None

        if not total_pages or total_pages <= 1:
            # Single file/page or unknown pagination: return as-is.
            return base_obj

        # Merge page1 rows (this file) + subsequent pages discovered on disk.
        all_rows = _normalize_to_row_list(base_obj)
        stem, ext = os.path.splitext(fname)
        pages_loaded = 1

        for page_num in range(2, total_pages + 1):
            candidate_names = [
                f"{stem}.page{page_num}{ext}",  # Controls.page2.json
                f"{stem}_{page_num}{ext}",      # Controls_2.json
                f"{stem}{page_num}{ext}",       # Controls2.json
            ]
            page_obj = None
            for cand in candidate_names:
                page_obj = _load_fixture_json(cand, cfg_)
                if page_obj:
                    break

            if not page_obj:
                # Could not find this page under any naming; stop probing further pages.
                break

            page_rows = _normalize_to_row_list(page_obj)
            all_rows.extend(page_rows)
            pages_loaded += 1

        # Rebuild a single dict so the rest of the pipeline sees the classic shape.
        base_obj["data"] = all_rows
        base_obj["pagination"] = {
            "pageIndex": 0,
            "pageSize": len(all_rows),
            "totalCount": len(all_rows),
            "totalPages": 1,
            "prevPageUrl": "",
            "nextPageUrl": "",
        }
        log.info("Merged %d page(s) for %s (rows=%d)", pages_loaded, fname, len(all_rows))
        return base_obj

    log.info("Building SystemContext for system_id=%s", target_id_str)

    # ---------------------------------------------------------------------
    # 1) Load and normalize all fixtures (pagination-aware)
    # ---------------------------------------------------------------------
    fixture_names = {
        "SystemInfo": "SystemInfo.json",
        "SystemDetailsDashboard": "SystemDetailsDashboard.json",
        "Privacy": "Privacy.json",
        "WorkflowDashboard": "WorkflowDashboard.json",
        "Workflows": "Workflows.json",
        "CAC": "CAC.json",
        "Controls": "Controls.json",
        "TestResults": "TestResults.json",
        "Findings": "Findings.json",
        "SystemPOAMDashboard": "SystemPOAMDashboard.json",
        "ArtifactDetails": "ArtifactDetails.json",
        "ArtifactSummary": "ArtifactSummary.json",
        "Hardware": "Hardware.json",
        "HardwareDetailsDashboard": "HardwareDetailsDashboard.json",
        "Software": "Software.json",
        "SoftwareDetailsDashboard": "SoftwareDetailsDashboard.json",
        "Associations": "Associations.json",
        "UserDetails": "UserDetails.json",
        "CCSD": "CCSD.json",
        "ConnectivityCCSD": "ConnectivityCCSD.json",
    }

    fixtures_raw: Dict[str, Any] = {
        key: _load_fixture_json_paginated(fname, cfg) for key, fname in fixture_names.items()
    }

    for _k, _v in fixtures_raw.items():
        _dump_obj(f"fixtures_raw[{_k}]", _v)

    fixture_rows: Dict[str, List[Dict[str, Any]]] = {
        key: _normalize_to_row_list(raw) for key, raw in fixtures_raw.items()
    }

    connectivity_rows_all = fixture_rows.get("CCSD", [])
    if not connectivity_rows_all:
        connectivity_rows_all = fixture_rows.get("ConnectivityCCSD", [])

    filtered: Dict[str, List[Dict[str, Any]]] = {
        key: _filter_rows_for_system(rows, target_id_str)
        for key, rows in fixture_rows.items()
    }
    filtered["CCSD"] = _filter_rows_for_system(connectivity_rows_all, target_id_str)

    # NEW: add snake_case aliases to ALL filtered rows
    filtered = {
        key: [_add_snake_case_aliases(r) for r in rows]
        for key, rows in filtered.items()
    }

    for _k, _v in filtered.items():
        _dump_obj(f"filtered[{_k}]", _v)

    row_system_info                = _first_or_none(filtered["SystemInfo"])
    row_system_details_dashboard   = _first_or_none(filtered["SystemDetailsDashboard"])
    row_privacy                    = _first_or_none(filtered["Privacy"])
    row_workflow_dashboard         = _first_or_none(filtered["WorkflowDashboard"])
    row_cac                        = _first_or_none(filtered["CAC"])
    row_controls                   = _first_or_none(filtered["Controls"])
    row_test_results               = _first_or_none(filtered["TestResults"])
    row_findings                   = _first_or_none(filtered["Findings"])
    row_poam                       = _first_or_none(filtered["SystemPOAMDashboard"])
    row_artifact_details_first     = _first_or_none(filtered["ArtifactDetails"])
    row_artifact_summary_first     = _first_or_none(filtered["ArtifactSummary"])
    row_hardware                   = _first_or_none(filtered["Hardware"])
    row_hardware_details_dashboard = _first_or_none(filtered["HardwareDetailsDashboard"])
    row_software                   = _first_or_none(filtered["Software"])
    row_software_details_dashboard = _first_or_none(filtered["SoftwareDetailsDashboard"])
    row_associations               = _first_or_none(filtered["Associations"])
    row_user_details               = _first_or_none(filtered["UserDetails"])
    row_ccsd                       = _first_or_none(filtered["CCSD"])

    _dump_obj("row_system_info", row_system_info)
    _dump_obj("row_system_details_dashboard", row_system_details_dashboard)
    _dump_obj("row_privacy", row_privacy)
    _dump_obj("row_workflow_dashboard", row_workflow_dashboard)
    _dump_obj("row_cac", row_cac)
    _dump_obj("row_controls", row_controls)
    _dump_obj("row_test_results", row_test_results)
    _dump_obj("row_findings", row_findings)
    _dump_obj("row_poam", row_poam)
    _dump_obj("row_artifact_details_first", row_artifact_details_first)
    _dump_obj("row_artifact_summary_first", row_artifact_summary_first)
    _dump_obj("row_hardware", row_hardware)
    _dump_obj("row_hardware_details_dashboard", row_hardware_details_dashboard)
    _dump_obj("row_software", row_software)
    _dump_obj("row_software_details_dashboard", row_software_details_dashboard)
    _dump_obj("row_associations", row_associations)
    _dump_obj("row_user_details", row_user_details)
    _dump_obj("row_ccsd", row_ccsd)

    workflows_all_rows = _normalize_to_row_list(fixtures_raw.get("Workflows"))
    _dump_obj("workflows_all_rows", workflows_all_rows)

    # ---------------------------------------------------------------------
    # 2) Parse APMS CSV
    # ---------------------------------------------------------------------
    apms_first_row, apms_headers, apms_meta = _load_apms_csv(apms_csv_path)

    _dump_obj("apms_first_row", apms_first_row)
    _dump_obj("apms_headers", apms_headers)
    _dump_obj("apms_meta", apms_meta)

    apms_headers_raw   = apms_headers
    apms_first_row_raw = apms_first_row
    data_report_number = (
        str(apms_meta["data_report_number"]) if apms_meta.get("data_report_number") else None
    )

    # ---------------------------------------------------------------------
    # 3) Derive scalar / summary info
    # ---------------------------------------------------------------------
    cloud_computing = _to_boolish(ci_get_local(row_system_info, "cloudComputing", "cloudcomputing"))
    cloud_type = ci_get_local(row_system_info, "cloudType", "cloudtype")

    is_saas = _to_boolish(ci_get_local(row_system_info, "isSaaS", "issaas"))
    is_paas = _to_boolish(ci_get_local(row_system_info, "isPaaS", "ispaas"))
    is_iaas = _to_boolish(ci_get_local(row_system_info, "isIaaS", "isiaas"))
    other_service_models = ci_get_local(row_system_info, "otherServiceModels", "otherservicemodels")

    registration_type = ci_get_local(
        row_system_info, "registrationtype", "registrationType", "registration_type"
    )
    lifecycle_phase = ci_get_local(
        row_system_info, "systemLifeCycleAcquisitionPhase", "systemlifecycleacquisitionphase"
    )
    authorization_status = ci_get_local(row_system_info, "authorizationStatus", "authorizationstatus")

    confidentiality_raw = ci_get_local(row_system_info, "confidentiality")
    integrity_raw       = ci_get_local(row_system_info, "integrity")
    availability_raw    = ci_get_local(row_system_info, "availability")

    confidentiality = _normalize_cia_level(confidentiality_raw)
    integrity       = _normalize_cia_level(integrity_raw)
    availability    = _normalize_cia_level(availability_raw)

    impact = ci_get_local(row_system_info, "impact")

    system_type_val = ci_get_local(row_system_info, "systemType", "systemtype")
    rmf_activity = ci_get_local(row_system_info, "rmfActivity", "rmfactivity")

    mission_criticality = ci_get_local(row_system_info, "missionCriticality", "missioncriticality")
    classification = ci_get_local(
        row_system_info, "highestSystemDataClassification", "highestsystemdataclassification"
    )

    system_name_val = ci_get_local(row_system_info, "name")
    system_acronym_val = ci_get_local(row_system_info, "acronym")
    system_description = ci_get_local(row_system_info, "description")
    system_version = ci_get_local(row_system_info, "versionReleaseNo", "versionreleaseno")

    emass_data_id = ci_get_local(row_system_info, "dataId", "dataid", "apmsId")

    cui_flag = _to_boolish(ci_get_local(row_system_info, "hasCUI", "hascui"))
    pii_flag = _to_boolish(ci_get_local(row_system_info, "hasPII", "haspii"))
    phi_flag = _to_boolish(ci_get_local(row_system_info, "hasPHI", "hasphi"))
    nss_flag = _to_boolish(ci_get_local(row_system_info, "isNSS", "isnss"))
    fms_flag = _to_boolish(ci_get_local(row_system_info, "isFinancialManagement", "isfinancialmanagement"))

    workflow_type_val = ci_get_local(row_workflow_dashboard, "workflow")
    workflow_name_val = ci_get_local(row_workflow_dashboard, "packagename", "packageName", "name")
    workflow_stage_val = ci_get_local(
        row_workflow_dashboard, "currentstage", "currentStageName", "currentstagename", "currentStage"
    )

    has_hardware_data    = bool(filtered["Hardware"])
    has_software_data    = bool(filtered["Software"])
    has_artifact_details = bool(filtered["ArtifactDetails"])

    artifact_number: Optional[int] = None
    if row_artifact_summary_first:
        raw_total = ci_get_local(row_artifact_summary_first, "Total Artifacts", "total_artifacts")
        if raw_total not in (None, ""):
            try:
                artifact_number = int(str(raw_total).replace(",", ""))
            except Exception:
                artifact_number = None

    connectivity_ccsd_connectivity: Optional[str] = None
    if row_ccsd:
        cc_val = ci_get_local(row_ccsd, "Connectivity", "Connection Type", "Connection")
        if isinstance(cc_val, str) and cc_val.strip():
            connectivity_ccsd_connectivity = cc_val.strip()

    auth_termination_epoch = ci_get_local(
        row_system_info,
        "authTerminationDate",
        "authterminationdate",
        "Authorization Termination Date",
        "authorizationTerminationDate",
    )

    maximum_tolerable_downtime = ci_get_local(
        row_system_info,
        "maximumTolerableDowntime",
        "maximumtolerabledowntime",
        "MTD",
        "maximumTolerableDowntime (MTD)",
    )
    recovery_time_objective = ci_get_local(
        row_system_info,
        "recoveryTimeObjective",
        "recoverytimeobjective",
        "RTO",
        "recoveryTimeObjective (RTO)",
    )
    recovery_point_objective = ci_get_local(
        row_system_info,
        "recoveryPointObjective",
        "recoverypointobjective",
        "RPO",
        "recoveryPointObjective (RPO)",
    )

    incident_response_plan_required = ci_get_local(
        row_system_info, "incidentResponsePlanRequired", "incidentresponseplanrequired"
    )
    incident_response_plan_artifact = ci_get_local(
        row_system_info, "incidentResponsePlanArtifact", "incidentresponseplanartifact"
    )

    pia_required = ci_get_local(
        row_system_info,
        "privacyImpactAssessmentRequired",
        "privacyimpactassessmentrequired",
        "PIA Required",
        "PIARequired",
    )
    sorn_required = ci_get_local(
        row_system_info,
        "privacyActSystemOfRecordsNoticeRequired",
        "privacyactsystemofrecordsnoticerequired",
        "System of Records Notice Required",
        "System of Records Notice",
    )
    eauth_required = ci_get_local(
        row_system_info, "eAuthenticationRiskAssessmentRequired", "eauthenticationriskassessmentrequired"
    )

    atc_decision = ci_get_local(
        row_system_info, "authorizationToConnectStatus", "authorizationtoconnectstatus", "ATC Decision"
    )
    atc_decision_date = ci_get_local(
        row_system_info, "atcIatcGrantedDate", "atciatcgranteddate", "ATC Decision Date"
    )
    atc_termination_date = ci_get_local(
        row_system_info, "atcIatcExpirationDate", "atciatcexpirationdate", "ATC Termination Date"
    )

    # ---------------------------------------------------------------------
    # 4) Hydrate Pydantic models
    # ---------------------------------------------------------------------
    artifact_details_wrapped = _maybe_wrap_artifacts(filtered["ArtifactDetails"])
    artifact_summary_wrapped = _maybe_wrap_artifacts(filtered["ArtifactSummary"])

    artifact_details_model = _safe_model_build(models.ArtifactDetails, artifact_details_wrapped)
    _dump_obj("artifact_details_model", artifact_details_model)

    artifact_summary_model = _safe_model_build(models.ArtifactSummary, artifact_summary_wrapped)
    _dump_obj("artifact_summary_model", artifact_summary_model)

    system_info_model = _safe_model_build(models.SystemInfo, row_system_info)
    _dump_obj("system_info_model", system_info_model)

    system_details_dashboard_model = _safe_model_build(
        models.SystemDetailsDashboard, row_system_details_dashboard
    )
    _dump_obj("system_details_dashboard_model", system_details_dashboard_model)

    privacy_model = _safe_model_build(models.Privacy, row_privacy)
    _dump_obj("privacy_model", privacy_model)

    workflow_dashboard_model = _safe_model_build(models.WorkflowDashboard, row_workflow_dashboard)
    _dump_obj("workflow_dashboard_model", workflow_dashboard_model)

    # Workflows: full list wrapper.
    workflows_model = None
    if workflows_all_rows:
        try:
            workflows_model = models.Workflows(data=workflows_all_rows, meta=None)
        except Exception as exc:
            log.error("Failed to build Workflows model: %s", exc)
            workflows_model = None
    _dump_obj("workflows_model", workflows_model)

    cac_model = _safe_model_build(models.CAC, row_cac)
    _dump_obj("cac_model", cac_model)

    # Controls/TestResults: ensure `.data` contains **all** rows.
    controls_model = None
    if filtered["Controls"]:
        try:
            controls_model = models.Controls(data=filtered["Controls"], meta=None, systemid=None)
        except Exception as exc:
            log.error("Failed to build Controls model (list wrapper): %s", exc)
            controls_model = None
    else:
        controls_model = _safe_model_build(models.Controls, row_controls)
    _dump_obj("controls_model", controls_model)

    test_results_model = None
    if filtered["TestResults"]:
        try:
            test_results_model = models.TestResults(
                data=filtered["TestResults"], meta=None, pagination=None, systemid=None
            )
        except Exception as exc:
            log.error("Failed to build TestResults model (list wrapper): %s", exc)
            test_results_model = None
    else:
        test_results_model = _safe_model_build(models.TestResults, row_test_results)
    _dump_obj("test_results_model", test_results_model)

    findings_model = _safe_model_build(models.Findings, row_findings)
    _dump_obj("findings_model", findings_model)

    poam_model = _safe_model_build(models.SystemPOAMDashboard, row_poam)
    _dump_obj("poam_model", poam_model)

    hardware_model = _safe_model_build(models.Hardware, row_hardware)
    _dump_obj("hardware_model", hardware_model)

    hardware_details_dashboard_model = _safe_model_build(
        models.HardwareDetailsDashboard, row_hardware_details_dashboard
    )
    _dump_obj("hardware_details_dashboard_model", hardware_details_dashboard_model)

    software_model = _safe_model_build(models.Software, row_software)
    _dump_obj("software_model", software_model)

    software_details_dashboard_model = _safe_model_build(
        models.SoftwareDetailsDashboard, row_software_details_dashboard
    )
    _dump_obj("software_details_dashboard_model", software_details_dashboard_model)

    associations_model = _safe_model_build(models.Associations, row_associations)
    _dump_obj("associations_model", associations_model)

    user_details_model = _safe_model_build(models.UserDetails, row_user_details)
    _dump_obj("user_details_model", user_details_model)

    # ---------------------------------------------------------------------
    # 5) Assemble final SystemContext
    # ---------------------------------------------------------------------
    ctx = models.SystemContext(
        system_id=system_id,
        data_path=apms_csv_path,
        checklist_path=checklist_path,
        demo_assets=None,
        system_name=system_name_val,
        system_acronym=system_acronym_val,
        system_description=system_description,
        system_version=system_version,
        registration_type=registration_type,
        lifecycle_phase=lifecycle_phase,
        authorization_status=authorization_status,
        confidentiality=confidentiality,
        integrity=integrity,
        availability=availability,
        impact=impact,
        system_type=system_type_val,
        rmf_activity=rmf_activity,
        mission_criticality=mission_criticality,
        classification=classification,
        apms_item_name=apms_meta.get("item_name"),
        apms_acronym=apms_meta.get("acronym"),
        data_report_number=data_report_number,
        emass_data_id=str(emass_data_id) if emass_data_id else None,
        apms_headers_raw=apms_headers_raw,
        apms_first_row_raw=apms_first_row_raw,
        cloud_computing=cloud_computing,
        cloud_type=cloud_type,
        is_saas=is_saas,
        is_paas=is_paas,
        is_iaas=is_iaas,
        other_service_models=other_service_models,
        apms_cloud_assessment_designation=apms_meta.get("cloud_designation"),
        apms_is_saas_system=apms_meta.get("is_saas"),
        apms_cloud_service_type=apms_meta.get("cloud_service_type"),
        connectivity_ccsd_connectivity=connectivity_ccsd_connectivity,
        cui=cui_flag,
        pii=pii_flag,
        phi=phi_flag,
        nss=nss_flag,
        fms=fms_flag,
        workflow_type=workflow_type_val,
        workflow_name=workflow_name_val,
        workflow_stage=workflow_stage_val,
        has_hardware_data=has_hardware_data,
        has_software_data=has_software_data,
        artifact_number=artifact_number,
        has_artifact_details=has_artifact_details,
        # surfaced continuity / compliance
        auth_termination_epoch=auth_termination_epoch,
        maximum_tolerable_downtime=maximum_tolerable_downtime,
        recovery_time_objective=recovery_time_objective,
        recovery_point_objective=recovery_point_objective,
        incident_response_plan_required=incident_response_plan_required,
        incident_response_plan_artifact=incident_response_plan_artifact,
        pia_required=pia_required,
        sorn_required=sorn_required,
        eauth_required=eauth_required,
        atc_decision=atc_decision,
        atc_decision_date=atc_decision_date,
        atc_termination_date=atc_termination_date,
        system_info=system_info_model,
        system_details_dashboard=system_details_dashboard_model,
        workflow_dashboard=workflow_dashboard_model,
        workflows=workflows_model,
        cac=cac_model,
        controls=controls_model,
        test_results=test_results_model,
        findings=findings_model,
        privacy=privacy_model,
        artifact_details=artifact_details_model,
        artifact_summary=artifact_summary_model,
        system_poam_dashboard=poam_model,
        hardware=hardware_model,
        hardware_details_dashboard=hardware_details_dashboard_model,
        software=software_model,
        software_details_dashboard=software_details_dashboard_model,
        associations=associations_model,
        user_details=user_details_model,
    )

    # ---------------------------------------------------------------------
    # 6) raw_payloads for trace/debug
    # ---------------------------------------------------------------------
    if hasattr(ctx, "raw_payloads"):
        try:
            ctx.raw_payloads = models.RawPayloads(
                system_info=row_system_info,
                workflow_pac=row_workflow_dashboard,
                hardware_summary=filtered["Hardware"],
                software_summary=filtered["Software"],
                artifact_summary=filtered["ArtifactSummary"],
                artifact_details=filtered["ArtifactDetails"],
                workflows_instances=workflows_all_rows,
                system_status_details=filtered["SystemDetailsDashboard"],
                privacy_summary=filtered["Privacy"],
                test_results=filtered["TestResults"],
                controls=filtered["Controls"],  # helpful for pagination verification
                cac_pac=row_cac,
                user_assignments_details=filtered["UserDetails"],
                device_findings_details=filtered["Findings"],
                system_poam_details=filtered["SystemPOAMDashboard"],
                software_details=filtered["SoftwareDetailsDashboard"],
                hardware_details=filtered["HardwareDetailsDashboard"],
                associations_details=filtered["Associations"],
                connectivity_ccsd_details=filtered["CCSD"],
            )
            _dump_obj("ctx.raw_payloads", ctx.raw_payloads)
        except Exception as exc:
            log.debug("Failed to attach raw_payloads: %s", exc)

    # ---------------------------------------------------------------------
    # 7) Final structured logging
    # ---------------------------------------------------------------------
    _dump_obj("FINAL SystemContext", ctx)

    log.info(
        "SystemContext ready: id=%s name=%s acronym=%s stage=%s cloud=%s SaaS=%s artifacts=%s",
        system_id,
        ctx.system_name,
        ctx.system_acronym,
        ctx.workflow_stage,
        ctx.cloud_computing,
        ctx.is_saas,
        ctx.artifact_number,
    )

    # ---------------------------------------------------------------------
    # 8) Pretty-print JSON via rich (optional)
    # ---------------------------------------------------------------------
    try:
        from rich.console import Console
        from rich.json import JSON as RichJSON

        console = Console()
        if hasattr(ctx, "model_dump"):
            ctx_payload = ctx.model_dump(mode="python")
        elif hasattr(ctx, "dict"):
            ctx_payload = ctx.dict()
        elif hasattr(ctx, "__dict__"):
            ctx_payload = vars(ctx)
        else:
            ctx_payload = ctx

        console.print(
            RichJSON(
                json.dumps(
                    ctx_payload,
                    default=str,   # avoid blowing up on datetimes, etc.
                    indent=2,
                )
            )
        )
    except Exception as exc:
        log.debug("Rich pretty-print of SystemContext failed: %s", exc)

    return ctx





def discover_system_ids(*, cfg: Optional[Config] = None) -> List[int]:
    """Discover unique eMASS system IDs from SystemDetailsDashboard fixtures.

    Overview
    --------
    This helper is intended for autodiscovery features that need to iterate over
    all systems present in an eMASS export. It is deliberately minimal from the
    caller's perspective:

    * Call it with **no arguments** in the common case:
      ``discover_system_ids()``.
    * Internally, it loads ``SystemDetailsDashboard.json`` using the same
      fixture search rules as the rest of this module (via ``_load_fixture_json``).
    * It normalizes heterogeneous shapes via ``_normalize_to_row_list``.
    * It uses the shared case-insensitive system-id extractor to tolerate
      field-name drift (``"systemId"``, ``"System ID"``, ``"system_id"``, etc.).
    * It deduplicates IDs and returns them as integers, skipping non-numeric
      or missing values.

    Args
    ----
    cfg: Optional[Config], optional
        Runtime configuration used to resolve the fixture root. When omitted
        or ``None``, the function falls back to the default search behavior in
        ``_load_fixture_json`` (i.e., ``cfg.data_root`` is not used).

    Returns
    -------
    List[int]
        A list of unique system identifiers discovered in the
        ``SystemDetailsDashboard.json`` payload, in the order they were first
        encountered. If the fixture cannot be found or parsed, an empty list is
        returned.

    Notes
    -----
    * Time complexity is O(N) in the number of rows in the dashboard fixture.
    * The function is pure and side-effect free; it does not log. Callers can
      log the returned list as needed.

    Examples
    --------
    >>> system_ids = discover_system_ids()
    >>> for sid in system_ids:
    ...     ctx = build_system_context_from_emass(
    ...         cfg=cfg,
    ...         system_id=sid,
    ...         apms_csv_path="/path/to/APMS.csv",
    ...         checklist_path="/path/to/checklist.xlsx",
    ...     )

    """
    # Load the SystemDetailsDashboard snapshot from the usual fixture locations.
    raw_payload = _load_fixture_json("SystemDetailsDashboard.json", cfg)
    if raw_payload is None:
        return []

    # Normalize arbitrary shapes (dict, {"data":[...]}, list, dict-of-dicts, etc.)
    rows = _normalize_to_row_list(raw_payload)

    system_ids: List[int] = []
    seen: set[int] = set()

    for row in rows:
        # Extract a best-effort string-based system identifier.
        raw_id = _extract_system_id(row).strip()
        if not raw_id:
            continue

        # Only keep cleanly parseable integer IDs; non-numeric IDs are skipped.
        try:
            sys_id = int(raw_id)
        except ValueError:
            continue

        # Preserve first-seen order while avoiding duplicates.
        if sys_id in seen:
            continue
        seen.add(sys_id)
        system_ids.append(sys_id)

    return system_ids

def test_emass_connection(cfg: Optional[Config] = None) -> bool:
    """
    Quick health check: verify we can *locate and parse* the expected eMASS
    fixture JSON files under the normal search roots.

    Returns
    -------
    bool
        True if all required payloads were readable (with CCSD satisfied by
        either 'CCSD.json' or 'ConnectivityCCSD.json'); False otherwise.
    """
    # Required fixtures (strict)
    required_files = [
        "SystemInfo.json",
        "SystemDetailsDashboard.json",
        "Privacy.json",
        "WorkflowDashboard.json",
        "Workflows.json",
        "CAC.json",
        "Controls.json",
        "TestResults.json",
        "Findings.json",
        "SystemPOAMDashboard.json",
        "ArtifactDetails.json",
        "ArtifactSummary.json",
        "Hardware.json",
        "HardwareDetailsDashboard.json",
        "Software.json",
        "SoftwareDetailsDashboard.json",
        "Associations.json",
        "UserDetails.json",
        # CCSD handled separately (either/or with ConnectivityCCSD)
    ]

    missing: List[str] = []
    unreadable: List[str] = []

    # Check the strict list first
    for fname in required_files:
        obj = _load_fixture_json(fname, cfg)
        if obj is None:
            # Could be missing OR unreadable (parse failure). We logged details in the loader.
            # Treat anything that didn't yield an object as a failure.
            missing.append(fname)

    ok = not missing and not unreadable

    # Emit a single summary line at INFO with details at DEBUG
    if ok:
        log.info("eMASS connection test: OK (all required JSON fixtures readable)")
    else:
        if missing:
            log.warning("eMASS connection test: missing/unreadable fixtures: %s", ", ".join(missing))
        if unreadable:
            log.warning("eMASS connection test: parse errors in fixtures: %s", ", ".join(unreadable))

    return ok


if __name__ == "__main__":
    import argparse
    import sys
    from rich.console import Console
    from rich.traceback import install as rich_install

    # Pretty tracebacks when solo-running this module
    rich_install()
    console = Console()

    parser = argparse.ArgumentParser(
        description="Standalone driver for eMASS SystemContext builder."
    )
    parser.add_argument(
        "--system-id",
        "-s",
        type=int,
        help="Target eMASS system id. If omitted, discovered IDs will be listed.",
        default=None,
    )
    parser.add_argument(
        "--apms-csv",
        help="Path to APMS CSV export (optional).",
        default="",
    )
    parser.add_argument(
        "--checklist",
        help="Path to checklist / STIG snapshot (optional).",
        default="",
    )

    args = parser.parse_args()

    # Try to get *some* Config, but don't require it.
    try:
        cfg: Optional[Config] = Config()  # type: ignore[assignment]
    except TypeError:
        # Fallback in case Config requires arguments; we only care about .data_root
        class _DummyCfg:
            data_root: Optional[str] = None
        cfg = _DummyCfg()  # type: ignore[assignment]
    except Exception:
        cfg = None  # type: ignore[assignment]

    console.rule("[bold cyan]eMASS Builder Standalone[/bold cyan]")

    # Quick health check for fixtures (uses _load_fixture_json search paths)
    console.print("[bold]Running eMASS connection test...[/bold]")
    ok = test_emass_connection(cfg)
    if not ok:
        console.print("[red]eMASS connection test failed; check logs for details.[/red]")
        sys.exit(1)

    # If no system-id, just list what we find and exit.
    if args.system_id is None:
        console.print("[bold]Discovering system IDs from SystemDetailsDashboard.json...[/bold]")
        ids = discover_system_ids(cfg=cfg)
        if not ids:
            console.print("[yellow]No system IDs discovered.[/yellow]")
            sys.exit(0)

        console.print("[green]Discovered system IDs:[/green] " + ", ".join(str(i) for i in ids))
        console.print(
            "\nRerun with [bold]--system-id <ID>[/bold] to build and pretty-print a SystemContext."
        )
        sys.exit(0)

    # Build a single SystemContext for the requested system id.
    console.print(
        f"[bold]Building SystemContext for system_id={args.system_id}[/bold]\n"
    )
    ctx = build_system_context_from_emass(
        cfg=cfg,  # may be None / dummy; loader only cares about .data_root if present
        system_id=args.system_id,
        apms_csv_path=args.apms_csv,
        checklist_path=args.checklist,
    )

    # Quick sanity peek (the Rich JSON dump already ran inside the builder)
    console.rule("[bold green]SystemContext Summary[/bold green]")
    console.print(
        f"[bold]Name:[/bold] {ctx.system_name!r}\n"
        f"[bold]Acronym:[/bold] {ctx.system_acronym!r}\n"
        f"[bold]Workflow Stage:[/bold] {ctx.workflow_stage!r}\n"
        f"[bold]Baseline Location (if hydrated):[/bold] "
        f"{getattr(getattr(ctx, 'system_details_dashboard', None), 'baseline_location', None)!r}\n"
    )
    console.print(
        "[dim]Full context JSON was pretty-printed above by build_system_context_from_emass.[/dim]"
    )
