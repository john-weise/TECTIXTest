// src/pages/Account.tsx
import React, { useEffect, useState, useCallback } from "react";
import CyberBackground from "../components/CyberBackground";
import TopNav from "../components/TopNav";
import TwoFactorEnrollModal from "../components/TwoFactorEnrollModal";
import "../styles/AdminPanel.css";
import "../styles/Dashboard.css";

type SessionInfo = {
  authenticated: boolean;
  user?: string;
  is_admin?: boolean;
};

type TwofaStatus = {
  enabled: boolean;
  configured: boolean;
};

export default function Account() {
  const [sessionInfo, setSessionInfo] = useState<SessionInfo>({
    authenticated: false,
  });

  // Password change state
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [showCur, setShowCur] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // 2FA state
  const [twofaStatus, setTwofaStatus] = useState<TwofaStatus | null>(null);
  const [twofaLoading, setTwofaLoading] = useState(false);
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [recoveryMsg, setRecoveryMsg] = useState<string | null>(null);
  const [recoveryErr, setRecoveryErr] = useState<string | null>(null);

  // 2FA enrollment modal
  const [twofaModalOpen, setTwofaModalOpen] = useState(false);

  /**
   * Fetches the current 2FA status for the logged-in user.
   * Safe to call multiple times; used on page load and after enrollment.
   */
  const refreshTwofaStatus = useCallback(async () => {
    try {
      const tfRes = await fetch("/api/account/2fa/status", {
        credentials: "include",
      });
      if (!tfRes.ok) {
        // Soft-fail: leave previous state, show generic hint.
        return;
      }
      const tfJson = await tfRes.json();
      setTwofaStatus({
        enabled: !!tfJson.enabled,
        configured: !!tfJson.configured,
      });
    } catch {
      // Soft-fail: caller can decide how to message this.
    }
  }, []);

  // Initial session + 2FA status
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/session", { credentials: "include" });
        const j = await r.json();
        setSessionInfo(j);

        if (j?.authenticated) {
          await refreshTwofaStatus();
        }
      } catch {
        setSessionInfo({ authenticated: false });
      }
    })();
  }, [refreshTwofaStatus]);

  const canSubmit =
    !busy &&
    currentPw.trim().length > 0 &&
    newPw.trim().length >= 8 &&
    newPw === confirmPw;

  const submitChange = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setMsg(null);
    setErr(null);

    try {
      const r = await fetch("/api/account/password", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: currentPw,
          new_password: newPw,
        }),
      });

      const j = await r.json();
      if (r.ok && j?.success) {
        setMsg("Password updated successfully.");
        setCurrentPw("");
        setNewPw("");
        setConfirmPw("");
      } else {
        setErr(j?.error || "Password change failed.");
      }
    } catch {
      setErr("Network error while changing password.");
    } finally {
      setBusy(false);
    }
  };

  /**
   * Regenerates recovery codes for the current user.
   * Only meaningful when 2FA is enabled.
   */
  const regenerateRecoveryCodes = async () => {
    if (!twofaStatus?.enabled) return;

    if (
      !window.confirm(
        "Regenerate recovery codes? Your existing recovery codes will no longer work."
      )
    ) {
      return;
    }

    setTwofaLoading(true);
    setRecoveryMsg(null);
    setRecoveryErr(null);
    setRecoveryCodes([]);

    try {
      const res = await fetch("/api/account/2fa/recovery/regenerate", {
        method: "POST",
        credentials: "include",
      });

      const j = await res.json();

      if (!res.ok) {
        throw new Error(j?.error || "Failed to regenerate recovery codes.");
      }

      if (!j?.recovery_codes || !Array.isArray(j.recovery_codes)) {
        throw new Error("Server did not return recovery codes.");
      }

      setRecoveryCodes(j.recovery_codes);
      setRecoveryMsg(
        "New recovery codes generated. Store them in a safe place; each code can be used once."
      );
    } catch (e: any) {
      setRecoveryErr(e?.message || "Failed to regenerate recovery codes.");
    } finally {
      setTwofaLoading(false);
    }
  };

  /**
   * Handles closing the 2FA enrollment modal.
   * We refetch status so the card reflects whether the user actually enabled 2FA.
   */
  const handleTwofaModalClose = async () => {
    setTwofaModalOpen(false);
    // reset recovery info UI; user might have new codes from enrollment
    setRecoveryCodes([]);
    setRecoveryMsg(null);
    setRecoveryErr(null);
    await refreshTwofaStatus();
  };

  return (
    <>
      {/* Subtle brand background */}
      <div className="dashboard-background-box">
        <CyberBackground />
      </div>

      {/* Floating TopNav */}
      <TopNav isAdmin={!!sessionInfo.is_admin} />

      {/* Ensure content clears the fixed TopNav */}
      <style>{`
        .account-wrapper { padding-top: 78px; } /* TopNav offset */
      `}</style>

      <div className="account-wrapper">
        <div className="admin-main" style={{ gridTemplateColumns: "1fr" }}>
          <section className="admin-content" style={{ marginTop: "20px" }}>
            <h2 className="section-title">Manage Account</h2>
            <div className="gold-rule" aria-hidden="true" />

            {sessionInfo.authenticated ? (
              <div className="meta" style={{ marginBottom: 12 }}>
                <div>
                  <strong>User:</strong> {sessionInfo.user}
                </div>
                <div>
                  <strong>Role:</strong>{" "}
                  {sessionInfo.is_admin ? "Admin" : "User"}
                </div>
              </div>
            ) : (
              <div className="error-banner">You are not signed in.</div>
            )}

            {err && <div className="error-banner">{err}</div>}
            {msg && (
              <div
                className="card"
                style={{ borderColor: "rgba(0,180,0,0.45)" }}
              >
                {msg}
              </div>
            )}

            {/* Change Password */}
            <div className="card">
              <h3 className="admin-subhead">Change Password</h3>
              <div className="admin-form" style={{ maxWidth: 520 }}>
                <div style={{ position: "relative" }}>
                  <input
                    className="admin-input"
                    type={showCur ? "text" : "password"}
                    placeholder="Current password"
                    value={currentPw}
                    onChange={(e) => setCurrentPw(e.target.value)}
                    autoComplete="current-password"
                  />
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => setShowCur((s) => !s)}
                    style={{
                      position: "absolute",
                      right: 6,
                      top: "50%",
                      transform: "translateY(-50%)",
                    }}
                    aria-label={
                      showCur
                        ? "Hide current password"
                        : "Show current password"
                    }
                  >
                    {showCur ? "Hide" : "Show"}
                  </button>
                </div>

                <div style={{ position: "relative" }}>
                  <input
                    className="admin-input"
                    type={showNew ? "text" : "password"}
                    placeholder="New password (min 8 chars)"
                    value={newPw}
                    onChange={(e) => setNewPw(e.target.value)}
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => setShowNew((s) => !s)}
                    style={{
                      position: "absolute",
                      right: 6,
                      top: "50%",
                      transform: "translateY(-50%)",
                    }}
                    aria-label={
                      showNew ? "Hide new password" : "Show new password"
                    }
                  >
                    {showNew ? "Hide" : "Show"}
                  </button>
                </div>

                <div style={{ position: "relative" }}>
                  <input
                    className="admin-input"
                    type={showConfirm ? "text" : "password"}
                    placeholder="Confirm new password"
                    value={confirmPw}
                    onChange={(e) => setConfirmPw(e.target.value)}
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => setShowConfirm((s) => !s)}
                    style={{
                      position: "absolute",
                      right: 6,
                      top: "50%",
                      transform: "translateY(-50%)",
                    }}
                    aria-label={
                      showConfirm
                        ? "Hide confirm password"
                        : "Show confirm password"
                    }
                  >
                    {showConfirm ? "Hide" : "Show"}
                  </button>
                </div>

                <div className="hint">
                  For security, we never log any password contents.
                </div>

                <div style={{ display: "flex", gap: 10, marginTop: 6 }}>
                  <button
                    className="generate-button"
                    disabled={!canSubmit}
                    onClick={submitChange}
                  >
                    {busy ? "Updating…" : "Update Password"}
                  </button>
                  <button
                    className="secondary-button"
                    onClick={() => {
                      setCurrentPw("");
                      setNewPw("");
                      setConfirmPw("");
                      setErr(null);
                      setMsg(null);
                    }}
                  >
                    Clear
                  </button>
                </div>
              </div>
            </div>

            {/* Two-Factor Authentication / Recovery Codes */}
            <div className="card" style={{ marginTop: 20 }}>
              <h3 className="admin-subhead">Two-Factor Authentication</h3>

              {twofaStatus ? (
                <>
                  <div className="meta" style={{ marginBottom: 8 }}>
                    <div>
                      <strong>Status:</strong>{" "}
                      {twofaStatus.enabled
                        ? "Enabled"
                        : "Not enabled on this account"}
                    </div>
                    {twofaStatus.configured && !twofaStatus.enabled && (
                      <div className="hint">
                        A 2FA secret exists for this account but has not been
                        fully confirmed yet.
                      </div>
                    )}
                  </div>

                  {/* Show self-enrollment button when 2FA is not enabled */}
                  {!twofaStatus.enabled && (
                    <div style={{ marginBottom: 12 }}>
                      <p className="helper-text">
                        Enable 2FA to require a code from an authenticator app
                        in addition to your password when logging in.
                      </p>
                      <button
                        className="generate-button"
                        type="button"
                        onClick={() => setTwofaModalOpen(true)}
                      >
                        Set Up 2FA
                      </button>
                    </div>
                  )}

                  {twofaStatus.enabled && (
                    <>
                      <p className="helper-text">
                        Recovery codes can be used if you lose access to your
                        authenticator device. Regenerating codes will invalidate
                        any existing ones.
                      </p>

                      {recoveryErr && (
                        <div className="error-banner">{recoveryErr}</div>
                      )}
                      {recoveryMsg && (
                        <div
                          className="card"
                          style={{
                            marginTop: 8,
                            borderColor: "rgba(0,180,0,0.45)",
                          }}
                        >
                          {recoveryMsg}
                        </div>
                      )}

                      {recoveryCodes.length > 0 && (
                        <div style={{ marginTop: 10 }}>
                          <div className="hint">
                            Store these codes securely. Each can be used once.
                          </div>
                          <ul className="code-list">
                            {recoveryCodes.map((c) => (
                              <li key={c}>
                                <code>{c}</code>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      <div style={{ marginTop: 10 }}>
                        <button
                          className="secondary-button"
                          disabled={twofaLoading}
                          onClick={regenerateRecoveryCodes}
                        >
                          {twofaLoading
                            ? "Regenerating…"
                            : "Regenerate Recovery Codes"}
                        </button>
                      </div>
                    </>
                  )}
                </>
              ) : (
                <div className="hint">
                  2FA status is currently unavailable. If you believe this is a
                  mistake, try refreshing the page or contacting an admin.
                </div>
              )}
            </div>
          </section>
        </div>
      </div>

      {/* 2FA Enrollment Modal (self-service) */}
      <TwoFactorEnrollModal open={twofaModalOpen} onClose={handleTwofaModalClose} />
    </>
  );
}


