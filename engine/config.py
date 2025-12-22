# engine/config.py
from __future__ import annotations

"""
Configuration module for the ATO test engine.

Key guarantees
--------------
- Config file location is **hard-coded** to `config.ini` by default.
- We **do not** use environment variables to locate the config file.
- If the file is missing/unreadable, construction **fails fast** with FileNotFoundError.
- Logging integrates with the host application's handlers if present; otherwise
  we install a minimal, safe handler.

Usage
-----
    from engine.config import Config

    # Strict load (raises FileNotFoundError if ./config.ini is missing)
    cfg = Config()  # or Config("config.ini")
    cfg.configure_logging()
    cfg.validate_minimums()  # no-op in explicit fixture mode

Testing (optional)
------------------
We can explicitly opt-in to a "fixture mode" for test runs by passing
`_force_fixture=True`. In that case no file is required and validation is relaxed.

    cfg = Config(_force_fixture=True)  # test-only, no file read
"""

import configparser
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union
import io
import re
import shutil
import time
from tempfile import NamedTemporaryFile

# -----------------------------
# Constants & Logger hierarchy
# -----------------------------

DEFAULT_CONFIG_PATH = "config.ini"

# We allow overriding the *logger family* root via env so engine logs can join
# the host app's logger tree. This does NOT affect config file location policy.
ENGINE_LOGGER_ROOT = os.getenv("ENGINE_LOGGER_ROOT", "TECTIX").strip() or "TECTIX"


def set_logger_root(name: str) -> None:
    """Override the logger family root (e.g., 'TECTIX') at runtime.

    Call very early (before most engine imports), so descendants pick up the
    intended hierarchy and handlers configured by the host application.

    Args:
        name: New logger root family name (e.g., 'TECTIX').
    """
    global ENGINE_LOGGER_ROOT, logger
    root = (name or "").strip() or "TECTIX"
    ENGINE_LOGGER_ROOT = root
    logger = logging.getLogger(f"{ENGINE_LOGGER_ROOT}.engine.config")


# Child logger of the app's family root (e.g., "TECTIX.engine.config")
logger = logging.getLogger(f"{ENGINE_LOGGER_ROOT}.engine.config")


