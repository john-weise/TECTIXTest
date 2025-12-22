// src/components/TwoFactor.tsx
import React, { useState, useEffect, useRef } from "react";

type TwoFactorModalProps = {
  open: boolean;
  loading: boolean;
  error?: string;
  /**
   * Called when the user submits either a TOTP code or a recovery code.
   * The backend is responsible for interpreting the value.
   */
  onSubmit: (code: string) => void;
  onClose: () => void;
};

/**
 * TwoFactorModal
 *
 * Generic 2FA prompt that supports:
 *  - Normal TOTP codes from an authenticator app.
 *  - Recovery codes for users who have lost access to their device.
 *
 * The component keeps "which kind of code am I entering?" as local UI state
 * only; the backend receives a single opaque `code` string and uses shared
 * verification logic (TOTP or recovery code).
 */
export default function TwoFactorModal({
  open,
  loading,
  error,
  onSubmit,
  onClose,
}: TwoFactorModalProps) {
  const [code, setCode] = useState("");
  const [mode, setMode] = useState<"totp" | "recovery">("totp");
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Whenever the modal opens, reset to the default TOTP mode & clear input.
  useEffect(() => {
    if (open) {
      setCode("");
      setMode("totp");
      // Slight delay to ensure element is in DOM before focusing.
      requestAnimationFrame(() => {
        if (inputRef.current) {
          inputRef.current.focus();
        }
      });
    }
  }, [open]);

  if (!open) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim() || loading) return;
    onSubmit(code.trim());
  };

  const toggleMode = () => {
    setCode("");
    setMode((prev) => (prev === "totp" ? "recovery" : "totp"));
    requestAnimationFrame(() => {
      if (inputRef.current) {
        inputRef.current.focus();
      }
    });
  };

  const isTotpMode = mode === "totp";

  const title =
    mode === "totp"
      ? "Two-Factor Authentication"
      : "Use a Recovery Code";

  const description = isTotpMode
    ? "Enter the 6-digit code from your authenticator app. If you cannot access your device, you can switch to a recovery code instead."
    : "Enter one of your single-use recovery codes. Using a recovery code will sign you in and consume that code.";

  const placeholder = isTotpMode ? "6-digit authenticator code" : "Recovery code";

  const toggleLabel = isTotpMode
    ? "Use a recovery code instead"
    : "Use an authenticator code instead";

  return (
    <div
      className="usg-modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="twofa-title"
    >
      <div className="usg-modal">
        <div className="usg-modal-bar" aria-hidden="true" />
        <h2 id="twofa-title" className="usg-title">
          {title}
        </h2>

        <p className="usg-intro">{description}</p>

        {error && <div className="login-error">{error}</div>}

        <form onSubmit={handleSubmit} className="twofa-form">
          <input
            type={isTotpMode ? "text" : "text"}
            inputMode={isTotpMode ? "numeric" : "text"}
            autoComplete="one-time-code"
            placeholder={placeholder}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className="login-input"
            ref={inputRef}
          />

          <div className="helper-text" style={{ marginTop: 6 }}>
            {isTotpMode
              ? "Codes rotate every 30 seconds. If one fails, wait for the next code and try again."
              : "Recovery codes are single-use. After using one, generate a fresh set from your account page."}
          </div>

          <button
            type="button"
            className="link-button"
            onClick={toggleMode}
            disabled={loading}
            style={{ marginTop: 8 }}
          >
            {toggleLabel}
          </button>

          <div className="twofa-actions">
            <button
              type="button"
              className="login-button usg-button secondary"
              onClick={onClose}
              disabled={loading}
            >
              Cancel
            </button>
            <button type="submit" className="login-button" disabled={loading}>
              {loading ? "Verifying..." : "Verify"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
