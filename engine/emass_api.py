# emass_api.py
from __future__ import annotations

"""
eMASS API client and SystemContext builder, integrated with project Config.

Highlights
----------
- Reads API base URL, API key, TLS verify, client certificate settings, and org_id from Config (config.ini).
- Supports PEM (cert + key) or PFX (converted to temp PEM) client authentication.
- Thin endpoint wrappers for the eMASS resources we call.
- Builds a SystemContext that includes APMS cross-check fields (Item Name, Acronym).
- Robust logging (use Config.configure_logging() before using this module).

Usage
-----
    cfg = Config()
    cfg.configure_logging()
    cfg.validate_minimums()

    session = init_emass_session_from_config(cfg)
    context = build_system_context_from_emass(
        cfg=cfg,
        sess=session,
        system_id=123,
        apms_csv_path="/app/data/apms.csv",
        checklist_path=cfg.checklist_path,
    )
"""

import atexit
import csv
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, Union

import requests

from engine.config import Config
from engine.models import SystemContext

#Sets up the logger to use the logger we setup within config.py
logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# PFX -> PEM lifecycle management
# -------------------------------------------------------------------
@dataclass
class _TempPEM:
    """Tracks a temporary directory holding PEM files derived from a PFX."""
    temp_dir: str
    cert_path: str
    key_path: str

    def cleanup(self) -> None:
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception as exc:
            logger.debug("Failed to cleanup temp PEM dir %s: %r", self.temp_dir, exc)


_TEMP_PEMS: list[_TempPEM] = []


@atexit.register
def _cleanup_temp_pems() -> None:
    """Remove any temp PEM directories created during this process."""
    for t in _TEMP_PEMS:
        t.cleanup()


def _pfx_to_pem(pfx_path: str, password: str) -> Tuple[str, str, _TempPEM]:
    """
    Convert a PFX bundle into temporary PEM certificate and key using OpenSSL.

    Returns
    -------
    (cert_pem_path, key_pem_path, tracker)
        tracker is an internal object ensuring the temp directory is cleaned up at exit.
    """
    tmp_dir = tempfile.mkdtemp(prefix="emass_pfx_")
    cert_pem = os.path.join(tmp_dir, "cert.pem")
    key_pem = os.path.join(tmp_dir, "key.pem")

    logger.debug("Converting PFX at %s to PEMs in %s", pfx_path, tmp_dir)

    subprocess.check_call([
        "openssl", "pkcs12", "-in", pfx_path,
        "-clcerts", "-nokeys", "-out", cert_pem,
        "-passin", f"pass:{password}",
    ])
    subprocess.check_call([
        "openssl", "pkcs12", "-in", pfx_path,
        "-nocerts", "-nodes", "-out", key_pem,
        "-passin", f"pass:{password}",
    ])

    tracker = _TempPEM(temp_dir=tmp_dir, cert_path=cert_pem, key_path=key_pem)
    _TEMP_PEMS.append(tracker)
    return cert_pem, key_pem, tracker


