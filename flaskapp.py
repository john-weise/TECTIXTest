### flaskapp.py (Flask Web Server)

# ─────────────────────────────────────────────────────────────────────────────
# Imports
# ─────────────────────────────────────────────────────────────────────────────

# Stdlib
import os
import re
import json
from json import JSONDecodeError
import time
import random
import secrets
import shutil
import subprocess
import threading
import traceback
from pathlib import Path
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Tuple
from datetime import datetime, timedelta, timezone
from functools import wraps
import signal 
import atexit


# Third-party
import pandas as pd
from pydantic import ValidationError
from whitenoise import WhiteNoise
from werkzeug.utils import secure_filename


# Flask
from flask import (
    Flask,
    request,
    jsonify,
    session,
    abort,
    send_file,
    send_from_directory,
    render_template,
    redirect,
    url_for,
    Response,
    stream_with_context,
    make_response,
)

# App models / schemas
from models import (
    ProcessInput,
    LoginInput,
    LoginResponse,
    # policy-related schemas
    ScanPolicyCreate,
    ScanPolicyUpdate,
    SystemsBatch,
    LastRunUpdate,
    ScanPolicyOut,
    DataFramePayload,
    SystemSummary,
    AddSystemInput,
    ContinuousItem,
    AddSystemBatchInput,
    TwoFactorCodeInput,
    TwoFactorCodeInput,
    TwoFactorStatusResponse,
)

# DB & services
from db import (
    # general auth/user/system utilities used across many endpoints
    init_db,
    verify_user,
    list_users,
    add_user,
    remove_user,
    get_user,
    change_own_password,
    get_session,           
    list_all_systems,
    set_system_csv_path,
    set_policy_last_run_epoch,
    mark_policy_last_run_now,
    compute_dashboard_flags,

    # ── legacy/low-level policy helpers (still present for older endpoints) ──
    create_scan_policy,
    get_scan_policy_by_id,
    list_scan_policies_with_systems,
    update_scan_policy,
    delete_scan_policy,
    enroll_systems_to_policy,
    list_systems_by_policy,
    remove_systems_from_policy,

    # ── new service-layer wrappers (use these for new/updated policy endpoints) ──
    policies_list,
    policies_create,
    policy_update,
    policy_delete,
    policies_enroll_systems,
    policies_remove_systems,
    get_latest_run_dataframe_for_system,
    get_latest_readiness_score_for_system,
    list_continuous_monitoring_items,
    list_readiness_history_for_system,
    get_all_policies,
    get_enrolled_system_ids,

    # service-layer exceptions (map to HTTP codes in Flask handlers)
    DBNotFound,
    DBConflict,
    DBValidation,
    SystemCsv,
)
#2fa stuff
from two_factor_auth import (
    is_2fa_enabled,
    verify_totp_code,
    start_twofa_enrollment,
    confirm_twofa_enrollment,
    disable_twofa,
    regenerate_recovery_codes,
    get_2fa_status,
)

# App-specific 
#from process_files import generate_checklist, process_output
#New python driven
from python_process_files import generate_checklist_compat as generate_checklist
from engine.test_api import discover_system_ids, test_emass_connection
from python_process_files import register_progress_sink
from scan_executor import start_background_scan_executor, stop_background_scan_executor
from scan_policy_scheduler import scan_now
from scan_executor import (
    start_background_scan_executor,
    stop_background_scan_executor,
    is_background_scan_executor_running,
)
from engine.config import (
    Config,
    DEFAULT_CONFIG_PATH,
    update_emass_credentials,
)
from helpers import compute_readiness_summary, verify_pkcs12_file
from log_config import setup_logging, get_logfile_path, search_log
from state import process_output, jobs, JobRecord

# Keep a second time alias for perf logging (existing code may rely on _time)
import time as _time


#Mitigate token reuse accross builds. 

SERVER_RUN_ID = secrets.token_hex(16)  # New value on each container start
#app = Flask(__name__)

# --- SSE helpers ------------------------------------------------
def sse_format(data: str) -> str:
    # Each SSE event must end with a blank line
    return f"data: {data}\n\n"


@dataclass
class JobRecord:
    owner: str           # session["user"]
    system_id: int
    job_dir: Path        # working/<user>/<job_id>
    json_path: Path      # working file
    # output_path optional; we’ll just scan the dir on download
    # output_path: Optional[Path] = None

jobs: Dict[str, JobRecord] = {}

# ─── Database & Auth Helpers ─────────────────────────────────────

# Initialize SQLite store and seed default admin
#init_db()

logger = setup_logging() 


def _session_valid_for_current_run() -> bool:
    return session.get("server_run_id") == SERVER_RUN_ID

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _session_valid_for_current_run():
            session.clear()
            return jsonify({"error": "not authenticated"}), 401
        if "user" not in session:
            return jsonify({"error": "not authenticated"}), 401
        return fn(*args, **kwargs)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _session_valid_for_current_run():
            session.clear()
            return jsonify({"error": "not authenticated"}), 401
        if not session.get("is_admin", False):
            return jsonify({"error": "forbidden"}), 403
        return fn(*args, **kwargs)
    return wrapper

def _clamp_int(val, *, default, min_v, max_v):
    try:
        v = int(val)
    except Exception:
        return default
    return max(min_v, min(max_v, v))


# ─── Flask App Setup ─────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SCRIPTS_DIR= BASE_DIR / "scripts"
WORKING_DIR= BASE_DIR / "working"
BUILD_DIR  = BASE_DIR / "react_build"
WORKING_DIR.mkdir(exist_ok=True)


app = Flask(__name__, static_folder=None)
app.wsgi_app = WhiteNoise(app.wsgi_app, root=str(BUILD_DIR), prefix='')
app.secret_key = os.environ["FLASK_SECRET_KEY"]
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", app.secret_key)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30)
)

# --- Stale job cleanup config ---
# how old a job dir must be to delete (default: 3 days)
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", 3 * 24 * 3600))
# how often to scan for stale jobs (default: every 6 hours)
CLEAN_INTERVAL_SECONDS = int(os.getenv("CLEAN_INTERVAL_SECONDS", 6 * 3600))

# ─── Scan policy runner ─────────────────────────────────────────────
# Start the background scheduler immediately on module import
_STOP_EVENT = start_background_scan_executor()
logger.info(
    "[FLASKAPP] scan executor running: %s",
    is_background_scan_executor_running(),
)

# Make sure we stop it on interpreter shutdown (defensive; scan_executor also does this)
atexit.register(stop_background_scan_executor)

# ─── Serve React SPA ─────────────────────────────────────────────
@app.route("/", defaults={"path":""})
@app.route("/<path:path>")
def serve_react(path):
    if path and (BUILD_DIR / path).exists():
        return send_from_directory(str(BUILD_DIR), path)
    return send_from_directory(str(BUILD_DIR), "index.html")

# ─── Auth Endpoints ─────────────────────────────────────────────


# in-memory rate-limit store: IP → timestamps
_login_attempts = defaultdict(deque)
_RATE_LIMIT   = 100            # max attempts
_RATE_WINDOW  = 10 * 60      # seconds


_MIN_AUTH_TIME = 0.25  # seconds, tune as you like

# Minimum time budget for /api/session checks (seconds)
_MIN_SESSION_TIME = 0.05


def _auth_sleep(start: float) -> None:
    """Normalize total auth time to reduce timing side-channels.

    Ensures the request takes at least `_MIN_AUTH_TIME` seconds from `start`,
    plus a small random jitter, regardless of success or failure path.
    """
    elapsed = time.perf_counter() - start
    extra = max(0.0, _MIN_AUTH_TIME - elapsed)
    # Small random jitter on top to make measurements noisier.
    time.sleep(extra + random.uniform(0.0, 0.05))




def _session_sleep(start: float) -> None:
    """Normalize total time for session checks to reduce timing signals.

    Ensures the handler takes at least `_MIN_SESSION_TIME` from `start`,
    plus a small random jitter, regardless of whether the session is valid.
    """
    elapsed = time.perf_counter() - start
    extra = max(0.0, _MIN_SESSION_TIME - elapsed)
    time.sleep(extra + random.uniform(0.0, 0.02))


@app.route("/api/login", methods=["POST"])
def login():
    """Authenticates a user and optionally initiates a 2FA challenge.

    This endpoint performs the first step of authentication using a username
    and password. It enforces per-IP rate limiting, validates the request
    payload with Pydantic, and verifies credentials against the database.

    If credentials are valid and the user does **not** have 2FA enabled, the
    endpoint establishes a full authenticated session and returns a successful
    `LoginResponse`.

    If credentials are valid and the user **does** have 2FA enabled, the
    endpoint creates a "pending 2FA" session (no fully authenticated user yet)
    and returns a `LoginResponse` that signals `two_factor_required=True`. The
    caller must then complete a second step (e.g., submit a TOTP code) to
    finalize the login.

    Behavior:
      * Rate limiting:
          - Requests are tracked per `remote_addr` in a sliding window defined
            by `_RATE_WINDOW`.
          - If an IP exceeds `_RATE_LIMIT` attempts in the window, the request
            is rejected with HTTP 429.
      * Validation:
          - Request JSON is validated via `LoginInput`. Invalid shape or
            constraints return HTTP 400.
      * Authentication:
          - Invalid credentials always return HTTP 401 with a generic error,
            without disclosing whether the username exists.
      * Sessions:
          - On non-2FA success: sets `session["user"]`, `session["is_admin"]`
            and `session["server_run_id"]`.
          - On 2FA-protected accounts: sets `session["pending_user"]`,
            `session["pending_is_admin"]`, `session["pending_2fa_created_at"]`,
            and `session["server_run_id"]`, but does **not** set `session["user"]`
            yet.

    Request JSON:
      {
        "username": "<string>",
        "password": "<string>"
      }

    Returns:
        flask.Response: A JSON-encoded `LoginResponse` with appropriate HTTP status:
          - 200:
              * `success=True`, `user=<username>`, `two_factor_required=False`
                when fully logged in (no 2FA).
              * `success=False`, `user=None`, `two_factor_required=True`
                when 2FA is required and a pending 2FA session was created.
          - 400: Invalid input (schema/validation failures).
          - 401: Invalid credentials.
          - 429: Too many attempts from the same IP within the rate window.

    Notes:
        This handler normalizes total request time using `_auth_sleep` on all
        code paths to make timing side-channels around authentication harder
        to exploit. Combined with a constant-work `verify_user`, this reduces
        username-enumeration and credential-timing signals.
    """
    start = time.perf_counter()

    ip = request.remote_addr or "unknown"
    now = time.time()
    tries = _login_attempts[ip]

    # Remove timestamps older than the rate window.
    while tries and now - tries[0] > _RATE_WINDOW:
        tries.popleft()

    if len(tries) >= _RATE_LIMIT:
        logger.warning("[RATE LIMIT] Too many login attempts from %s", ip)
        resp = LoginResponse(
            success=False,
            error="Too many login attempts. Please try again later.",
        )
        _auth_sleep(start)
        return jsonify(resp.model_dump()), 429

    body = request.get_json() or {}
    logger.info("[LOGIN ATTEMPT] ip=%s", ip)
    tries.append(now)

    # Pydantic will validate structure and basic constraints.
    try:
        creds = LoginInput(**body)
    except ValidationError as e:
        logger.warning("[LOGIN INPUT INVALID] ip=%s errors=%s", ip, e.errors())
        resp = LoginResponse(success=False, error="Invalid username/password format")
        _auth_sleep(start)
        return jsonify(resp.model_dump()), 400

    # Authenticate against DB.
    v = verify_user(creds.username, creds.password)

    if not v:
        logger.warning("[LOGIN FAILED] ip=%s user=%s", ip, creds.username)
        resp = LoginResponse(success=False, error="Invalid credentials")
        _auth_sleep(start)
        return jsonify(resp.model_dump()), 401

    username = v["username"]
    is_admin = v["is_admin"]
    twofa_enabled = v.get("twofa_enabled", False)

    # Reset any existing session before creating a new one.
    session.clear()

    if twofa_enabled:
        # 2FA enabled, create a pending 2FA session.
        session.permanent = True
        session["server_run_id"] = SERVER_RUN_ID
        session["pending_user"] = username
        session["pending_is_admin"] = is_admin
        session["pending_2fa_created_at"] = int(time.time())

        logger.info("[LOGIN 2FA PENDING] ip=%s user=%s", ip, username)

        resp = LoginResponse(
            success=False,
            user=None,
            error=None,
            two_factor_required=True,
        )
        _auth_sleep(start)
        return jsonify(resp.model_dump()), 200

    # No 2FA, then full login.
    session.permanent = True
    session["server_run_id"] = SERVER_RUN_ID
    session["user"] = username
    session["is_admin"] = is_admin

    logger.info("[LOGIN SUCCESS] ip=%s user=%s", ip, username)
    resp = LoginResponse(success=True, user=username)
    _auth_sleep(start)
    return jsonify(resp.model_dump()), 200



@app.route("/api/session")
def session_check():
    """Returns session info and dashboard flags.

    Backward compatibility:
      - Always returns the original keys expected by legacy clients:
        * authenticated: bool
        * user: str
        * is_admin: bool

    Additional keys (non-breaking):
      - is_default_admin: bool
      - needs_password_reset: bool
      - show_welcome: bool
      - twofa_enabled: bool

    Semantics:
      - Sessions from an old container run (mismatched `server_run_id`) are
        treated as invalid and cleared.
      - Pending 2FA sessions (where `pending_user` is set but no `user`) are
        **not** considered authenticated and return `{"authenticated": False}`.
      - Only sessions with a bound `user` and a corresponding DB row are
        treated as authenticated.

    Returns:
      flask.Response: A JSON response describing the current authenticated user
      state. If there is no valid session, returns {"authenticated": False}.

    Notes:
      This handler normalizes its execution time via `_session_sleep` so that
      different unauthenticated states (no cookie, expired session, deleted
      user, pending 2FA) are harder to distinguish via timing.
    """
    start = time.perf_counter()

    # Invalidate sessions from old container runs first.
    if not _session_valid_for_current_run():
        session.clear()
        resp = {"authenticated": False}
        _session_sleep(start)
        return jsonify(resp)

    # Pending 2FA sessions are not considered authenticated.
    if "pending_user" in session and "user" not in session:
        resp = {"authenticated": False}
        _session_sleep(start)
        return jsonify(resp)

    username = session.get("user")
    if not username:
        resp = {"authenticated": False}
        _session_sleep(start)
        return jsonify(resp)

    user_info = get_user(username)
    if not user_info:
        # Stale cookie or deleted account.
        session.clear()
        resp = {"authenticated": False}
        _session_sleep(start)
        return jsonify(resp)

    # Baseline (legacy) payload.
    payload: Dict[str, Any] = {
        "authenticated": True,
        "user": user_info["username"],
        "is_admin": user_info["is_admin"],
        "twofa_enabled": user_info.get("twofa_enabled", False),
    }

    # Optional dashboard flags.
    try:
        flags = compute_dashboard_flags(username)
        payload.update(flags)
    except Exception as err:  # noqa: BLE001
        logger.warning("compute_dashboard_flags failed for user=%s: %s", username, err)

    _session_sleep(start)
    return jsonify(payload)

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})

#2fa stuff
# 2fa stuff

