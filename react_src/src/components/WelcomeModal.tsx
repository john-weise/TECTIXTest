// src/components/WelcomeModal.tsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom";
import "./WelcomeModal.css";

type Props = {
  username: string;            // the CURRENT (default) admin's username (e.g., "admin")
  onClose: () => void;         // close modal (used only after success or if you later add "Skip")
  // The following are kept for prop-compatibility with Dashboard wiring
  isDefaultAdmin?: boolean;    // not needed (this modal is only shown to default user)
  needsPasswordReset?: boolean;// not used (no such endpoint); kept to avoid type churn
};

type OpState = "idle" | "submitting" | "success" | "error";

const WelcomeModal: React.FC<Props> = ({ username, onClose }) => {
  // Steps:
  // 0 = Welcome
  // 1 = Create New Admin
  // 2 = Remove Default & Logout (confirmation + action)
  const [step, setStep] = useState<0 | 1 | 2>(0);

  // ----- Create user form -----
  const [nuUsername, setNuUsername] = useState("");
  const [nuPassword, setNuPassword] = useState("");
  const [nuConfirm, setNuConfirm] = useState("");
  const [nuIsAdmin] = useState(true); // fixed: this flow is specifically to create a new admin
  const [nuStatus, setNuStatus] = useState<OpState>("idle");
  const [nuErr, setNuErr] = useState("");

  // show/hide toggles
  const [nuShowPw, setNuShowPw] = useState(false);
  const [nuShowConf, setNuShowConf] = useState(false);

  // ----- Remove default + logout -----
  const [rmStatus, setRmStatus] = useState<OpState>("idle");
  const [rmErr, setRmErr] = useState("");

  // a11y / focus
  const dialogRef = useRef<HTMLDivElement>(null);
  const firstFocusableRef = useRef<HTMLButtonElement>(null);

  // Modal portal root
  const modalRoot =
    document.getElementById("modal-root") ||
    (() => {
      const el = document.createElement("div");
      el.id = "modal-root";
      document.body.appendChild(el);
      return el;
    })();

  // Focus + ESC
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    setTimeout(() => firstFocusableRef.current?.focus(), 0);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      prev?.focus();
    };
  }, [onClose]);

  // ---------- Password requirements & strength ----------
  const pwIssues = useMemo(() => {
    const issues: string[] = [];
    if (nuPassword.length < 12) issues.push("At least 12 characters");
    if (!/[A-Z]/.test(nuPassword)) issues.push("One uppercase letter");
    if (!/[a-z]/.test(nuPassword)) issues.push("One lowercase letter");
    if (!/[0-9]/.test(nuPassword)) issues.push("One number");
    if (!/[^\w\s]/.test(nuPassword)) issues.push("One symbol");
    if (nuUsername && nuPassword && nuPassword.toLowerCase().includes(nuUsername.toLowerCase())) {
      issues.push("Should not contain the username");
    }
    if (nuConfirm && nuPassword !== nuConfirm) {
      issues.push("New and confirm must match");
    }
    if (nuUsername.trim() === username.trim()) {
      issues.push("New admin username must be different from the default username");
    }
    return issues;
  }, [nuUsername, nuPassword, nuConfirm, username]);

  const strongEnough = pwIssues.filter((i) => i !== "New and confirm must match").length === 0;

  // simple strength estimate (0–4)
  const strength = useMemo(() => {
    let s = 0;
    if (nuPassword.length >= 12) s++;
    if (/[A-Z]/.test(nuPassword)) s++;
    if (/[a-z]/.test(nuPassword)) s++;
    if (/[0-9]/.test(nuPassword)) s++;
    if (/[^\w\s]/.test(nuPassword)) s++;
    return Math.min(s, 4);
  }, [nuPassword]);

  // ---------- API helpers ----------
  async function safeMessage(res: Response): Promise<string | undefined> {
    try {
      const data = await res.json();
      return (data && (data.detail || data.error || data.message)) as string | undefined;
    } catch {
      try {
        return await res.text();
      } catch {
        return undefined;
      }
    }
  }

  // POST /api/admin/users — create the permanent admin
  const createUser = async () => {
    setNuStatus("submitting");
    setNuErr("");
    try {
      if (!nuUsername.trim() || !nuPassword) {
        throw new Error("Username and password are required");
      }
      if (!strongEnough) {
        throw new Error("Please satisfy the password requirements.");
      }
      const res = await fetch("/api/admin/users", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: nuUsername.trim(),
          password: nuPassword,
          is_admin: nuIsAdmin, // always true for this flow
        }),
      });
      if (!res.ok) throw new Error((await safeMessage(res)) || "Create user failed");
      setNuStatus("success");
      // Proceed after a short success flash
      setTimeout(() => setStep(2), 400);
    } catch (e: any) {
      setNuStatus("error");
      setNuErr(e?.message || "Unexpected error");
    }
  };

  // DELETE /api/admin/users/<username> THEN POST /api/logout
  const removeDefaultAndLogout = async () => {
    setRmStatus("submitting");
    setRmErr("");
    try {
      // 1) delete the CURRENT default admin (e.g., "admin")
      const del = await fetch(`/api/admin/users/${encodeURIComponent(username)}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!del.ok) {
        throw new Error((await safeMessage(del)) || "Failed to remove default user");
      }
      // 2) log out current session
      await fetch("/api/logout", {
        method: "POST",
        credentials: "include",
      });
      setRmStatus("success");
      // Hard redirect to /login – they should now sign in with the new admin
      window.location.href = "/login";
    } catch (e: any) {
      setRmStatus("error");
      setRmErr(e?.message || "Unexpected error");
    }
  };

  // ---------- UI ----------
  return ReactDOM.createPortal(
    <div className="ttx-modal__backdrop" role="presentation">
      <div
        ref={dialogRef}
        className="ttx-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="welcome-title"
        aria-describedby={step === 0 ? "welcome-desc" : step === 1 ? "nu-desc" : "rm-desc"}
      >
        {/* Header */}
        <div className="ttx-modal__header">
          <div className="ttx-brand">
            <img src="/logo.png" alt="TECTIX logo" className="ttx-brand__logo" />
            <div className="ttx-brand__wordmark">TECTIX</div>
          </div>
          <button
            className="ttx-iconbtn"
            aria-label="Close"
            onClick={onClose}
            title="Close"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="ttx-modal__body">
          {step === 0 && (
            <section>
              <h2 id="welcome-title" className="ttx-modal__title">Welcome to TECTIX</h2>
              <p id="welcome-desc" className="ttx-modal__copy">
                You’re signed in with the bundled <strong>default admin</strong> account (
                <code>{username}</code>). We’ll help you bootstrap a permanent admin and then remove
                the default credentials for security.
              </p>
              <div className="ttx-callout">
                <strong>What happens next:</strong> Create your new admin → Remove default → Logout.
                On the next sign-in, use your new admin credentials.
              </div>
            </section>
          )}

          {step === 1 && (
            <section>
              <h2 id="welcome-title" className="ttx-modal__title">Create New Admin</h2>
              <p id="nu-desc" className="ttx-modal__copy ttx-muted">
                This will be your permanent administrator account. You can add more users later in
                <em> Admin → Users</em>.
              </p>

              <form
                className="ttx-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (nuStatus !== "submitting") createUser();
                }}
              >
                <div className="ttx-field">
                  <label htmlFor="nu-username">Username</label>
                  <input
                    id="nu-username"
                    type="text"
                    value={nuUsername}
                    onChange={(e) => setNuUsername(e.target.value)}
                    required
                    spellCheck={false}
                  />
                </div>

                <div className="ttx-field">
                  <label htmlFor="nu-password">Password</label>
                  <div className="ttx-input-with-toggle">
                    <input
                      id="nu-password"
                      type={nuShowPw ? "text" : "password"}
                      value={nuPassword}
                      onChange={(e) => setNuPassword(e.target.value)}
                      required
                      autoComplete="new-password"
                      aria-describedby="pw-rules"
                    />
                    <button
                      type="button"
                      className="ttx-toggle"
                      onClick={() => setNuShowPw((v) => !v)}
                      aria-label={nuShowPw ? "Hide password" : "Show password"}
                    >
                      {nuShowPw ? "Hide" : "Show"}
                    </button>
                  </div>
                  <StrengthBar value={strength} />
                </div>

                <div className="ttx-field">
                  <label htmlFor="nu-confirm">Confirm password</label>
                  <div className="ttx-input-with-toggle">
                    <input
                      id="nu-confirm"
                      type={nuShowConf ? "text" : "password"}
                      value={nuConfirm}
                      onChange={(e) => setNuConfirm(e.target.value)}
                      required
                      autoComplete="new-password"
                    />
                    <button
                      type="button"
                      className="ttx-toggle"
                      onClick={() => setNuShowConf((v) => !v)}
                      aria-label={nuShowConf ? "Hide password" : "Show password"}
                    >
                      {nuShowConf ? "Hide" : "Show"}
                    </button>
                  </div>
                </div>

                <PasswordHints issues={pwIssues} />

                {nuStatus === "error" && (
                  <div className="ttx-alert ttx-alert--error" role="alert">
                    {nuErr}
                  </div>
                )}
                {nuStatus === "success" && (
                  <div className="ttx-alert ttx-alert--success" role="status">
                    User created.
                  </div>
                )}

                <div className="ttx-modal__actions">
                  <button
                    type="button"
                    className="ttx-btn ttx-btn--ghost"
                    onClick={() => setStep(0)}
                    disabled={nuStatus === "submitting"}
                    ref={firstFocusableRef}
                  >
                    Back
                  </button>
                  <button
                    type="submit"
                    className="ttx-btn ttx-btn--primary"
                    disabled={
                      nuStatus === "submitting" ||
                      !nuUsername.trim() ||
                      !nuPassword ||
                      !nuConfirm ||
                      !strongEnough
                    }
                    aria-busy={nuStatus === "submitting"}
                  >
                    {nuStatus === "submitting" ? "Creating…" : "Create Admin"}
                  </button>
                </div>
              </form>
            </section>
          )}

          {step === 2 && (
            <section>
              <h2 id="welcome-title" className="ttx-modal__title">Remove Default Admin</h2>
              <p id="rm-desc" className="ttx-modal__copy">
                You created <strong>{nuUsername}</strong>. We’ll now remove the bundled default
                account <strong>{username}</strong> and sign you out. Next sign-in, use your new
                credentials.
              </p>
              {rmStatus === "error" && (
                <div className="ttx-alert ttx-alert--error" role="alert">
                  {rmErr}
                </div>
              )}
              <div className="ttx-modal__actions">
                <button
                  type="button"
                  className="ttx-btn ttx-btn--ghost"
                  onClick={() => setStep(1)}
                  disabled={rmStatus === "submitting"}
                >
                  Back
                </button>
                <button
                  type="button"
                  className="ttx-btn ttx-btn--danger"
                  onClick={removeDefaultAndLogout}
                  disabled={rmStatus === "submitting"}
                  aria-busy={rmStatus === "submitting"}
                >
                  {rmStatus === "submitting" ? "Removing & Logging out…" : "Remove & Logout"}
                </button>
              </div>
            </section>
          )}
        </div>

        {/* Footer */}
        <div className="ttx-modal__footer">
          {step === 0 && (
            <div className="ttx-modal__actions">
              <button
                ref={firstFocusableRef}
                className="ttx-btn ttx-btn--primary"
                onClick={() => setStep(1)}
              >
                Get Started
              </button>
            </div>
          )}
        </div>
      </div>
    </div>,
    modalRoot
  );
};

export default WelcomeModal;

/* ---------- small subcomponents ---------- */

const PasswordHints: React.FC<{ issues: string[] }> = ({ issues }) => {
  const ok = issues.length === 0;
  const rules = [
    "At least 12 characters",
    "One uppercase letter",
    "One lowercase letter",
    "One number",
    "One symbol",
    "Should not contain the username",
    "New and confirm must match",
    "New admin username must be different from the default username",
  ];
  return (
    <div className="ttx-hints" id="pw-rules" aria-live="polite">
      <div className="ttx-hints__title">Requirements</div>
      <ul className="ttx-hints__list">
        {rules.map((rule) => {
          const satisfied = !issues.includes(rule);
          return (
            <li key={rule} className={satisfied ? "ok" : "bad"}>
              {rule}
            </li>
          );
        })}
      </ul>
      {ok && <div className="ttx-hints__ok"> Minimum Password Requirments Met. Proceed</div>}
    </div>
  );
};

const StrengthBar: React.FC<{ value: number }> = ({ value }) => {
  // 0..4 segments
  return (
    <div className="ttx-strength" aria-hidden="true">
      {[0, 1, 2, 3].map((i) => (
        <span key={i} className={`seg ${i < value ? "on" : ""}`} />
      ))}
    </div>
  );
};

