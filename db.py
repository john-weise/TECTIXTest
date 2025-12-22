# db.py
from __future__ import annotations
from typing import Optional, Dict, List, Any, Iterable, Tuple
from werkzeug.security import generate_password_hash, check_password_hash
from log_config import setup_logging

# --- SQLAlchemy imports ---
import os
from datetime import datetime, timezone, time, timedelta
import enum
import json
from pathlib import Path
from sqlalchemy import (
    create_engine,
    Integer,
    String,
    DateTime,
    Time,
    select,
    func,
    Boolean,
    update,
    BigInteger,
    Enum,
    ForeignKey,
    JSON,
    Text,
    UniqueConstraint,
    Index,
    CheckConstraint,
    Select,
    and_,
    desc,
)
import pandas as pd
from sqlalchemy.dialects.sqlite import INTEGER 
import uuid
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    sessionmaker,
    Session,
    relationship,
)
from helpers import compute_readiness_summary
from models import ATOStatus


logger = setup_logging()

_DEFAULT_ADMIN_USERNAME = "TECTIX"
_DEFAULT_ADMIN_PASSWORD = "TECTIXAdmin"

# =============================================================================
# Engine / Session setup
# =============================================================================

# Prefer DATABASE_URL (e.g., "postgresql+psycopg://user:pass@host/db"); fall back to local SQLite.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///systems.sqlite3")

_engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # handle dropped connections in long-lived processes
    future=True,
)
_SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, class_=Session)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


def get_session() -> Session:
    """
    Factory for a new SQLAlchemy Session.

    Prefer dependency-injected sessions in request handlers and tests so you can
    control commit/rollback lifecycles explicitly.
    """
    return _SessionLocal()



# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------

class FrequencyEnum(str, enum.Enum):
    """Supported scan frequencies."""
    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"   # supports "nth weekday-of-month" (e.g., 3rd Sunday)


class DayOfWeek(str, enum.Enum):
    """Python weekday index mapping: Monday=0 .. Sunday=6."""
    MONDAY    = "Monday"
    TUESDAY   = "Tuesday"
    WEDNESDAY = "Wednesday"
    THURSDAY  = "Thursday"
    FRIDAY    = "Friday"
    SATURDAY  = "Saturday"
    SUNDAY    = "Sunday"

    @property
    def index(self) -> int:
        mapping = {
            DayOfWeek.MONDAY: 0,
            DayOfWeek.TUESDAY: 1,
            DayOfWeek.WEDNESDAY: 2,
            DayOfWeek.THURSDAY: 3,
            DayOfWeek.FRIDAY: 4,
            DayOfWeek.SATURDAY: 5,
            DayOfWeek.SUNDAY: 6,
        }
        return mapping[self]


class TestCategory(enum.Enum):
    SYSTEM = "System"
    PACKAGE = "Package"
    MANAGEMENT = "Management"
    RELATIONSHIPS = "Relationships"
    ARTIFACTS = "Artifacts"
    ASSETS = "Assets"
    CONTROLS = "Controls"
    POAMS = "POA&Ms"  


class ResultStatus(enum.Enum):
    PASS_ = "PASS"
    FAIL = "FAIL"
    CONCERN = "CONCERN"
    # Add optional statuses if they appear in other feeds:
    NA = "N/A"          # not always used
    UNKNOWN = "UNKNOWN" # parser fallback


class ReworkAction(enum.Enum):
    YES = "Yes"
    NO = "No"
    NO_FURTHER_ACTION = "No Further Action Required"
    NO_ADD_TERMS = "No-Add to Terms & Conditions"
    ISO_OSTC = "ISO - On the Spot Correction Suffices"

# =============================================================================
# ORM Models
# =============================================================================

class User(Base):
    """Application user account.

    This model stores authentication and authorization data for a single user,
    including optional TOTP-based 2FA configuration and recovery codes.

    Attributes:
        username: Unique username for the account. Serves as the primary key.
        password_hash: Hashed password for the user (e.g., using bcrypt or argon2).
        is_admin: Whether the user has administrative privileges.

        twofa_enabled: Whether TOTP-based two-factor authentication is enabled
            for this user.
        twofa_secret: Base32-encoded TOTP secret used to generate one-time
            passwords. ``None`` if 2FA is not configured.
        twofa_recovery_codes: Optional serialized collection (e.g., JSON or a
            delimited string) of *hashed* recovery codes that can be used when
            TOTP codes are unavailable. ``None`` if no recovery codes exist.

        created_at: Timestamp when the user record was created.
        updated_at: Timestamp when the user record was last updated.
    """
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- 2FA fields ---
    twofa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    twofa_secret: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    twofa_recovery_codes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SystemCsv(Base):
    """
    Minimal table mapping a numeric system_id to a CSV filepath.

    Notes:
        - system_id is the natural key (PRIMARY KEY).
        - csv_path is normalized to an absolute path before persistence (may be NULL).
        - updated_at tracks last write time by the app.
        - last_scanned records the last successful scan time (NULL means never).
        - scan_policy is a human-readable string identifying which scan policy
          applies to this system (may be NULL).
    """
    __tablename__ = "system_csv"

    system_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    csv_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now()
    )
    last_scanned: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=False), nullable=True, default=None
    )
    scan_policy: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, default=None
    )



class ScanPolicy(Base):
    """
    Defines a recurring scan schedule policy.

    Fields:
        name (unique): Human-readable unique key. `SystemCsv.scan_policy` will
                       reference this value for lookup.
        frequency:     One of FrequencyEnum (DAILY, WEEKLY, BIWEEKLY, MONTHLY).
        time_of_day:   UTC time to run.
        day_of_week:   Required for WEEKLY and MONTHLY; optional for BIWEEKLY
                       (if provided, used to derive a default anchor).
        week_of_month: Required for MONTHLY; 1..5 (5 = "fifth if exists else last").
        anchor_epoch:  Optional UNIX epoch (UTC) establishing cadence origin
                       for strict BIWEEKLY (+14d multiples).
        last_run_epoch: Optional UNIX epoch (UTC) of last successful run.

    Notes:
        - All epoch computations are performed in UTC.
        - For BIWEEKLY, next time is computed strictly as anchor/last_run + 14d
          multiples. If neither anchor nor last_run is present, we derive an
          initial anchor from day_of_week/time_of_day (if set), else time_of_day
          today/tomorrow; callers should persist it to `anchor_epoch`.
    """
    __tablename__ = "scan_policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)

    frequency: Mapped[FrequencyEnum] = mapped_column(SqlEnum(FrequencyEnum), nullable=False)
    time_of_day: Mapped[time] = mapped_column(Time, nullable=False)

    # For WEEKLY/BIWEEKLY and MONTHLY variants
    day_of_week: Mapped[Optional[DayOfWeek]] = mapped_column(SqlEnum(DayOfWeek), nullable=True)

    # For MONTHLY (nth weekday-of-month like "3rd Sunday")
    week_of_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1..5

    # BIWEEKLY cadence anchors (UTC epoch seconds)
    anchor_epoch: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    last_run_epoch: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)




# --------------------------
# Result storage Entities 
# --------------------------



# --- Core entities -----------------------------------------------------------