@app.route("/api/login/2fa", methods=["POST"])
def login_2fa():
    """Completes login by verifying a 2FA factor (TOTP or recovery code).

    This endpoint expects an existing pending 2FA session created by
    `/api/login`. On successful verification, it promotes the session
    to a full authenticated session.

    Request JSON:
      {
        "code": "123456"   // TOTP from authenticator, or recovery code
      }

    Returns:
      200 OK with LoginResponse(success=True) on success.
      400/401 on invalid or expired pending session or code.
    """
    if not _session_valid_for_current_run():
        session.clear()
        resp = LoginResponse(success=False, error="Session is invalid or expired.")
        return jsonify(resp.model_dump()), 401

    pending_user = session.get("pending_user")
    pending_is_admin = session.get("pending_is_admin")
    created_at = session.get("pending_2fa_created_at")

    if not pending_user or not created_at:
        logger.warning("[2FA] No pending 2FA login in session.")
        resp = LoginResponse(success=False, error="No pending 2FA login.")
        return jsonify(resp.model_dump()), 400

    # Optional: 5-minute validity for the 2FA step.
    if time.time() - created_at > 300:
        logger.info("[2FA EXPIRED] user=%s", pending_user)
        session.clear()
        resp = LoginResponse(success=False, error="2FA session expired.")
        return jsonify(resp.model_dump()), 401

    body = request.get_json() or {}
    try:
        data = TwoFactorCodeInput(**body)
    except ValidationError as e:
        logger.warning(
            "[2FA INPUT INVALID] user=%s errors=%s",
            pending_user,
            e.errors(),
        )
        resp = LoginResponse(success=False, error="Invalid 2FA code format.")
        return jsonify(resp.model_dump()), 400

    code = (data.code or "").strip()
    if not code:
        resp = LoginResponse(success=False, error="2FA code is required.")
        return jsonify(resp.model_dump()), 400

    # This helper accepts both authenticator TOTP codes and recovery codes.
    if not verify_totp_code(pending_user, code):
        logger.warning("[2FA INVALID] user=%s", pending_user)
        time.sleep(random.uniform(0.1, 0.2))
        resp = LoginResponse(
            success=False,
            error="Invalid 2FA or recovery code.",
        )
        return jsonify(resp.model_dump()), 401

    # Promote pending session to full session.
    session.permanent = True
    session["server_run_id"] = SERVER_RUN_ID
    session["user"] = pending_user
    session["is_admin"] = bool(pending_is_admin)

    for key in ("pending_user", "pending_is_admin", "pending_2fa_created_at"):
        session.pop(key, None)

    logger.info("[LOGIN 2FA SUCCESS] user=%s", pending_user)
    resp = LoginResponse(success=True, user=pending_user)
    return jsonify(resp.model_dump()), 200

@app.route("/api/account/2fa/status", methods=["GET"])
@login_required
def twofa_status():
    """Returns the 2FA status for the authenticated user or a target user if admin.

    Behavior:
      - Non-admins: always act on their own account, regardless of query params.
      - Admins: may optionally supply ?username=<target>, otherwise act on self.

    Returns:
      200 OK with:
        {
          "enabled": bool,
          "configured": bool
        }
    """
    session_user = session.get("user")
    is_admin = bool(session.get("is_admin", False))
    if not session_user:
        return jsonify({"success": False, "error": "Not authenticated."}), 401

    # For admins, allow targeting another user via ?username=.
    target_user = session_user
    requested = request.args.get("username")
    if requested and requested != session_user:
        if is_admin:
            target_user = requested
            logger.info(
                "[2FA STATUS ADMIN OVERRIDE] admin=%s target=%s",
                session_user,
                target_user,
            )
        else:
            logger.warning(
                "[2FA STATUS ACCESS DENIED] session_user=%s requested_username=%s",
                session_user,
                requested,
            )
            return jsonify({"success": False, "error": "Forbidden."}), 403

    status = get_2fa_status(target_user)
    resp = TwoFactorStatusResponse(**status)
    return jsonify(resp.model_dump()), 200


@app.route("/api/account/2fa/confirm", methods=["POST"])
@login_required
def twofa_confirm():
    """Confirms 2FA enrollment by verifying a TOTP code.

    Behavior:
      - Non-admins: can only confirm 2FA for their own account.
      - Admins: may optionally provide "username" in JSON to confirm for another user.

    Request JSON:
      {
        "code": "123456",
        // optional for admins:
        // "username": "other_user"
      }

    Returns:
      200 OK with {"success": True} on success.
      400/401/403 with {"success": False, "error": "..."} on error.
    """
    session_user = session.get("user")
    is_admin = bool(session.get("is_admin", False))
    if not session_user:
        return jsonify({"success": False, "error": "Not authenticated."}), 401

    body = request.get_json() or {}
    requested = body.get("username")

    # Resolve target username with admin override semantics
    target_user = session_user
    if requested and requested != session_user:
        if is_admin:
            target_user = requested
            logger.info(
                "[2FA CONFIRM ADMIN OVERRIDE] admin=%s target=%s",
                session_user,
                target_user,
            )
        else:
            logger.warning(
                "[2FA CONFIRM ACCESS DENIED] session_user=%s requested_username=%s",
                session_user,
                requested,
            )
            return jsonify({"success": False, "error": "Forbidden."}), 403

    try:
        data = TwoFactorCodeInput(**body)
    except ValidationError as e:
        logger.warning(
            "[2FA CONFIRM INPUT INVALID] user=%s errors=%s",
            target_user,
            e.errors(),
        )
        return jsonify({"success": False, "error": "Invalid 2FA code format."}), 400

    if not confirm_twofa_enrollment(username=target_user, code=data.code):
        return jsonify(
            {"success": False, "error": "Invalid or expired 2FA code."}
        ), 401

    return jsonify({"success": True}), 200


@app.route("/api/account/2fa/disable", methods=["POST"])
@login_required
def twofa_disable():
    """Disables 2FA for the authenticated user or a target user if admin.

    Behavior:
      - Non-admins: can only disable 2FA for themselves.
      - Admins: may optionally provide "username" in JSON to disable for another user.

    Request JSON:
      {
        // optional for admins:
        // "username": "other_user"
      }

    Returns:
      200 OK with {"success": True} on success.
    """
    session_user = session.get("user")
    is_admin = bool(session.get("is_admin", False))
    if not session_user:
        return jsonify({"success": False, "error": "Not authenticated."}), 401

    body = (request.get_json() or {}) if request.is_json else {}
    requested = body.get("username")

    target_user = session_user
    if requested and requested != session_user:
        if is_admin:
            target_user = requested
            logger.info(
                "[2FA DISABLE ADMIN OVERRIDE] admin=%s target=%s",
                session_user,
                target_user,
            )
        else:
            logger.warning(
                "[2FA DISABLE ACCESS DENIED] session_user=%s requested_username=%s",
                session_user,
                requested,
            )
            return jsonify({"success": False, "error": "Forbidden."}), 403

    disable_twofa(username=target_user)
    logger.info(
        "[2FA DISABLE] actor=%s target=%s admin=%s",
        session_user,
        target_user,
        is_admin,
    )
    return jsonify({"success": True}), 200


@app.route("/api/account/2fa/recovery/regenerate", methods=["POST"])
@login_required
def twofa_regenerate_recovery():
    """Regenerates 2FA recovery codes for the authenticated user or a target user if admin.

    Existing recovery codes are invalidated and replaced by a new set.

    Behavior:
      - Non-admins: can only regenerate their own recovery codes.
      - Admins: may optionally provide "username" in JSON to act on another user.

    Request JSON:
      {
        // optional for admins:
        // "username": "other_user"
      }

    Returns:
      200 OK with:
        {
          "recovery_codes": ["...", ...]
        }
    """
    session_user = session.get("user")
    is_admin = bool(session.get("is_admin", False))
    if not session_user:
        return jsonify({"success": False, "error": "Not authenticated."}), 401

    body = (request.get_json() or {}) if request.is_json else {}
    requested = body.get("username")

    target_user = session_user
    if requested and requested != session_user:
        if is_admin:
            target_user = requested
            logger.info(
                "[2FA RECOVERY REGEN ADMIN OVERRIDE] admin=%s target=%s",
                session_user,
                target_user,
            )
        else:
            logger.warning(
                "[2FA RECOVERY REGEN ACCESS DENIED] session_user=%s requested_username=%s",
                session_user,
                requested,
            )
            return jsonify({"success": False, "error": "Forbidden."}), 403

    codes = regenerate_recovery_codes(username=target_user)
    logger.info(
        "[2FA RECOVERY REGEN] actor=%s target=%s admin=%s",
        session_user,
        target_user,
        is_admin,
    )
    return jsonify({"recovery_codes": codes}), 200



@app.route("/api/admin/users/<username>/2fa/disable", methods=["POST"])
@admin_required
def admin_disable_user_twofa(username: str):
    """Admin override: disable 2FA for a specific user.

    This is a thin wrapper so the existing frontend
    (/api/admin/users/:username/2fa/disable) keeps working.

    Args:
      username: Path parameter of the target user.

    Returns:
      200 OK with {"success": True} on success.
      404 if user does not exist (if your DB helpers raise KeyError).
    """
    actor = session.get("user")

    try:
        # Direct DB-level operation – same helper used by account endpoints
        disable_twofa(username=username)
    except KeyError:
        return jsonify({"success": False, "error": "User not found."}), 404

    logger.info(
        "[ADMIN 2FA DISABLE] admin=%s target=%s",
        actor,
        username,
    )
    return jsonify({"success": True}), 200

@app.route("/api/account/2fa/start", methods=["POST"])
@login_required
def twofa_start():
    """Starts 2FA enrollment for the authenticated user or a target user if admin.

    Behavior:
      - Non-admins: can only start enrollment for themselves.
      - Admins: may optionally provide "username" in JSON to start for another user.

    Request JSON:
      {
        // optional for admins:
        // "username": "other_user"
      }

    Returns:
      200 OK with:
        {
          "success": true,
          "secret": "BASE32SECRET",
          "otpauth_uri": "otpauth://totp/...",
          "recovery_codes": ["...", ...]
        }

      4xx/5xx with:
        {
          "success": false,
          "error": "..."
        }
    """
    session_user = session.get("user")
    is_admin = bool(session.get("is_admin", False))
    if not session_user:
        logger.warning("[2FA START] Not authenticated request.")
        return jsonify({"success": False, "error": "Not authenticated."}), 401

    body = (request.get_json() or {}) if request.is_json else {}
    requested = body.get("username")

    # Resolve target user (admin override allowed)
    target_user = session_user
    if requested and requested != session_user:
        if is_admin:
            target_user = requested
            logger.info(
                "[2FA START ADMIN OVERRIDE] admin=%s target=%s",
                session_user,
                target_user,
            )
        else:
            logger.warning(
                "[2FA START ACCESS DENIED] session_user=%s requested_username=%s",
                session_user,
                requested,
            )
            return jsonify({"success": False, "error": "Forbidden."}), 403

    try:
        enrollment = start_twofa_enrollment(username=target_user)
        # enrollment keys from two_factor_auth.py:
        #   "secret", "provisioning_uri", "recovery_codes"
        secret = enrollment.get("secret")
        provisioning_uri = enrollment.get("provisioning_uri")
        recovery_codes = enrollment.get("recovery_codes", [])

        if not secret or not provisioning_uri:
            logger.error(
                "[2FA START BUG] enrollment missing fields: "
                "has_secret=%s has_provisioning_uri=%s",
                bool(secret),
                bool(provisioning_uri),
            )
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Internal 2FA configuration error.",
                    }
                ),
                500,
            )

    except ValueError as exc:
        logger.warning(
            "[2FA START FAILED] actor=%s target=%s admin=%s error=%s",
            session_user,
            target_user,
            is_admin,
            exc,
        )
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:  # hard guard
        logger.exception(
            "[2FA START ERROR] actor=%s target=%s admin=%s",
            session_user,
            target_user,
            is_admin,
        )
        return jsonify({"success": False, "error": "Unable to start 2FA."}), 500

    logger.info(
        "[2FA START SUCCESS] actor=%s target=%s admin=%s "
        "(secret_len=%s uri_present=%s rc_count=%s)",
        session_user,
        target_user,
        is_admin,
        len(secret),
        bool(provisioning_uri),
        len(recovery_codes),
    )

    # NOTE: we expose `otpauth_uri` for the frontend, but also include the
    # original `provisioning_uri` for any future/legacy callers.
    return (
        jsonify(
            {
                "success": True,
                "secret": secret,
                "otpauth_uri": provisioning_uri,
                "provisioning_uri": provisioning_uri,
                "recovery_codes": recovery_codes,
            }
        ),
        200,
    )

# ─── Admin CRUD Endpoints ───────────────────────────────────────
@app.route("/api/admin/users", methods=["GET"])
@login_required
@admin_required
def get_users():
    return jsonify(list_users())

@app.route("/api/admin/users", methods=["POST"])
@login_required
@admin_required
def create_user():
    data = request.get_json() or {}
    u = data.get("username")
    p = data.get("password")
    a = bool(data.get("is_admin"))
    if not u or not p:
        return jsonify({"error":"username & password required"}), 400
    add_user(u, p, a)
    return jsonify({"success": True}), 201

@app.route("/api/admin/users/<username>", methods=["DELETE"])
@login_required
@admin_required
def delete_user(username):
    remove_user(username)
    return jsonify({"success": True})




@app.route("/loading")
@login_required
def loading():
    # Serve React’s index.html so react SPA handles the loading route
    return send_from_directory(str(BUILD_DIR), "index.html")

@app.route("/process", methods=["POST"])
@login_required
def process():
    try:
        # --- Auth context ---
        user = session.get("user")
        if not user:
            return jsonify({"error": "not authenticated"}), 401

        # --- Validate System ID (int only) ---
        raw_system_id = request.form.get("system_id", "").strip()
        if not raw_system_id.isdigit():
            logger.warning(f"[PROCESS] Invalid system_id={raw_system_id!r}")
            return jsonify({"error": "System ID must be numeric."}), 400
        system_id = int(raw_system_id)

        # --- Validate upload ---
        uploaded = request.files.get("data_file")
        if not uploaded:
            return jsonify({"error": "data file upload is required."}), 400
        if not uploaded.filename.endswith(".csv"):
            return jsonify({"error": "Only CSV files are supported."}), 400

        # --- Create per-user/per-job dir ---
        job_id = secrets.token_urlsafe(16)
        user_dir = WORKING_DIR / secure_filename(user)
        job_dir  = user_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        # --- Save upload ---
        data_path = job_dir / secure_filename(uploaded.filename)
        uploaded.save(data_path)
        logger.info(f"[PROCESS] user={user} system_id={system_id} job_id={job_id} file={data_path.name}")

        # --- File paths for outputs ---
        json_path = job_dir / "test_results.json"
        checklist_template = STATIC_DIR / "DeepDiveTests.xlsx"

        # --- Init SSE buffer for this job (unchanged) ---
        process_output[job_id] = [f"[INFO] Starting processing for system {system_id}..."]

        # --- Register progress sink so the new worker can emit into SSE buffer ---
        register_progress_sink(job_id, lambda line: process_output[job_id].append(line))

        # --- Track job record (unchanged) ---
        jobs[job_id] = JobRecord(
            owner=user,
            system_id=system_id,
            job_dir=job_dir,
            json_path=json_path,
        )

        # --- Launch worker thread (now calls the compat wrapper) ---
        threading.Thread(
            target=generate_checklist,  # compat wrapper from python_process_files
            args=(job_id, system_id, data_path, json_path, job_dir, checklist_template),
            daemon=True
        ).start()

        return jsonify({"success": True, "job_id": job_id}), 202

    except Exception:
        logger.exception("[PROCESS ERROR]")
        return jsonify({"error": "Internal server error occurred during processing."}), 500

