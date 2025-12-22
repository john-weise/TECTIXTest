#helpers.py
from __future__ import annotations
import pandas as pd
from typing import Any, Dict, Optional
from cryptography import x509
from cryptography.hazmat.primitives.serialization.pkcs12 import (
    load_key_and_certificates,
)
from cryptography.exceptions import UnsupportedAlgorithm, InvalidKey

#----------------
#   File validation helpers
#---------------------



def verify_pkcs12_file(pfx_bytes: bytes, password: Optional[str]) -> Dict[str, Any]:
    """Validate that the provided bytes are a genuine PKCS#12 (PFX) container.

    The function attempts to load the PFX with the given password using
    `cryptography`. If parsing succeeds, we consider it a valid PKCS#12 file
    (and *not* just a mislabeled blob). We return light metadata to aid UI.

    Args:
      pfx_bytes: Raw file bytes as uploaded by the client.
      password: Password used to unlock the PKCS#12. Empty string is treated as
        no password. Use None if the PFX is unencrypted.

    Returns:
      A dictionary with:
        - "valid": bool indicating whether parsing succeeded.
        - "has_private_key": bool, True if a private key was present.
        - "subject": str | None, RFC4514 subject of the end-entity certificate.
        - "issuer": str | None, RFC4514 issuer of the end-entity certificate.
        - "chain_length": int, number of CA certificates included.
        - "error": str | None, short error text if invalid.

    Raises:
      None. This function never raises; it reports errors in the return map.
    """
    pwd_bytes = None
    if password is not None:
        pwd = password.encode("utf-8")
        pwd_bytes = pwd if len(pwd) > 0 else b""

    try:
        key, cert, addl = load_key_and_certificates(pfx_bytes, pwd_bytes)
        subject = cert.subject.rfc4514_string() if isinstance(cert, x509.Certificate) else None
        issuer = cert.issuer.rfc4514_string() if isinstance(cert, x509.Certificate) else None
        return {
            "valid": True,
            "has_private_key": key is not None,
            "subject": subject,
            "issuer": issuer,
            "chain_length": len(addl) if addl else 0,
            "error": None,
        }
    except (ValueError, UnsupportedAlgorithm, InvalidKey) as e:
        # ValueError for parse/decrypt failures; UnsupportedAlgorithm for odd ciphers.
        return {
            "valid": False,
            "has_private_key": False,
            "subject": None,
            "issuer": None,
            "chain_length": 0,
            "error": f"{type(e).__name__}: {e}",
        }
    except Exception as e:  # Defensive: catch-all
        return {
            "valid": False,
            "has_private_key": False,
            "subject": None,
            "issuer": None,
            "chain_length": 0,
            "error": f"{type(e).__name__}: {e}",
        }


#----------------
#Test helpers
#--------------
# Columns we explicitly treat as status fields, in priority order.
_STATUS_COLUMN_CANDIDATES = (
    "Result",
    "result",
    "Status",
    "status",
    "Outcome",
    "outcome",
    "test_status",
    "Test Status",
)


def _normalize_status_value(raw: Any) -> str:
    """Normalize an arbitrary status-like value into one of four buckets.

    Returns:
        One of:
            - "pass"
            - "fail"
            - "concern"
            - "neutral"  (includes N/A / unknown / empty)
    """
    if raw is None:
        return "neutral"

    text = str(raw).strip()
    if not text:
        return "neutral"

    upper = text.upper()

    # Handle both plain strings ("PASS") and Enum reprs ("ResultStatus.PASS_").
    if "PASS" in upper:
        return "pass"
    if "FAIL" in upper:
        return "fail"
    if "CONCERN" in upper or "WARN" in upper or "RISK" in upper:
        return "concern"

    # Explicitly treat N/A-ish values as neutral.
    if upper in {"N/A", "NA", "NOT APPLICABLE", "UNKNOWN"}:
        return "neutral"

    # Fallback: anything else is neutral for scoring purposes.
    return "neutral"


def compute_readiness_summary(frame: pd.DataFrame) -> Dict[str, Any]:
    """Compute readiness metrics and a score from a test-results DataFrame.

    Semantics:

      * Prefer a dedicated status column if present:
            "Result", "result", "Status", "status",
            "Outcome", "outcome", "test_status", "Test Status".

      * If no explicit status column exists, scan each row's cells until a
        status-like value is found.

      * Count rows by normalized status bucket: pass / fail / concern / neutral.

      * Compute a score excluding neutral rows:

            score = pass / (pass + fail + concern)

    Args:
        frame: DataFrame where each row represents a test outcome. One column
            should ideally contain a status-like value (e.g. PASS/FAIL/etc),
            but the function will still attempt to infer status if not.

    Returns:
        Dict[str, Any]: A dictionary with the following keys:

        - ``status_column``: ``str | None``
            Name of the column that was treated as the primary status column,
            or ``None`` if no explicit column was found.
        - ``pass``: ``int``
            Number of rows whose status normalized to "pass".
        - ``fail``: ``int``
            Number of rows whose status normalized to "fail".
        - ``concern``: ``int``
            Number of rows whose status normalized to "concern".
        - ``neutral``: ``int``
            Number of rows whose status normalized to "neutral"
            (includes N/A / skipped / unknown).
        - ``considered``: ``int``
            Total number of "considered" rows: ``pass + fail + concern``.
        - ``score_pct``: ``int | None``
            Integer percentage score (0–100), or ``None`` if there were no
            considered rows.
        - ``formula``: ``str``
            Human-readable description of the scoring formula.
    """
    # Fast path: empty / None → deterministic zeroed structure.
    if frame is None or frame.empty:
        return {
            "status_column": None,
            "pass": 0,
            "fail": 0,
            "concern": 0,
            "neutral": 0,
            "considered": 0,
            "score_pct": None,
            "formula": "score = pass / (pass + fail + concern)",
        }

    # Pick the first known status-like column that actually exists.
    columns = [str(col) for col in frame.columns]
    status_column = next(
        (candidate for candidate in _STATUS_COLUMN_CANDIDATES if candidate in columns),
        None,
    )

    pass_count = 0
    fail_count = 0
    concern_count = 0
    neutral_count = 0

    # Iterate row-by-row so we can fall back to "scan all cells" when needed.
    for _, row in frame.iterrows():
        if status_column is not None:
            # Primary path: trust the explicit status column if present.
            status = _normalize_status_value(row.get(status_column))
        else:
            # Fallback path: hunt in all cells on this row until we find a
            # non-neutral status signal.
            status = "neutral"
            for col_name in row.index:
                candidate = _normalize_status_value(row.get(col_name))
                if candidate != "neutral":
                    status = candidate
                    break

        if status == "pass":
            pass_count += 1
        elif status == "fail":
            fail_count += 1
        elif status == "concern":
            concern_count += 1
        else:
            # Includes "neutral" and any unknown / unmapped values.
            neutral_count += 1

    considered_count = pass_count + fail_count + concern_count
    score_pct = round((pass_count / considered_count) * 100) if considered_count else None

    return {
        "status_column": status_column,
        "pass": pass_count,
        "fail": fail_count,
        "concern": concern_count,
        "neutral": neutral_count,
        "considered": considered_count,
        "score_pct": score_pct,
        "formula": "score = pass / (pass + fail + concern)",
    }