class Config:
    """Centralized configuration loader for the ATO test suite.

    Location policy:
      - The config file path is **hard-coded**: by default `config.ini` in CWD.
      - We do **not** consult environment variables to find it.
      - If the file is missing or unreadable, construction **fails fast**.

    Logging behavior:
      - If the host app already configured handlers on the process root or the
        logger family root (ENGINE_LOGGER_ROOT), we integrate by setting levels
        only and allow propagation; we do not add duplicate handlers.
      - Otherwise, we install a minimal handler (stdout or file).

    Fixture mode:
      - Intended exclusively for tests: pass `_force_fixture=True` to skip file
        loading and to relax `validate_minimums()`. This mode is **never**
        toggled by environment variables.
    """

    # ---------- Factory ----------
    @classmethod
    def load_or_default(cls, file_path: Optional[str] = None) -> Config:
        """Construct a Config from `file_path` or from the default hard-coded path.

        Unlike previous versions, this **raises** FileNotFoundError if the file
        does not exist or cannot be read. No env var fallbacks are used.

        Args:
            file_path: Optional explicit path; defaults to `DEFAULT_CONFIG_PATH`.

        Returns:
            Config: Loaded configuration object.
        """
        return cls(file_path=file_path)

    # ---------- Lifecycle ----------
    def __init__(self, file_path: Optional[str] = None, _force_fixture: bool = False) -> None:
        """Initialize and load configuration.

        Args:
            file_path: Optional explicit INI path; if None, uses DEFAULT_CONFIG_PATH.
            _force_fixture: Test-only flag to bypass file loading and relax validations.

        Raises:
            FileNotFoundError: If the config file is missing/unreadable (strict mode).
        """
        self._path = file_path or DEFAULT_CONFIG_PATH

        # Parser: no %() interpolation (prevents log format clashes), tolerate dups.
        self._cfg = configparser.RawConfigParser(strict=False)

        # Determine operating mode:
        # - Strict by default: require the file to exist and be readable.
        # - Fixture mode only if explicitly requested by caller.
        path_exists = Path(self._path).exists()

        if not _force_fixture:
            if not path_exists:
                raise FileNotFoundError(f"Config file not found: {self._path}")
            read_ok = self._cfg.read(self._path)
            if not read_ok:
                raise FileNotFoundError(f"Failed to read config file: {self._path}")
            self.fixture_mode = False
            logger.info("Config loaded from %s.", self._path)
        else:
            # Explicit fixture mode: useful for unit tests / offline runs
            self.fixture_mode = True
            logger.info("Config initialized in FIXTURE MODE (path=%s).", self._path)

        # -----------------------------
        # Field extraction (with sane fallbacks so partial files are okay)
        # -----------------------------

        # --- eMASS API config ---
        self.emass_api_base: str = (
            self._cfg.get("emass", "api_base", fallback="https://connect.emass.apps.mil/api").rstrip("/")
        )
        self.emass_api_key: str = self._cfg.get("emass", "api_key", fallback="")
        self.emass_cert_path: Optional[str] = self._cfg.get("emass", "cert_path", fallback="") or None
        self.emass_key_path: Optional[str] = self._cfg.get("emass", "key_path", fallback="") or None
        self.emass_pfx_path: Optional[str] = self._cfg.get("emass", "pfx_path", fallback="") or None
        self.emass_pfx_pass: Optional[str] = self._cfg.get("emass", "pfx_pass", fallback="") or None
        self.emass_verify_raw: str = self._cfg.get("emass", "verify", fallback="true")
        self.emass_system_id: str = self._cfg.get("emass", "system_id", fallback="SYS-123")

        # --- paths (no APMS CSV here; it’s provided at runtime) ---
        self.checklist_path: str = self._cfg.get("paths", "checklist", fallback="DeepDiveTests.xlsx")
        self.demo_assets: Optional[str] = self._cfg.get("paths", "demo_assets", fallback=None)
        # Base directory for engine-relative JSON/fixtures (used by test_api._load_json)
        # Default to the repo's notional assets directory.
        self.data_root: str = self._cfg.get(
            "paths",
            "data_root",
            fallback="TECTIXv2/engine/Notionalassets",
        )

        # --- logging preferences ---
        self.log_destination: str = self._cfg.get("logging", "destination", fallback="stdout").lower()
        self.log_file: str = self._cfg.get(
            "logging",
            "file",
            fallback=self._cfg.get("logging", "log_file", fallback="/app/logs/ato_tests.log"),
        )
        self.log_level: str = self._cfg.get("logging", "level", fallback="INFO").upper()
        # Raw format string allowed (no interpolation)
        self.log_format: str = self._cfg.get(
            "logging", "format", fallback="%(asctime)s [%(levelname)s] %(name)s: %(message)s", raw=True
        )

    # ---------- Logging ----------
    def configure_logging(self) -> None:
        """Integrate with host logging or install a minimal fallback handler.

        Behavior:
        1) If handlers exist on either the process root or the family root
           (ENGINE_LOGGER_ROOT), we DO NOT add new handlers. We only adjust
           the level and allow propagation so engine logs flow into the app.
        2) Otherwise, we attach a single handler (stdout or file) to the family
           root and propagate to it.
        """
        level = getattr(logging, self.log_level, logging.INFO)

        family_root = logging.getLogger(ENGINE_LOGGER_ROOT)
        process_root = logging.getLogger()

        # Case 1: app already configured logging
        if family_root.handlers or process_root.handlers:
            family_root.setLevel(level)
            logger.propagate = True
            logger.debug(
                "Engine logging integrated with existing handlers (destination=%s, file=%s)",
                self.log_destination,
                self.log_file,
            )
            return

        # Case 2: fallback handler
        if self.log_destination == "file":
            path = Path(self.log_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            handler: logging.Handler = logging.FileHandler(path)
        else:
            handler = logging.StreamHandler()  # stdout

        formatter = logging.Formatter(self.log_format)
        handler.setFormatter(formatter)

        family_root.addHandler(handler)
        family_root.setLevel(level)
        family_root.propagate = False  # owns the handler

        # Ensure our module logger bubbles up to the family root
        logger.propagate = True
        logger.debug(
            "Engine logging configured (fallback; destination=%s, file=%s)",
            self.log_destination,
            self.log_file,
        )

    # ---------- eMASS helpers ----------
    def tls_verify(self) -> Union[bool, str]:
        """Convert the `verify` setting to a requests-compatible value.

        Returns:
            True/False for strict/disabled TLS verification, or a path to a CA bundle.
        """
        raw = (self.emass_verify_raw or "").strip().lower()
        if raw in {"true", "1", "yes"}:
            return True
        if raw in {"false", "0", "no"}:
            return False
        # Otherwise treat as a custom CA bundle path
        return self.emass_verify_raw

    def emass_cert_tuple(self) -> Optional[Tuple[str, str]]:
        """Return a (cert_path, key_path) tuple if PEM client auth is configured, else None."""
        if self.emass_cert_path and self.emass_key_path:
            return (self.emass_cert_path, self.emass_key_path)
        return None

    def has_pfx(self) -> bool:
        """True if a PFX + password are configured for client auth."""
        return bool(self.emass_pfx_path and self.emass_pfx_pass)

    def validate_minimums(self) -> None:
        """Validate minimum configuration for live eMASS usage.

        - In fixture mode (tests), this is a NO-OP.
        - In strict mode, require API key and client auth (PEM or PFX).
        """
        if self.fixture_mode:
            logger.debug("validate_minimums(): skipped (fixture mode).")
            return

        if not self.emass_api_key:
            raise ValueError("Missing eMASS API key (emass.api_key).")
        if not (self.emass_cert_tuple() or self.has_pfx()):
            raise ValueError("Missing client auth: provide cert_path+key_path OR pfx_path+pfx_pass.")

    # ---------- Path helpers ----------
    def resolve_data_path(self, fname: str | Path) -> str:
        """Return absolute path under `data_root` (or `fname` if already absolute)."""
        p = Path(fname)
        if p.is_absolute():
            return str(p)
        base = Path(self.data_root)
        return str((base / p).resolve())

    # ---------- Org ID accessors ----------
    @property
    def emass_org_id(self) -> str:
        """Organization scope for eMASS dashboards (string for querystring usage)."""
        return str(self._cfg.get("emass", "org_id", fallback="20")).strip()

    def set_emass_org_id(self, value: int | str, persist: bool = False) -> None:
        """Update the eMASS org_id in memory and optionally persist to the INI.

        Args:
            value: New organization id (int or str, numeric).
            persist: If True, write back to the current INI on disk.

        Raises:
            RuntimeError: If persist=True but the config path is unknown.
            ValueError: If `value` is not numeric.
        """
        s = str(value).strip()
        if not s.isdigit():
            raise ValueError(f"org_id must be numeric, got: {value!r}")
        if not self._cfg.has_section("emass"):
            self._cfg.add_section("emass")
        self._cfg.set("emass", "org_id", s)
        logger.info("Set eMASS org_id to %s (persist=%s)", s, persist)
        if persist:
            if not getattr(self, "_path", None):
                raise RuntimeError("Config file path unknown; cannot persist changes.")
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w") as f:
                self._cfg.write(f)
            logger.debug("Persisted org_id=%s to %s", s, self._path)

    # ---------- Diagnostics ----------
    @property
    def path(self) -> str:
        """Return the resolved INI path recorded by this instance."""
        return self._path

    def as_dict(self) -> Dict[str, Any]:
        """Return a (lightly redacted) snapshot of key config values for diagnostics."""
        return {
            "path": self._path,
            "fixture_mode": self.fixture_mode,
            "emass_api_base": self.emass_api_base,
            "emass_api_key_set": bool(self.emass_api_key),
            "emass_verify_raw": self.emass_verify_raw,
            "emass_cert_path": bool(self.emass_cert_path),
            "emass_key_path": bool(self.emass_key_path),
            "emass_pfx_path": bool(self.emass_pfx_path),
            "emass_system_id": self.emass_system_id,
            "emass_org_id": self.emass_org_id,
            "checklist_path": self.checklist_path,
            "demo_assets": self.demo_assets,
            "data_root": self.data_root,
            "log_destination": self.log_destination,
            "log_file": self.log_file,
            "log_level": self.log_level,
            "logger_root": ENGINE_LOGGER_ROOT,
        }


def update_emass_credentials(
    *,
    ini_path: Union[str, Path] = DEFAULT_CONFIG_PATH,
    cert_path: Optional[str] = None,
    api_key: Optional[str] = None,
    pfx_pass: Optional[str] = None,
    make_backup: bool = True,
) -> Path:
    """Update selected credentials in the `[emass]` section of an INI file.

    This function performs targeted, in-place edits of the `[emass]` section to
    preserve comments and overall formatting (it does **not** round-trip with
    `configparser.write()`, which would strip comments and reflow the file).
    Only keys explicitly provided are changed; all other content remains
    untouched.

    The following keys may be updated:
      - `cert_path`  (PEM client certificate path)
      - `api_key`    (eMASS API key)
      - `pfx_pass`   (password for `pfx_path` bundle)

    To avoid partial writes, the function writes to a temporary file in the
    same directory and then atomically renames it into place. It can also
    create a timestamped `.bak` backup of the original file.

    Args:
      ini_path: Path to the INI file. Defaults to `DEFAULT_CONFIG_PATH`.
      cert_path: New value for `emass.cert_path`. If `None`, this key is not
        modified.
      api_key: New value for `emass.api_key`. If `None`, this key is not
        modified.
      pfx_pass: New value for `emass.pfx_pass`. If `None`, this key is not
        modified.
      make_backup: If True, create a timestamped `.bak` copy of the original
        file before writing.

    Returns:
      The `Path` of the updated INI file.

    Raises:
      FileNotFoundError: If `ini_path` does not exist or is unreadable.
      ValueError: If the INI lacks an `[emass]` section.
      OSError: If the function cannot write the updated file.

    Examples:
      Update all three in one call:

      >>> update_emass_credentials(
      ...     cert_path="/etc/pki/emass/client.crt",
      ...     api_key="MY_REAL_API_KEY",
      ...     pfx_pass="CorrectHorseBatteryStaple!",
      ... )

      Update just the API key (other values unchanged):

      >>> update_emass_credentials(api_key="new-key-123")
    """
    ini_path = Path(ini_path)

    if not ini_path.exists() or not ini_path.is_file():
        raise FileNotFoundError(f"Config file not found: {ini_path}")

    original_text = ini_path.read_text(encoding="utf-8", errors="strict")

    # Locate [emass] section boundaries.
    section_header_pattern = re.compile(r"(?mi)^\s*\[(?P<name>[^\]]+)\]\s*$")
    emass_header_pattern = re.compile(r"(?mi)^\s*\[emass\]\s*$")

    emass_match = emass_header_pattern.search(original_text)
    if not emass_match:
        raise ValueError(
            f"Section [emass] not found in {ini_path}. "
            "Cannot update credentials."
        )

    # Find the start of [emass] content and the start of the next section.
    emass_start = emass_match.end()
    next_section = section_header_pattern.search(original_text, emass_start)
    emass_end = next_section.start() if next_section else len(original_text)

    before = original_text[:emass_start]
    emass_block = original_text[emass_start:emass_end]
    after = original_text[emass_end:]

    # Helper to replace-or-append a single key in the emass block.
    def _upsert_key(block: str, key: str, value: str) -> str:
        """
        Replace the first occurrence of 'key = ...' within the emass block
        (ignoring comments and leading whitespace). If not found, append a new
        line at the end of the block, preserving the block's trailing newline.
        """
        # Match an uncommented assignment line for this key.
        # - Start of line
        # - Optional whitespace
        # - key
        # - optional whitespace
        # - '=' and the rest of the line
        assign_re = re.compile(rf"(?mi)^(?P<prefix>\s*){re.escape(key)}\s*=.*?$")

        if assign_re.search(block):
            # Replace only the first occurrence to avoid accidental multi-write.
            return assign_re.sub(rf"\g<prefix>{key} = {value}", block, count=1)

        # If the key doesn't exist, append it neatly. Preserve whether the block
        # ended with a newline.
        ends_with_nl = block.endswith("\n")
        new_line = f"{key} = {value}"
        if ends_with_nl:
            return block + new_line + "\n"
        return block + "\n" + new_line + "\n"

    # Perform requested edits.
    updated_block = emass_block
    if cert_path is not None:
        updated_block = _upsert_key(updated_block, "cert_path", str(cert_path))
    if api_key is not None:
        updated_block = _upsert_key(updated_block, "api_key", str(api_key))
    if pfx_pass is not None:
        updated_block = _upsert_key(updated_block, "pfx_pass", str(pfx_pass))

    # If nothing changed, short-circuit without touching the file.
    if updated_block == emass_block:
        return ini_path

    new_text = before + updated_block + after

    # Optionally create a timestamped backup.
    if make_backup:
        ts = time.strftime("%Y%m%d-%H%M%S")
        backup_path = ini_path.with_suffix(ini_path.suffix + f".{ts}.bak")
        shutil.copy2(ini_path, backup_path)

    # Preserve permissions; default to 0o600 if unreadable.
    try:
        mode = ini_path.stat().st_mode
    except OSError:
        mode = 0o600

    # Atomic write in the same directory.
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(ini_path.parent)) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(new_text)
        tmp.flush()
        os.fsync(tmp.fileno())
    try:
        os.chmod(tmp_path, mode)
    except OSError:
        # Non-fatal: continue with rename even if chmod fails.
        pass

    tmp_path.replace(ini_path)  # Atomic on POSIX when same filesystem.

    return ini_path


# ------------------------------------------------------------------------------
# CLI Self-Test
#   Run:
#       python -m engine.config
#    or python engine/config.py
# ------------------------------------------------------------------------------
def _self_test() -> int:
    """Minimal self-test for config loading/logging/validation."""
    try:
        cfg = Config.load_or_default(DEFAULT_CONFIG_PATH)
        cfg.configure_logging()

        try:
            cfg.validate_minimums()
        except Exception as e:
            logger.error("validate_minimums failed: %s", e)
            if not cfg.fixture_mode:
                print(json.dumps(cfg.as_dict(), indent=2))
                return 2

        print(json.dumps(cfg.as_dict(), indent=2))
        return 0
    except Exception as e:
        sys.stderr.write(f"[config self-test] ERROR: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(_self_test())