@app.route("/stream_output/<job_id>")
@login_required
def stream_output(job_id):
    """
    Server-Sent Events stream for a job's live logs.

    Guarantees kept (frontend contract):
      - Sends initial:
          "retry: 5000\\n\\n"
          sse_format("[INIT] Stream connected")
          ": ping\\n\\n"
      - Emits each appended line from process_output[job_id] via sse_format(...).
      - Triggers completion after either:
          a) a line exactly "[DONE]" (trimmed), OR
          b) a line containing "[SUCCESS] File ready at:", OR
          c) a generated checklist XLSX detected in job_dir
        with a short grace period, then sends:
          sse_format("[DONE]")
          "event: done\\ndata: ok\\n\\n"
      - Heartbeat ": ping\\n\\n" roughly every 10s.
    """
    user = session.get("user")
    rec = jobs.get(job_id)
    if not user or not rec or rec.owner != user:
        return jsonify({"error": "not found"}), 404

    # Tunables kept local to this route for clarity.
    HEARTBEAT_SEC = 10.0
    POLL_INTERVAL_SEC = 0.25
    GRACE_START_SEC = 0.0        # wait before grace if completion seen (kept 0)
    GRACE_DURATION_SEC = 5.0     # total grace time
    FLUSH_CATCHUP_SEC = 2.5      # one extra flush mid-grace

    def file_already_exists() -> bool:
        # Be generous with casing + accommodate the new _PISSM.xlsx as well.
        patterns = ("Checklist_*.xlsx", "CheckList_*.xlsx", "checklist_*.xlsx")
        for pat in patterns:
            if any(rec.job_dir.glob(pat)):
                return True
        return False

    def lines_for(job_id: str):
        # Ensure the buffer exists so we can safely append elsewhere.
        buf = process_output.get(job_id)
        if buf is None:
            buf = []
            process_output[job_id] = buf
        return buf

    def gen():
        last_index = 0
        last_ping = time.time()
        completion_t0 = None
        flushed_mid_grace = False

        # Immediate setup so the client renders quickly.
        yield "retry: 5000\n\n"
        yield sse_format("[INIT] Stream connected")
        yield ": ping\n\n"

        # Event loop
        try:
            while True:
                buf = lines_for(job_id)

                # Stream any new lines since last_index.
                if last_index < len(buf):
                    for ln in buf[last_index:]:
                        # yield per line for immediate paint
                        yield sse_format((ln or "").rstrip())
                    last_index = len(buf)

                # Completion signals (buffer + filesystem)
                has_done = bool(buf and (buf[-1].strip() == "[DONE]"))
                has_success = any("[SUCCESS] File ready at:" in (ln or "") for ln in buf)
                exists = file_already_exists()

                if (has_done or has_success or exists) and completion_t0 is None:
                    completion_t0 = time.time() + GRACE_START_SEC  # optional delay before grace

                # If in grace period, optionally do a catch-up flush, then finalize
                if completion_t0 is not None:
                    now = time.time()
                    elapsed = now - completion_t0

                    # One catch-up flush a bit after we enter grace (if new lines landed)
                    if not flushed_mid_grace and elapsed > FLUSH_CATCHUP_SEC:
                        if last_index < len(buf):
                            for ln in buf[last_index:]:
                                yield sse_format((ln or "").rstrip())
                            last_index = len(buf)
                        flushed_mid_grace = True

                    # End after GRACE_DURATION_SEC
                    if elapsed > GRACE_DURATION_SEC:
                        # Final flush just in case
                        if last_index < len(buf):
                            for ln in buf[last_index:]:
                                yield sse_format((ln or "").rstrip())
                            last_index = len(buf)
                        # Emit completion markers expected by the frontend
                        yield sse_format("[DONE]")
                        yield "event: done\ndata: ok\n\n"
                        break

                # Heartbeat so proxies/browsers don’t buffer indefinitely
                now = time.time()
                if now - last_ping > HEARTBEAT_SEC:
                    yield ": ping\n\n"
                    last_ping = now

                time.sleep(POLL_INTERVAL_SEC)

        except GeneratorExit:
            # Client disconnected; just exit cleanly.
            return
        except Exception as e:
            # If something blows up, write a final line the UI can display.
            yield sse_format(f"[ERROR] stream aborted: {e!r}")
            yield sse_format("[DONE]")
            yield "event: done\ndata: error\n\n"

    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # disable proxy buffering (nginx etc.)
    }
    return Response(stream_with_context(gen()), headers=headers, mimetype="text/event-stream")



 


@app.route("/stream_summary/<system_id>")
@login_required
def stream_summary(system_id):
    def gen():
        last = 0
        seen = set()
        while True:
            lines = process_output.get(system_id, [])
            if last < len(lines):
                for ln in lines[last:]:
                    stripped = ln.strip()

                    # Trigger on "Test X: Description" format
                    match = re.match(r"Test\s+(\d+):\s+(.+)", stripped, re.IGNORECASE)
                    if match:
                        test_num, desc = match.groups()
                        message = f"Running Test {test_num}: {desc}"
                    elif "Deep Dive Testing" in stripped:
                        message = "Beginning Deep Dive Testing..."
                    elif "System has no active workflows" in stripped:
                        message = "No active workflows for this system"
                    elif "Found eMASS Hardware Data" in stripped:
                        message = "eMASS Hardware data retrieved"
                    elif "Found eMASS Software Data" in stripped:
                        message = "eMASS Software data retrieved"
                    elif "Artifacts found for system" in stripped:
                        message = "Artifacts pulled from system"
                    elif "Successfully Pulled Artifact Detail Data" in stripped:
                        message = "Artifact detail data retrieved"
                    elif "***data AITR number and eMASS data ID do NOT Match" in stripped:
                        message = "AITR number mismatch detected"
                    elif "data Report number and eMASS data ID Match" in stripped:
                        message = "AITR numbers match"
                    else:
                        message = None

                    if message and message not in seen:
                        seen.add(message)
                        yield f"data: {message}\n\n"

                last = len(lines)
            if lines and lines[-1].strip() == "[DONE]":
                break
            time.sleep(0.5)
    return Response(gen(), mimetype="text/event-stream")

@app.route("/status/<job_id>")
@login_required
def status(job_id: str):
    """
    Return the completion status for a background checklist job.

    Contract (unchanged):
      - Response JSON shape: {"done": <bool>}
      - "done" becomes true if any of the following is detected:
          (a) the SSE buffer’s last line equals "[DONE]" (trimmed), or
          (b) any SSE line contains "[SUCCESS] File ready at:", or
          (c) a generated checklist workbook exists on disk
                matching "Checklist_*.xlsx" (case-insensitive variants allowed).

    Parameters
    ----------
    job_id : str
        Opaque identifier returned by POST /process. Used to look up the job
        record (owner, job_dir) and its in-memory SSE buffer.

    Returns
    -------
    flask.Response
        200 with {"done": bool} on success.
        404 with {"error": "not found"} if the job is unknown or not owned
        by the current user.

    Security
    --------
    - Enforces ownership: only the user who created the job can query its status.

    Performance
    -----------
    - Performs a small, bounded glob in the job's directory to confirm artifact
      existence. This is cheap given per-job isolation.

    Side Effects
    ------------
    - None. Pure read of in-memory buffer and filesystem.

    Examples
    --------
    GET /status/abc123
    -> {"done": false}
    """
    user = session.get("user")
    rec = jobs.get(job_id)
    if not user or not rec or rec.owner != user:
        return jsonify({"error": "not found"}), 404

    # (1) In-memory completion signals from the SSE buffer.
    lines = process_output.get(job_id, [])
    has_done = bool(lines and lines[-1].strip() == "[DONE]")
    has_success = any(("[SUCCESS] File ready at:" in (ln or "")) for ln in lines)

    # (2) Filesystem completion signal: presence of a generated checklist workbook.
    #     Be liberal with pattern casing to accommodate legacy differences.
    patterns = ("Checklist_*.xlsx", "CheckList_*.xlsx", "checklist_*.xlsx")
    file_exists = any(rec.job_dir.glob(pat) for pat in patterns)

    done = has_done or has_success or file_exists
    return jsonify({"done": done})

@app.route("/reporting_json/<job_id>")
@login_required
def get_reporting_json(job_id: str):
    """
    Serve the normalized reporting payload for a completed job.

    Contract (unchanged):
      • 200 -> JSON body is exactly the contents of <job_dir>/latest_results.json
      • 404 -> {"error": "not found"} if job is unknown/not owned OR file missing
      • 500 -> {"error": "<message>"} on unexpected read/parse failures
    """
    try:
        current_user = session.get("user")
        job_rec = jobs.get(job_id)

        if not current_user or not job_rec or job_rec.owner != current_user:
            return jsonify({"error": "not found"}), 404

        reporting_path = job_rec.job_dir / "latest_results.json"
        if not reporting_path.exists():
            return jsonify({"error": "not found"}), 404

        # Robust read: tolerate race with writer by retrying JSON parse briefly
        attempts = 3
        delay_sec = 0.06  # ~60ms per retry
        for attempt in range(attempts):
            try:
                with open(reporting_path, encoding="utf-8") as fh:
                    payload = json.load(fh)
                return jsonify(payload)
            except JSONDecodeError as exc:
                # Likely a partial read right after writer rotated; brief retry
                if attempt < attempts - 1:
                    time.sleep(delay_sec)
                    continue
                # Last attempt failed — surface a clean error
                return jsonify({"error": f"invalid json: {exc}"}), 500

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/reporting")
@login_required
def get_reporting_json_qp():
    """
    Query-parameter alias for /reporting_json/<job_id>.

    Purpose
    -------
    Some clients call /reporting?job_id=... instead of the path-param form.
    This thin adapter preserves the exact response/contract by delegating to
    `get_reporting_json`.

    Request
    -------
    GET /reporting?job_id=<opaque id>

    Returns
    -------
    flask.Response
        Whatever `get_reporting_json(job_id)` would return.
    """
    job_id = (request.args.get("job_id") or "").strip()
    if not job_id:
        return jsonify({"error": "missing job_id"}), 400
    return get_reporting_json(job_id)

@app.route("/download")
@login_required
def download():
    user = session.get("user")
    job_id = request.args.get("job_id", "")

    rec = jobs.get(job_id)
    if not user or not rec or rec.owner != user:
        return "File not found", 404

    # Look for the generated checklist in the job dir
    candidates = list(rec.job_dir.glob("Checklist_*.xlsx"))
    if not candidates:
        return "File not ready", 404

    path = candidates[0]
    resp = send_file(path, as_attachment=True)

    # Optional cleanup: remove job artifacts after download
    try:
        for p in rec.job_dir.glob("*"):
            try:
                p.unlink()
            except Exception:
                pass
        rec.job_dir.rmdir()
    except Exception as e:
        logger.warning(f"[DOWNLOAD CLEANUP] job_id={job_id} cleanup issue: {e}")

    # Clear registries
    jobs.pop(job_id, None)
    process_output.pop(job_id, None)

    return resp

# ─── Admin Log Endpoints ─────────────────────────────────────────
@app.route("/api/admin/logs/info", methods=["GET"])
@login_required
@admin_required
def admin_logs_info():
    path = get_logfile_path(logger)
    try:
        stat = path.stat()
        return jsonify({
            "path": str(path),
            "exists": True,
            "size_bytes": stat.st_size,
            "mtime": int(stat.st_mtime),
        })
    except FileNotFoundError:
        return jsonify({
            "path": str(path),
            "exists": False,
            "size_bytes": 0,
            "mtime": None,
        })
    
