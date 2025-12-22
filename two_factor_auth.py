"""Two-factor authentication (2FA) logic for TECTIX.

This module implements Time-based One-Time Password (TOTP) 2FA and recovery
code behavior. All database access is delegated to helper functions defined
in `db.py`. This keeps persistence concerns isolated while allowing this
module to focus on cryptography and control flow.

Typical usage:

  1. Enrollment:
     - Call `start_twofa_enrollment()` to generate a TOTP secret, a
       provisioning URI (for QR code display), and a set of recovery codes.
     - The frontend renders the QR code and shows recovery codes to the user.
     - The user enters a code from their authenticator app; the frontend
       calls `confirm_twofa_enrollment()` to enable 2FA.

  2. Login:
     - The login endpoint calls `is_2fa_enabled()` to determine whether a
       second factor is required.
     - A separate endpoint calls `verify_totp_code()` to validate either a
       TOTP code or a recovery code.

  3. Account management:
     - `regenerate_recovery_codes()` issues new recovery codes and invalidates
       old ones.
     - `disable_twofa()` turns off 2FA and wipes related secrets.

All functions in this module are pure with respect to SQLAlchemy; they only
interact with the database through functions imported from `db.py`.
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Dict, List, Optional

from log_config import setup_logging
import pyotp
from werkzeug.security import check_password_hash, generate_password_hash

from db import (
    get_twofa_flags,
    is_twofa_enabled as db_is_twofa_enabled,
    set_twofa_enrollment,
    enable_twofa,
    disable_twofa as db_disable_twofa,
    get_twofa_secret,
    get_twofa_recovery_hashes,
    set_twofa_recovery_hashes,
)


logger = setup_logging() 

TOTP_ISSUER_NAME = os.getenv("TECTIX_2FA_ISSUER", "TECTIX")

DEFAULT_RECOVERY_CODE_COUNT = 10
DEFAULT_RECOVERY_CODE_LENGTH = 10


def is_2fa_enabled(username: str) -> bool:
    """Returns whether 2FA is enabled for the given user.

    This is a thin wrapper over the corresponding `db.py` helper and is
    intended for use in the login flow.

    Args:
      username: The username of the user to query.

    Returns:
      True if 2FA is enabled for the user; False otherwise.
    """
    return db_is_twofa_enabled(username)


def get_2fa_status(username: str) -> Dict[str, bool]:
    """Returns a high-level 2FA status summary for the user.

    This function is intended for UI surfaces that need to know if a user
    has 2FA configured and whether it is currently enforced.

    Args:
      username: The username of the user to query.

    Returns:
      A dict with:
        enabled: True if 2FA is enforced for the user.
        configured: True if a secret exists, even if 2FA is not enabled.

    Raises:
      KeyError: If the user does not exist.
    """
    return get_twofa_flags(username)


def start_twofa_enrollment(
    username: str,
    issuer_name: Optional[str] = None,
    recovery_code_count: int = DEFAULT_RECOVERY_CODE_COUNT,
) -> Dict[str, object]:
    """Starts 2FA enrollment and returns provisioning details.

    This function generates a new TOTP secret, a provisioning URI, and a set
    of recovery codes. It persists the secret and hashed recovery codes via
    `db.py` and marks 2FA as not yet enabled. Any existing secret or recovery
    codes are overwritten.

    Args:
      username: The username of the user starting enrollment.
      issuer_name: Optional override for the TOTP issuer displayed in
        authenticator apps. If not provided, uses TOTP_ISSUER_NAME.
      recovery_code_count: Number of recovery codes to generate. Must be
        non-negative.

    Returns:
      A dict containing:
        secret: The base32-encoded TOTP secret.
        provisioning_uri: The TOTP provisioning URI for QR code generation.
        recovery_codes: A list of plaintext recovery codes.

    Raises:
      KeyError: If the user does not exist.
      ValueError: If recovery_code_count is negative.
    """
    if recovery_code_count < 0:
        raise ValueError("recovery_code_count must be non-negative")

    issuer = issuer_name or TOTP_ISSUER_NAME
    secret = pyotp.random_base32()

    recovery_codes = _generate_recovery_codes(
        count=recovery_code_count,
        length=DEFAULT_RECOVERY_CODE_LENGTH,
    )
    hashed_codes = [_hash_recovery_code(code) for code in recovery_codes]

    # Persist secret and hashed codes; twofa_enabled is set to False inside db.
    set_twofa_enrollment(username=username, secret=secret, hashed_recovery_codes=hashed_codes)

    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=username, issuer_name=issuer)

    logger.info("2FA enrollment started for user '%s'", username)

    return {
        "secret": secret,
        "provisioning_uri": provisioning_uri,
        "recovery_codes": recovery_codes,
    }


def confirm_twofa_enrollment(username: str, code: str) -> bool:
    """Confirms 2FA enrollment after a user enters a TOTP code.

    This function verifies the given code against the stored TOTP secret and,
    on success, marks 2FA as enabled for the user.

    Args:
      username: The username of the user confirming enrollment.
      code: The 6-digit TOTP code from the user's authenticator app.

    Returns:
      True if the code is valid and 2FA has been enabled; False if the code
      is invalid or no secret is configured.

    Raises:
      KeyError: If the user does not exist.
    """
    normalized_code = (code or "").strip()
    if not normalized_code:
        return False

    secret = get_twofa_secret(username)
    if not secret:
        logger.warning("confirm_twofa_enrollment: user '%s' has no secret", username)
        return False

    totp = pyotp.TOTP(secret)
    is_valid = bool(totp.verify(normalized_code, valid_window=1))
    if not is_valid:
        logger.warning("confirm_twofa_enrollment: invalid OTP for user '%s'", username)
        return False

    enable_twofa(username)
    logger.info("2FA enrollment confirmed for user '%s'", username)
    return True


def disable_twofa(username: str) -> None:
    """Disables 2FA for a user and clears related secrets.

    This is a thin wrapper over the corresponding `db.py` helper and is
    intended for account settings flows or administrative actions.

    Args:
      username: The username of the user whose 2FA should be disabled.

    Raises:
      KeyError: If the user does not exist.
    """
    db_disable_twofa(username)
    logger.info("2FA disabled for user '%s'", username)


def regenerate_recovery_codes(
    username: str,
    count: int = DEFAULT_RECOVERY_CODE_COUNT,
) -> List[str]:
    """Regenerates recovery codes for a user.

    Existing recovery codes are invalidated and replaced by a new set.
    The TOTP secret and 2FA enabled status are left unchanged.

    Args:
      username: The username of the user to update.
      count: The number of codes to generate. Must be non-negative.

    Returns:
      A list of plaintext recovery codes. These should be shown to the user
      at generation time. They cannot be retrieved later.

    Raises:
      KeyError: If the user does not exist.
      ValueError: If count is negative.
    """
    if count < 0:
        raise ValueError("count must be non-negative")

    recovery_codes = _generate_recovery_codes(
        count=count,
        length=DEFAULT_RECOVERY_CODE_LENGTH,
    )
    hashed_codes = [_hash_recovery_code(code) for code in recovery_codes]

    set_twofa_recovery_hashes(username=username, hashed_codes=hashed_codes)
    logger.info("2FA recovery codes regenerated for user '%s'", username)
    return recovery_codes


def verify_totp_code(username: str, code: str) -> bool:
    """Verifies a TOTP code or recovery code for a user.

    This function is intended for use during the 2FA step of login. It
    validates the candidate code in two stages:

      1. TOTP verification against the user's stored TOTP secret.
      2. Recovery code verification against stored hashed recovery codes.

    If the code matches a recovery code, that recovery code is consumed and
    removed from the stored set.

    Args:
      username: The username of the user submitting the code.
      code: The code to verify. This can be a TOTP code or a recovery code.

    Returns:
      True if the code is valid (either as a TOTP code or a recovery code);
      False otherwise.

    Raises:
      KeyError: If the user does not exist.
    """
    normalized_code = (code or "").strip()
    if not normalized_code:
        return False

    # 1. TOTP verification.
    secret = get_twofa_secret(username)
    if secret:
        totp = pyotp.TOTP(secret)
        if totp.verify(normalized_code, valid_window=1):
            logger.info("TOTP code accepted for user '%s'", username)
            return True

    # 2. Recovery code verification.
    hashed_codes = get_twofa_recovery_hashes(username)
    if not hashed_codes:
        logger.warning("2FA verification failed for user '%s': no recovery codes", username)
        return False

    matched_index: Optional[int] = None
    for idx, hashed in enumerate(hashed_codes):
        if check_password_hash(hashed, normalized_code):
            matched_index = idx
            break

    if matched_index is None:
        logger.warning("2FA verification failed for user '%s': invalid code", username)
        return False

    # Consume the matched recovery code.
    del hashed_codes[matched_index]
    set_twofa_recovery_hashes(username=username, hashed_codes=hashed_codes)
    logger.info("Recovery code accepted for user '%s'", username)
    return True


def _generate_recovery_codes(count: int, length: int) -> List[str]:
    """Generates a list of random plaintext recovery codes.

    Recovery codes are generated as random hexadecimal strings and truncated
    to the requested length. Hex encoding favors readability and ease of
    manual entry over maximum entropy per character.

    Args:
      count: Number of codes to generate. Must be non-negative.
      length: Length of each code in characters. Must be positive.

    Returns:
      A list of plaintext recovery codes.

    Raises:
      ValueError: If count is negative or length is not positive.
    """
    if count < 0:
        raise ValueError("count must be non-negative")
    if length <= 0:
        raise ValueError("length must be positive")

    codes: List[str] = []
    for _ in range(count):
        raw = secrets.token_hex(16)  # 32 hex characters
        codes.append(raw[:length])

    return codes


def _hash_recovery_code(code: str) -> str:
    """Hashes a plaintext recovery code for storage.

    This helper uses the same password hashing primitives as the main
    authentication flow. The resulting hash includes a random salt and is
    intentionally slow to resist offline cracking.

    Args:
      code: The plaintext recovery code to hash.

    Returns:
      A hashed representation of the recovery code suitable for storage.
    """
    return generate_password_hash(code)