# -------------------------------------------------------------------
# HTTP session wrapper
# -------------------------------------------------------------------
class EmassSession:
    """
    Thin wrapper around `requests` configured for eMASS:

    - Base URL management
    - API-key header injection
    - Client certificate (PEM tuple) and TLS verify control
    - JSON parsing with clear error messages
    - **Exponential backoff** with jitter for transient HTTP/network errors
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        cert: Optional[Tuple[str, str]] = None,
        verify: Union[bool, str] = True,
        timeout_seconds: float = 30.0,
        max_retries: int = 5,              # 5 total attempts
        backoff_base_seconds: float = 5.0, # start at 5s
        backoff_jitter: float = 0.25,      # +/-25% jitter
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.cert = cert
        self.verify = verify
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_jitter = backoff_jitter

        logger.debug(
            "EmassSession(base_url=%s, verify=%s, timeout=%.1fs, retries=%d, backoff_base=%.1fs, jitter=%.2f)",
            self.base_url, self.verify, self.timeout_seconds, self.max_retries,
            self.backoff_base_seconds, self.backoff_jitter,
        )

    def _sleep_with_backoff(self, attempt: int, retry_after: Optional[str] = None) -> None:
        """
        Sleep using exponential backoff (attempt is 1-based):
          base * 2^(attempt-1) with +/- jitter.
        Example with base=5s: 5s, 10s, 20s, 40s, ...

        If a Retry-After header is present, honor it (seconds or HTTP-date).
        """
        import time as _time, random as _random
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone

        # Honor Retry-After if present and valid
        if retry_after:
            delay: Optional[int] = None
            try:
                delay = int(retry_after)
            except ValueError:
                try:
                    dt = parsedate_to_datetime(retry_after)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    now = datetime.now(tz=timezone.utc)
                    delay = max(0, int((dt - now).total_seconds()))
                except Exception:
                    delay = None
            if delay and delay > 0:
                logger.warning("Retry-After honored: sleeping %ss", delay)
                _time.sleep(delay)
                return

        # Exponential backoff with jitter
        nominal = self.backoff_base_seconds * (2 ** (attempt - 1))
        jitter = nominal * self.backoff_jitter
        delay = max(0.0, _random.uniform(nominal - jitter, nominal + jitter))
        logger.warning("Backoff sleep: %.1fs (before attempt %d)", delay, attempt + 1)
        _time.sleep(delay)

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        import json as _json
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = kwargs.pop("headers", {}) or {}
        headers["api-key"] = self.api_key

        kwargs.setdefault("timeout", self.timeout_seconds)
        kwargs.setdefault("verify", self.verify)
        if self.cert:
            kwargs.setdefault("cert", self.cert)
        kwargs["headers"] = headers

        # Retriable statuses: rate-limit + common 5xx
        retriable_statuses = {429, 500, 502, 503, 504}

        attempt = 0
        while True:
            attempt += 1
            try:
                resp = requests.request(method, url, **kwargs)

                # Handle retriable HTTP status codes
                if resp.status_code in retriable_statuses and attempt < self.max_retries:
                    retry_after = resp.headers.get("Retry-After")
                    logger.warning(
                        "HTTP %s on %s %s (attempt %d/%d).",
                        resp.status_code, method, url, attempt, self.max_retries
                    )
                    self._sleep_with_backoff(attempt, retry_after)
                    continue

                resp.raise_for_status()

                try:
                    return resp.json()
                except _json.JSONDecodeError as jde:
                    snippet = resp.text[:500]
                    raise RuntimeError(
                        f"Expected JSON from {url}; got non-JSON body (status {resp.status_code}). "
                        f"Body (truncated): {snippet}"
                    ) from jde

            except requests.RequestException as req_err:
                if attempt < self.max_retries:
                    logger.warning(
                        "Request error on %s %s (attempt %d/%d): %s",
                        method, url, attempt, self.max_retries, req_err
                    )
                    self._sleep_with_backoff(attempt)
                    continue
                logger.error(
                    "Request failed on %s %s after %d attempt(s): %s",
                    method, url, attempt, req_err
                )
                raise

    def get(self, path: str, **kwargs) -> Dict[str, Any]:
        """Perform a GET request relative to the configured base URL."""
        return self._request("GET", path, **kwargs)



# -------------------------------------------------------------------
# Session factory using project Config
# -------------------------------------------------------------------
def init_emass_session_from_config(cfg: Config) -> EmassSession:
    """
    Create an `EmassSession` instance using values from `Config` (config.ini).

    Reads
    -----
    - cfg.emass_api_base
    - cfg.emass_api_key
    - cfg.tls_verify() -> bool | str
    - cfg.emass_cert_tuple() OR cfg.has_pfx() (PFX converted to temp PEM)
    """
    verify = cfg.tls_verify()
    pem_tuple = cfg.emass_cert_tuple()

    if pem_tuple:
        logger.info("Initializing EmassSession with PEM cert/key from config.")
        return EmassSession(
            base_url=cfg.emass_api_base,
            api_key=cfg.emass_api_key,
            cert=pem_tuple,
            verify=verify,
        )

    if cfg.has_pfx():
        logger.info("Initializing EmassSession with PFX (converted to temp PEM).")
        cert_pem, key_pem, _ = _pfx_to_pem(cfg.emass_pfx_path, cfg.emass_pfx_pass)  # type: ignore[arg-type]
        return EmassSession(
            base_url=cfg.emass_api_base,
            api_key=cfg.emass_api_key,
            cert=(cert_pem, key_pem),
            verify=verify,
        )

    raise RuntimeError(
        "Client certificate not configured. Provide cert_path+key_path OR pfx_path+pfx_pass in config.ini."
    )


# -------------------------------------------------------------------
# Endpoint wrappers
# -------------------------------------------------------------------
def get_system_info(session: EmassSession, system_id: str) -> Dict[str, Any]:
    """GET /systems/{system_id}"""
    return session.get(f"systems/{system_id}")


def get_workflow_pac(session: EmassSession, system_id: str) -> Dict[str, Any]:
    """GET /systems/{system_id}/approval/pac"""
    return session.get(f"systems/{system_id}/approval/pac")


def get_dashboard_system_hardware_summary(session: EmassSession, org_id: str) -> Dict[str, Any]:
    """GET /dashboards/system-hardware-summary?orgId={orgId}"""
    return session.get(f"dashboards/system-hardware-summary?orgId={org_id}")


def get_dashboard_system_software_summary(session: EmassSession, org_id: str) -> Dict[str, Any]:
    """GET /dashboards/system-software-summary?orgId={org_id}"""
    return session.get(f"dashboards/system-software-summary?orgId={org_id}")


def get_dashboard_system_artifacts_summary(session: EmassSession, org_id: str) -> Dict[str, Any]:
    """GET /dashboards/system-artifacts-summary?orgId={org_id}"""
    return session.get(f"dashboards/system-artifacts-summary?orgId={org_id}")


def get_dashboard_system_artifacts_details(session: EmassSession, org_id: str) -> Dict[str, Any]:
    """GET /dashboards/system-artifacts-details?orgId={org_id}"""
    return session.get(f"dashboards/system-artifacts-details?orgId={org_id}")


# -------------------------------------------------------------------
# SystemContext builder
# -------------------------------------------------------------------
def _first_or_none(reader: csv.DictReader) -> Optional[dict[str, Any]]:
    """Return the first row from a DictReader, or None if the CSV is empty."""
    try:
        return next(reader)
    except StopIteration:
        return None


def build_system_context_from_emass(
    *,
    cfg: Config,
    sess: EmassSession,
    system_id: int,
    apms_csv_path: str,
    checklist_path: str,
) -> SystemContext:
    """
    Build a `SystemContext` by querying eMASS and correlating with APMS CSV data.

    Design:
    - `system_id` is an **int** (authoritative). We only coerce to `str` at API/CSV boundaries:
        * URL path segments (HTTP) require strings.
        * APMS CSV keys/values are strings.
    - All comparisons to APMS fields use normalized strings to avoid type/format mismatches.

    Populates:
      • Core system metadata (name, acronym, description, version, registration, CIA, impact, type, RMF activity)
      • Classification flags (CUI, PII, PHI, NSS, FMS)
      • Workflow (type/name/stage) via PAC endpoint
      • Presence hints for hardware/software via org-scoped dashboards
      • Artifact counts and whether artifact details exist
      • Cross-check fields from APMS CSV:
          - data_report_number  (DATA Number | AITR Number)
          - apms_item_name      (Item Name)
          - apms_acronym        (Acronym)
          - emass_data_id       (from eMASS)

    Args:
        cfg: Loaded configuration (org_id, logging, TLS/cert, etc.).
        sess: Initialized `EmassSession` (auth, retries, TLS verify).
        system_id: **Integer** eMASS system identifier (e.g., 101, 200).
        apms_csv_path: Path to the APMS CSV for this run.
        checklist_path: Path to the checklist file.

    Returns:
        A fully-populated `SystemContext` ready for test execution.

    Raises:
        Any exceptions from HTTP, I/O, or parsing will bubble unless explicitly caught/logged below.
    """
    logger.info("Building SystemContext (system_id=%d)", system_id)

    # --- System Info ---
    sys_info = get_system_info(sess, str(system_id))  # URL path segment: stringify
    sys_data = sys_info.get("data", {}) or {}
    logger.debug("System info keys: %s", list(sys_data.keys()))

    # --- Workflow (PAC) ---
    workflow_data = get_workflow_pac(sess, str(system_id)).get("data") or None
    if workflow_data:
        logger.debug(
            "Workflow: %s | %s | stage=%s",
            workflow_data.get("workflow"),
            workflow_data.get("name"),
            workflow_data.get("currentStageName"),
        )
    else:
        logger.info("No active workflow for system_id=%d", system_id)

    # --- Org scope for dashboards (from config) ---
    org_id = cfg.emass_org_id

    # --- Presence hints: hardware/software ---
    has_hardware_data: Optional[bool] = None
    has_software_data: Optional[bool] = None
    try:
        hw_summary = get_dashboard_system_hardware_summary(sess, org_id).get("data", [])
        sw_summary = get_dashboard_system_software_summary(sess, org_id).get("data", [])
        sys_id_str = str(system_id)
        has_hardware_data = any(str(r.get("System ID")) == sys_id_str for r in hw_summary)
        has_software_data = any(str(r.get("System ID")) == sys_id_str for r in sw_summary)
    except Exception as exc:
        logger.warning("Failed to fetch HW/SW summaries (org_id=%s): %r", org_id, exc)

    # --- Artifacts ---
    artifact_number: Optional[int] = None
    has_artifact_details: Optional[bool] = None
    try:
        art_summary = get_dashboard_system_artifacts_summary(sess, org_id).get("data", [])
        art_row = next((r for r in art_summary if str(r.get("System ID")) == str(system_id)), None)
        if art_row and "Total Artifacts" in art_row:
            try:
                artifact_number = int(art_row.get("Total Artifacts"))
            except Exception:
                artifact_number = None

        art_details = get_dashboard_system_artifacts_details(sess, org_id).get("data", [])
        has_artifact_details = any(str(r.get("System ID")) == str(system_id) for r in art_details)
    except Exception as exc:
        logger.warning("Failed to fetch artifact dashboards (org_id=%s): %r", org_id, exc)

    # --- APMS CSV cross-check ---
    data_report_number: Optional[str] = None
    apms_item_name: Optional[str] = None
    apms_acronym: Optional[str] = None
    if apms_csv_path and os.path.exists(apms_csv_path):
        try:
            with open(apms_csv_path, newline="") as csv_file:
                reader = csv.DictReader(csv_file)
                first_row = _first_or_none(reader)
                if first_row:
                    data_report_number = first_row.get("DATA Number") or first_row.get("AITR Number")
                    apms_item_name = first_row.get("Item Name")
                    apms_acronym = first_row.get("Acronym")
                    apms_PII = first_row.get("PIA Required")
                    apms_PHI = first_row.get("Does the system contain Protected Health Information (PHI)")
                    logger.debug(
                        "APMS CSV first row: report_no=%s, item_name=%s, acronym=%s",
                        data_report_number, apms_item_name, apms_acronym
                    )
        except Exception as exc:
            logger.warning("Failed to parse APMS CSV at %s: %r", apms_csv_path, exc)
    else:
        logger.warning("APMS CSV path missing or does not exist: %s", apms_csv_path)

    emass_data_id = sys_data.get("dataId") or sys_data.get("apmsId")
    if data_report_number and emass_data_id:
        if str(data_report_number).strip() != str(emass_data_id).strip():
            logger.warning(
                "APMS report number mismatch with eMASS data id: APMS=%s, eMASS=%s",
                data_report_number, emass_data_id
            )

    # --- Assemble SystemContext ---
    context = SystemContext(
        # Identifiers & paths
        system_id=system_id,  
        data_path=apms_csv_path,
        checklist_path=checklist_path,

        # Connection meta (if present)
        connection_code=str(sys_info.get("meta", {}).get("code")) if isinstance(sys_info.get("meta"), dict) else None,

        # Core system fields
        system_name=sys_data.get("name"),
        system_acronym=sys_data.get("acronym"),
        system_description=sys_data.get("description"),
        system_version=sys_data.get("versionReleaseNo"),
        registration_type=sys_data.get("registrationtype"),
        lifecycle_phase=sys_data.get("systemLifeCycleAcquisitionPhase"),
        authorization_status=sys_data.get("authorizationStatus"),
        confidentiality=sys_data.get("confidentiality"),
        integrity=sys_data.get("integrity"),
        availability=sys_data.get("availability"),
        impact=sys_data.get("impact"),
        system_type=sys_data.get("systemType"),
        rmf_activity=sys_data.get("rmfActivity"),
        reciprocity=sys_data.get("isReciprocity"),

        #public facing information
        public=sys_data.get("isPublicFacing"),
        WhiteListId=sys_data.get("whitelistId"),
        WhiteListInventory=sys_data.get("whitelistInventory"),

        # Classification flags
        cui=_to_bool(sys_data.get("hasCUI")),
        pii=_to_bool(sys_data.get("hasPII")),
        phi=_to_bool(sys_data.get("hasPHI")),
        nss=_to_bool(sys_data.get("isNSS")),
        fms=_to_bool(sys_data.get("isFinancialManagement")),

        classification=sys_data.get("highestSystemDataClassification"),
        mission_criticality=sys_data.get("missionCriticality"),

        # Workflow
        workflow_type=(workflow_data or {}).get("workflow") if workflow_data else None,
        workflow_name=(workflow_data or {}).get("name") if workflow_data else None,
        workflow_stage=(workflow_data or {}).get("currentStageName") if workflow_data else None,

        # Presence hints
        has_hardware_data=has_hardware_data,
        has_software_data=has_software_data,

        # Artifacts
        artifact_number=artifact_number,
        has_artifact_details=has_artifact_details,

        # Cross-checks
        data_report_number=str(data_report_number) if data_report_number else None,
        emass_data_id=str(emass_data_id) if emass_data_id else None,
        apms_item_name=apms_item_name,
        apms_acronym=apms_acronym,
    )

    logger.info(
        "SystemContext ready (system_id=%d, name=%s, acronym=%s, reg=%s, CIA=%s/%s/%s, artifacts=%s, org_id=%s)",
        system_id,
        context.system_name,
        context.system_acronym,
        context.registration_type,
        context.confidentiality, context.integrity, context.availability,
        context.artifact_number,
        org_id,
    )
    return context



# -------------------------------------------------------------------
# Utility
# -------------------------------------------------------------------
def _to_bool(value: Any) -> Optional[bool]:
    """Best-effort coercion of truthy/falsey strings into bools; returns None on unknown."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"true", "yes", "y", "1"}:
        return True
    if s in {"false", "no", "n", "0"}:
        return False
    return None