@app.route("/api/report/<job_id>")
@login_required
def get_report_json(job_id):
    rec = jobs.get(job_id)
    if not rec:
        return jsonify({"error": "job not found"}), 404

    results_path = rec.job_dir / f"{job_id}_results.json"
    if not results_path.exists():
        return jsonify({"error": "report not available yet"}), 404

    try:
        with open(results_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        logger.exception(f"[REPORT ERROR] Failed to load {results_path}")
        return jsonify({"error": "could not read report"}), 500


@app.route("/api/admin/logs/tail", methods=["GET"])
@login_required
@admin_required
def admin_logs_tail():
    # query: bytes (default 200_000), max 2_000_000
    nbytes = _clamp_int(request.args.get("bytes", 200_000),
                        default=200_000, min_v=1_000, max_v=2_000_000)

    path = get_logfile_path(logger)
    if not path.exists():
        return jsonify({"path": str(path), "exists": False, "lines": []})

    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        start = max(0, size - nbytes)
        f.seek(start, os.SEEK_SET)
        chunk = f.read()

    text = chunk.decode("utf-8", errors="replace")
    lines = text.splitlines()
    # include where this slice starts in the file (approx line no unknown)
    return jsonify({
        "path": str(path),
        "exists": True,
        "size_bytes": size,
        "slice_start_byte": start,
        "returned_bytes": len(chunk),
        "line_count": len(lines),
        "lines": lines[-5000:],  # keep response size sane
        "truncated": len(lines) > 5000
    })

@app.route("/api/admin/logs/search", methods=["POST"])
@login_required
@admin_required
def admin_logs_search():
    """
    Safe search: supports only glob-like wildcards * and ? (no raw regex).
    Body JSON:
      pattern: str (required)
      case_sensitive: bool (optional)
      max_bytes: int <= 2_000_000 (optional)
      max_matches: int <= 1000 (optional)
      context: int <= 5 (optional)
      per_line_limit: int <= 20000 (optional)
      timeout_s: float <= 2.0 (optional)
    """
    data = request.get_json(silent=True) or {}
    pattern = (data.get("pattern") or "").strip()
    if not pattern:
        return jsonify({"error": "pattern is required"}), 400

    case_sensitive = bool(data.get("case_sensitive", False))
    max_bytes      = _clamp_int(data.get("max_bytes", 2_000_000),
                                default=2_000_000, min_v=10_000, max_v=2_000_000)
    max_matches    = _clamp_int(data.get("max_matches", 200),
                                default=200, min_v=1, max_v=1000)
    context        = _clamp_int(data.get("context", 0),
                                default=0, min_v=0, max_v=5)
    per_line_limit = _clamp_int(data.get("per_line_limit", 20_000),
                                default=20_000, min_v=500, max_v=20_000)
    # allow a small bump but keep it tight
    try:
        timeout_s = float(data.get("timeout_s", 1.0))
    except Exception:
        timeout_s = 1.0
    timeout_s = max(0.05, min(2.0, timeout_s))

    try:
        hits = search_log(
            pattern,
            use_glob=True,  # stays safe (no raw regex)
            case_sensitive=case_sensitive,
            max_bytes=max_bytes,
            max_matches=max_matches,
            context=context,
            per_line_limit=per_line_limit,
            timeout_s=timeout_s,
            logger=logger,
        )
        return jsonify({
            "pattern": pattern,
            "case_sensitive": case_sensitive,
            "hits": hits,
            "hit_count": len(hits),
            "truncated": len(hits) >= max_matches
        })
    except ValueError as ve:
        # e.g., pattern too long
        return jsonify({"error": str(ve)}), 400
    except Exception:
        logger.exception("[LOG SEARCH ERROR]")
        return jsonify({"error": "log search failed"}), 500

@app.route("/api/admin/logs/download", methods=["GET"])
@login_required
@admin_required
def admin_logs_download():
    """
    Download the full current log file.
    """
    path = get_logfile_path(logger)
    if not path.exists():
        return jsonify({"error": "log file not found", "path": str(path)}), 404
    # Let the browser download; small files only, logs are rotated externally if needed
    return send_file(path, as_attachment=True, download_name=path.name)

@app.route("/api/account/password", methods=["POST"])
@login_required
def change_password_self():
    """
    Change password for the currently authenticated user.
    Body JSON:
      {
        "current_password": "...",   # required
        "new_password": "...",       # required
        "username": "optional"       # if supplied and != session user => suspicious
      }
    """
    ip = request.remote_addr or "unknown"
    session_user = session.get("user")

    body = request.get_json(silent=True) or {}
    target_user = (body.get("username") or session_user or "").strip()
    current_pw = (body.get("current_password") or "")
    new_pw = (body.get("new_password") or "")

    # If someone tries to change another user's password via this endpoint, log & block.
    if target_user != session_user:
        logger.warning(
            "[SECURITY][PW CHANGE] user=%s ip=%s attempted to change password for '%s' (denied)",
            session_user, ip, target_user
        )
        return jsonify({"success": False, "error": "forbidden"}), 403

    # Basic input checks (do NOT log password contents)
    if not current_pw or not new_pw:
        logger.warning("[PW CHANGE] user=%s ip=%s missing fields", session_user, ip)
        return jsonify({"success": False, "error": "current_password and new_password required"}), 400

    # Minimal password policy (tweak as needed; do not log contents)
    if len(new_pw) < 8:
        logger.warning("[PW CHANGE] user=%s ip=%s rejected new password (policy: too short)", session_user, ip)
        return jsonify({"success": False, "error": "password too short"}), 400

    # Attempt change
    ok = change_own_password(session_user, current_pw, new_pw)
    if ok:
        logger.info("[PW CHANGE] user=%s ip=%s success", session_user, ip)
        return jsonify({"success": True})
    else:
        # Could be bad current pw or DB error; message stays generic
        logger.warning("[PW CHANGE] user=%s ip=%s failed (bad current or error)", session_user, ip)
        # Small jitter to make timing less oracle-y
        time.sleep(random.uniform(0.08, 0.22))
        return jsonify({"success": False, "error": "password change failed"}), 400
  


def start_cleanup_worker_singleton(lock_path: str = "/tmp/atoaas_cleanup.lock"):
    import os, time, shutil, threading, errno
    try:
        import fcntl
    except Exception as e:
        logger.warning("[CLEANUP] fcntl not available (%s); skipping singleton lock.", e)
        return

    TTL = int(os.getenv("JOB_TTL_SECONDS", 3 * 24 * 3600))
    INTERVAL = int(os.getenv("CLEAN_INTERVAL_SECONDS", 6 * 3600))

    def _fmt_bytes(n: int) -> str:
        if n >= 1_000_000: return f"{n/1_000_000:.1f} MB"
        if n >= 1_000: return f"{n/1_000:.1f} KB"
        return f"{n} B"

    def _dir_size_bytes(p: Path) -> int:
        total = 0
        for f in p.rglob("*"):
            try:
                if f.is_file():
                    total += f.stat().st_size
            except Exception:
                pass
        return total

    def _dir_latest_mtime(p: Path) -> float:
        try:
            latest = p.stat().st_mtime
            for f in p.rglob("*"):
                try:
                    m = f.stat().st_mtime
                    if m > latest:
                        latest = m
                except Exception:
                    pass
            return latest
        except Exception:
            return time.time()

    def cleanup_now() -> int:
        now = time.time()
        removed = 0
        bytes_freed = 0
        started = time.time()

        if not WORKING_DIR.exists():
            logger.info("[CLEANUP] Sweep: workdir missing (%s). Nothing to do.", WORKING_DIR)
            return 0

        active = set(jobs.keys())
        logger.info("[CLEANUP] Sweep started (ttl=%ds, dir=%s, active_jobs=%d)", TTL, WORKING_DIR, len(active))

        for user_dir in WORKING_DIR.iterdir():
            if not user_dir.is_dir():
                continue
            for job_dir in user_dir.iterdir():
                if not job_dir.is_dir():
                    continue

                job_id = job_dir.name
                if job_id in active:
                    logger.debug("[CLEANUP] Skipping active job '%s' (user=%s).", job_id, user_dir.name)
                    continue

                age = now - _dir_latest_mtime(job_dir)
                if age >= TTL:
                    try:
                        size = _dir_size_bytes(job_dir)
                        shutil.rmtree(job_dir)
                        process_output.pop(job_id, None)
                        removed += 1
                        bytes_freed += size
                        logger.info("[CLEANUP] Removed stale job '%s' (user=%s, age=%ds, freed=%s)",
                                    job_id, user_dir.name, int(age), _fmt_bytes(size))
                    except Exception as e:
                        logger.warning("[CLEANUP] Failed to remove '%s': %s", job_dir, e)

        dur = time.time() - started
        if removed:
            logger.info("[CLEANUP] Sweep complete: removed=%d, freed=%s, took=%.2fs",
                        removed, _fmt_bytes(bytes_freed), dur)
        else:
            logger.info("[CLEANUP] Sweep complete: nothing to remove (took=%.2fs)", dur)

        return removed

    def _worker():
        logger.info("[CLEANUP] Worker starting (interval=%ds, ttl=%ds, dir=%s)", INTERVAL, TTL, WORKING_DIR)
        time.sleep(10)
        while True:
            try:
                cleanup_now()
            except Exception:
                logger.exception("[CLEANUP] Unhandled error during cleanup")
            logger.debug("[CLEANUP] Sleeping for %ds…", INTERVAL)
            time.sleep(INTERVAL)

    def _start_worker_once():
        if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
            logger.info("[CLEANUP] Dev reloader parent process: skipping worker start.")
            return

        lock_fd = None
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno in (errno.EACCES, errno.EAGAIN):
                logger.info("[CLEANUP] Another process holds %s; not starting in PID %s.", lock_path, os.getpid())
                if lock_fd is not None:
                    os.close(lock_fd)
                return
            logger.exception("[CLEANUP] Could not acquire lock %s: %s", lock_path, e)
            if lock_fd is not None:
                os.close(lock_fd)
            return

        setattr(app, "_cleanup_lock_fd", lock_fd)

        if getattr(app, "_cleanup_worker_started", False):
            return
        setattr(app, "_cleanup_worker_started", True)
        threading.Thread(target=_worker, daemon=True).start()
        logger.info("[CLEANUP] Worker thread started in PID %s (lock=%s).", os.getpid(), lock_path)

    # Start immediately instead of using before_first_request (Flask 3.x)
    _start_worker_once()

    globals()["cleanup_old_jobs"] = cleanup_now

# ─── Helpers for "latest summary" endpoint ─────────────────────────────────────
def _user_job_dirs(user: str) -> List[Path]:
    """Return all job dirs for a user, newest first by mtime of a checklist or dir."""
    user_dir = WORKING_DIR / secure_filename(user)
    if not user_dir.exists():
        print(f"[api_summary_latest] no user_dir: {user_dir}", flush=True)
        return []
    scored: List[Tuple[float, Path]] = []
    for jd in user_dir.iterdir():
        if not jd.is_dir():
            continue
        xl = sorted(
            list(jd.glob("Checklist_*.xlsx")) + list(jd.glob("CheckList_*.xlsx")),
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        if xl:
            ts = xl[0].stat().st_mtime
        else:
            rj = sorted(
                list(jd.glob("*_results.json")) + list(jd.glob("latest_results.json")),
                key=lambda p: p.stat().st_mtime, reverse=True
            )
            ts = rj[0].stat().st_mtime if rj else jd.stat().st_mtime
        scored.append((ts, jd))
    scored.sort(key=lambda t: t[0], reverse=True)
    out = [jd for _, jd in scored]
    print(f"[api_summary_latest] found {len(out)} job dirs under {user_dir}", flush=True)
    return out


def resolve_job_dir(user: str, job_hint: Optional[str]) -> Optional[Path]:
    """If job_hint is provided, pick that job dir; otherwise newest finished one."""
    all_dirs = _user_job_dirs(user)
    if not all_dirs:
        return None
    if job_hint:
        cand = WORKING_DIR / secure_filename(user) / secure_filename(job_hint)
        if cand.exists() and cand.is_dir():
            print(f"[api_summary_latest] using hinted job dir: {cand}", flush=True)
            return cand
        print(f"[api_summary_latest] hinted job dir not found: {cand}", flush=True)
    # fallback: newest dir that has a checklist
    for jd in all_dirs:
        xl = sorted(
            list(jd.glob("Checklist_*.xlsx")) + list(jd.glob("CheckList_*.xlsx")),
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        if xl:
            print(f"[api_summary_latest] using newest finished dir: {jd}", flush=True)
            return jd
    # if none have a checklist, just return newest dir
    print(f"[api_summary_latest] no finished checklists; using newest dir: {all_dirs[0]}", flush=True)
    return all_dirs[0]



def _parse_system_id_from_outputs(job_dir: Path) -> Optional[int]:
    # Try from checklist filename
    for p in job_dir.glob("Checklist_*.xlsx"):
        m = re.search(r"Checklist_(\d+)\.xlsx$", p.name, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    # Fallback: from live registry if present
    job_id = job_dir.name
    rec = jobs.get(job_id)
    if rec:
        return int(rec.system_id)
    return None


def _tabularize_json(obj) -> Optional[pd.DataFrame]:
    """Coerce common JSON shapes into a DataFrame and normalize columns for the UI."""
    import pandas as pd
    import re

    def _classify(text: str) -> str:
        s = (text or "").strip().lower()
        if re.search(r"\bpass(?:ed)?\b|ok|success|compliant|green|true", s):
            return "pass"
        if re.search(r"\bfail(?:ed)?\b|non\s*compliant|error|critical|red|false", s):
            return "fail"
        if re.search(r"\bconcern|warning|warn|yellow|partial|medium|high\b", s):
            return "concern"
        if re.search(r"^\s*$|^n/?a$|^na$|not applicable|skip(?:ped)?", s):
            return "neutral"
        # conservative default
        return "concern"

    def _ensure_status_cols(df: pd.DataFrame) -> pd.DataFrame:
        # if no obvious status/result column, derive 'result' from test_description
        lower = {str(c).lower(): c for c in df.columns}
        has_status = any(k in lower for k in ("result", "status", "outcome", "test_status"))
        if not has_status and "test_description" in lower:
            cdesc = lower["test_description"]
            df["result"] = df[cdesc].astype("string").fillna("").map(_classify)
        return df

    # Case 1: list[dict]  (what pwsh is writing: [{"Cell": "...", "Value": "..."}])
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        df = pd.DataFrame(obj)

        # Normalize column names (case-insensitive)
        rename_map = {}
        for c in list(df.columns):
            cl = str(c).lower()
            if cl == "value":
                rename_map[c] = "test_description"
            elif cl == "cell":
                rename_map[c] = "cell"
        if rename_map:
            df = df.rename(columns=rename_map)

        df = _ensure_status_cols(df)
        return df

    # Case 2: {"rows": [...], "columns": [...]}
    if isinstance(obj, dict):
        rows = obj.get("rows")
        cols = obj.get("columns")
        if isinstance(rows, list):
            df = pd.DataFrame(rows, columns=cols) if isinstance(cols, list) else pd.DataFrame(rows)
            # Normalize names if present
            for c in list(df.columns):
                if str(c).lower() == "value":
                    df = df.rename(columns={c: "test_description"})
            df = _ensure_status_cols(df)
            return df

    # Unknown shape
    return None



def _load_best_dataframe(job_dir: Path) -> tuple[pd.DataFrame, str]:
    """Prefer results JSON table; else fall back to the uploaded CSV."""
    # 1) Prefer results JSON (latest_results.json or *_results.json)
    json_candidates = []
    lr = job_dir / "latest_results.json"
    if lr.exists():
        json_candidates.append(lr)
    json_candidates += sorted(job_dir.glob("*_results.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for jp in json_candidates:
        try:
            with open(jp, "r", encoding="utf-8") as f:
                data = json.load(f)
            df = _tabularize_json(data)
            if df is not None and not df.empty:
                return df, str(jp)
        except Exception:
            continue

    # 2) Fallback to newest CSV in the job dir
    csvs = sorted(job_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if csvs:
        try:
            df = pd.read_csv(csvs[0])
            return df, str(csvs[0])
        except Exception:
            pass

    # 3) Nothing usable; return empty
    return pd.DataFrame(), "(none)"


# --- super-verbose console printing helpers -------------------


def p(msg: str):
    print(msg, flush=True)

def df_preview(df: pd.DataFrame, rows: int = 10) -> dict:
    try:
        return {
            "shape": [int(df.shape[0]), int(df.shape[1])],
            "columns": [str(c) for c in list(df.columns)[:50]],
            "head": df.head(rows).to_dict(orient="records"),
        }
    except Exception as e:
        p(f"[api_summary_latest] df_preview error: {e}")
        return {"shape": [0, 0], "columns": [], "head": []}

def json_preview(obj: dict, max_chars: int = 20000) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2)
        return s if len(s) <= max_chars else (s[:max_chars] + "\n...<truncated>...")
    except Exception as e:
        return f"<failed to serialize preview: {e}>"

# add near the other helpers (top of file)
_ROW_RE = re.compile(r"^([A-Z]+)(\d+)$")

def _norm_status_from_text(s: str) -> str:
    """Map the long message in col G to PASS/FAIL/CONCERN/N/A."""
    if not s:
        return None
    t = str(s).strip().lower()
    if "pass" in t:
        return "PASS"
    if "fail" in t:
        return "FAIL"
    if "concern" in t or "manual" in t or "needs review" in t or "warning" in t:
        return "CONCERN"
    if "not applicable" in t or "n/a" in t or "na" == t:
        return "N/A"
    return None  # unknown

def _cells_colG_to_row_status(cell_items: list[dict]) -> pd.DataFrame:
    """
    From [{Cell:'G140', Value:'TEST RESULT: PASS ...'}, ...] produce a
    DataFrame indexed by excel row with columns: ['Result','Note'].
    """
    rows = {}
    for it in cell_items or []:
        cell = str(it.get("Cell") or "")
        m = _ROW_RE.match(cell)
        if not m:
            continue
        col, row = m.group(1), int(m.group(2))
        if col != "G":
            continue
        val = it.get("Value")
        st = _norm_status_from_text(val)
        rows[row] = {"Result": st, "Note": None if val is None else str(val)}
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "excel_row"
    return df

def _add_excel_row_numbers_to_template(xlsx_path: Path) -> tuple[pd.DataFrame, int]:
    """
    Parse P-ISSM_Checklist and add a 1-based 'excel_row' that matches real sheet rows,
    so we can merge with cell coordinates (e.g., G140).
    Returns (df, data_start_row).
    """
    raw = pd.read_excel(xlsx_path, sheet_name="P-ISSM_Checklist", header=None)
    hdr = _find_header_row(raw)
    if hdr is None:
        return pd.DataFrame(), 0
    df = _parse_p_issm_checklist(xlsx_path)
    if df.empty:
        return df, 0
    # header row in Excel is 1-based; data start is next row
    excel_header_row = hdr + 1
    data_start_row = excel_header_row + 1
    df.insert(0, "excel_row", range(data_start_row, data_start_row + len(df)))
    return df, data_start_row




# =============================================================================
# Helper functions (mirror client logic where appropriate)
# =============================================================================

_STATUS_KEYS_CANONICAL = ["Result", "result", "status", "outcome", "test_status"]


def normalize_status_value(value: Any) -> str:
    """
    Convert a free-form status value into one of: 'pass', 'fail', 'concern', 'neutral'.

    This mirrors the client-side normalization to keep server and UI in sync.

    Args:
        value: Arbitrary value found in a row/column that may indicate status.

    Returns:
        str: One of {'pass', 'fail', 'concern', 'neutral'}.
    """
    if value is None:
        return "neutral"

    if isinstance(value, bool):
        return "pass" if value else "fail"

    s = str(value).strip().lower()
    if not s or s in {"n/a", "na", "skip", "skipped", "none", "null"}:
        return "neutral"

    if any(tok in s for tok in ["pass", "ok", "success", "compliant", "true", "green"]):
        return "pass"
    if any(tok in s for tok in ["fail", "non compliant", "not compliant", "false", "red", "error", "critical"]):
        return "fail"
    if any(tok in s for tok in ["concern", "warning", "warn", "yellow", "partial", "medium", "high"]):
        return "concern"

    # When in doubt, treat as a 'concern' (not neutral but not an explicit pass/fail)
    return "concern"


def pick_first_matching_key(columns: List[str], candidates: List[str]) -> Optional[str]:
    """
    Return the first column name from 'columns' that matches any of 'candidates' (case-insensitive).

    Args:
        columns: Available column names.
        candidates: Candidate names in order of preference.

    Returns:
        The original column name if a match is found; otherwise None.
    """
    lower_map = {c.lower(): c for c in columns}
    for cand in candidates:
        hit = lower_map.get(cand.lower())
        if hit:
            return hit
    return None




def infer_system_id_from_artifacts(job_directory: Path) -> Optional[int]:
    """
    Infer the system ID from artifacts in a job directory.

    Priority:
      1) 'latest_results.json' row field 'system_id' (if present)
      2) First 'Checklist_<system_id>*.xlsx' filename pattern
      3) None (unknown)

    Args:
        job_directory: Path to the job's artifact folder.

    Returns:
        int | None: The inferred system ID, or None if it cannot be determined.
    """
    try:
        results_json_path = job_directory / "latest_results.json"
        if results_json_path.exists():
            rows = json.loads(results_json_path.read_text(encoding="utf-8"))
            if isinstance(rows, list) and rows:
                raw_id = rows[0].get("system_id")
                if isinstance(raw_id, int) or (isinstance(raw_id, str) and raw_id.isdigit()):
                    return int(raw_id)
    except Exception:
        pass

    try:
        for xlsx_path in sorted(job_directory.glob("Checklist_*.xlsx")):
            # Example filename: "Checklist_101.xlsx" → system_id = 101
            name = xlsx_path.stem
            parts = name.split("_", 1)
            if len(parts) == 2 and parts[1].isdigit():
                return int(parts[1])
    except Exception:
        pass

    return None


def load_engine_or_csv_dataframe(job_directory: Path) -> Tuple[pd.DataFrame, str]:
    """
    Load a tabular payload for the given job directory.

    Preference order:
      1) Engine-normalized 'latest_results.json'
      2) The first uploaded '*.csv' found in the directory
      3) Empty DataFrame as a last resort

    Args:
        job_directory: Path to the job folder.

    Returns:
        (DataFrame, source_label): Tuple with the DataFrame and a human-readable source string.
    """
    # 1) Engine output (normalized, preferred)
    results_json_path = job_directory / "latest_results.json"
    if results_json_path.exists():
        try:
            rows = json.loads(results_json_path.read_text(encoding="utf-8"))
            if isinstance(rows, list):
                return pd.DataFrame(rows), "latest_results.json"
        except Exception:
            # Fall through to CSV
            pass

    # 2) Uploaded CSV fallback
    csv_candidates = sorted(job_directory.glob("*.csv"))
    if csv_candidates:
        try:
            return pd.read_csv(csv_candidates[0]), csv_candidates[0].name
        except Exception:
            pass

    # 3) Nothing usable
    return pd.DataFrame(), "(empty)"


def resolve_job_directory_for_user(current_user: str, job_id_hint: Optional[str]) -> Optional[Path]:
    """
    Resolve the correct job directory for a user.

    If `job_id_hint` is provided, it must:
      - exist in the in-memory `jobs` registry, and
      - belong to `current_user`.

    If no hint is provided:
      - pick the most recent *finished* job in the user's working folder,
        where "finished" means the folder contains either:
          * 'latest_results.json', or
          * at least one 'Checklist_*.xlsx' (or 'CheckList_*.xlsx').

    Args:
        current_user: Username from session.
        job_id_hint: Optional specific job ID to resolve.

    Returns:
        Path | None: The resolved job directory or None if nothing qualifies.
    """
    if job_id_hint:
        record = jobs.get(job_id_hint)
        if record and record.owner == current_user and record.job_dir.exists():
            return record.job_dir
        return None

    user_folder = WORKING_DIR / secure_filename(current_user)
    if not user_folder.exists():
        return None

    finished_candidates: List[Tuple[float, Path]] = []
    for subdir in user_folder.iterdir():
        if not subdir.is_dir():
            continue
        has_json = (subdir / "latest_results.json").exists()
        has_xlsx = bool(list(subdir.glob("Checklist_*.xlsx")) or list(subdir.glob("CheckList_*.xlsx")))
        if not (has_json or has_xlsx):
            continue

        try:
            # Use the latest mtime among directory contents as recency
            mtimes = [p.stat().st_mtime for p in [subdir, *subdir.glob("*")]]
            finished_candidates.append((max(mtimes), subdir))
        except Exception:
            continue

    if not finished_candidates:
        return None

    finished_candidates.sort(key=lambda t: t[0], reverse=True)
    return finished_candidates[0][1]


def dataframe_payload_to_dict(df_payload: "DataFramePayload") -> Dict[str, Any]:
    """
    Safely convert a DataFramePayload to a plain Python dict.

    Handles common model styles:
      - Pydantic v2 (model_dump)
      - Pydantic v1 (dict)
      - Custom classes exposing as_dict()

    Args:
        df_payload: The payload object returned by DataFramePayload.from_dataframe(...).

    Returns:
        dict: Plain dict representation suitable for jsonify().
    """
    for accessor in ("as_dict", "model_dump", "dict"):
        fn = getattr(df_payload, accessor, None)
        if callable(fn):
            try:
                out = fn()
                if isinstance(out, dict):
                    return out
            except Exception:
                pass

    # Conservative fallback (best-guess projection)
    return {
        "system_id": getattr(df_payload, "system_id", None),
        "source": getattr(df_payload, "source", ""),
        "shape": getattr(df_payload, "shape", [0, 0]),
        "columns": getattr(df_payload, "columns", []),
        "dtypes": getattr(df_payload, "dtypes", {}),
        "records": getattr(df_payload, "records", []),
    }


# =============================================================================
# Route
# =============================================================================

@app.get("/api/summary/latest")
@login_required
def api_summary_latest():
    """Return the latest scan summary for the logged-in user (optionally by job_id).

    This endpoint surfaces a compact snapshot used by the Reporting UI. It prefers
    the engine-emitted JSON (`latest_results.json`) and falls back to the flat
    CSV when needed. The response includes a **top-level** `system_name` field
    (best-effort), in addition to the tabular payload.

    Response body (backward compatible; new field `system_name` is optional):
      {
        "job_id": string,
        "system_id": number | null,
        "system_name": string | null,                     
        "ran_at_epoch": number,
        "ran_at_iso": string,
        "dataframe": { "system_id", "source", "shape", "columns", "dtypes", "records" },
        "dataframe_truncated": boolean,
        "readiness": {
          "status_column": string | null,
          "pass": number, "fail": number, "concern": number, "neutral": number,
          "considered": number, "score_pct": number | null,
          "formula": "score = pass / (pass + fail + concern)"
        }
      }

    Query parameters:
      job_id: Optional job identifier. When provided, must belong to the caller.
      limit : Optional integer row cap for the dataframe payload (default 2000; max 10000).

    Security:
      - Enforces job ownership via the in-memory `jobs` registry and per-user folders.

    Behavior:
      - Prefers `latest_results.json` generated by the engine; falls back to the uploaded CSV.
      - Timestamps derive from the newest Checklist_*.xlsx if present; otherwise the job folder mtime.

    Returns:
      200 on success with the summary JSON.
      401 if unauthenticated.
      404 if no finished job is available.
      500 on unexpected errors.
    """
    current_user = session.get("user")
    if not current_user:
        return jsonify({"error": "not authenticated"}), 401

    job_id_hint = request.args.get("job_id") or None

    try:
        # Resolve the caller's most-recent finished job (or a specific job via ?job_id=).
        job_dir = resolve_job_directory_for_user(current_user, job_id_hint)
        if job_dir is None:
            return jsonify({"error": "no finished jobs found"}), 404

        # Determine the run timestamp from the most recent checklist workbook; fall back to dir mtime.
        xlsx_candidates = sorted(
            list(job_dir.glob("Checklist_*.xlsx")) + list(job_dir.glob("CheckList_*.xlsx")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if xlsx_candidates:
            ran_epoch = xlsx_candidates[0].stat().st_mtime
        else:
            ran_epoch = job_dir.stat().st_mtime
        ran_iso = datetime.utcfromtimestamp(ran_epoch).isoformat(timespec="seconds") + "Z"

        # Identify job/system.
        job_id_resolved = job_dir.name
        system_id_resolved = infer_system_id_from_artifacts(job_dir) or None

        # Load the tabular data (engine JSON preferred, CSV as fallback).
        df, df_source = load_engine_or_csv_dataframe(job_dir)

        # Enforce a reasonable row limit to keep payload sizes predictable.
        try:
            row_limit = int(request.args.get("limit", 2000))
            row_limit = max(1, min(row_limit, 10000))
        except Exception:
            row_limit = 2000

        # Serialize the dataframe to the standard payload, honoring the row cap.
        try:
            df_payload = DataFramePayload.from_dataframe(
                df if df is not None else pd.DataFrame(),
                system_id=system_id_resolved or 0,
                source=df_source,
                limit=row_limit,  # if unsupported by the model, we trim manually below
            )
        except Exception:
            # Manual trim fallback when `limit` isn't supported by the serializer.
            if df is None:
                df = pd.DataFrame()
            df_trimmed = df.head(row_limit).copy()
            df_payload = DataFramePayload.from_dataframe(
                df_trimmed,
                system_id=system_id_resolved or 0,
                source=df_source,
            )

        # Compute readiness/summary (neutral rows excluded from score).
        is_truncated = bool(df is not None and df.shape[0] > getattr(df_payload, "shape", [0])[0])
        readiness = compute_readiness_summary(df if df is not None else pd.DataFrame())

        # Best-effort extraction of a human-readable system name from the dataframe.
        # We look for common header variants and take the first non-empty value in row 0.
        def _extract_system_name(payload: DataFramePayload) -> Optional[str]:
            try:
                cols = getattr(payload, "columns", []) or []
                records = getattr(payload, "records", []) or []
                if not cols or not records:
                    return None
                lower = {c.lower(): c for c in cols}
                for candidate in ("system name", "systemname", "system_name", "name", "item name", "itemname"):
                    col = lower.get(candidate)
                    if col:
                        raw = str(records[0].get(col, "")).strip()
                        if raw:
                            return raw
                return None
            except Exception:
                return None

        system_name = _extract_system_name(df_payload)

        # Assemble the response (non-breaking addition of `system_name`).
        body = {
            "job_id": job_id_resolved,
            "system_id": system_id_resolved,
            "system_name": system_name,  # NEW: optional, may be null
            "ran_at_epoch": int(ran_epoch),
            "ran_at_iso": ran_iso,
            "dataframe": dataframe_payload_to_dict(df_payload),
            "dataframe_truncated": is_truncated,
            "readiness": readiness,
        }
        return jsonify(body)

    except Exception as exc:
        # Log for operators; return a succinct error to the client.
        print("[api_summary_latest] ERROR:", exc, flush=True)
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 500


def _has_csv_on_disk(path_str: Optional[str]) -> bool:
    """
    True if the path exists and is a regular file; tolerates None/empty.
    """
    if not path_str:
        return False
    p = Path(path_str)
    return p.exists() and p.is_file()



@app.route("/api/admin/systems", methods=["GET"])
@login_required
@admin_required
def admin_list_systems():
    """
    List all systems currently tracked in the SystemCsv database, including the scan
    policy each system is associated with (if any).

    Returns:
        flask.Response:
            JSON array of SystemSummary objects. Each element includes:
              - system_id (int): Numeric system identifier.
              - time_added (str): ISO-8601 timestamp derived from `updated_at`.
              - last_scanned (Optional[str]): ISO-8601 timestamp of last scan, or null.
              - has_csv (bool): Whether the CSV path exists on disk.
              - scan_policy (Optional[str]): Human-readable scan policy name, or null.

    Design:
        - Pulls all rows in a single SELECT (no N+1 access pattern).
        - Filesystem existence checks are done per row; acceptable for small-to-medium lists.
        - The DB helper `list_all_systems()` is expected to return the policy *name* in
          the `scan_policy` field (or None). If it returns a policy ID instead, join and
          alias to name in the helper.

    Raises:
        None directly. Returns a 200 JSON payload or a 500 propagated by Flask if an
        unexpected exception bubbles up.

    Notes:
        Keep the wire format stable—additive changes only. Downstream UI depends on
        these keys.
    """
    with get_session() as session:
        # Single round-trip DB query; shape: List[Dict[str, Any]]
        # Keys expected from the helper: system_id, csv_path, updated_at, last_scanned, scan_policy
        rows = list_all_systems(session)

        payload: List[SystemSummary] = []
        for row in rows:
            updated_at = row["updated_at"]
            last_scanned = row.get("last_scanned")
            csv_path = row.get("csv_path")  # May be None if not uploaded yet
            scan_policy_name = row.get("scan_policy")  # May be None if not assigned

            # Normalize timestamps to ISO-8601 strings for transport.
            time_added_iso = (
                updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at)
            )
            last_scanned_iso = last_scanned.isoformat() if last_scanned else None

            # Filesystem check is intentionally done here (I/O near edge) to keep DB pure.
            has_csv = _has_csv_on_disk(csv_path)

            payload.append(
                SystemSummary(
                    system_id=int(row["system_id"]),
                    time_added=time_added_iso,
                    last_scanned=last_scanned_iso,
                    has_csv=has_csv,
                    scan_policy=scan_policy_name,  # <-- new field surfaced in API
                )
            )

        # Serialize to list of dicts so jsonify can handle it
        return jsonify([item.model_dump() for item in payload])


@app.route("/api/admin/systems", methods=["POST"])
@login_required
@admin_required
def admin_add_system():
    """
    Add (or upsert) system mappings in the SystemCsv database.

    Request Body (JSON):

    Single mode (backward compatible):
        {
          "system_id": <int>,         # required
          "csv_path": "<string|null>" # optional, can be omitted or null
        }

    Batch mode (new):
        {
          "items": [
            {
              "system_id": <int>,
              "csv_path": "<string|null>"
            },
            ...
          ]
        }

    Behavior:
        - For single requests, behaves exactly as before.
        - For batch requests:
            * Validates all items with Pydantic.
            * Upserts all items in a single transaction (all-or-nothing).
        - If csv_path is provided, it is normalized and stored.
        - If omitted/null, we persist NULL until a CSV is uploaded.
        - If the system_id already exists, this acts as an update.

    Returns:
        Single mode:
            JSON object of SystemSummary for the new/updated system.
        Batch mode:
            JSON array of SystemSummary objects for all new/updated systems.

    Errors:
        400: Validation error on input (generic, no internal details)
        500: Database error (generic, no internal details)
    """
    body = request.get_json(silent=True) or {}

    # Lightly sanitized / truncated for logs so you can see what's going on
    def _safe_body_snippet(obj) -> str:
        try:
            raw = json.dumps(obj, default=str)
        except Exception:
            raw = str(obj)
        # Don't spam logs with giant payloads
        return raw[:2000]

    is_batch = isinstance(body, dict) and "items" in body
    body_snippet = _safe_body_snippet(body)

    logger.debug(
        "[ADMIN] /api/admin/systems POST received (%s mode) body=%s",
        "batch" if is_batch else "single",
        body_snippet,
    )

    # ----------------------- Batch mode -----------------------------------
    if is_batch:
        try:
            # No ValidationError import; catch generic exceptions
            batch = AddSystemBatchInput(**body)
        except Exception as e:
            # Full details only in logs
            logger.warning(
                "[ADMIN] add_system (batch) validation error: %r | body=%s",
                e,
                body_snippet,
            )
            return jsonify({"error": "invalid payload"}), 400

        with get_session() as s:
            try:
                for item in batch.items:
                    set_system_csv_path(s, item.system_id, item.csv_path)
                s.commit()
            except Exception as ex:
                s.rollback()
                logger.exception(
                    "[ADMIN] add_system (batch) failed for items=%s | body=%s",
                    [i.system_id for i in batch.items],
                    body_snippet,
                )
                return jsonify({"error": "db error"}), 500

            now_iso = datetime.utcnow().isoformat()
            summaries: list[SystemSummary] = []
            for item in batch.items:
                summaries.append(
                    SystemSummary(
                        system_id=item.system_id,
                        time_added=now_iso,
                        last_scanned=None,
                        has_csv=_has_csv_on_disk(item.csv_path),
                    )
                )

            logger.info(
                "[ADMIN] add_system (batch) succeeded for %d system(s): %s",
                len(batch.items),
                [i.system_id for i in batch.items],
            )
            return jsonify([s.model_dump() for s in summaries]), 201

    # ----------------------- Single mode ----------------------------------
    try:
        data = AddSystemInput(**body)
    except Exception as e:
        logger.warning(
            "[ADMIN] add_system (single) validation error: %r | body=%s",
            e,
            body_snippet,
        )
        return jsonify({"error": "invalid payload"}), 400

    with get_session() as s:
        try:
            set_system_csv_path(s, data.system_id, data.csv_path)
            s.commit()
        except Exception as ex:
            s.rollback()
            logger.exception(
                "[ADMIN] add_system (single) failed for system_id=%s | body=%s",
                data.system_id,
                body_snippet,
            )
            return jsonify({"error": "db error"}), 500

        resp = SystemSummary(
            system_id=data.system_id,
            time_added=datetime.utcnow().isoformat(),
            last_scanned=None,
            has_csv=_has_csv_on_disk(data.csv_path),
        )

        logger.info(
            "[ADMIN] add_system (single) succeeded for system_id=%s",
            data.system_id,
        )
        return jsonify(resp.model_dump()), 201



@app.route("/api/admin/systems/<int:system_id>/csv", methods=["POST"])
@login_required
@admin_required
def admin_upload_system_csv(system_id: int):
    """
    Upload and persist a CSV for the given system_id.

    Request:
        multipart/form-data with a "file" field.

    Behavior:
        - Saves the uploaded file to WORKING_DIR/systems/<system_id>.csv
        - Updates or creates the DB mapping for system_id → csv_path
        - Does not modify the `last_scanned` field (scanning flow should handle that)

    Responses:
        201 Created: JSON body with SystemSummary of the updated row
        400 Bad Request: Missing file field or invalid filename
        500 Internal Server Error: File save failure or DB commit failure
    """
    # Ensure multipart form includes a file
    if "file" not in request.files:
        return jsonify({"error": "missing file field"}), 400

    uploaded_file = request.files["file"]
    if not uploaded_file or uploaded_file.filename.strip() == "":
        return jsonify({"error": "empty filename"}), 400

    # Validate extension (only allow .csv)
    safe_name = secure_filename(uploaded_file.filename)
    if not safe_name.lower().endswith(".csv"):
        return jsonify({"error": "only .csv files are allowed"}), 400

    # Derive canonical storage path: WORKING_DIR/systems/<system_id>.csv
    systems_dir = WORKING_DIR / "systems"
    systems_dir.mkdir(parents=True, exist_ok=True)
    target_path = systems_dir / f"{system_id}.csv"

    # Attempt to persist the file to disk
    try:
        uploaded_file.save(str(target_path))
    except Exception as ex:
        logger.exception("[ADMIN] CSV upload failed: could not save to disk")
        return jsonify({"error": "file save failed", "details": str(ex)}), 500

    # Update DB mapping (system_id → csv_path)
    with get_session() as session:
        try:
            set_system_csv_path(session, system_id, str(target_path))
            session.commit()
        except Exception as ex:
            session.rollback()
            logger.exception("[ADMIN] CSV upload failed: DB update error")
            return jsonify({"error": "db error", "details": str(ex)}), 500

        # Convert DB row into SystemSummary for API response
        system_summary = SystemSummary(
            system_id=system_id,
            time_added=datetime.utcnow().isoformat(),  # updated_at in DB is more authoritative
            last_scanned=None,
            has_csv=_has_csv_on_disk(str(target_path)),
        )
        return jsonify(system_summary.model_dump()), 201

def _row_to_summary(row: dict) -> dict:
    """
    Convert a dict row (from list_all_systems) into a SystemSummary JSON dict.
    """
    updated_at = row["updated_at"]
    last_scanned = row.get("last_scanned")
    csv_path = row.get("csv_path")
    return SystemSummary(
        system_id=int(row["system_id"]),
        time_added=(updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at)),
        last_scanned=(last_scanned.isoformat() if last_scanned else None),
        has_csv=_has_csv_on_disk(csv_path),
    ).model_dump()


@app.route("/api/admin/systems/<int:system_id>", methods=["DELETE"])
@login_required
@admin_required
def admin_delete_system(system_id: int):
    """
    Delete a system row from SystemCsv. Optionally purge the CSV file from disk.

    Query Params:
        purge_file: "1" or "true" to also remove the CSV from disk if it exists.
                    Any other value (or omitted) means do NOT remove the file.

    Behavior:
        - If the system does not exist, returns 404.
        - If purge_file is requested and the CSV path exists on disk, attempts removal.
        - Removes the DB row and commits the transaction.

    Responses:
        200 OK with JSON:
            {
              "deleted": true,
              "system_id": <int>,
              "purged_csv": <bool>,
              "csv_path": "<str|null>"
            }
        404 if system not found.
        500 on unexpected failures.
    """
    purge_file = str(request.args.get("purge_file", "")).lower() in {"1", "true", "yes"}

    with get_session() as session:
        try:
            row: Optional[SystemCsv] = session.get(SystemCsv, system_id)
            if not row:
                return jsonify({"error": "system not found", "system_id": system_id}), 404

            csv_path_before: Optional[str] = row.csv_path
            session.delete(row)
            session.commit()

            purged = False
            if purge_file and csv_path_before and _has_csv_on_disk(csv_path_before):
                try:
                    Path(csv_path_before).unlink(missing_ok=True)  # Py3.8+: wrap with exists check if needed
                    purged = True
                except Exception as ex:
                    # Non-fatal: row is deleted; file cleanup failed
                    logger.warning("[ADMIN] purge_file failed for system_id=%s path=%s err=%s",
                                   system_id, csv_path_before, ex)

            return jsonify({
                "deleted": True,
                "system_id": system_id,
                "purged_csv": purged,
                "csv_path": csv_path_before
            })
        except Exception as ex:
            session.rollback()
            logger.exception("[ADMIN] delete_system failed")
            return jsonify({"error": "db error", "details": str(ex)}), 500

@app.route("/api/admin/systems/<int:system_id>/csv", methods=["PATCH"])
@login_required
@admin_required
def admin_unset_system_csv(system_id: int):
    """
    Set a system's CSV path to NULL (unset). Optionally purge the file on disk.

    Request Body (JSON):
        {
          "csv_path": null   # REQUIRED to be null; any other value is rejected
        }

    Query Params:
        purge_file: "1" or "true" to also remove the CSV from disk if it exists.

    Behavior:
        - Validates that the row exists; 404 if not found.
        - If purge_file is requested and a file path exists, attempts file deletion.
        - Updates DB to store NULL csv_path (using set_system_csv_path(..., None)).
        - Returns the updated SystemSummary for this row.

    Responses:
        200 OK with SystemSummary JSON.
        400 if csv_path is not null or body invalid.
        404 if system not found.
        500 on DB failures.
    """
    body = request.get_json(silent=True) or {}
    if "csv_path" not in body or body["csv_path"] is not None:
        return jsonify({"error": "csv_path must be present and set to null"}), 400

    purge_file = str(request.args.get("purge_file", "")).lower() in {"1", "true", "yes"}

    with get_session() as session:
        try:
            row: Optional[SystemCsv] = session.get(SystemCsv, system_id)
            if not row:
                return jsonify({"error": "system not found", "system_id": system_id}), 404

            # Optionally purge the current file from disk before unsetting
            csv_path_before: Optional[str] = row.csv_path
            if purge_file and csv_path_before and _has_csv_on_disk(csv_path_before):
                try:
                    Path(csv_path_before).unlink(missing_ok=True)
                except Exception as ex:
                    logger.warning("[ADMIN] purge_file failed for system_id=%s path=%s err=%s",
                                   system_id, csv_path_before, ex)

            # Set csv_path to NULL (no file path recorded)
            set_system_csv_path(session, system_id, None)
            session.commit()

            # Build a SystemSummary response using a fresh read of this row
            rows = [r for r in list_all_systems(session) if int(r["system_id"]) == system_id]
            if not rows:
                # Should not happen, but guard anyway
                return jsonify({"error": "system not found after update"}), 500

            return jsonify(_row_to_summary(rows[0]))
        except Exception as ex:
            session.rollback()
            logger.exception("[ADMIN] unset_system_csv failed")
            return jsonify({"error": "db error", "details": str(ex)}), 500

def _has_csv_on_disk(path_str: Optional[str]) -> bool:
    """Return True if path exists and is a regular file. Tolerates None/empty."""
    if not path_str:
        return False
    p = Path(path_str)
    return p.exists() and p.is_file()




@app.route("/api/monitoring/continuous", methods=["GET"])
@login_required
def api_monitoring_continuous():
    """List systems and their latest continuous monitoring status.

    Enrollment / monitored semantics:
      * A system appears in this list if it has a row in `system_csv`
        (i.e., it is part of the continuous monitoring portfolio).
      * The `monitored` flag is True if that row’s `scan_policy` value
        resolves to an existing `ScanPolicy.name`. Systems with a null
        or stale policy reference are still present but marked as
        `monitored=False`.

    Field semantics:
      * system_id:
          Integer identifier from `system_csv.system_id`.

      * score:
          Latest readiness score from the most recent `TestRun` for that
          system. The value is sourced from `TestRun.readiness_score_pct`
          via `get_latest_readiness_score_for_system(...)`. If no score is
          available, this endpoint returns 0 for convenience in the UI.

      * last_scanned:
          ISO-8601 timestamp representing the most recent run timestamp for
          that system (using `max(coalesce(finished_at, started_at))`), or
          null if the system has never been scanned.

      * monitored:
          Boolean indicating whether the system is currently enrolled in a
          valid scan policy (as defined above).

    Returns:
        Flask Response: JSON array of objects, each shaped as:
            {
              "system_id": number,
              "score": 0..100,
              "last_scanned": ISO8601 | null,
              "monitored": boolean
            }
    """
    current_user = session.get("user")
    if not current_user:
        return jsonify({"error": "not authenticated"}), 401

    logger.info(
        "[CM][LIST] user=%s requested continuous monitoring systems",
        current_user,
    )

    try:
        with get_session() as db_session:
            # DB helper returns raw per-system metrics from SystemCsv, ScanPolicy,
            # and TestRun (including readiness_score_pct).
            raw_items = list_continuous_monitoring_items(db_session)

            items: List[ContinuousItem] = []
            for rec in raw_items:
                system_id = int(rec["system_id"])
                last_scanned_dt: Optional[datetime] = rec.get("last_scanned")
                readiness_score: Optional[int] = rec.get("readiness_score_pct")
                monitored_flag: bool = bool(rec.get("monitored", False))

                # Frontend expects a numeric score; normalize None → 0.
                score_value = int(readiness_score) if readiness_score is not None else 0

                # Backend timestamps are stored as naive UTC; isoformat() is sufficient.
                last_scanned_iso: Optional[str]
                if last_scanned_dt is not None:
                    last_scanned_iso = last_scanned_dt.isoformat()
                else:
                    last_scanned_iso = None

                items.append(
                    ContinuousItem(
                        system_id=system_id,
                        score=score_value,
                        last_scanned=last_scanned_iso,
                        monitored=monitored_flag,
                    )
                )

            logger.info(
                "[CM][LIST] user=%s systems=%d monitored=%d",
                current_user,
                len(items),
                sum(1 for item in items if item.monitored),
            )

            # Preserve the original shape: array of serialized ContinuousItem models.
            return jsonify([item.model_dump() for item in items])

    except Exception as exc:
        logger.exception(
            "[CM][LIST][ERROR] user=%s failed to build continuous monitoring list",
            current_user,
        )
        return jsonify(
            {
                "error": "internal server error",
                "detail": str(exc),
            }
        ), 500


@app.get("/api/continuous_monitoring/system/<int:system_id>/compliance_over_time")
@login_required
def api_continuous_monitoring_system_compliance_over_time(system_id: int):
    """Return readiness scores over time for a single system.

    This endpoint powers the "Compliance Over Time" chart for a system. It
    returns all recorded readiness scores in chronological order, along with
    the first and last timestamps so the frontend can auto-scale the time axis.
    """
    # Use Flask's `session`, which you imported above
    current_user = session.get("user")
    if not current_user:
        return jsonify({"error": "not authenticated"}), 401

    logger.info(
        "[CM][TIMESERIES] user=%s system_id=%s requested compliance-over-time",
        current_user,
        system_id,
    )

    try:
        with get_session() as db_session:
            history = list_readiness_history_for_system(
                db_session,
                system_id=system_id,
            )

            if not history:
                body = {
                    "system_id": system_id,
                    "has_data": False,
                    "first_ts_iso": None,
                    "last_ts_iso": None,
                    "points": [],
                }
                logger.info(
                    "[CM][TIMESERIES] user=%s system_id=%s has no runs yet",
                    current_user,
                    system_id,
                )
                return jsonify(body)

            # History is already chronological (oldest → newest).
            first_ts = history[0]["ts"]
            last_ts = history[-1]["ts"]

            def _to_utc(dt: datetime) -> datetime:
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)

            first_utc = _to_utc(first_ts)
            last_utc = _to_utc(last_ts)

            points: List[Dict[str, Any]] = []
            for entry in history:
                ts = _to_utc(entry["ts"])
                ts_epoch = int(ts.timestamp())
                ts_iso = ts.isoformat(timespec="seconds").replace("+00:00", "Z")

                points.append(
                    {
                        "run_id": entry["run_id"],
                        "ts_epoch": ts_epoch,
                        "ts_iso": ts_iso,
                        "score": entry["readiness_score_pct"],
                    }
                )

            body = {
                "system_id": system_id,
                "has_data": True,
                "first_ts_iso": first_utc.isoformat(timespec="seconds").replace(
                    "+00:00", "Z"
                ),
                "last_ts_iso": last_utc.isoformat(timespec="seconds").replace(
                    "+00:00", "Z"
                ),
                "points": points,
            }

            logger.info(
                "[CM][TIMESERIES] user=%s system_id=%s runs=%d first=%s last=%s",
                current_user,
                system_id,
                len(points),
                body["first_ts_iso"],
                body["last_ts_iso"],
            )

            return jsonify(body)

    except Exception as exc:
        logger.exception(
            "[CM][TIMESERIES][ERROR] user=%s system_id=%s failed to build series",
            current_user,
            system_id,
        )
        return (
            jsonify(
                {
                    "error": "internal server error",
                    "detail": str(exc),
                }
            ),
            500,
        )



@app.get("/api/continuous_monitoring/system/<int:system_id>/latest")
@login_required
def api_continuous_monitoring_system_latest(system_id: int):
    """Return the latest continuous-monitoring scan summary for a specific system.

    This endpoint mirrors the JSON schema of `/api/summary/latest` but sources
    its data from the persisted TestRun/TestOutcome tables used by continuous
    monitoring. It is used by the Reporting UI to render the most recent stored
    scan for systems enrolled in continuous monitoring.

    Behavior:
      * Selects the latest finished TestRun for the given system from the DB.
      * Hydrates a tabular DataFrame from TestOutcome/TestCatalog rows using
        `get_latest_run_dataframe_for_system`.
      * Computes readiness using `compute_readiness_summary(frame)` and then
        overrides the `score_pct` field with the stored readiness score from
        `TestRun.readiness_score_pct` (via
        `get_latest_readiness_score_for_system`) when available.
      * Emits a JSON object with the same shape as `/api/summary/latest` so the
        Reporting UI components can be reused without changes.

    Query parameters:
      limit: Optional integer row cap for the dataframe payload (default 2000;
             max 10000). Readiness is always computed over the full DataFrame;
             the limit only affects the returned rows.

    Security:
      * Requires an authenticated session (`login_required`).
      * Callers SHOULD enforce system ownership/visibility via a higher-level
        access-control layer mapping users to system IDs. This endpoint assumes
        that the provided `system_id` is authorized for the caller.

    Returns:
      200: Success with the summary JSON.
      401: If unauthenticated.
      404: If no finished run exists for the system
           (code = "NO_SCAN_FOR_SYSTEM").
      500: On unexpected errors.
    """
    current_user = session.get("user")
    if not current_user:
        return jsonify({"error": "not authenticated"}), 401

    # Parse and clamp row limit (same semantics as /api/summary/latest).
    try:
        row_limit = int(request.args.get("limit", 2000))
        row_limit = max(1, min(row_limit, 10000))
    except Exception:
        row_limit = 2000

    logger.info(
        "[CM][SUMMARY] user=%s system_id=%s limit=%s",
        current_user,
        system_id,
        row_limit,
    )

    db_session = get_session()
    try:
        result = get_latest_run_dataframe_for_system(db_session, system_id=system_id)
        if result is None:
            logger.warning(
                "[CM][SUMMARY] user=%s system_id=%s no finished runs found",
                current_user,
                system_id,
            )
            # Structured response so the frontend can distinguish "no scan yet".
            return (
                jsonify(
                    {
                        "error": "no finished runs found for system",
                        "code": "NO_SCAN_FOR_SYSTEM",
                        "system_id": system_id,
                        "has_scan": False,
                    }
                ),
                404,
            )

        run, df = result

        # Serialize the dataframe to the standard payload, honoring the row cap.
        try:
            df_payload = DataFramePayload.from_dataframe(
                df if df is not None else pd.DataFrame(),
                system_id=run.system_id,
                source="db:continuous_monitoring",
                limit=row_limit,  # if unsupported by the model, we trim manually below
            )
        except Exception:
            # Manual trim fallback when `limit` isn't supported by the serializer.
            if df is None:
                df = pd.DataFrame()
            df_trimmed = df.head(row_limit).copy()
            df_payload = DataFramePayload.from_dataframe(
                df_trimmed,
                system_id=run.system_id,
                source="db:continuous_monitoring",
            )

        # Compute readiness/summary (neutral rows excluded from score).
        is_truncated = bool(
            df is not None and df.shape[0] > getattr(df_payload, "shape", [0])[0]
        )
        readiness = compute_readiness_summary(df if df is not None else pd.DataFrame())

        # Prefer the stored readiness score from the latest TestRun row, if present.
        try:
            persisted_score = get_latest_readiness_score_for_system(system_id=system_id)
        except Exception:
            logger.exception(
                "[CM][SUMMARY] user=%s system_id=%s failed to fetch stored readiness score",
                current_user,
                system_id,
            )
            persisted_score = None

        if persisted_score is not None:
            readiness["score_pct"] = persisted_score

        # Timestamp selection: prefer finished_at, fall back to started_at;
        # guard against None and normalize to UTC.
        ts: Optional[datetime] = run.finished_at or run.started_at
        if ts is None:
            ts = datetime.utcnow()

        if ts.tzinfo is None:
            ts_utc = ts.replace(tzinfo=timezone.utc)
        else:
            ts_utc = ts.astimezone(timezone.utc)

        ran_epoch = int(ts_utc.timestamp())
        ran_iso = ts_utc.isoformat(timespec="seconds").replace("+00:00", "Z")

        # Best-effort system name: run.system_name, then related System.name.
        system_name: Optional[str] = run.system_name
        try:
            if (
                not system_name
                and getattr(run, "system", None) is not None
                and run.system.name
            ):
                system_name = run.system.name
        except Exception:
            logger.debug(
                "[CM][SUMMARY] user=%s system_id=%s system relationship lookup failed",
                current_user,
                system_id,
            )

        body: Dict[str, Any] = {
            "job_id": run.job_id or run.id,
            "system_id": run.system_id,
            "system_name": system_name,
            "ran_at_epoch": ran_epoch,
            "ran_at_iso": ran_iso,
            "dataframe": dataframe_payload_to_dict(df_payload),
            "dataframe_truncated": is_truncated,
            "readiness": readiness,
        }

        logger.info(
            "[CM][SUMMARY] user=%s system_id=%s run_id=%s score=%s truncated=%s",
            current_user,
            system_id,
            run.id,
            readiness.get("score_pct"),
            is_truncated,
        )

        return jsonify(body)

    except Exception as exc:
        logger.exception(
            "[CM][SUMMARY][ERROR] user=%s system_id=%s failed to build summary",
            current_user,
            system_id,
        )
        return (
            jsonify(
                {
                    "error": "internal server error",
                    "detail": str(exc),
                }
            ),
            500,
        )
    finally:
        db_session.close()


@app.get("/api/autodiscovery")
@login_required
@admin_required
def api_autodiscovery() -> Any:
    """Autodiscover systems and annotate them with scan-policy enrollment.

    Overview
    --------
    This endpoint wires together three layers:

    * `engine.test_api.discover_system_ids()` to discover system IDs from
      eMASS fixtures (e.g., SystemDetailsDashboard.json).
    * `db.get_all_policies()` to fetch defined `ScanPolicy` rows.
    * `db.get_enrolled_system_ids()` to determine which systems are enrolled
      to which policies.

    It returns a flattened list of items, one per discovered system ID, with
    basic policy-enrollment metadata for UI use.

    Returns
    -------
    flask.Response
        JSON array with shape::

            [
              {
                "system_id": 101,
                "has_policy": true,
                "policies": ["Daily Scan", "ATO Baseline"]
              },
              {
                "system_id": 102,
                "has_policy": false,
                "policies": []
              },
              ...
            ]

        If no systems are discovered, an empty list is returned.
    """
    # 1) Discover candidate systems from eMASS fixtures.
    discovered_ids: List[int] = discover_system_ids()
    if not discovered_ids:
        return jsonify([])

    # 2) Pre-seed a map from system_id -> enrolled policy names.
    policy_map: Dict[int, List[str]] = {sid: [] for sid in discovered_ids}

    # 3) Fetch all scan policies and check enrollment in one DB session.
    policies = get_all_policies()
    if policies:
        with get_session() as session:
            for policy in policies:
                # Assumes ScanPolicy has a `.name` field used by get_enrolled_system_ids.
                enrolled_ids = get_enrolled_system_ids(session, policy.name)
                for sid in enrolled_ids:
                    if sid in policy_map:
                        policy_map[sid].append(policy.name)

    # 4) Flatten into a list of items suitable for frontend consumption.
    items: List[Dict[str, Any]] = []
    for sid in discovered_ids:
        policy_names = policy_map.get(sid, [])
        items.append(
            {
                "system_id": sid,
                "has_policy": bool(policy_names),
                "policies": policy_names,
            }
        )

    return jsonify(items)


# ─────────────────────────────────────────────────────────────────────────────
# Request helpers (JSON + query parsing)
# ─────────────────────────────────────────────────────────────────────────────

def _json_or_400():
    """
    Parse the request body as JSON and return a Python object or abort(400).

    Why:
        The frontend expects JSON-only responses. Flask's default HTML error
        pages break fetch() handlers and TS JSON parsing.

    Behavior:
        - Empty body → {} (helpful for partial updates).
        - Content-Type application/json → returns parsed JSON ({} if empty).
        - Otherwise → abort(400) with a short *JSON* error message, not HTML.
    """
    if not request.data:
        return {}
    if request.is_json:
        obj = request.get_json(silent=True)
        return obj if isinstance(obj, (dict, list)) else (obj or {})
    raw = (request.data or b"").decode("utf-8", errors="replace")[:400]
    return abort(400, description=f"expected application/json; got {request.content_type or 'none'}; body starts: {raw!r}")


def _parse_bool_query_flag(param_name: str, default: bool = False) -> bool:
    """
    Parse a boolean-ish query value (?strict=1|true|yes / 0|false|no).
    """
    val = request.args.get(param_name)
    if val is None:
        return default
    v = str(val).strip().lower()
    if v in {"1", "true", "yes"}:
        return True
    if v in {"0", "false", "no"}:
        return False
    return default


def _normalize_system_ids(raw_ids) -> list[int]:
    """
    Normalize and de-duplicate a user-provided list of system IDs.

    Args:
        raw_ids: JSON list containing strings or numbers.

    Returns:
        list[int] with first-seen ordering preserved.

    Raises:
        ValueError if the payload is not a list or any element is not int-coercible.
    """
    if not isinstance(raw_ids, list):
        raise ValueError("system_ids must be a JSON array")
    seen, out = set(), []
    for x in raw_ids:
        try:
            sid = int(x)
        except Exception:
            raise ValueError(f"invalid system_id entry: {x!r}")
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/policies", methods=["GET"], strict_slashes=False)
@login_required
def api_policies_list():
    """
    GET /api/policies — List all scan policies (authenticated)

    Returns:
        200 OK with array[ScanPolicyOut]-shaped JSON
        500 on server/DB error
    """
    t0 = _time.time()
    actor = session.get("user_id")
    try:
        payload = policies_list()  # returns list of dicts already shaped for JSON
        logger.info("[POLICY][LIST] actor=%s count=%d dur_ms=%d",
                    actor, len(payload), int((_time.time() - t0) * 1000))
        return jsonify(payload)
    except Exception as ex:
        logger.exception("[POLICY][LIST][ERR] actor=%s", actor)
        return jsonify({"error": "db error", "details": str(ex)}), 500


@app.route("/api/policies", methods=["POST"], strict_slashes=False)
@login_required
@admin_required
def api_policies_create():
    """
    POST /api/policies — Create a new scan policy (admin)

    Body JSON:
      {
        "name": "Nightly-2AM",
        "frequency": "daily"|"weekly"|"biweekly"|"monthly",
        "time_of_day": "HH:MM[:SS]" (UTC),
        "day_of_week": "Monday"|... (required for weekly/monthly; optional for biweekly),
        "week_of_month": 1..5 (required for monthly),
        "anchor_epoch": <int> (optional; strict biweekly cadence anchor)
      }

    Returns:
        201 Created {"id": <int>, "message": "Policy created"}
        400 on validation errors
        500 on server/DB error
    """
    t0 = _time.time()
    actor = session.get("user_id")
    data = _json_or_400()
    try:
        new_id = policies_create(
            name=data.get("name", ""),
            frequency=data.get("frequency"),
            time_of_day=data.get("time_of_day"),
            day_of_week=data.get("day_of_week"),
            week_of_month=data.get("week_of_month"),
            anchor_epoch=data.get("anchor_epoch"),
        )
        logger.info("[POLICY][CREATE] actor=%s name=%s id=%s dur_ms=%d",
                    actor, data.get("name"), new_id, int((_time.time() - t0) * 1000))
        return jsonify({"id": int(new_id), "message": "Policy created"}), 201

    except DBValidation as ve:
        logger.warning("[POLICY][CREATE][400] actor=%s details=%s", actor, ve)
        return jsonify({"error": "invalid payload", "details": str(ve)}), 400
    except Exception as ex:
        logger.exception("[POLICY][CREATE][ERR] actor=%s name=%s", actor, data.get("name"))
        return jsonify({"error": "db error", "details": str(ex)}), 500


@app.route("/api/policies/<int:policy_id>", methods=["PUT"], strict_slashes=False)
@login_required
@admin_required
def api_policy_update(policy_id: int):
    """
    PUT /api/policies/<policy_id> — Partial update (admin)
    Send `null` to clear nullable fields; omit to leave unchanged.
    """
    t0 = _time.time()
    actor = session.get("user_id")
    raw = _json_or_400()

    # Prepare values; keep "__omit__" for fields we must not touch
    day_of_week = "__omit__"
    if "day_of_week" in raw:
        day_of_week = raw["day_of_week"]  # may be None or a string

    try:
        policy_update(
            policy_id,
            name=raw.get("name"),
            frequency=raw.get("frequency"),
            time_of_day=raw.get("time_of_day"),
            day_of_week=day_of_week,
            week_of_month=raw.get("week_of_month", "__omit__"),
            anchor_epoch=raw.get("anchor_epoch", "__omit__"),
        )
        logger.info("[POLICY][UPDATE] actor=%s id=%s dur_ms=%d",
                    actor, policy_id, int((_time.time() - t0) * 1000))
        return jsonify({"message": "Policy updated"})

    except DBNotFound:
        logger.warning("[POLICY][UPDATE][404] actor=%s id=%s", actor, policy_id)
        return jsonify({"error": "Policy not found"}), 404
    except DBValidation as ve:
        logger.warning("[POLICY][UPDATE][400] actor=%s id=%s details=%s", actor, policy_id, ve)
        return jsonify({"error": "invalid payload", "details": str(ve)}), 400
    except Exception as ex:
        logger.exception("[POLICY][UPDATE][ERR] actor=%s id=%s", actor, policy_id)
        return jsonify({"error": "db error", "details": str(ex)}), 500


@app.route("/api/policies/<int:policy_id>", methods=["DELETE"], strict_slashes=False)
@login_required
@admin_required
def api_policy_delete(policy_id: int):
    """
    DELETE /api/policies/<policy_id> — Delete policy and clear enrollments (admin)
    """
    t0 = _time.time()
    actor = session.get("user_id")
    try:
        policy_delete(policy_id)
        logger.info("[POLICY][DELETE] actor=%s id=%s dur_ms=%d",
                    actor, policy_id, int((_time.time() - t0) * 1000))
        return jsonify({"message": "Policy deleted"})
    except DBNotFound:
        logger.warning("[POLICY][DELETE][404] actor=%s id=%s", actor, policy_id)
        return jsonify({"error": "Policy not found"}), 404
    except Exception as ex:
        logger.exception("[POLICY][DELETE][ERR] actor=%s id=%s", actor, policy_id)
        return jsonify({"error": "db error", "details": str(ex)}), 500


@app.route("/api/policies/<int:policy_id>/systems", methods=["POST"], strict_slashes=False)
@login_required
@admin_required
def api_policy_enroll_systems(policy_id: int):
    """
    POST /api/policies/<policy_id>/systems — Enroll systems (admin)

    Body JSON:
      { "system_ids": [114, 207, 309] }

    Query:
      ?strict=1  → all-or-nothing; if any ID doesn’t exist, returns 409 and no mutation.

    Returns:
      200 OK {"message":"Systems enrolled","updated":N,"missing":[...]}
      400 on validation
      404 if policy not found
      409 if strict=1 and some IDs missing (no mutation)
    """
    t0 = _time.time()
    actor = session.get("user_id")
    data = _json_or_400()

    try:
        # Validate shape in the web layer (good UX for obvious errors)
        ids = _normalize_system_ids(data.get("system_ids", []))
    except ValueError as ve:
        logger.warning("[POLICY][ENROLL][400] actor=%s id=%s err=%s", actor, policy_id, ve)
        return jsonify({"error": str(ve)}), 400

    strict_mode = _parse_bool_query_flag("strict", default=False)

    try:
        result = policies_enroll_systems(policy_id, ids, strict=strict_mode)
        logger.info("[POLICY][ENROLL] actor=%s id=%s updated=%d missing=%d dur_ms=%d",
                    actor, policy_id, result["updated"], len(result["missing"]),
                    int((_time.time() - t0) * 1000))
        return jsonify({
            "message": "Systems enrolled",
            "updated": int(result["updated"]),
            "missing": result["missing"],
        })
    except DBNotFound:
        logger.warning("[POLICY][ENROLL][404] actor=%s id=%s", actor, policy_id)
        return jsonify({"error": "Policy not found"}), 404
    except DBConflict as ce:
        # strict=True and some IDs missing — surface the list so UI can “add now?”
        missing = []
        try:
            # try to parse list literal if present in message
            import ast
            missing = ast.literal_eval(str(ce).split(":", 1)[1].strip())
        except Exception:
            pass
        logger.warning("[POLICY][ENROLL][409] actor=%s id=%s missing=%s", actor, policy_id, missing)
        return jsonify({
            "error": "unknown_systems",
            "message": "Some system IDs are not in the portfolio.",
            "missing": missing,
        }), 409
    except DBValidation as ve:
        logger.warning("[POLICY][ENROLL][400] actor=%s id=%s details=%s", actor, policy_id, ve)
        return jsonify({"error": "invalid payload", "details": str(ve)}), 400
    except Exception as ex:
        logger.exception("[POLICY][ENROLL][ERR] actor=%s id=%s", actor, policy_id)
        return jsonify({"error": "db error", "details": str(ex)}), 500


@app.route("/api/policies/<int:policy_id>/systems", methods=["DELETE"], strict_slashes=False)
@login_required
@admin_required
def api_policy_remove_systems(policy_id: int):
    """
    DELETE /api/policies/<policy_id>/systems — Unenroll systems (admin)

    Body JSON:
      { "system_ids": [114, 207, 309] }

    Returns:
      200 OK {"message":"Systems removed","cleared":N,"not_found":M}
      400 on validation
      404 if policy not found
    """
    t0 = _time.time()
    actor = session.get("user_id")
    data = _json_or_400()

    try:
        ids = _normalize_system_ids(data.get("system_ids", []))
    except ValueError as ve:
        logger.warning("[POLICY][REMOVE][400] actor=%s id=%s err=%s", actor, policy_id, ve)
        return jsonify({"error": str(ve)}), 400

    try:
        result = policies_remove_systems(policy_id, ids)
        logger.info("[POLICY][REMOVE] actor=%s id=%s cleared=%d not_found=%d dur_ms=%d",
                    actor, policy_id, result["cleared"], result["not_found"],
                    int((_time.time() - t0) * 1000))
        return jsonify({
            "message": "Systems removed",
            "cleared": int(result["cleared"]),
            "not_found": int(result["not_found"]),
        })
    except DBNotFound:
        logger.warning("[POLICY][REMOVE][404] actor=%s id=%s", actor, policy_id)
        return jsonify({"error": "Policy not found"}), 404
    except DBValidation as ve:
        logger.warning("[POLICY][REMOVE][400] actor=%s id=%s details=%s", actor, policy_id, ve)
        return jsonify({"error": "invalid payload", "details": str(ve)}), 400
    except Exception as ex:
        logger.exception("[POLICY][REMOVE][ERR] actor=%s id=%s", actor, policy_id)
        return jsonify({"error": "db error", "details": str(ex)}), 500



def _run_policy_now_worker(policy_id: int, *, blocking: Optional[bool], actor: Optional[str]) -> None:
    """
    Fire-and-forget worker that executes a policy right now.
    Logs success/failure; exceptions are contained here.
    """
    t0 = _time.time()
    try:
        ok = scan_now(policy_id=policy_id, blocking=blocking)
        logger.info(
            "[POLICY][RUNNOW][WORKER] actor=%s id=%s ok=%s blocking=%s dur_ms=%d",
            actor, policy_id, ok, blocking, int((_time.time() - t0) * 1000),
        )
    except Exception:
        logger.exception("[POLICY][RUNNOW][WORKER][ERR] actor=%s id=%s", actor, policy_id)


# --- route -------------------------------------------------------------------
@app.route("/api/policies/<int:policy_id>/run", methods=["POST"], strict_slashes=False)
@login_required
@admin_required
def api_policy_run_now(policy_id: int):
    """
    POST /api/policies/<id>/run — Execute a policy immediately (async).

    Body JSON (optional):
      { "blocking": true|false }  # overrides SCAN_BLOCKING for this execution only

    Query (optional alternative):
      ?blocking=1|true|yes  or  0|false|no

    Returns:
      202 {"dispatched": true, "policy_id": <id>, "blocking": <bool|null>}
      404 {"error": "Policy not found"}
      409 {"error": "nothing_to_run"}  # policy exists but has no systems
      500 {"error": "db error"}        # unexpected DB error
    """
    t0 = _time.time()
    actor = session.get("user_id")

    # Prefer JSON, allow query flag as fallback
    body = _json_or_400() if request.data else {}
    blocking = body.get("blocking", None)
    if blocking is None and request.args.get("blocking") is not None:
        blocking = _parse_bool_query_flag("blocking", default=False)

    # Validate the policy exists and has systems to run before spinning a thread
    try:
        with get_session() as s:
            pol = get_scan_policy_by_id(s, policy_id)
            if not pol:
                return jsonify({"error": "Policy not found"}), 404

            # Determine if there's anything to do. This mirrors scheduler behavior.
            # list_systems_by_policy returns a list of system IDs for a policy name.
            system_ids = list_systems_by_policy(s, pol.name)
            if not system_ids:
                logger.info("[POLICY][RUNNOW][NOOP] actor=%s id=%s (no systems)", actor, policy_id)
                return jsonify({"error": "nothing_to_run"}), 409
    except Exception as ex:
        logger.exception("[POLICY][RUNNOW][ERR] actor=%s id=%s (precheck)", actor, policy_id)
        return jsonify({"error": "db error", "details": str(ex)}), 500

    # Kick off the async worker and return immediately
    try:
        th = threading.Thread(
            target=_run_policy_now_worker,
            args=(policy_id,),
            kwargs={"blocking": blocking, "actor": actor},
            daemon=True,
        )
        th.start()

        logger.info(
            "[POLICY][RUNNOW][DISPATCHED] actor=%s id=%s blocking=%s dur_ms=%d",
            actor, policy_id, blocking, int((_time.time() - t0) * 1000),
        )
        return jsonify({
            "dispatched": True,
            "policy_id": policy_id,
            "blocking": bool(blocking) if isinstance(blocking, bool) else None,
        }), 202

    except Exception as ex:
        logger.exception("[POLICY][RUNNOW][DISPATCH_ERR] actor=%s id=%s", actor, policy_id)
        return jsonify({"error": "internal error", "details": str(ex)}), 500



#-----------------------------------------------------------------------------
# Config managment
#-----------------------------------------------------------------------------

_EMASS_SECTION_HEADER_RE = re.compile(r"(?mi)^\s*\[emass\]\s*$")
_SECTION_HEADER_RE = re.compile(r"(?mi)^\s*\[(?P<name>[^\]]+)\]\s*$")


def _upsert_ini_key_preserving_comments(
    *, ini_path: Path, section: str, key: str, value: str
) -> None:
    """Replace or append a single key in an INI section without touching comments/formatting.

    Args:
      ini_path: Path to the INI to update in place.
      section: Section name (e.g., "emass").
      key: Key to set (e.g., "pfx_path").
      value: Value to write.

    Raises:
      FileNotFoundError: If the INI is missing.
      ValueError: If the section doesn't exist.
      OSError: If write/rename fails.
    """
    text = ini_path.read_text(encoding="utf-8", errors="strict")

    # Locate section boundaries
    sect_pat = re.compile(rf"(?mi)^\s*\[{re.escape(section)}\]\s*$")
    m = sect_pat.search(text)
    if not m:
        raise ValueError(f"Section [{section}] not found in {ini_path}")
    start = m.end()
    next_m = _SECTION_HEADER_RE.search(text, start)
    end = next_m.start() if next_m else len(text)

    before, block, after = text[:start], text[start:end], text[end:]

    # Replace first uncommented assignment of key, otherwise append neatly.
    assign_re = re.compile(rf"(?mi)^(?P<prefix>\s*){re.escape(key)}\s*=.*?$")
    if assign_re.search(block):
        new_block = assign_re.sub(rf"\g<prefix>{key} = {value}", block, count=1)
    else:
        new_line = f"{key} = {value}"
        new_block = block + ("" if block.endswith("\n") else "\n") + new_line + "\n"

    if new_block == block:
        return

    new_text = before + new_block + after

    # Atomic write preserving perms
    mode = ini_path.stat().st_mode
    tmp_path = ini_path.with_suffix(ini_path.suffix + f".tmp.{int(time.time())}")
    tmp_path.write_text(new_text, encoding="utf-8")
    try:
        os.chmod(tmp_path, mode)
    except OSError:
        pass
    tmp_path.replace(ini_path)


def _bool_from_form(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

@app.route("/api/admin/update_emass", methods=["POST"], strict_slashes=False)
@login_required
@admin_required
def api_admin_update_emass() -> Any:
    """Upload & apply new eMASS credentials safely; verify, persist, and confirm.

    Request (multipart/form-data or application/json):
      - `api_key` (optional str): New API key.
      - `cert_path` (optional str): New PEM cert path for `emass.cert_path`.
      - `pfx_pass` (optional str): New password for PKCS#12 bundle.
      - `pfx_file` (optional file): New PKCS#12 file to store and use.
      - `pfx_filename` (optional str): Desired filename for the saved PFX (sanitized).
      - `ini_path` (optional str): Override path to INI; defaults to DEFAULT_CONFIG_PATH.
      - `make_backup` (optional bool-ish): Whether to create a timestamped .bak of INI.

    Semantics:
      * At least one of {api_key, cert_path, pfx_pass, pfx_file} must be supplied.
      * If `pfx_file` is supplied, `pfx_pass` must also be supplied (so we can verify
        the container is legit PKCS#12, not a mislabeled file).
      * The new PFX is saved in the same directory as the currently configured `pfx_path`
        (or default `/app/certs` if not set), with a sanitized filename. Permissions 0600.
      * The INI is updated using `update_emass_credentials` (api_key, cert_path, pfx_pass),
        and `pfx_path` is upserted to point to the newly written PFX when provided.
      * The config is reloaded to verify the applied changes.

    Returns:
      JSON body for the frontend, e.g.:

      {
        "ok": true,
        "updated": {
          "api_key": true,
          "cert_path": false,
          "pfx_pass": true,
          "pfx_path": true
        },
        "pfx_meta": {
          "subject": "CN=Example",
          "issuer": "CN=CA",
          "chain_length": 1,
          "has_private_key": true
        },
        "paths": {
          "ini": "/app/TECTIX/config.ini",
          "pfx_saved_to": "/app/certs/eMASSAPIKey-20251112-120102.pfx"
        },
        "message": "eMASS credentials updated."
      }

      On failure, `"ok": false` with `"error"` explaining what to fix.
    """
    # Accept JSON or multipart form (React can send either).
    if request.content_type and request.content_type.startswith("application/json"):
        payload = request.get_json(silent=True) or {}
        form_get = payload.get
        files = {}
    else:
        form_get = request.form.get
        files = request.files

    # Gather inputs
    api_key = form_get("api_key")
    cert_path = form_get("cert_path")
    pfx_pass = form_get("pfx_pass")
    ini_path_str = form_get("ini_path") or DEFAULT_CONFIG_PATH
    make_backup = _bool_from_form(form_get("make_backup"), default=True)

    pfx_file = files.get("pfx_file")
    pfx_filename_requested = form_get("pfx_filename")

    if not any([api_key, cert_path, pfx_pass, pfx_file]):
        return jsonify({
            "ok": False,
            "error": "No changes specified. Provide at least one of api_key, cert_path, pfx_pass, or pfx_file.",
        }), 400

    if pfx_file and not pfx_pass:
        return jsonify({
            "ok": False,
            "error": "pfx_file was provided but pfx_pass is missing. Provide the password to validate the PKCS#12.",
        }), 400

    ini_path = Path(ini_path_str)
    try:
        cfg = Config.load_or_default(str(ini_path))
    except FileNotFoundError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    # Determine target directory for storing the new PFX.
    # Prefer directory of currently configured pfx_path, else default to /app/certs.
    current_pfx_path = cfg.emass_pfx_path or "/app/certs/eMASSAPIKey.pfx"
    target_dir = Path(current_pfx_path).expanduser().resolve().parent
    if not target_dir.exists():
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return jsonify({"ok": False, "error": f"Failed to ensure directory {target_dir}: {e}"}), 500

    updated_flags = {"api_key": False, "cert_path": False, "pfx_pass": False, "pfx_path": False}
    pfx_meta: Dict[str, Any] = {}
    pfx_saved_to: Optional[str] = None

    # If a PFX file is uploaded, validate it's genuine and write it securely.
    if pfx_file:
        try:
            pfx_bytes = pfx_file.read()
            meta = verify_pkcs12_file(pfx_bytes, pfx_pass)
            if not meta.get("valid"):
                return jsonify({
                    "ok": False,
                    "error": f"Uploaded file is not a valid PKCS#12: {meta.get('error')}",
                }), 400

            # Choose filename
            basename = secure_filename(pfx_filename_requested or pfx_file.filename or "")
            if not basename.lower().endswith(".pfx"):
                # Enforce .pfx extension
                ts = time.strftime("%Y%m%d-%H%M%S")
                basename = (basename or "eMASSAPIKey") + f"-{ts}.pfx"
            saved_path = (target_dir / basename).resolve()

            # Write with 0600 perms
            with open(saved_path, "wb") as f:
                f.write(pfx_bytes)
            os.chmod(saved_path, 0o600)

            # Re-verify the saved bytes from disk (defense-in-depth)
            disk_bytes = saved_path.read_bytes()
            meta2 = verify_pkcs12_file(disk_bytes, pfx_pass)
            if not meta2.get("valid"):
                try:
                    saved_path.unlink(missing_ok=True)  # clean up partial
                except Exception:
                    pass
                return jsonify({
                    "ok": False,
                    "error": "Post-save verification failed; file not a valid PKCS#12 on disk.",
                    "details": meta2,
                }), 500

            pfx_meta = {
                "subject": meta2.get("subject"),
                "issuer": meta2.get("issuer"),
                "chain_length": meta2.get("chain_length"),
                "has_private_key": meta2.get("has_private_key"),
            }
            pfx_saved_to = str(saved_path)
        except Exception as e:
            return jsonify({"ok": False, "error": f"PFX save failed: {e}"}), 500

    # Apply INI updates (api_key, cert_path, pfx_pass) via your updater.
    try:
        before = cfg.as_dict()
        update_emass_credentials(
            ini_path=ini_path,
            cert_path=cert_path,
            api_key=api_key,
            pfx_pass=pfx_pass,
            make_backup=make_backup,
        )
        # If we saved a new PFX, also point pfx_path to it, preserving comments.
        if pfx_saved_to:
            _upsert_ini_key_preserving_comments(
                ini_path=ini_path,
                section="emass",
                key="pfx_path",
                value=pfx_saved_to,
            )
    except Exception as e:
        # If we wrote a new PFX, do not delete it automatically—an operator may want it.
        return jsonify({"ok": False, "error": f"Failed to update INI: {e}"}), 500

    # Reload to verify what actually took effect.
    try:
        cfg2 = Config.load_or_default(str(ini_path))
        after = cfg2.as_dict()
        updated_flags["api_key"] = bool(api_key) and after.get("emass_api_key_set", False)
        updated_flags["cert_path"] = bool(cert_path) and bool(cfg2.emass_cert_path)
        updated_flags["pfx_pass"] = bool(pfx_pass) and bool(cfg2.emass_pfx_pass)
        if pfx_saved_to:
            updated_flags["pfx_path"] = (cfg2.emass_pfx_path == pfx_saved_to)
        message = "eMASS credentials updated."
        # If user tried to update a field but the reload didn't reflect it, flag it.
        problems: List[str] = []
        for k, v in updated_flags.items():
            # only complain for fields the caller attempted to set
            attempted = {"api_key": api_key, "cert_path": cert_path, "pfx_pass": pfx_pass, "pfx_path": pfx_saved_to}.get(k)
            if attempted and not v:
                problems.append(k)
        if problems:
            message = (
                "Partial update: the following fields did not reflect after reload: "
                + ", ".join(sorted(problems))
            )

        return jsonify({
            "ok": all(v for (k, v) in updated_flags.items() if {"api_key": api_key, "cert_path": cert_path, "pfx_pass": pfx_pass, "pfx_path": pfx_saved_to}.get(k)),
            "updated": updated_flags,
            "pfx_meta": pfx_meta or None,
            "paths": {"ini": str(ini_path), "pfx_saved_to": pfx_saved_to},
            "message": message,
        }), (200 if not problems else 207)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Post-update verification failed: {e}"}), 500


@app.route("/api/admin/test_emass", methods=["POST", "GET"], strict_slashes=False)
@login_required
@admin_required
def api_test_emass() -> "flask.Response":
    """
    Quick health check for eMASS fixture accessibility.

    Request (optional JSON):
      { "data_root": "/path/to/fixtures" }

    Response:
      { "ok": true }  # bool only, per React contract

    HTTP 200 when ok=True; HTTP 503 when ok=False.
    """
    payload = {}
    try:
        payload = request.get_json(silent=True) or {}
    except Exception:
        payload = {}

    data_root = payload.get("data_root")
    cfg = None
    if data_root and Config is not None:
        try:
            cfg = Config(data_root=data_root)
        except Exception:
            # If constructing Config fails, we still try with None (default search paths)
            cfg = None

    ok = False
    try:
        ok = bool(test_emass_connection(cfg))
    except Exception:
        ok = False  # defensive: never let the route crash

    status = 200 if ok else 503
    return jsonify({"ok": ok}), status


#GRAFANA STUFF!

@app.get("/internal/nginx_auth")
@login_required
def nginx_auth():
    """Internal auth endpoint for Nginx auth_request.

    Purpose
    -------
    Provide a lightweight, machine-oriented check used by Nginx to determine
    whether the caller is authenticated to TECTIX and, if so, expose the
    username via an HTTP header for downstream systems (Grafana auth proxy).

    Security
    --------
    - Decorated with @login_required, so unauthenticated callers receive
      HTTP 401 with a small JSON error body.
    - Intended to be invoked only by Nginx via the internal location
      `/_nginx_auth`; it is not a user-facing API.
    - Uses the same session cookie and 'user' field as the rest of the API.

    Behavior
    --------
    - When the session contains a non-empty 'user':
        - Returns HTTP 200 with an `X-User` header containing the username.
    - When no authenticated session exists:
        - @login_required returns HTTP 401 with `{"error": "not authenticated"}`.
    - When a session exists but `user` cannot be resolved to a non-empty string:
        - Returns HTTP 403 to signal an invalid or incomplete session.

    Returns
    -------
    - 200 with `X-User` header when the caller is authenticated.
    - 401 when unauthenticated (via @login_required).
    - 403 when the session is present but malformed.
    """
    current_user = session.get("user")
    username = str(current_user).strip() if current_user is not None else ""

    if not username:
        # We should never get here if @login_required is working correctly,
        # but this protects against weird/empty session values.
        return jsonify({"error": "invalid session"}), 403

    response = make_response("", 200)
    response.headers["X-User"] = username
    return response

# ─────────────────────────────────────────────────────────────────────────────
# Boot & background executor wiring
# ─────────────────────────────────────────────────────────────────────────────


# Single handle for the background scheduler (daemon thread).
STOP_EVENT: Optional[threading.Event] = None


def _install_signal_handlers() -> None:
    """
    Register SIGINT/SIGTERM handlers to stop background services.
    Safe to call multiple times; handlers are replaced idempotently.
    """
    def _on_shutdown(signum, _frame):
        try:
            logger.info("[APP] received signal %s; stopping background executor", signum)
        except Exception:
            pass
        try:
            stop_background_scan_executor()
        except Exception:
            try:
                logger.exception("[APP] error while stopping background executor")
            except Exception:
                pass

    for _sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(_sig, _on_shutdown)


def _bootstrap_app() -> None:
    """
    Bring up logging, database, and long-running background services.

    Order matters:
      1) Configure logging first so subsequent init logs are captured.
      2) Initialize DB schema/seed.
      3) Start the background policy scheduler (daemon).
      4) Install signal handlers for graceful shutdown.

    Notes:
      - We DO NOT recreate `app` here. It must already be defined and configured
        above (e.g., `app = Flask(__name__)`, WhiteNoise, secrets, etc.).
      - We also respect any config already set; we only set defaults if missing.
    """
    global STOP_EVENT
    global logger
    global app

    # Sanity: app must already exist (created earlier in this file).
    if "app" not in globals() or app is None:
        raise RuntimeError("Flask `app` must be created before calling _bootstrap_app()")

    # 1) logging ( pattern)
    logger = setup_logging()
    logger.info("[APP] logging initialized")

    # 1a) ensure baseline config keys exist (don't clobber if already set earlier)
    app.config.setdefault("MAX_CONTENT_LENGTH", int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024)
    app.config.setdefault("JSON_SORT_KEYS", False)

    # 2) database
    init_db()
    logger.info("[APP] database initialized")

    # 3) background executor (daemon thread that evaluates scan policies)
    STOP_EVENT = start_background_scan_executor()
    logger.info("[APP] background scan executor started (daemon)")

    # 4) shutdown hooks
    _install_signal_handlers()
    logger.info("[APP] signal handlers installed (SIGINT/SIGTERM)")


# Kick off boot sequence at import time (WSGI workers will each run this).
_bootstrap_app()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point (dev/prod single-process launcher; prod typically uses gunicorn)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        # Start any one-off background services before Flask boots
        start_cleanup_worker_singleton()
        logger.info("[APP] cleanup worker singleton started")

        # Configure host/port/debug from env (safe for prod overrides)
        host = os.getenv("HOST", "0.0.0.0")
        port = int(os.getenv("PORT", "5000"))
        debug = os.getenv("FLASK_DEBUG", "0").strip().lower() in {"1", "true", "yes"}

        logger.info("[APP] starting Flask server on %s:%s (debug=%s)", host, port, debug)
        app.run(host=host, port=port, debug=debug)

    except Exception:
        logger.exception("[APP] fatal error during startup")

    finally:
        # Always stop the background scan executor gracefully
        try:
            stop_background_scan_executor()
            logger.info("[APP] background scan executor stopped cleanly")
        except Exception:
            logger.exception("[APP] error during executor shutdown")