class System(Base):
    """A system under test (SUT). Skeletal; used only to group runs."""
    __tablename__ = "systems"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    external_ref: Mapped[Optional[str]] = mapped_column(String(64), unique=True)  # e.g., eMASS ID
    name: Mapped[Optional[str]] = mapped_column(String(256), index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    runs: Mapped[list["TestRun"]] = relationship(
        back_populates="system", cascade="all, delete-orphan"
    )

class TestOutcome(Base):
    __tablename__ = "test_outcomes"
    __table_args__ = (
        UniqueConstraint("run_id", "test_id", name="uq_outcome_run_test"),
        Index("ix_outcomes_run_status", "run_id", "status"),
        {"sqlite_autoincrement": True},  # optional
    )

    # MUST be Integer in SQLite for rowid autogen
    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    run_id: Mapped[str] = mapped_column(
        ForeignKey("test_runs.id", ondelete="CASCADE"), index=True
    )

    # make sure this matches TestCatalog.id type (you already switched that to Integer)
    test_id: Mapped[int] = mapped_column(
        ForeignKey("test_catalog.id", ondelete="CASCADE"), index=True
    )

    status: Mapped[ResultStatus] = mapped_column(Enum(ResultStatus), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    facts_json: Mapped[dict] = mapped_column(JSON, default=dict)

    run: Mapped["TestRun"] = relationship(back_populates="outcomes")
    test: Mapped["TestCatalog"] = relationship(back_populates="results")


class TestCatalog(Base):
    __tablename__ = "test_catalog"
    __table_args__ = {"sqlite_autoincrement": True}  # optional but nice to have

    # Use Integer here (rowid in SQLite) — NOT BigInteger
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # or INTEGER if you want dialect-specific

    test_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    test_code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    display_name: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    results: Mapped[list["TestOutcome"]] = relationship(
        back_populates="test", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("test_number", name="uq_testcatalog_number"),
        Index("ix_testcatalog_number", "test_number"),
        {"sqlite_autoincrement": True},  # keep if you also keep the tuple table_args
    )



class TestRun(Base):
    """One execution of the test suite for a single system.

    This table stores:
      * Timing metadata (start/finish timestamps and duration).
      * Optional adornments for traceability (job_id, label, environment, etc.).
      * Rollups derived from ATOStatus (per-status counts + total).
      * Optional readiness score (0–100) derived from pass/fail/concern counts.

    The readiness score mirrors the backend helper:

        score = pass / (pass + fail + concern)

    where the result is rounded to an integer percentage. When the score cannot
    be computed (e.g., no considered tests), this field remains NULL.
    """

    __tablename__ = "test_runs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    system_id: Mapped[int] = mapped_column(
        ForeignKey("systems.id", ondelete="CASCADE"),
        index=True,
    )

    # Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        index=True,
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)

    # Optional adornments
    scan_label: Mapped[Optional[str]] = mapped_column(String(128))   # e.g. “nightly-2025-11-05”
    job_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    script_version: Mapped[Optional[str]] = mapped_column(String(64))
    commit_hash: Mapped[Optional[str]] = mapped_column(String(64))
    environment: Mapped[Optional[str]] = mapped_column(String(32))
    data_path: Mapped[Optional[str]] = mapped_column(String(512))
    system_name: Mapped[Optional[str]] = mapped_column(
        String(256)
    )  # passthrough from ATOStatus.system_name
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    # Rollups from ATOStatus
    total_tests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pass_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    concern_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    na_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Optional readiness score (0–100), derived from pass/fail/concern counts.
    # When no tests are "considered" for scoring, this field should remain NULL.
    readiness_score_pct: Mapped[Optional[int]] = mapped_column(Integer)

    system: Mapped["System"] = relationship(back_populates="runs")
    outcomes: Mapped[list["TestOutcome"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_runs_system_started", "system_id", "started_at"),
        CheckConstraint("total_tests >= 0", name="ck_test_runs_total_tests_nonnegative"),
        CheckConstraint(
            "readiness_score_pct IS NULL OR (readiness_score_pct >= 0 AND readiness_score_pct <= 100)",
            name="ck_test_runs_readiness_score_pct_range",
        ),
    )







# =============================================================================
# Initialization
# =============================================================================

def init_db() -> None:
    """
    Create all tables if they don't exist and seed default users.

    This is idempotent and safe to call at process startup.
    """
    Base.metadata.create_all(_engine)
    logger.info("[DB] Initialized schema at %s", DATABASE_URL)

    # Seed a few defaults if they don't already exist.
    defaults = [
        ("TECTIX", "TECTIXAdmin", True)
    ]
    with get_session() as session:
        changed = False
        for uname, pwd, admin in defaults:
            if not session.get(User, uname):
                session.add(User(
                    username=uname,
                    password_hash=generate_password_hash(pwd),
                    is_admin=admin,
                ))
                logger.info("[USERS] Seeded user '%s' (admin=%s)", uname, admin)
                changed = True
        if changed:
            session.commit()


# =============================================================================
# Users API (backward-compatible function names)
# =============================================================================

# Dummy hash used to normalize work for non-existent users. Helps resist timing attacks
_DUMMY_PASSWORD_HASH = generate_password_hash("dummy-password-for-timing-only")


def verify_user(username: str, password: str) -> Optional[Dict]:
    """Verifies a user's credentials and returns an auth context.

    This function looks up the user by username, validates the provided
    plaintext password against a password hash, and returns a minimal user
    context on success.

    To reduce username-enumeration timing side-channels, it always performs
    a password-hash check, even if the user does not exist, by using a
    dummy hash in that case.

    Args:
        username: The unique username identifying the user.
        password: The plaintext password to validate for the given user.

    Returns:
        A dictionary with the following keys on successful authentication:
            - "username": The username of the authenticated user.
            - "is_admin": Whether the user has administrative privileges.
            - "twofa_enabled": Whether TOTP-based 2FA is enabled for the user.
        Returns ``None`` if authentication fails or the user cannot be found.

    Notes:
        This function does not perform 2FA verification; it only reports
        whether 2FA is enabled for the user so that the caller can enforce
        a second step if required. It also deliberately performs a password
        hash comparison for both existing and non-existing users to make
        timing differences less informative to an attacker.
    """
    with get_session() as session:
        row = session.get(User, username)

        # Always perform a hash check to normalize work.
        if row is not None:
            pw_hash = row.password_hash
        else:
            pw_hash = _DUMMY_PASSWORD_HASH

        try:
            password_ok = check_password_hash(pw_hash, password)
        except Exception:
            # Malformed hash, unsupported algorithm, etc.
            password_ok = False

        if row is not None and password_ok:
            return {
                "username": row.username,
                "is_admin": row.is_admin,
                "twofa_enabled": getattr(row, "twofa_enabled", False),
            }

    return None

def list_users() -> List[Dict]:
    """List all users (no password hashes).

    Returns:
        List[Dict]: A list of user records, where each record contains:
            - "username": str
            - "is_admin": bool
            - "twofa_enabled": bool
    """
    with get_session() as session:
        stmt = (
            select(
                User.username,
                User.is_admin,
                User.twofa_enabled,
            )
            .order_by(User.username.asc())
        )
        rows = session.execute(stmt).all()

        return [
            {
                "username": username,
                "is_admin": is_admin,
                "twofa_enabled": bool(twofa_enabled),
            }
            for (username, is_admin, twofa_enabled) in rows
        ]



def add_user(username: str, password: str, is_admin: bool = False) -> None:
    """
    Create (or overwrite) a user.

    Behavior:
        - If the user exists, updates password + is_admin.
        - Otherwise, inserts a new row.
    """
    with get_session() as session:
        row = session.get(User, username)
        if row:
            row.password_hash = generate_password_hash(password)
            row.is_admin = bool(is_admin)
            logger.info("[USERS] Updated user '%s' (admin=%s)", username, is_admin)
        else:
            session.add(User(
                username=username,
                password_hash=generate_password_hash(password),
                is_admin=bool(is_admin),
            ))
            logger.info("[USERS] Created user '%s' (admin=%s)", username, is_admin)
        session.commit()


def remove_user(username: str) -> None:
    """
    Delete a user by username. No-op if user does not exist.
    """
    with get_session() as session:
        row = session.get(User, username)
        if row:
            session.delete(row)
            session.commit()
            logger.info("[USERS] Removed user '%s'", username)
        else:
            logger.warning("[USERS] remove_user: user '%s' not found", username)


def get_user(username: str) -> Optional[Dict]:
    """
    Fetch a user by username.
    """
    with get_session() as session:
        row = session.get(User, username)
        if row:
            return {
                "username": row.username,
                "is_admin": row.is_admin,
                "twofa_enabled": getattr(row, "twofa_enabled", False),
            }
    return None


def change_own_password(username: str, current_password: str, new_password: str) -> bool:
    """
    Change password for `username`, validating the current password.

    Returns:
        True on success, False on failure (bad user or bad current password).
    """
    with get_session() as session:
        row = session.get(User, username)
        if not row:
            logger.warning("[USERS] change_own_password: user not found '%s'", username)
            return False
        if not check_password_hash(row.password_hash, current_password):
            logger.warning("[USERS] change_own_password: bad password for '%s'", username)
            return False
        row.password_hash = generate_password_hash(new_password)
        session.commit()
        logger.info("[USERS] Password changed for '%s'", username)
        return True




def compute_dashboard_flags(username: str) -> Dict[str, bool]:
    """Computes per-user dashboard flags for post-login UX.

    This helper inspects the authenticated user's record to derive a set of
    boolean flags that drive conditional UI behavior on the dashboard. It
    detects whether the user is still using the factory default admin
    credentials and exposes whether TOTP-based 2FA is enabled for the account.

    The intent is to keep all “what should the dashboard show?” logic in one
    place so that the frontend can rely on a stable, boolean-only contract.

    Args:
        username: The authenticated user's username.

    Returns:
        Dict[str, bool]: A mapping with the following keys:
            - is_default_admin: True if the user is the factory admin and the
              stored password hash still validates against the factory password.
            - needs_password_reset: True when the account appears to be on a
              default/temporary password (currently mirrors ``is_default_admin``).
            - show_welcome: Whether to show the one-time “Welcome to TECTIX”
              modal (currently mirrors ``is_default_admin``).
            - twofa_enabled: True if the user's account has TOTP-based 2FA
              enabled according to the ORM model; False if disabled or the
              column is absent.

    Raises:
        KeyError: If the user row does not exist. Callers should treat this as
            an unauthenticated or invalid session (for example, clear cookies
            and return HTTP 401).

    Notes:
        This function does not itself enforce security policies such as 2FA
        verification or password rotation. It only surfaces state so that
        higher layers (e.g., route handlers or the frontend) can decide what
        to display or require.
    """
    with get_session() as sess:
        row = sess.get(User, username)
        if row is None:
            raise KeyError(f"user not found: {username!r}")

        # Default admin detection: username must match AND the stored hash must
        # still validate against the password.
        try:
            is_default_admin = (
                row.username == _DEFAULT_ADMIN_USERNAME
                and bool(check_password_hash(row.password_hash, _DEFAULT_ADMIN_PASSWORD))
            )
        except Exception:
            # Security fix: if the stored hash is malformed, don't misclassify it.
            is_default_admin = False

        needs_password_reset = is_default_admin
        show_welcome = is_default_admin

        #2FA flag for dashboard UX
        twofa_enabled = getattr(row, "twofa_enabled", False)

        return {
            "is_default_admin": is_default_admin,
            "needs_password_reset": needs_password_reset,
            "show_welcome": show_welcome,
            "twofa_enabled": twofa_enabled,
        }

#==============================================================================
#           2-Factor Auth Helpers
#==============================================================================




def get_twofa_flags(username: str) -> Dict[str, bool]:
    """Gets the 2FA state flags for a user.

    Args:
      username: The username of the user to query.

    Returns:
      A dict with:
        enabled: True if 2FA is enforced for this user.
        configured: True if a secret exists, even if 2FA is not enabled.

    Raises:
      KeyError: If the user does not exist.
    """
    with get_session() as session:
        row = session.get(User, username)
        if row is None:
            raise KeyError(f"user not found: {username!r}")

        secret_present = bool(getattr(row, "twofa_secret", None))
        enabled = bool(getattr(row, "twofa_enabled", False))

        return {
            "enabled": enabled,
            "configured": secret_present,
        }


def is_twofa_enabled(username: str) -> bool:
    """Returns whether 2FA is currently enabled for a user.

    Args:
      username: The username of the user to query.

    Returns:
      True if the user exists and 2FA is enabled; False otherwise.
    """
    try:
        flags = get_twofa_flags(username)
    except KeyError:
        return False
    return flags["enabled"]


def set_twofa_enrollment(username: str, secret: str, hashed_recovery_codes: List[str]) -> None:
    """Sets the 2FA enrollment state for a user.

    This function stores the TOTP secret and recovery codes and marks
    2FA as not yet enabled. It is used to begin or reset 2FA enrollment.

    Args:
      username: The username of the user to update.
      secret: The base32-encoded TOTP secret.
      hashed_recovery_codes: A list of hashed recovery codes to store.

    Raises:
      KeyError: If the user does not exist.
    """
    with get_session() as session:
        row = session.get(User, username)
        if row is None:
            raise KeyError(f"user not found: {username!r}")

        row.twofa_secret = secret
        row.twofa_enabled = False
        row.twofa_recovery_codes = json.dumps(list(hashed_recovery_codes))
        session.commit()
        logger.info("[2FA] Enrollment reset for user '%s'", username)


def enable_twofa(username: str) -> None:
    """Enables 2FA for a user.

    This function sets the twofa_enabled flag to True. It assumes a
    valid TOTP secret is already stored.

    Args:
      username: The username of the user to update.

    Raises:
      KeyError: If the user does not exist.
      ValueError: If the user does not have a TOTP secret configured.
    """
    with get_session() as session:
        row = session.get(User, username)
        if row is None:
            raise KeyError(f"user not found: {username!r}")

        if not getattr(row, "twofa_secret", None):
            raise ValueError("Cannot enable 2FA for user without a secret")

        row.twofa_enabled = True
        session.commit()
        logger.info("[2FA] Enabled for user '%s'", username)


def disable_twofa(username: str) -> None:
    """Disables 2FA for a user and clears 2FA-related fields.

    Args:
      username: The username of the user to update.

    Raises:
      KeyError: If the user does not exist.
    """
    with get_session() as session:
        row = session.get(User, username)
        if row is None:
            raise KeyError(f"user not found: {username!r}")

        row.twofa_enabled = False
        row.twofa_secret = None
        row.twofa_recovery_codes = None
        session.commit()
        logger.info("[2FA] Disabled for user '%s'", username)


def get_twofa_secret(username: str) -> Optional[str]:
    """Gets the TOTP secret for a user.

    Args:
      username: The username of the user to query.

    Returns:
      The base32-encoded TOTP secret if present, or None if no secret
      is configured for the user.

    Raises:
      KeyError: If the user does not exist.
    """
    with get_session() as session:
        row = session.get(User, username)
        if row is None:
            raise KeyError(f"user not found: {username!r}")

        return getattr(row, "twofa_secret", None)


def get_twofa_recovery_hashes(username: str) -> List[str]:
    """Gets the stored hashed recovery codes for a user.

    Args:
      username: The username of the user to query.

    Returns:
      A list of hashed recovery codes. Returns an empty list if no
      recovery codes are stored.

    Raises:
      KeyError: If the user does not exist.
    """
    with get_session() as session:
        row = session.get(User, username)
        if row is None:
            raise KeyError(f"user not found: {username!r}")

        raw = getattr(row, "twofa_recovery_codes", None)
        if not raw:
            return []

        try:
            codes = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            logger.error("[2FA] Malformed recovery codes for user '%s'", username)
            return []

        # Ensure list of strings.
        return [str(c) for c in codes]


def set_twofa_recovery_hashes(username: str, hashed_codes: List[str]) -> None:
    """Sets the stored hashed recovery codes for a user.

    Args:
      username: The username of the user to update.
      hashed_codes: The list of hashed recovery codes to store.

    Raises:
      KeyError: If the user does not exist.
    """
    with get_session() as session:
        row = session.get(User, username)
        if row is None:
            raise KeyError(f"user not found: {username!r}")

        row.twofa_recovery_codes = json.dumps(list(hashed_codes))
        session.commit()
        logger.info("[2FA] Updated recovery codes for user '%s'", username)



# -----------------------------------------------------------------------------
# Helpers for path normalization and conversions
# -----------------------------------------------------------------------------

# replace previous normalization helper
def _normalize_csv_path(csv_path: Optional[str]) -> Optional[str]:
    """
    Normalize to an absolute filesystem path if provided; allow None.

    This supports pre-provisioned systems that don't yet have a CSV.
    """
    if csv_path is None or str(csv_path).strip() == "":
        return None
    return str(Path(csv_path).expanduser().resolve())


def _row_to_dict(row: SystemCsv) -> Dict[str, Any]:
    return {
        "system_id": row.system_id,
        "csv_path": row.csv_path,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _normalize_policy_label(policy: Optional[str]) -> Optional[str]:
    """
    Normalize a scan-policy label.

    Parameters
    ----------
    policy:
        Raw policy label or ``None``.

    Returns
    -------
    Optional[str]
        Stripped policy label or ``None`` when input is ``None`` or empty/whitespace.
    """
    if not isinstance(policy, str):
        return None
    policy = policy.strip()
    return policy or None

# -----------------------------------------------------------------------------
# Scheduling helpers (Used for policy stuffs)
# -----------------------------------------------------------------------------

def _to_frequency_enum(val) -> FrequencyEnum:
    """Accept FrequencyEnum or raw string ('daily', 'weekly', etc.)."""
    if isinstance(val, FrequencyEnum):
        return val
    if isinstance(val, str):
        return FrequencyEnum(val)
    raise ValueError(f"Invalid frequency: {val!r}")

def _to_dayofweek_enum(val) -> Optional[DayOfWeek]:
    """Accept DayOfWeek, raw string ('Monday'..'Sunday'), or None."""
    if val is None:
        return None
    if isinstance(val, DayOfWeek):
        return val
    if isinstance(val, str):
        return DayOfWeek(val)
    raise ValueError(f"Invalid day_of_week: {val!r}")



def get_all_policies() -> List[ScanPolicy]:
    """
    Return all ScanPolicy rows.

    Notes:
        - Session lifecycle is managed internally.
        - Returns ORM instances detached from session scope (expire_on_commit=False).
    """
    with get_session() as session:
        return session.execute(select(ScanPolicy)).scalars().all()


def get_enrolled_system_ids(session: Session, policy_name: str) -> List[int]:
    """
    Return system_ids enrolled to the given policy name.

    This is a thin alias over `list_systems_by_policy` to keep scheduler imports
    stable and the DB logic centralized here.
    """
    return list_systems_by_policy(session, policy_name)



def stamp_policy_last_run_now(policy_id: int, *, session: Optional[Session] = None) -> bool:
    """Stamp `scan_policy.last_run_epoch` to the current UTC epoch seconds.

    This mirrors the scheduler's semantics: we record that the policy has
    been evaluated/triggered *now* so the next due-window pass won't re-fire
    the same minute. Call it after you dispatch scans (or when skipping an
    empty policy), regardless of individual system scan outcomes.

    Args:
        policy_id: Primary key of the `ScanPolicy` to stamp.
        session:   Optional existing SQLAlchemy Session. If omitted, a short
                   session/transaction is created and committed internally.

    Returns:
        bool: True if an existing row was updated (rowcount == 1), False if
              the policy id didn't exist (rowcount == 0).

    Raises:
        Any SQLAlchemy exception encountered during execution; callers that
        pass an external `session` are responsible for rollback handling.
    """
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    owns_session = session is None

    if owns_session:
        with get_session() as session:
            result = session.execute(
                update(ScanPolicy)
                .where(ScanPolicy.id == policy_id)
                .values(last_run_epoch=now_epoch, updated_at=datetime.utcnow())
            )
            # SQLAlchemy 2.x: result.rowcount is reliable for UPDATE
            return (result.rowcount or 0) > 0

    # Use caller-managed session (no commit here—caller decides)
    result = session.execute(
        update(ScanPolicy)
        .where(ScanPolicy.id == policy_id)
        .values(last_run_epoch=now_epoch, updated_at=datetime.utcnow())
    )
    return (result.rowcount or 0) > 0




def _parse_iso8601(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601–style timestamp into a naive UTC datetime.

    This helper is tolerant of several common variants and always returns a
    **naive** ``datetime`` normalized to UTC when parsing succeeds.

    Supported forms include (non-exhaustive):

    * ``"2025-11-08T15:15:36Z"``
    * ``"2025-11-08T15:15:36.735419Z"``
    * ``"2025-11-08T15:15:36+00:00"``
    * ``"2025-11-08 15:15:36"``

    Args:
        value: Timestamp value to parse. May be a :class:`datetime` instance,
            string, or any object that can be meaningfully converted to string.

    Returns:
        A naive :class:`datetime` instance in UTC on success; otherwise ``None``.

    Notes:
        - Aware datetimes are converted to UTC and then stripped of tzinfo.
        - On failure, this function logs a warning and returns ``None``.
    """
    if value is None:
        return None

    # Already a datetime: normalize to naive UTC.
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.replace(tzinfo=None)

    text = str(value).strip()
    if not text:
        return None

    # First, try the modern/ISO path.
    try:
        if text.endswith("Z"):
            # Attempt the "+00:00" trick first to leverage fromisoformat.
            try:
                dt = datetime.fromisoformat(text[:-1] + "+00:00")
            except ValueError:
                # Fallback for e.g. "2025-11-08T15:15:36.735419Z" on older runtimes.
                dt = None
                for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
                    try:
                        dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
                if dt is None:
                    raise
        else:
            dt = datetime.fromisoformat(text)

        # Normalize any aware datetime to naive UTC.
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    except (ValueError, TypeError):
        # Fallback: a couple of common non-Z, non-offset formats.
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue

        logger.warning("Could not parse timestamp: %r", value)
        return None



def _coerce_int(v: Any) -> Optional[int]:
    """Return `int(v)` if possible, else None."""
    try:
        return int(v) if v is not None else None
    except Exception:
        return None


def _to_enum(value: Any, enum_cls: enum.EnumMeta, *, default=None):
    """
    Best-effort mapping of strings or enum instances to a target Enum member.

    Matches against both .name and .value (case-insensitive).
    """
    if value is None:
        return default
    if isinstance(value, enum_cls):
        return value
    s = str(value).strip()
    for member in enum_cls:
        if s.lower() == str(member.value).lower() or s.lower() == member.name.lower():
            return member
    return default


def _category_from_str(raw: Optional[str]) -> TestCategory:
    """
    Map free-form category text to TestCategory enum; default to SYSTEM.
    """
    if raw:
        hit = _to_enum(raw, TestCategory)
        if hit is not None:
            return hit
    return TestCategory.SYSTEM
    
# -----------------------------------------------------------------------------
# Scheduling helpers (pure)
# -----------------------------------------------------------------------------

def compute_next_scan_epoch(
    *,
    frequency: FrequencyEnum,
    time_of_day: time,
    day_of_week: Optional[DayOfWeek],
    week_of_month: Optional[int],
    anchor_epoch: Optional[int],
    last_run_epoch: Optional[int],
    now_utc: Optional[datetime] = None,
) -> int:
    """
    Compute the next scan time (UTC) as UNIX epoch given a policy definition.

    Behavior:
        DAILY:    today at time_of_day if in future, else tomorrow.
        WEEKLY:   next occurrence of day_of_week at time_of_day (within 7 days).
        BIWEEKLY: strict +14-day cadence from (last_run_epoch or anchor_epoch).
                  If neither set, derive an anchor (see below) and return that.
        MONTHLY:  Nth occurrence of day_of_week in this month at time_of_day;
                  if that datetime <= now, compute for next month. When nth=5
                  and the 5th doesn't exist, use the last such weekday of month.

    BIWEEKLY anchor derivation (used only if both anchor and last_run are None):
        - If day_of_week provided: next upcoming {day_of_week} at time_of_day (UTC).
        - Else: today at time_of_day (or +14 days if already passed).

    All computations are in UTC.

    Raises:
        ValueError for invalid/missing required parameters.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    elif now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    today = now_utc.date()
    base_today = datetime.combine(today, time_of_day, tzinfo=timezone.utc)

    if frequency == FrequencyEnum.DAILY:
        nxt = base_today if base_today > now_utc else base_today + timedelta(days=1)
        return int(nxt.timestamp())

    if frequency == FrequencyEnum.WEEKLY:
        if day_of_week is None:
            raise ValueError("day_of_week is required for WEEKLY schedules.")
        days_ahead = (day_of_week.index - now_utc.weekday()) % 7
        candidate = base_today + timedelta(days=days_ahead)
        if candidate <= now_utc:
            candidate += timedelta(days=7)
        return int(candidate.timestamp())

    if frequency == FrequencyEnum.BIWEEKLY:
        # Strict cadence using last_run or anchor
        origin_epoch = last_run_epoch if last_run_epoch is not None else anchor_epoch
        if origin_epoch is not None:
            origin_dt = datetime.fromtimestamp(origin_epoch, tz=timezone.utc)
            # Next is the smallest origin + 14k days strictly greater than now
            delta_days = 14
            candidate = origin_dt
            # If origin is in the past, roll forward by 14-day blocks
            while candidate <= now_utc:
                candidate += timedelta(days=delta_days)
            # Snap candidate's time to time_of_day if you want anchor to control only cadence:
            candidate = candidate.replace(hour=time_of_day.hour, minute=time_of_day.minute,
                                          second=time_of_day.second, microsecond=0)
            # Ensure still > now after snapping
            if candidate <= now_utc:
                candidate += timedelta(days=delta_days)
            return int(candidate.timestamp())

        # Derive initial anchor on-the-fly (not persisted here)
        if day_of_week is not None:
            days_ahead = (day_of_week.index - now_utc.weekday()) % 7
            candidate = base_today + timedelta(days=days_ahead)
            if candidate <= now_utc:
                candidate += timedelta(days=14)  # first cadence point in the future
            return int(candidate.timestamp())

        # No weekday constraint → today at time, else +14
        candidate = base_today if base_today > now_utc else base_today + timedelta(days=14)
        return int(candidate.timestamp())

    if frequency == FrequencyEnum.MONTHLY:
        if day_of_week is None or not isinstance(week_of_month, int) or not (1 <= week_of_month <= 5):
            raise ValueError("MONTHLY requires day_of_week and week_of_month in 1..5.")

        candidate_date = _nth_weekday_of_month(
            year=today.year,
            month=today.month,
            weekday_index=day_of_week.index,
            nth=week_of_month,
        )
        candidate_dt = datetime.combine(candidate_date, time_of_day, tzinfo=timezone.utc)

        if candidate_dt <= now_utc:
            next_year, next_month = _add_month(today.year, today.month, 1)
            candidate_date = _nth_weekday_of_month(
                year=next_year,
                month=next_month,
                weekday_index=day_of_week.index,
                nth=week_of_month,
            )
            candidate_dt = datetime.combine(candidate_date, time_of_day, tzinfo=timezone.utc)

        return int(candidate_dt.timestamp())

    raise ValueError(f"Unsupported frequency: {frequency}")


def _nth_weekday_of_month(*, year: int, month: int, weekday_index: int, nth: int) -> date:
    """
    Return the date of the Nth (1..5) given weekday in a specific month/year.

    If nth==5 and the 5th occurrence does not exist for the month, returns the
    *last* occurrence of that weekday in the month.
    """
    if not (1 <= nth <= 5):
        raise ValueError("nth must be in 1..5.")

    first = date(year, month, 1)
    first_wd = first.weekday()  # Monday=0..Sunday=6
    days_to_first_target = (weekday_index - first_wd) % 7
    first_occurrence = first + timedelta(days=days_to_first_target)

    # 1st..4th straightforward
    candidate = first_occurrence + timedelta(days=7 * (nth - 1))
    if nth <= 4:
        return candidate

    # nth == 5 → return 5th if it exists, else last (4th)
    fifth = first_occurrence + timedelta(days=28)
    return fifth if fifth.month == month else (first_occurrence + timedelta(days=21))


def _add_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """Add delta months to (year, month) and return normalized (year, month)."""
    z = (month - 1) + delta
    return (year + z // 12, (z % 12) + 1)


# -----------------------------------------------------------------------------
# Public API: CRUD-ish helpers for the SystemCsv store
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# System CSV store:  Reads
# -----------------------------------------------------------------------------

def get_system_csv_path(session: Session, system_id: int) -> Optional[str]:
    """
    Return the normalized CSV path for a system.

    Parameters
    ----------
    session:
        Active SQLAlchemy session (caller manages transaction).
    system_id:
        Numeric system identifier (primary key).

    Returns
    -------
    Optional[str]
        Absolute CSV path if present, otherwise ``None``.
    """
    row = session.get(SystemCsv, system_id)
    return row.csv_path if row else None


def get_scan_policy(session: Session, system_id: int) -> Optional[str]:
    """
    Return the scan-policy label for a system.

    Parameters
    ----------
    session:
        Active SQLAlchemy session (caller manages transaction).
    system_id:
        Numeric system identifier (primary key).

    Returns
    -------
    Optional[str]
        Scan-policy label if present, otherwise ``None``.
    """
    row = session.get(SystemCsv, system_id)
    return row.scan_policy if row else None


def get_last_scanned(session: Session, system_id: int) -> Optional[datetime]:
    """
    Return the last successful scan timestamp for a system.

    Parameters
    ----------
    session:
        Active SQLAlchemy session (caller manages transaction).
    system_id:
        Numeric system identifier (primary key).

    Returns
    -------
    Optional[datetime]
        UTC timestamp of the last successful scan, or ``None`` if never.
    """
    row = session.get(SystemCsv, system_id)
    return row.last_scanned if row else None


# -----------------------------------------------------------------------------
# System CSV store: Writes / upserts
# -----------------------------------------------------------------------------

def set_system_csv_path(
    session: Session,
    system_id: int,
    csv_path: Optional[str],
    *,
    scan_policy: Optional[str] = None,
    preserve_existing_policy: bool = True,
) -> None:
    """
    Upsert the CSV path for a system and optionally assign a scan-policy label.

    The CSV path is normalized to an absolute path when provided; falsy inputs
    (``None``, empty string) are persisted as ``NULL``. The upsert is idempotent.

    Parameters
    ----------
    session:
        Active SQLAlchemy session. Caller is responsible for commit/rollback.
    system_id:
        Numeric system identifier (primary key).
    csv_path:
        Path to a CSV file or ``None``. Falsy values store as ``NULL``.
    scan_policy:
        Optional human-readable policy label (e.g., ``"Policy 1"``).
        Empty/whitespace values are normalized to ``NULL``.
    preserve_existing_policy:
        When ``True`` and ``scan_policy`` is ``None``, the stored policy is left
        unchanged. When ``False``, the stored policy will be overwritten with
        the provided value (including ``NULL``).

    Raises
    ------
    TypeError
        If ``system_id`` is not an ``int``.

    Notes
    -----
    This function does **not** commit the transaction.
    """
    if not isinstance(system_id, int):
        raise TypeError("system_id must be an int")

    normalized_path = _normalize_csv_path(csv_path)
    normalized_policy = _normalize_policy_label(scan_policy)
    now = datetime.utcnow()

    row = session.get(SystemCsv, system_id)
    if row:
        row.csv_path = normalized_path
        row.updated_at = now
        if normalized_policy is not None or not preserve_existing_policy:
            row.scan_policy = normalized_policy
        logger.info(
            "[SYSTEMS] Updated system_id=%s csv_path=%s scan_policy=%s",
            system_id, normalized_path, row.scan_policy,
        )
    else:
        session.add(SystemCsv(
            system_id=system_id,
            csv_path=normalized_path,
            updated_at=now,
            scan_policy=normalized_policy,
        ))
        logger.info(
            "[SYSTEMS] Inserted system_id=%s csv_path=%s scan_policy=%s",
            system_id, normalized_path, normalized_policy,
        )


def set_scan_policy(session: Session, system_id: int, scan_policy: Optional[str]) -> None:
    """
    Create or update only the scan-policy label for a system.

    Parameters
    ----------
    session:
        Active SQLAlchemy session. Caller is responsible for commit/rollback.
    system_id:
        Numeric system identifier (primary key).
    scan_policy:
        Policy label to assign, or ``None`` to clear. Empty/whitespace values
        normalize to ``NULL``.

    Notes
    -----
    If the system does not exist yet, this performs an insert with a ``NULL``
    ``csv_path`` and the given policy.
    """
    normalized_policy = _normalize_policy_label(scan_policy)
    now = datetime.utcnow()

    row = session.get(SystemCsv, system_id)
    if row:
        row.scan_policy = normalized_policy
        row.updated_at = now
        logger.info(
            "[SYSTEMS] Updated scan_policy for system_id=%s to %r",
            system_id, row.scan_policy
        )
    else:
        session.add(SystemCsv(
            system_id=system_id,
            csv_path=None,
            updated_at=now,
            scan_policy=normalized_policy,
        ))
        logger.info(
            "[SYSTEMS] Inserted system_id=%s with scan_policy=%r",
            system_id, normalized_policy
        )


def set_last_scanned(session: Session, system_id: int, when: Optional[datetime] = None) -> None:
    """
    Update the ``last_scanned`` field for a system.

    Parameters
    ----------
    session:
        Active SQLAlchemy session. Caller is responsible for commit/rollback.
    system_id:
        Numeric system identifier (primary key).
    when:
        Timestamp to set. Defaults to :func:`datetime.utcnow` when ``None``.

    Raises
    ------
    ValueError
        If ``system_id`` does not exist.

    Notes
    -----
    This function does **not** commit the transaction.
    """
    row = session.get(SystemCsv, system_id)
    if not row:
        raise ValueError(f"system_id {system_id} not found; cannot set last_scanned")
    row.last_scanned = when or datetime.utcnow()
    logger.info(
        "[SYSTEMS] Set last_scanned for system_id=%s to %s",
        system_id, row.last_scanned.isoformat()
    )


def remove_system(session: Session, system_id: int) -> bool:
    """
    Delete a system record.

    Parameters
    ----------
    session:
        Active SQLAlchemy session. Caller is responsible for commit/rollback.
    system_id:
        Numeric system identifier (primary key).

    Returns
    -------
    bool
        ``True`` if a row was deleted, ``False`` if no matching row was found.

    Notes
    -----
    This function does **not** commit the transaction.
    """
    row = session.get(SystemCsv, system_id)
    if not row:
        logger.warning("[SYSTEMS] remove_system: system_id=%s not found", system_id)
        return False
    session.delete(row)
    logger.info("[SYSTEMS] Removed system_id=%s", system_id)
    return True


# -----------------------------------------------------------------------------
# Listings / queries
# -----------------------------------------------------------------------------

def list_all_systems(session: Session) -> List[Dict[str, Any]]:
    """
    Fetch all systems and selected fields in a single round trip.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.

    Returns
    -------
    List[Dict[str, Any]]
        List of dictionaries with keys:
        ``system_id``, ``csv_path``, ``updated_at``, ``last_scanned``, ``scan_policy``.

    Example
    -------
    >>> systems = list_all_systems(session)
    >>> systems[0]["scan_policy"]
    'Policy 1'
    """
    stmt = (
        select(
            SystemCsv.system_id,
            SystemCsv.csv_path,
            SystemCsv.updated_at,
            SystemCsv.last_scanned,
            SystemCsv.scan_policy,
        )
        .order_by(SystemCsv.system_id.asc())
    )

    rows = session.execute(stmt).all()
    results: List[Dict[str, Any]] = []
    for system_id, csv_path, updated_at, last_scanned, scan_policy in rows:
        results.append({
            "system_id": system_id,
            "csv_path": csv_path,
            "updated_at": updated_at,
            "last_scanned": last_scanned,
            "scan_policy": scan_policy,
        })
    return results


# ---------------------------------------------------------------------------
# Tiny coercion & normalization helpers
# ---------------------------------------------------------------------------

def _coerce_frequency(value: Union[FrequencyEnum, str, None]) -> Optional[FrequencyEnum]:
    """
    Convert a user-supplied value into a FrequencyEnum or None.

    Accepts:
      - FrequencyEnum instance (returned as-is)
      - A valid string ("daily"|"weekly"|"biweekly"|"monthly")
      - None
    Raises:
      ValueError for invalid strings.
    """
    if value is None:
        return None
    if isinstance(value, FrequencyEnum):
        return value
    return FrequencyEnum(value)


def _coerce_day_of_week(value: Union[DayOfWeek, str, None]) -> Optional[DayOfWeek]:
    """
    Convert a user-supplied value into a DayOfWeek enum or None.

    Accepts:
      - DayOfWeek instance (returned as-is)
      - A valid string ("Monday".."Sunday")
      - None
    Raises:
      ValueError for invalid strings.
    """
    if value is None:
        return None
    if isinstance(value, DayOfWeek):
        return value
    return DayOfWeek(value)


def _norm_text_sql(col):
    """
    SQL-level normalization for robust equality (trim + lower).
    Useful when comparing policy names across tables.
    """
    return func.trim(func.lower(col))


def _now_utc_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())

# ─────────────────────────────────────────────────────────────────────────────
# Time helpers
# ─────────────────────────────────────────────────────────────────────────────

def _coerce_time_of_day(value: Union[str, datetime]) -> datetime:
    """
    Convert a user-supplied time-of-day into a naive `datetime.time` for SQLAlchemy.

    Accepted inputs:
      - str in "HH:MM" or "HH:MM:SS" (interpreted as **UTC wall clock**)
      - `datetime.time` (tz-aware or naive). If tz-aware, tzinfo is stripped.

    Returns:
      `datetime.time` (naive) suitable for a `Time` column (e.g., SQLite).

    Raises:
      TypeError   - if value type isn't str or time
      ValueError  - if string format isn't one of the accepted patterns

    Why naive?
      SQLite's `Time` type expects a Python `time` without tzinfo. We store all
      policy times as **UTC wall time** by convention, so stripping tzinfo is correct.
    """
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)

    if isinstance(value, str):
        v = value.strip()
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(v, fmt).time()
            except ValueError:
                continue
        raise ValueError(f"Invalid time_of_day format: {value!r} (expected HH:MM or HH:MM:SS)")

    raise TypeError(f"time_of_day must be str or datetime.time; got {type(value).__name__}")


def _now_utc_epoch() -> int:
    """Return current time as UNIX epoch seconds in UTC."""
    return int(datetime.now(timezone.utc).timestamp())

# ---------------------------------------------------------------------------
# Simple system listing by policy
# ---------------------------------------------------------------------------

def list_systems_by_policy(session: Session, scan_policy: str) -> List[int]:
    """
    Return system IDs that currently reference the given scan-policy label.

    Args:
        session: Active SQLAlchemy session.
        scan_policy: Exact policy label to match. Whitespace is trimmed before
                     comparison; match is case-sensitive at the Python level.

    Returns:
        Sorted list of matching system IDs.
    """
    label = (scan_policy or "").strip()
    if not label:
        return []

    stmt = (
        select(SystemCsv.system_id)
        .where(SystemCsv.scan_policy == label)
        .order_by(SystemCsv.system_id.asc())
    )
    return [row[0] for row in session.execute(stmt).all()]


# ---------------------------------------------------------------------------
# CRUD: create / list / update / delete
# ---------------------------------------------------------------------------

def create_scan_policy(
    session: Session,
    *,
    name: str,
    frequency: Union["FrequencyEnum", str],
    time_of_day: Union[str, datetime],  # "HH:MM[:SS]" or datetime.time
    day_of_week: Optional[Union["DayOfWeek", str]] = None,
    week_of_month: Optional[int] = None,
    anchor_epoch: Optional[int] = None,
) -> int:
    """Create and persist a new `ScanPolicy`.

    Args:
        session: Open SQLAlchemy session.
        name: Unique, human-readable policy name (trimmed).
        frequency: Frequency enum or string: {"daily","weekly","biweekly","monthly"}.
        time_of_day: UTC policy time, as "HH:MM[:SS]" or `datetime.time`.
        day_of_week: Required for weekly/monthly; optional for biweekly.
        week_of_month: 1..5 for monthly (“Nth weekday”).
        anchor_epoch: Optional UTC epoch for strict biweekly origin.

    Returns:
        The new policy id.
    """
    policy = ScanPolicy(
        name=name.strip(),
        frequency=_coerce_frequency(frequency),
        time_of_day=_coerce_time_of_day(time_of_day),
        day_of_week=_coerce_day_of_week(day_of_week),
        week_of_month=week_of_month,
        anchor_epoch=anchor_epoch,
    )
    # NOTE: no policy.validate(); validation is handled at the service/Pydantic layer.
    session.add(policy)
    session.flush()  # assigns PK
    return policy.id

def list_scan_policies_with_systems(session: Session) -> List[dict]:
    """List all scan policies and the system IDs enrolled in each.

    Args:
        session: Open SQLAlchemy session.

    Returns:
        A list of dicts ready for JSON serialization, one per policy. Each item
        includes policy fields plus `systems`: List[int] of enrolled system IDs.
    """
    policies = session.execute(select(ScanPolicy)).scalars().all()
    results: List[dict] = []

    for policy in policies:
        system_ids = list_systems_by_policy(session, policy.name)
        results.append({
            "id": policy.id,
            "name": policy.name,
            "frequency": policy.frequency.value if isinstance(policy.frequency, FrequencyEnum) else str(policy.frequency),
            "time_of_day": str(policy.time_of_day),
            "day_of_week": policy.day_of_week.value if policy.day_of_week else None,
            "week_of_month": policy.week_of_month,
            "anchor_epoch": policy.anchor_epoch,
            "last_run_epoch": policy.last_run_epoch,
            "created_at": policy.created_at.isoformat() if policy.created_at else None,
            "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
            "systems": system_ids,
        })
    return results

def list_system_ids_by_policy_id(policy_id: int) -> List[int]:
    """
    Return system IDs enrolled in the given policy id.
    Resolves by ScanPolicy.name -> SystemCsv.scan_policy.
    """
    with get_session() as session:
        pol = session.get(ScanPolicy, policy_id)
        if pol is None:
            return []
        rows = (
            session.execute(
                select(SystemCsv.system_id).where(SystemCsv.scan_policy == pol.name)
            )
            .scalars()
            .all()
        )
        return [int(x) for x in rows]


def update_scan_policy(
    session: Session,
    policy_id: int,
    *,
    name: Optional[str] = None,
    frequency: Optional[Union["FrequencyEnum", str]] = None,
    time_of_day: Optional[Union[str, datetime]] = None,
    # Sentinels: "__omit__" means "leave unchanged"; None means "clear"
    day_of_week: Optional[Union["DayOfWeek", str]] = "__omit__",
    week_of_month: Optional[int] = "__omit__",
    anchor_epoch: Optional[int] = "__omit__",
) -> bool:
    """Patch fields on an existing `ScanPolicy` with omit/clear semantics.

    Args:
        session: Open SQLAlchemy session.
        policy_id: Target policy id.
        name: New name, or None to leave unchanged.
        frequency: New frequency enum/str, or None to leave unchanged.
        time_of_day: New time ("HH:MM[:SS]" or `datetime.time`), or None to leave.
        day_of_week: "__omit__" to leave; None to clear; or weekday enum/str.
        week_of_month: "__omit__" to leave; None to clear; or 1..5.
        anchor_epoch: "__omit__" to leave; None to clear; or epoch seconds.

    Returns:
        True if updated; False if the policy was not found.
    """
    policy = session.get(ScanPolicy, policy_id)
    if not policy:
        return False

    old_name = policy.name

    if name is not None:
        policy.name = name.strip()
    if frequency is not None:
        policy.frequency = _coerce_frequency(frequency)
    if time_of_day is not None:
        policy.time_of_day = _coerce_time_of_day(time_of_day)

    if day_of_week != "__omit__":
        policy.day_of_week = None if day_of_week is None else _coerce_day_of_week(day_of_week)
    if week_of_month != "__omit__":
        policy.week_of_month = week_of_month
    if anchor_epoch != "__omit__":
        policy.anchor_epoch = anchor_epoch

    # NOTE: no policy.validate(); invariants are enforced at the service layer.

    # Cascade rename onto SystemCsv.scan_policy, using normalized comparison.
    if policy.name != old_name:
        session.execute(
            update(SystemCsv)
            .where(func.trim(func.lower(SystemCsv.scan_policy)) == func.trim(func.lower(old_name)))
            .values(scan_policy=policy.name, updated_at=func.now())
        )

    session.flush()
    return True


def delete_scan_policy(session: Session, policy_id: int) -> bool:
    """Delete a policy and clear `SystemCsv.scan_policy` for enrolled systems.

    Args:
        session: Open SQLAlchemy session.
        policy_id: Target policy id.

    Returns:
        True if a row was deleted; False if not found.
    """
    policy = session.get(ScanPolicy, policy_id)
    if not policy:
        return False

    session.execute(
        update(SystemCsv)
        .where(_norm_text_sql(SystemCsv.scan_policy) == _norm_text_sql(policy.name))
        .values(scan_policy=None, updated_at=func.now())
    )
    session.delete(policy)
    session.flush()
    return True


# ---------------------------------------------------------------------------
# Enrollment core (one implementation), plus legacy-shaped wrappers
# ---------------------------------------------------------------------------

class UnknownSystemsError(ValueError):
    """
    Raised when strict enrollment is requested and one or more system_ids do
    not exist in SystemCsv. The missing IDs are available on .missing_ids.
    """
    def __init__(self, missing_ids: List[int]):
        self.missing_ids = missing_ids
        super().__init__(f"Unknown system_ids: {missing_ids}")


def _core_enrollment_mutation(
    session: Session,
    policy_id: int,
    system_ids: Iterable[int],
    *,
    mode: str,           # "enroll" or "remove"
    strict: bool = False # for enroll only
) -> Dict[str, int | List[int]]:
    """
    Single, deduplicated implementation for both enroll and remove mutations.

    Args:
        policy_id: Target ScanPolicy.id
        system_ids: Iterable of IDs (ints/strings accepted by caller)
        mode: "enroll" → set SystemCsv.scan_policy to policy.name
              "remove" → set SystemCsv.scan_policy to NULL (only if matches)
        strict: If True (enroll only), and any IDs do not exist, raise
                UnknownSystemsError and do NOT mutate anything.

    Returns (by mode):
        enroll → {"updated": int, "already": int, "missing": [int,...]}
        remove → {"cleared": int, "not_found": int, "not_in_policy": int}

    Raises:
        ValueError if policy does not exist.
        UnknownSystemsError when strict=True and missing IDs exist.
    """
    policy = session.get(ScanPolicy, policy_id)
    if not policy:
        raise ValueError("Policy not found")

    ids = list(dict.fromkeys(int(x) for x in system_ids))  # de-dupe, preserve order
    if not ids:
        return {"updated": 0, "already": 0, "missing": []} if mode == "enroll" else \
               {"cleared": 0, "not_found": 0, "not_in_policy": 0}

    # Load all rows in one round-trip
    rows = session.execute(
        select(SystemCsv).where(SystemCsv.system_id.in_(ids))
    ).scalars().all()
    by_id = {r.system_id: r for r in rows}

    if mode == "enroll":
        missing = [sid for sid in ids if sid not in by_id]
        if strict and missing:
            # No changes applied yet; let caller roll back.
            raise UnknownSystemsError(missing)

        updated = 0
        already = 0
        for sid in ids:
            row = by_id.get(sid)
            if not row:
                continue  # strict=False: ignore missing, just report
            if (row.scan_policy or "") == policy.name:
                already += 1
                continue
            row.scan_policy = policy.name
            row.updated_at = datetime.utcnow()
            updated += 1

        session.flush()
        return {"updated": updated, "already": already, "missing": missing}

    elif mode == "remove":
        not_found = 0
        not_in_policy = 0
        cleared = 0
        for sid in ids:
            row = by_id.get(sid)
            if not row:
                not_found += 1
                continue
            if (row.scan_policy or "") != policy.name:
                not_in_policy += 1
                continue
            row.scan_policy = None
            row.updated_at = datetime.utcnow()
            cleared += 1

        session.flush()
        return {"cleared": cleared, "not_found": not_found, "not_in_policy": not_in_policy}

    else:
        raise ValueError(f"Unknown enrollment mode: {mode}")


# ---- Public wrappers (keep legacy names and return shapes) ------------------

# Back-compat alias (if older code expects a private helper)
#_get_policy_by_id = get_scan_policy_by_id

def get_scan_policy_by_id(session: Session, policy_id: int) -> Optional["ScanPolicy"]:
    """
    Fetch a ScanPolicy row by its primary key.

    Args:
        session: Active SQLAlchemy session (transaction boundaries are managed by caller).
        policy_id: Integer primary key of the policy to retrieve.

    Returns:
        The matching ScanPolicy instance when found; otherwise None.

    Notes:
        - This function performs no commit/flush and raises no custom exceptions.
          It’s a thin read helper intended for use by Flask endpoints and
          higher-level service wrappers.
        - Callers should handle None (not found) and any DB exceptions as appropriate.
    """
    if policy_id is None:
        return None
    return session.get(ScanPolicy, int(policy_id))

def enroll_systems_to_policy(
    session: Session,
    policy_id: int,
    system_ids: Iterable[int],
) -> Tuple[int, int]:
    """
    Legacy wrapper: enroll systems and return (updated, not_found).

    For strict/all-or-nothing behavior, call _core_enrollment_mutation with
    strict=True from a service layer (e.g. Flask endpoint wrapper).
    """
    result = _core_enrollment_mutation(session, policy_id, system_ids, mode="enroll", strict=False)
    # Legacy tuple returns updated + not_found; here not_found = len(missing) in non-strict
    return int(result["updated"]), len(result.get("missing", []))


def remove_systems_from_policy(
    session: Session,
    policy_id: int,
    system_ids: Iterable[int],
) -> Tuple[int, int]:
    """
    Legacy wrapper: remove systems and return (cleared, not_found).

    Matches previous signature used by Flask endpoints.
    """
    result = _core_enrollment_mutation(session, policy_id, system_ids, mode="remove")
    return int(result["cleared"]), int(result["not_found"])


# Optional “strict” variant for higher-level service wrapper:
def enroll_systems_to_policy_strict(
    session: Session,
    policy_id: int,
    system_ids: Iterable[int],
) -> Dict[str, Any]:
    """
    Enroll systems with strict all-or-nothing semantics.

    Raises:
        UnknownSystemsError with .missing_ids on any absent systems.
    """
    return _core_enrollment_mutation(session, policy_id, system_ids, mode="enroll", strict=True)


# ---------------------------------------------------------------------------
# Last-run helpers (unchanged)
# ---------------------------------------------------------------------------

def set_policy_last_run_epoch(
    session: Session,
    policy_id: int,
    *,
    last_run_epoch: int,
) -> bool:
    """Set last_run_epoch to the given UTC epoch seconds."""
    policy = session.get(ScanPolicy, policy_id)
    if not policy:
        return False
    policy.last_run_epoch = int(last_run_epoch)
    session.flush()
    return True


def mark_policy_last_run_now(session: Session, policy_id: int) -> bool:
    """Set last_run_epoch to the current UTC epoch seconds."""
    return set_policy_last_run_epoch(session, policy_id, last_run_epoch=_now_utc_epoch())


# ─────────────────────────────────────────────────────────────────────────────
# Service-layer wrappers for policy endpoints
# Keep CRUD/enrollment logic here; Flask layer calls these and maps exceptions
# ─────────────────────────────────────────────────────────────────────────────



# If these are already defined above in db.py, you can remove the re-definitions.
class DBNotFound(Exception):
    """Raised when a requested resource does not exist (maps to HTTP 404)."""

class DBConflict(Exception):
    """Raised when a strict constraint fails (maps to HTTP 409)."""

class DBValidation(Exception):
    """Raised when inputs fail semantic validation (maps to HTTP 400)."""


def _missing_system_ids(session: Session, system_ids: Iterable[int]) -> List[int]:
    """
    Return the subset of system_ids that do not exist in SystemCsv.

    Args:
        session: Active SQLAlchemy session.
        system_ids: Iterable of user-provided IDs (ints/strs acceptable).

    Returns:
        Ordered list of missing IDs (deduped, first-seen order preserved).
    """
    ids = list(dict.fromkeys(int(x) for x in system_ids))  # unique, preserve order
    if not ids:
        return []
    existing = {
        sid for (sid,) in session.execute(
            select(SystemCsv.system_id).where(SystemCsv.system_id.in_(ids))
        ).all()
    }
    return [sid for sid in ids if sid not in existing]


def policies_list() -> List[Dict[str, Any]]:
    """
    List all scan policies including enrolled system IDs.

    Returns:
        List[dict]: Each dict matches ScanPolicyOut (id, name, frequency, time_of_day,
                    day_of_week, week_of_month, anchor_epoch, last_run_epoch, timestamps,
                    systems[]).
    """
    with get_session() as session:
        # Pure read path; let exceptions bubble to caller if needed.
        return list_scan_policies_with_systems(session)


def policies_create(
    *,
    name: str,
    frequency: str,
    time_of_day,                   # "HH:MM[:SS]" (already parsed to DB-acceptable type upstream is fine)
    day_of_week: Optional[str],
    week_of_month: Optional[int],
    anchor_epoch: Optional[int],
) -> int:
    """
    Create a policy using the existing create helper; handles enum coercion + commit.

    Raises:
        DBValidation: if enum coercion or model validation fails.
    """
    with get_session() as session:
        try:
            # Coerce enums via model enums; let ValueError bubble as DBValidation
            freq_enum = FrequencyEnum(frequency)
            dow_enum = DayOfWeek(day_of_week) if day_of_week else None

            new_id = create_scan_policy(
                session,
                name=name,
                frequency=freq_enum,
                time_of_day=time_of_day,
                day_of_week=dow_enum,
                week_of_month=week_of_month,
                anchor_epoch=anchor_epoch,
            )
            session.commit()
            return new_id
        except (ValueError, TypeError) as ve:
            session.rollback()
            raise DBValidation(str(ve)) from ve
        except Exception:
            session.rollback()
            raise


def policy_update(
    policy_id: int,
    *,
    name: Optional[str] = None,
    frequency: Optional[str] = None,
    time_of_day = None,
    # Sentinels match  lower-level helper semantics:
    day_of_week: Optional[str] | str = "__omit__",   # "__omit__" | None | "Monday".."Sunday"
    week_of_month: Optional[int] | str = "__omit__", # "__omit__" | None | int
    anchor_epoch: Optional[int] | str = "__omit__",  # "__omit__" | None | int
) -> None:
    """
    Partial update wrapper. Allows omit vs. explicit null for nullable fields.

    Raises:
        DBNotFound: if the policy does not exist.
        DBValidation: if enum coercion or validation fails.
    """
    with get_session() as session:
        try:
            if not get_scan_policy_by_id(session, policy_id):
                raise DBNotFound(f"Policy {policy_id} not found")

            freq_enum = FrequencyEnum(frequency) if frequency is not None else None

            # day_of_week can be "__omit__", None, or a valid weekday string
            if day_of_week not in (None, "__omit__"):
                day_of_week = DayOfWeek(day_of_week)  # type: ignore[assignment]

            ok = update_scan_policy(
                session,
                policy_id,
                name=name,
                frequency=freq_enum,
                time_of_day=time_of_day,
                day_of_week=day_of_week,      # may be "__omit__", None, or DayOfWeek
                week_of_month=week_of_month,  # may be "__omit__", None, or int
                anchor_epoch=anchor_epoch,    # may be "__omit__", None, or int
            )
            if not ok:
                # Extremely rare race: vanished between existence check and update
                raise DBNotFound(f"Policy {policy_id} not found")

            session.commit()
        except (ValueError, TypeError) as ve:
            session.rollback()
            raise DBValidation(str(ve)) from ve
        except Exception:
            session.rollback()
            raise


def policy_delete(policy_id: int) -> None:
    """
    Delete a policy and clear SystemCsv.scan_policy references.

    Raises:
        DBNotFound: if the policy does not exist.
    """
    with get_session() as session:
        try:
            if not get_scan_policy_by_id(session, policy_id):
                raise DBNotFound(f"Policy {policy_id} not found")
            ok = delete_scan_policy(session, policy_id)
            if not ok:
                raise DBNotFound(f"Policy {policy_id} not found")
            session.commit()
        except Exception:
            session.rollback()
            raise


def policies_enroll_systems(
    policy_id: int,
    system_ids: Iterable[int],
    *,
    strict: bool = False,
) -> Dict[str, Any]:
    """
    Enroll systems into a policy.

    Behavior:
        - Validates policy existence.
        - Computes missing IDs in SystemCsv up front.
        - If strict=True and any missing → **rollback** and raise DBConflict (409).
        - Otherwise enrolls existing systems, commits, and returns:
            {"updated": int, "missing": List[int]}

    Raises:
        DBNotFound: if policy is missing.
        DBConflict: if strict=True and any IDs are missing (no mutation).
    """
    with get_session() as session:
        try:
            if not get_scan_policy_by_id(session, policy_id):
                raise DBNotFound(f"Policy {policy_id} not found")

            ids = list(dict.fromkeys(int(x) for x in system_ids))
            missing = _missing_system_ids(session, ids)

            if strict and missing:
                session.rollback()
                raise DBConflict(f"Unknown systems: {missing}")

            updated, _not_found = enroll_systems_to_policy(session, policy_id, ids)
            session.commit()
            return {"updated": int(updated), "missing": missing}
        except Exception:
            session.rollback()
            raise


def policies_remove_systems(
    policy_id: int,
    system_ids: Iterable[int],
) -> Dict[str, int]:
    """
    Unenroll systems from a policy.

    Returns:
        {"cleared": int, "not_found": int}

    Raises:
        DBNotFound: if policy is missing.
    """
    with get_session() as session:
        try:
            if not get_scan_policy_by_id(session, policy_id):
                raise DBNotFound(f"Policy {policy_id} not found")

            ids = list(dict.fromkeys(int(x) for x in system_ids))
            cleared, not_found = remove_systems_from_policy(session, policy_id, ids)
            session.commit()
            return {"cleared": int(cleared), "not_found": int(not_found)}
        except Exception:
            session.rollback()
            raise






# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
# --------------------------
# Small, tight utility layer
# --------------------------

def _result_to_db_status(val) -> ResultStatus:
    """
    Convert engine/TestResult.result (enum or string) to ORM ResultStatus.

    Accepts:
      - engine Result enum (with .value like 'PASS', 'FAIL', 'CONCERN', 'N/A')
      - plain strings ('PASS', 'Fail', 'na', 'N/A', etc.)
      - already a ResultStatus
    Falls back to UNKNOWN.
    """
    if isinstance(val, ResultStatus):
        return val

    # Try enum .value then .name then the raw input as strings
    candidates = []
    if hasattr(val, "value"):
        candidates.append(getattr(val, "value"))
    if hasattr(val, "name"):
        candidates.append(getattr(val, "name"))
    candidates.append(val)

    for c in candidates:
        if isinstance(c, str):
            s = c.strip().upper()
            if s == "NA":
                s = "N/A"        # normalize common 'NA' to stored 'N/A'
            try:
                # construct by **value**; e.g., ResultStatus("PASS") -> ResultStatus.PASS_
                return ResultStatus(s)
            except ValueError:
                continue

    return ResultStatus.UNKNOWN


def _test_code(num: int) -> str:
    """Stable, human-friendly test code.

    Args:
        num: Test number.

    Returns:
        str: Code like "T005".
    """
    return f"T{num:03d}"


# ---------------------------------
# Public API (opens/closes session)
# ---------------------------------

def store_scan_results(
    system_id: int,
    run_meta: Dict[str, Any],
    status: ATOStatus,
) -> str:
    """Persist one scan run and its per-test outcomes from an `ATOStatus`.

    This top-level entry point manages its own DB session and commit. It persists:
      * A `System` row (upsert by primary key).
      * A `TestRun` row populated from `run_meta` and the `ATOStatus` rollups.
      * One `TestOutcome` per `TestCatalog` test (upserting catalog by test number).

    Args:
        system_id: Primary key of the SUT in the `systems` table.
        run_meta: Optional run-level metadata. Recognized keys (all optional):
            - run_id (str, UUID)       : Explicit run identifier; generated if absent.
            - job_id (str)             : External job/pipeline identifier.
            - started_at (str|datetime): ISO8601 or datetime; defaults to now().
            - finished_at (str|datetime): ISO8601 or datetime; defaults to started_at.
            - duration_seconds (int)   : Precomputed duration.
            - script_version (str)     : Runner/collector version.
            - commit_hash (str)        : Source commit SHA.
            - environment (str)        : "dev" | "test" | "prod" (free-form).
            - data_path (str)          : Source path / artifact location.
            - scan_label (str)         : Friendly name ("nightly-2025-11-05").
            Any additional keys are preserved in `TestRun.metadata_json`.
        status: The in-memory `ATOStatus` object (system_name, counters, results[]).

    Returns:
        str: The persisted `run_id` (UUID).
    """
    with get_session() as session:
        run_id = _store_scan_results_txn(session, system_id, run_meta, status)
        session.commit()
        return run_id


# -------------------------------------------------
# Transactional core (caller owns the session/txn)
# -------------------------------------------------

def _store_scan_results_txn(
    session: Session,
    system_id: int,
    run_meta: Dict[str, Any],
    status: ATOStatus,
) -> str:
    """Write a run and its outcomes using the new ORM schema (transactional).

    Behavior:
      * Ensures a `System` row exists for `system_id`.
      * Creates a `TestRun` row populated from `run_meta` + `ATOStatus` rollups.
      * Computes and stores an optional readiness score percentage using
        `compute_readiness_summary(...)`.
      * Upserts `TestCatalog` by `test_number` (primary key for tests).
      * Inserts one `TestOutcome` per test (unique per (run, test) via constraint).

    Args:
        session: Open SQLAlchemy session.
        system_id: Foreign key to `systems.id`.
        run_meta: Run metadata (see `store_scan_results` for keys).
        status: In-memory `ATOStatus` with rollups and individual results.

    Returns:
        str: The persisted `run_id` (UUID string).
    """
    # 1) Ensure the System row exists (skeletal OK).
    system_row = session.get(System, system_id)
    if system_row is None:
        system_row = System(
            id=system_id,
            name=status.system_name,  # optional; nice for listings
            metadata_json={"created_by": "store_scan_results"},
        )
        session.add(system_row)
        session.flush()

    # 2) Normalize run metadata.
    run_id: str = str(run_meta.get("run_id") or uuid.uuid4())
    started_at = _parse_iso8601(run_meta.get("started_at")) or datetime.utcnow()
    finished_at = _parse_iso8601(run_meta.get("finished_at")) or started_at
    duration_seconds = _coerce_int(run_meta.get("duration_seconds"))

    known_keys = {
        "run_id",
        "job_id",
        "started_at",
        "finished_at",
        "duration_seconds",
        "script_version",
        "commit_hash",
        "environment",
        "data_path",
        "scan_label",
    }
    extra_meta = {k: v for k, v in run_meta.items() if k not in known_keys}

    # 3) Compute readiness score at store time (optional).
    #
    # We intentionally reuse the same helper the reporting layer uses so the
    # semantics stay consistent:
    #
    #     score = pass / (pass + fail + concern)
    #
    # Implementation detail:
    #   We only need a status-like column for the helper to work. A tiny
    #   one-column frame with "Result" populated from ATOStatus results is
    #   sufficient and cheap to construct.
    readiness_score_pct: Optional[int] = None
    try:
        rows_for_readiness = [{"Result": str(tr.result)} for tr in status.results]
        df_for_readiness = pd.DataFrame(rows_for_readiness)
        readiness_summary = compute_readiness_summary(df_for_readiness)
        # Helper returns {"score_pct": int|None, ...}
        raw_score = readiness_summary.get("score_pct")
        if isinstance(raw_score, (int, float)):
            # Store as int 0–100; DB-level CHECK keeps it in range.
            readiness_score_pct = int(raw_score)
    except Exception:
        # If anything goes wrong here, we still persist the run; the score field
        # simply remains NULL and can be recomputed offline if needed.
        logger.exception(
            "[RUNS] Failed to compute readiness score (system_id=%s, run_id=%s)",
            system_id,
            run_id,
        )

    # 4) Create the TestRun row.
    run_row = TestRun(
        id=run_id,
        system_id=system_row.id,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration_seconds,
        job_id=run_meta.get("job_id"),
        script_version=run_meta.get("script_version"),
        commit_hash=run_meta.get("commit_hash"),
        environment=run_meta.get("environment"),
        data_path=run_meta.get("data_path"),
        scan_label=run_meta.get("scan_label"),
        # rollups from ATOStatus:
        system_name=status.system_name,
        total_tests=len(status.results),
        pass_count=status.pass_count,
        fail_count=status.fail_count,
        concern_count=status.concern_count,
        na_count=status.na_count,
        # newly-added readiness score (may be None if computation failed):
        readiness_score_pct=readiness_score_pct,
        metadata_json=extra_meta,
    )
    session.add(run_row)
    session.flush()  # PK available for FK below

    # 5) Upsert catalog + write outcomes.
    for mem_tr in status.results:
        test_num = int(mem_tr.test_number)
        test_code = _test_code(test_num)

        # Upsert TestCatalog based on stable test_number.
        cat_row = session.execute(
            select(TestCatalog).where(TestCatalog.test_number == test_num)
        ).scalar_one_or_none()

        if cat_row is None:
            # Allow fallback by code if needed (first migrations).
            cat_row = session.execute(
                select(TestCatalog).where(TestCatalog.test_code == test_code)
            ).scalar_one_or_none()

        if cat_row is None:
            cat_row = TestCatalog(
                test_number=test_num,
                test_code=test_code,
                display_name=(mem_tr.name or f"Test {test_num}").strip(),
                metadata_json={},
            )
            session.add(cat_row)
            session.flush()
        else:
            latest_name = (mem_tr.name or "").strip()
            # Keep the catalog name fresh, but only overwrite if the new value
            # is non-empty and actually different.
            if latest_name and (
                not (cat_row.display_name or "").strip()
                or cat_row.display_name != latest_name
            ):
                cat_row.display_name = latest_name
                session.add(cat_row)

        # One outcome per (run, test).
        session.add(
            TestOutcome(
                run_id=run_row.id,
                test_id=cat_row.id,
                status=_result_to_db_status(mem_tr.result),
                message=mem_tr.message or "",
                facts_json={},  # reserved for future structured evidence
            )
        )

    logger.info(
        "[RUNS] Persisted run_id=%s system_id=%s results=%d readiness_score_pct=%r",
        run_row.id,
        system_id,
        len(status.results),
        readiness_score_pct,
    )
    return run_row.id



#--------------------------------------------------------------
#   Runner stuff for Continuous Monitoring
#-------------------------------------------------------------

def try_claim_policy(policy_id: int, now_epoch: int, min_epoch: int) -> bool:
    """Attempt to atomically claim a scan policy for execution.

    This function conditionally updates ``ScanPolicy.last_run_epoch`` to
    ``now_epoch`` **only if** the current value is **strictly less than**
    ``min_epoch``. It uses a row-level lock via SQLAlchemy’s
    ``SELECT ... FOR UPDATE`` (DB-agnostic) to serialize concurrent claim
    attempts across processes/threads.

    The pattern prevents duplicate triggers in windowed schedulers:
    the scheduler computes a time window (e.g., last 5 minutes) and calls
    this function with ``min_epoch`` set to the window’s start. If another
    worker has already claimed or executed the policy within the window,
    this function returns ``False``.

    Args:
      policy_id: Primary key of the policy to claim.
      now_epoch: UTC epoch seconds to write to ``last_run_epoch`` on success.
      min_epoch: Minimum epoch threshold; claim proceeds only if the current
        ``last_run_epoch`` is ``< min_epoch``.

    Returns:
      True if the policy existed and was claimed (``last_run_epoch`` updated);
      False if the policy does not exist or was already claimed/executed
      within the given window.

    Raises:
      Any SQLAlchemy/DB exceptions encountered during I/O are propagated to the caller.

    Notes:
      * This implementation is database-agnostic (no vendor-specific SQL).
      * On databases that do not support row locks, SQLAlchemy will emulate or
        degrade gracefully; behavior remains safe under typical configurations.
    """
    with get_session() as session:
        # Lock the row to serialize concurrent claim attempts.
        pol = (
            session.execute(
                select(ScanPolicy)
                .where(ScanPolicy.id == policy_id)
                .with_for_update()
            )
            .scalar_one_or_none()
        )

        if pol is None:
            # Policy not found; nothing to claim.
            session.rollback()
            return False

        # Already claimed/executed within the scheduler's window — do nothing.
        if (pol.last_run_epoch or 0) >= int(min_epoch):
            session.rollback()
            return False

        # Claim it by stamping now.
        pol.last_run_epoch = int(now_epoch)
        session.add(pol)
        session.commit()
        return True


#------------------------------------
#   Fetching stored scan results
#-------------------------------------
def get_latest_run_dataframe_for_system(
    session: Session,
    system_id: int,
) -> Optional[Tuple[TestRun, pd.DataFrame]]:
    """Return the latest finished TestRun and a DataFrame of its outcomes.

    This helper powers the DB-backed reporting endpoint. It selects the most
    recent finished run for the given system and flattens its TestOutcome rows
    and associated TestCatalog metadata into a pandas DataFrame.

    The resulting DataFrame is shaped to align with the Reporting UI and
    readiness computation:

    * `test_num` (numeric) is used as the "Test #" column in the UI.
    * `Result` is the primary status column (PASS/FAIL/CONCERN/N/A/etc).
    * `Test Description` is the human-readable description of the test.
    * Additional fields (e.g., `Test Code`, `Message`, `Category`,
      `elapsed_seconds`) are included for richer display and debugging.

    Args:
      session: Open SQLAlchemy session used for querying.
      system_id: Identifier of the system whose latest finished run
        should be loaded.

    Returns:
      A tuple `(run, dataframe)` where:
        * `run` is the latest finished TestRun for the system.
        * `dataframe` is a pandas DataFrame representing test outcomes.
      Returns `None` if no finished runs exist for the system.

    Raises:
      SQLAlchemyError: If the underlying query fails.
    """
    # Latest finished run for this system (prefer finished_at, then started_at).
    run_stmt: Select[TestRun] = (
        select(TestRun)
        .where(
            and_(
                TestRun.system_id == system_id,
                TestRun.finished_at.is_not(None),
            )
        )
        .order_by(desc(TestRun.finished_at), desc(TestRun.started_at))
        .limit(1)
    )

    run: Optional[TestRun] = session.execute(run_stmt).scalars().first()
    if run is None:
        return None

    # Fetch outcomes joined with catalog entries for that run.
    oc_stmt: Select[Tuple[TestOutcome, TestCatalog]] = (
        select(TestOutcome, TestCatalog)
        .join(TestOutcome.test)
        .where(TestOutcome.run_id == run.id)
        .order_by(TestCatalog.test_number.asc())
    )

    rows: List[Dict[str, Any]] = []
    result_iter = session.execute(oc_stmt)

    for outcome, test in result_iter:
        facts = outcome.facts_json or {}
        meta = test.metadata_json or {}

        # Derive a human-readable description:
        description: Optional[str] = None
        if test.display_name:
            description = str(test.display_name).strip()
        else:
            # Try common metadata keys for a name/title/description.
            for key in ("title", "description", "name"):
                val = meta.get(key) or facts.get(key)
                if isinstance(val, str) and val.strip():
                    description = val.strip()
                    break

        if not description:
            description = f"Test {test.test_number} ({test.test_code})"

        rows.append(
            {
                # Used by the UI as "Test #"
                "test_num": test.test_number,
                # Primary status column (matches _STATUS_KEYS_CANONICAL: Result/result/status/...)
                "Result": outcome.status.value,  # "PASS", "FAIL", "CONCERN", "N/A", etc.
                # Human-readable description; UI looks for "Test Description" et al.
                "Test Description": description,
                # Extra context / debug fields
                "Test Code": test.test_code,
                "Message": outcome.message or "",
                # Category hook for section filtering (e.g., SYSTEM, PACKAGE, etc.).
                "Category": meta.get("category"),
                # Run-level timing exposed on each row for header "Processing Time"
                "elapsed_seconds": run.duration_seconds,
            }
        )

    df = pd.DataFrame(rows)
    return run, df


def get_latest_readiness_score_for_system(system_id: int) -> Optional[int]:
    """Return the readiness score for the most recent scan of a system.

    This helper looks up the latest `TestRun` row for the provided system and
    returns its stored `readiness_score_pct` value. "Latest" is defined as:

      1. The run with the greatest non-null `finished_at` timestamp, and
      2. Ties are broken by `started_at` in descending order.

    If no runs exist for the system, or the most recent run has a null
    readiness score, the function returns ``None``.

    Args:
        system_id: Primary key of the system whose readiness score should be
            retrieved.

    Returns:
        The readiness score percentage from 0 to 100 for the most recent run,
        or ``None`` if no applicable run exists.

    Logging:
        Emits an INFO log when a score is found and a DEBUG log when no run
        exists for the system.
    """

    with get_session() as session:
        # Order by finished_at DESC, then started_at DESC as a stable tie-breaker.
        stmt = (
            select(
                TestRun.id,
                TestRun.finished_at,
                TestRun.started_at,
                TestRun.readiness_score_pct,
            )
            .where(TestRun.system_id == system_id)
            .order_by(
                desc(TestRun.finished_at),
                desc(TestRun.started_at),
            )
            .limit(1)
        )

        row = session.execute(stmt).one_or_none()
        if row is None:
            logger.debug(
                "[RUNS] No TestRun rows found for system_id=%s when fetching readiness score",
                system_id,
            )
            return None

        run_id, finished_at, started_at, readiness_score_pct = row

        logger.info(
            "[RUNS] Latest readiness score for system_id=%s is %r (run_id=%s, finished_at=%s, started_at=%s)",
            system_id,
            readiness_score_pct,
            run_id,
            finished_at,
            started_at,
        )

        # May legitimately be None if computation failed or was skipped for that run.
        return readiness_score_pct



def list_continuous_monitoring_items(session: Session) -> List[Dict[str, Any]]:
    """Return a consolidated continuous-monitoring view keyed by system_id.

    This helper is the single source of truth for the “Continuous Monitoring”
    dashboard. It is intentionally opinionated about what “monitored” means and
    how recency/score are derived:

      * Enrollment:
          A system is considered *enrolled* (monitored=True) if there is a
          `system_csv` row whose `scan_policy` value resolves to an existing
          `ScanPolicy.name`. Systems without a valid policy are still returned
          but marked `monitored=False`.

      * Last scanned:
          The last scan timestamp is taken from `test_runs` for that system
          using:

              max(coalesce(finished_at, started_at))

          If no runs exist, `last_scanned` is None.

      * Readiness score:
          The readiness score is obtained via
          `get_latest_readiness_score_for_system(system_id)` so the logic is
          centralized and consistent with other callers. If no score can be
          computed, this value is None.

    Args:
        session: Open SQLAlchemy session used for the listing query.

    Returns:
        List of dictionaries, each shaped as:
            {
                "system_id": int,
                "last_scanned": datetime | None,
                "readiness_score_pct": int | None,
                "monitored": bool,
            }
    """
    # Coalesced timestamp used to define “latest run”:
    # prefer finished_at, fall back to started_at.
    coalesced_ts = func.coalesce(TestRun.finished_at, TestRun.started_at)

    # Subquery: for each system_id that has runs, compute the most recent
    # scan timestamp.
    latest_run_subq = (
        select(
            TestRun.system_id.label("system_id"),
            func.max(coalesced_ts).label("last_scanned"),
        )
        .group_by(TestRun.system_id)
        .subquery()
    )

    # Main query:
    #   SystemCsv ⟕ latest_run_subq ⟕ ScanPolicy
    #
    # Notes:
    #   * SystemCsv is the authoritative source of “systems in portfolio”.
    #   * Joining to ScanPolicy by name lets us detect stale/invalid policy
    #     references; only existing policies mark a system as “monitored”.
    stmt = (
        select(
            SystemCsv.system_id,
            latest_run_subq.c.last_scanned,
            ScanPolicy.id.label("policy_id"),
        )
        .select_from(SystemCsv)
        .outerjoin(
            latest_run_subq,
            latest_run_subq.c.system_id == SystemCsv.system_id,
        )
        .outerjoin(
            ScanPolicy,
            ScanPolicy.name == SystemCsv.scan_policy,
        )
        .order_by(SystemCsv.system_id)
    )

    rows = session.execute(stmt).all()

    results: List[Dict[str, Any]] = []
    for system_id, last_scanned, policy_id in rows:
        system_id_int = int(system_id)

        # Delegate readiness score logic to the shared helper so that any future
        # changes (e.g., recomputation from counts) are centralized. This helper
        # manages its own DB session internally.
        try:
            readiness_score = get_latest_readiness_score_for_system(system_id_int)
        except Exception:
            # Score calculation should not block the listing; failures are logged
            # inside the helper or by the caller as needed.
            readiness_score = None

        results.append(
            {
                "system_id": system_id_int,
                "last_scanned": last_scanned,            # datetime | None
                "readiness_score_pct": readiness_score,  # int | None
                "monitored": bool(policy_id),            # True only if policy exists
            }
        )

    return results



def list_readiness_history_for_system(
    session: Session,
    system_id: int,
) -> List[Dict[str, Any]]:
    """Return the full readiness history for a system across all runs.

    For the given ``system_id``, this helper returns one entry per recorded
    ``TestRun``, ordered chronologically by the effective run timestamp.

    The effective timestamp is defined as:

        ts = coalesce(finished_at, started_at)

    The readiness score is taken directly from ``TestRun.readiness_score_pct``.
    If that field is NULL (for older runs or in case of earlier failures), the
    score is recomputed on the fly from the stored rollups:

        considered = pass_count + fail_count + concern_count
        score = round(pass_count / considered * 100)  if considered > 0  else None

    Args:
        session: Open SQLAlchemy session.
        system_id: Primary key of the system whose readiness history should be
            retrieved.

    Returns:
        List[Dict[str, Any]]: One dictionary per run, each shaped like:

            {
                "run_id": str,
                "ts": datetime,               # effective timestamp
                "readiness_score_pct": int | None,
            }

        The list is sorted by ``ts`` ascending. Runs with no timestamp at all
        (both started_at and finished_at NULL) are skipped defensively.
    """
    # Coalesced timestamp used for ordering and charting.
    coalesced_ts = func.coalesce(TestRun.finished_at, TestRun.started_at)

    stmt = (
        select(
            TestRun.id,
            coalesced_ts.label("ts"),
            TestRun.readiness_score_pct,
            TestRun.pass_count,
            TestRun.fail_count,
            TestRun.concern_count,
        )
        .where(TestRun.system_id == system_id)
        .order_by(coalesced_ts.asc(), TestRun.started_at.asc())
    )

    rows = session.execute(stmt).all()
    history: List[Dict[str, Any]] = []

    for run_id, ts, stored_score, pass_count, fail_count, concern_count in rows:
        if ts is None:
            # Extremely defensive: in practice we should always have at least
            # started_at, but skip any pathological rows.
            continue

        readiness_score_pct = stored_score
        if readiness_score_pct is None:
            # Recompute lazily from stored rollups if needed.
            try:
                considered = int(pass_count or 0) + int(fail_count or 0) + int(concern_count or 0)
                if considered > 0:
                    readiness_score_pct = int(round((int(pass_count or 0) / considered) * 100))
                else:
                    readiness_score_pct = None
            except Exception:
                # If recomputation fails, leave as None; caller can decide how to display.
                readiness_score_pct = None

        history.append(
            {
                "run_id": str(run_id),
                "ts": ts,
                "readiness_score_pct": readiness_score_pct,
            }
        )

    return history


#TODO: ENSURE ABSTRACTING DB LAYER BEHIND SQLALCHEMY PROPERLY. 
#Run once at import
init_db()