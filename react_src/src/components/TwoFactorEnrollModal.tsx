// src/components/TwoFactorEnrollModal.tsx
import React, { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";

type TwoFactorEnrollModalProps = {
  /** Whether the enrollment modal is visible. */
  open: boolean;
  /** Called when the modal should be closed. */
  onClose: () => void;
};

type StartResponse = {
  /** Base32 TOTP secret for manual entry. */
  secret: string;
  /** otpauth:// TOTP provisioning URI (used for QR + app import). */
  otpauth_uri: string;
  /** One-time recovery codes generated at enrollment. */
  recovery_codes: string[];
};

/**
 * TwoFactorEnrollModal
 *
 * Flow:
 * 1. Intro step explaining 2FA and prompting to start enrollment.
 * 2. Enrollment step:
 *    - POST /api/account/2fa/start
 *    - Show QR (generated from otpauth_uri)
 *    - Show manual secret + recovery codes
 *    - Confirm with a 6-digit TOTP code.
 * 3. Done step confirming 2FA is enabled.
 */
export default function TwoFactorEnrollModal({
  open,
  onClose,
}: TwoFactorEnrollModalProps) {
  const [step, setStep] = useState<"intro" | "enroll" | "done">("intro");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  const [secret, setSecret] = useState("");
  const [otpauthUri, setOtpauthUri] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);

  const [code, setCode] = useState("");
  const codeInputRef = useRef<HTMLInputElement | null>(null);

  // Reset internal state whenever the modal is closed.
  useEffect(() => {
    if (!open) {
      setStep("intro");
      setLoading(false);
      setError("");
      setSecret("");
      setOtpauthUri("");
      setRecoveryCodes([]);
      setQrDataUrl(null);
      setCode("");
    }
  }, [open]);

  // Focus OTP input when entering the enroll step.
  useEffect(() => {
    if (step === "enroll" && codeInputRef.current) {
      codeInputRef.current.focus();
    }
  }, [step]);

  if (!open) return null;

  /**
   * Start 2FA enrollment by calling POST /api/account/2fa/start.
   * Expects:
   *   { success: true, secret, otpauth_uri, recovery_codes: [...] }
   */
  const handleBeginEnrollment = async () => {
    setError("");
    setLoading(true);
    setQrDataUrl(null);

    try {
      const res = await fetch("/api/account/2fa/start", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}), // backend resolves user from session
      });

      const data: Partial<StartResponse> & {
        success?: boolean;
        error?: string;
      } = await res.json().catch(() => ({} as any));

      if (!res.ok || data.success === false) {
        const msg =
          data.error ||
          `Failed to start 2FA enrollment (status ${res.status})`;
        throw new Error(msg);
      }

      if (!data.secret || !data.otpauth_uri) {
        throw new Error("Server did not return a TOTP secret or URI.");
      }

      setSecret(data.secret);
      setOtpauthUri(data.otpauth_uri);
      setRecoveryCodes(data.recovery_codes || []);

      // Generate QR code from otpauth_uri.
      try {
        const url = await QRCode.toDataURL(data.otpauth_uri);
        setQrDataUrl(url);
      } catch (qrErr) {
        console.error("[TwoFactorEnrollModal] Failed to generate QR", qrErr);
        // Non-fatal: user can still use the manual secret.
      }

      setStep("enroll");
    } catch (err: any) {
      console.error("[2FA enroll start error]", err);
      setError(err?.message || "Unable to start 2FA enrollment.");
    } finally {
      setLoading(false);
    }
  };

  /**
   * Confirm enrollment by sending the 6-digit code to
   * POST /api/account/2fa/confirm.
   */
  const handleConfirmEnrollment = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = code.trim();
    if (!trimmed || loading) return;

    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/account/2fa/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ code: trimmed }),
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok || !data?.success) {
        const msg = data?.error || "Invalid or expired 2FA code.";
        throw new Error(msg);
      }

      setStep("done");
    } catch (err: any) {
      console.error("[2FA enroll confirm error]", err);
      setError(err?.message || "Unable to confirm 2FA enrollment.");
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    onClose();
  };

  return (
    <div
      className="usg-modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="twofa-enroll-title"
    >
      <div className="usg-modal">
        <div className="usg-modal-bar" aria-hidden="true" />
        <h2 id="twofa-enroll-title" className="usg-title">
          Protect Your Account with 2FA
        </h2>

        {step === "intro" && (
          <>
            <p className="usg-intro">
              For your security, we strongly recommend enabling two-factor
              authentication (2FA). 2FA adds a one-time code from an
              authenticator app on top of your password, making it much harder
              for attackers to access your account.
            </p>
            <ul className="usg-list">
              <li>Use TOTP apps like Google Authenticator, 1Password, or Authy.</li>
              <li>Recovery codes let you back in if you lose your device.</li>
              <li>Setup typically takes less than a minute.</li>
            </ul>

            {error && <div className="login-error">{error}</div>}

            <div className="usg-actions">
              <button
                type="button"
                className="login-button usg-button secondary"
                onClick={handleClose}
                disabled={loading}
              >
                Not Now
              </button>
              <button
                type="button"
                className="login-button usg-button"
                onClick={handleBeginEnrollment}
                disabled={loading}
              >
                {loading ? "Preparing 2FA..." : "Set Up 2FA"}
              </button>
            </div>
          </>
        )}

        {step === "enroll" && (
          <>
            <p className="usg-intro">
              Scan this configuration into your authenticator app, or enter the
              secret manually. Then enter the 6-digit code below to confirm.
            </p>

            {error && <div className="login-error">{error}</div>}

            <div className="twofa-enroll-block">
              {/* QR code if we were able to generate it */}
              {qrDataUrl && (
                <div className="twofa-qr-wrapper" aria-label="Authenticator QR code">
                  <img
                    src={qrDataUrl}
                    alt="Scan this QR code with your authenticator app"
                    className="twofa-qr-image"
                  />
                </div>
              )}

              <h3 className="field-label" style={{ marginTop: 12 }}>
                TOTP Secret (manual entry)
              </h3>
              <code className="code-block">{secret}</code>

              <h3 className="field-label" style={{ marginTop: 8 }}>
                Provisioning URI
              </h3>
              <code className="code-block small">{otpauthUri}</code>

              {recoveryCodes.length > 0 && (
                <>
                  <h3 className="field-label" style={{ marginTop: 12 }}>
                    Recovery Codes
                  </h3>
                  <p className="helper-text">
                    Store these in a safe place. Each recovery code can be used
                    once if you lose access to your authenticator device.
                  </p>
                  <ul className="code-list">
                    {recoveryCodes.map((rc) => (
                      <li key={rc}>
                        <code>{rc}</code>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>

            <form onSubmit={handleConfirmEnrollment} className="twofa-form">
              <label htmlFor="twofaCode" className="field-label">
                Enter code from your authenticator
              </label>
              <input
                id="twofaCode"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="6-digit code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                className="login-input"
                ref={codeInputRef}
              />

              <div className="twofa-actions">
                <button
                  type="button"
                  className="login-button usg-button secondary"
                  onClick={handleClose}
                  disabled={loading}
                >
                  Cancel
                </button>
                <button type="submit" className="login-button" disabled={loading}>
                  {loading ? "Verifying..." : "Confirm 2FA"}
                </button>
              </div>
            </form>
          </>
        )}

        {step === "done" && (
          <>
            <p className="usg-intro">
              Two-factor authentication is now enabled on your account. From now
              on, you&apos;ll be asked for a 2FA code when logging in.
            </p>

            <div className="usg-actions">
              <button
                type="button"
                className="login-button usg-button"
                onClick={handleClose}
              >
                Close
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

