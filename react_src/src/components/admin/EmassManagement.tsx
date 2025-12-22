// src/components/admin/EmassManagement.tsx
import React, { useMemo, useState } from "react";

/**
 * EmassManagement
 *
 * eMASS Connection Management UI (admin-only).
 * Requires BOTH:
 *  - API key
 *  - PFX password
 *
 * You may optionally upload/replace the PFX bundle. The server validates the PFX
 * structure before saving and can create a timestamped INI backup.
 *
 * POST multipart/form-data to: /api/admin/update_emass
 * Verify endpoint: POST /api/admin/test_emass  -> { ok: boolean }
 */
export default function EmassManagement(): React.ReactElement {
  // Form state
  const [apiKey, setApiKey] = useState("");
  const [pfxFile, setPfxFile] = useState<File | null>(null);
  const [pfxPass, setPfxPass] = useState("");
  const [makeBackup, setMakeBackup] = useState(true);

  // UX state
  const [submitting, setSubmitting] = useState(false);
  const [serverJson, setServerJson] = useState<any | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);

  // Verify eMASS connection state
  type VerifyState = "idle" | "checking" | "ok" | "fail";
  const [verifyState, setVerifyState] = useState<VerifyState>("idle");
  const [verifyMsg, setVerifyMsg] = useState<string>("Not verified yet");

  // Derived — enforce BOTH apiKey AND pfxPass
  const hasRequiredPair = useMemo(() => Boolean(apiKey && pfxPass), [apiKey, pfxPass]);
  const canSubmit = useMemo(() => {
    if (submitting) return false;
    if (!hasRequiredPair) return false;
    return true;
  }, [submitting, hasRequiredPair]);

  function resetForm(): void {
    setApiKey("");
    setPfxFile(null);
    setPfxPass("");
    setServerJson(null);
    setErrorText(null);
    setVerifyState("idle");
    setVerifyMsg("Not verified yet");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErrorText(null);
    setServerJson(null);

    if (!hasRequiredPair) {
      setErrorText("API Key and PFX Password are BOTH required.");
      return;
    }
    if (pfxFile && !pfxPass) {
      setErrorText("A PFX password is required when uploading a PFX.");
      return;
    }

    const fd = new FormData();
    fd.append("api_key", apiKey);
    fd.append("pfx_pass", pfxPass);
    if (pfxFile) fd.append("pfx_file", pfxFile, pfxFile.name);
    fd.append("make_backup", makeBackup ? "true" : "false");

    setSubmitting(true);
    try {
      const res = await fetch("/api/admin/update_emass", {
        method: "POST",
        body: fd,
        credentials: "include",
      });
      const json = await res.json().catch(() => ({}));
      setServerJson(json);

      if (!res.ok || json?.ok === false) {
        const msg =
          json?.error ??
          json?.message ??
          `Request failed with status ${res.status} ${res.statusText}`;
        setErrorText(String(msg));
      }
    } catch (err: any) {
      setErrorText(`Network error: ${err?.message ?? err}`);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerify() {
    setVerifyState("checking");
    setVerifyMsg("Checking fixtures…");
    try {
      const res = await fetch("/api/admin/test_emass", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({}), // optional: { data_root: "…" }
      });
      const json = await res.json().catch(() => ({}));
      const ok = Boolean(json?.ok) && res.ok;
      if (ok) {
        setVerifyState("ok");
        setVerifyMsg("eMASS fixtures reachable and readable");
      } else {
        setVerifyState("fail");
        setVerifyMsg("Unable to read required eMASS fixtures");
      }
    } catch (e: any) {
      setVerifyState("fail");
      setVerifyMsg(`Network error: ${e?.message ?? e}`);
    }
  }

  // Medal icon (SVG) — color varies by verify state
  function MedalIcon({ state }: { state: VerifyState }) {
    const fill =
      state === "ok"
        ? "url(#medalGradOk)"
        : state === "checking"
        ? "url(#medalGradChecking)"
        : state === "fail"
        ? "url(#medalGradFail)"
        : "url(#medalGradIdle)";

    const ring =
      state === "ok" ? "#3fea8c" : state === "fail" ? "#ff6b6b" : state === "checking" ? "#e5c34b" : "#818181";

    return (
      <svg
        width="56"
        height="56"
        viewBox="0 0 64 64"
        role="img"
        aria-label={
          state === "ok"
            ? "eMASS verified"
            : state === "checking"
            ? "Verifying eMASS"
            : state === "fail"
            ? "eMASS verification failed"
            : "eMASS not verified"
        }
      >
        <defs>
          <linearGradient id="medalGradOk" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#1adf73" />
            <stop offset="100%" stopColor="#0fbf5b" />
          </linearGradient>
          <linearGradient id="medalGradChecking" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#ffd86a" />
            <stop offset="100%" stopColor="#e5c34b" />
          </linearGradient>
          <linearGradient id="medalGradFail" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#ff8a8a" />
            <stop offset="100%" stopColor="#ff6b6b" />
          </linearGradient>
          <linearGradient id="medalGradIdle" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#f3d00bff" />
            <stop offset="100%" stopColor="#f3c808ff" />
          </linearGradient>
        </defs>
        {/* Ribbon */}
        <path d="M18 2 L28 2 L32 18 L22 18 Z" fill="#6a89ff" opacity="0.85" />
        <path d="M46 2 L36 2 L32 18 L42 18 Z" fill="#9bb3ff" opacity="0.85" />
        {/* Medal */}
        <circle cx="32" cy="38" r="14" fill={fill} stroke={ring} strokeWidth="2.5" />
        {/* Check/Spinner/Cross/Idle */}
        {state === "ok" && (
          <path
            d="M26 38 l5 5 l9 -10"
            fill="none"
            stroke="#0c3b24"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}
        {state === "checking" && (
          <g>
            <circle cx="32" cy="38" r="8" fill="none" stroke="#2f2f2f" strokeOpacity="0.25" strokeWidth="3" />
            <path
              d="M40 38 a8 8 0 0 1 -8 8"
              fill="none"
              stroke="#2f2f2f"
              strokeWidth="3"
              strokeLinecap="round"
            />
          </g>
        )}
        {state === "fail" && (
          <path d="M27 33 l10 10 M37 33 l-10 10" stroke="#3b0c0c" strokeWidth="3" strokeLinecap="round" />
        )}
      </svg>
    );
  }

  return (
    <div className="panel-wrap">
      <h2 className="section-title">eMASS Connection Management</h2>
      <div className="gold-rule" aria-hidden="true" />

      <div className="card subtle" style={{ marginBottom: 16 }}>
        <p className="admin-copy" style={{ margin: 0 }}>
          Provide <strong>both</strong> your <strong>API Key</strong> and the <strong>PFX password</strong>.
          You may optionally upload/replace the PFX bundle. The server validates the PFX before saving
          and can create a timestamped backup of your INI.
        </p>
      </div>

      {/* Status banners */}
      {errorText && (
        <div className="error-banner" role="alert" style={{ marginTop: 10 }}>
          {errorText}
        </div>
      )}
      {serverJson && serverJson.ok && (
        <div className="card" role="status" style={{ marginTop: 10 }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div className="meta">
              <strong style={{ color: "#7df59d" }}>Success</strong>
              <span className="hint">{serverJson.message || "Operation completed."}</span>
            </div>
            <span className="badge badge-ok">OK</span>
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} noValidate>
        {/* Spacious two-column layout */}
        <div className="grid two-col" style={{ gap: 20 }}>
          {/* LEFT: API + Verify */}
          <div className="card">
            <div className="admin-subhead">API Key (required)</div>
            <div className="form-grid">
              <label>
                <span>API Key</span>
                <input
                  className="admin-input"
                  type="password"
                  placeholder="REPLACE_WITH_REAL_API_KEY"
                  autoComplete="off"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  aria-required="true"
                />
                <span className="hint">Required.</span>
              </label>
            </div>

            {/* Verify eMASS connection */}
            <div
              className="divider"
              aria-hidden="true"
              style={{ height: 1, background: "linear-gradient(90deg, #222, #555, #222)", margin: "12px 0" }}
            />
            <div className="admin-subhead" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span>Verify eMASS connection</span>
            </div>

            <div
              className="row"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                marginTop: 8,
                flexWrap: "wrap",
              }}
            >
              <div className="row" style={{ display: "flex", alignItems: "center", gap: 12 }}>
                {/* Only show the medal AFTER a test has been run */}
                {verifyState !== "idle" && <MedalIcon state={verifyState} />}
                <div>
                  <div className="meta" style={{ fontWeight: 600 }}>
                    {verifyState === "ok"
                      ? "Verified"
                      : verifyState === "checking"
                      ? "Verifying…"
                      : verifyState === "fail"
                      ? "Verification failed"
                      : "No check run yet"}
                  </div>
                  <div className="hint" aria-live="polite">
                    {verifyState === "idle" ? "Click Run Check to verify fixtures." : verifyMsg}
                  </div>
                </div>
              </div>

              <button
                type="button"
                className={`secondary-button${verifyState === "checking" ? " is-loading" : ""}`}
                onClick={handleVerify}
                disabled={verifyState === "checking"}
                aria-busy={verifyState === "checking"}
                title="Checks that required eMASS fixture JSON files are readable"
              >
                {verifyState === "checking" ? "Checking…" : "Run Check"}
              </button>
            </div>
          </div>

          {/* RIGHT: PFX */}
          <div className="card">
            <div className="admin-subhead">PKCS#12 (PFX) — password required</div>
            <div className="form-grid">
              <label>
                <span>PFX Bundle (optional replace)</span>
                <input
                  className="admin-input"
                  type="file"
                  accept=".pfx,application/x-pkcs12,application/pkcs12"
                  onChange={(e) => setPfxFile(e.target.files?.[0] ?? null)}
                />
                <span className="hint">Attach only if you want to replace the stored bundle.</span>
              </label>

              <label>
                <span>PFX Password</span>
                <input
                  className="admin-input"
                  type="password"
                  placeholder="Enter PFX password"
                  autoComplete="off"
                  value={pfxPass}
                  onChange={(e) => setPfxPass(e.target.value)}
                  aria-required={true}
                />
                <span className="hint">Required even if you are not replacing the PFX file.</span>
              </label>
            </div>
          </div>
        </div>

        {/* Options */}
        <div className="card subtle" style={{ marginTop: 6 }}>
          <div className="admin-subhead" style={{ margin: 0 }}>Options</div>
          <div style={{ marginTop: 10 }}>
            <label className="checkbox-label" htmlFor="emass-make-backup">
              <input
                id="emass-make-backup"
                type="checkbox"
                checked={makeBackup}
                onChange={(e) => setMakeBackup(e.target.checked)}
              />
              Create a timestamped .bak before writing
            </label>
          </div>
        </div>

        {/* Actions */}
        <div className="row end" style={{ gap: 10, marginTop: 12 }}>
          <button
            type="button"
            className="secondary-button"
            onClick={resetForm}
            disabled={submitting}
            title="Clear all fields"
          >
            Reset
          </button>
          <button
            type="submit"
            className="generate-button"
            disabled={!canSubmit}
            aria-busy={submitting}
            title="Apply changes to eMASS credentials"
          >
            {submitting ? "Applying…" : "Apply Changes"}
          </button>
        </div>
      </form>

      {/* Server Details */}
      {serverJson && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="admin-subhead">Server Response</div>

          {/* Quick summary chips */}
          <div className="chips-row" style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
            {serverJson.ok ? (
              <span className="chip">Saved</span>
            ) : (
              <span className="chip muted">Not Saved</span>
            )}
            {serverJson.updated?.api_key && <span className="chip">API key updated</span>}
            {serverJson.updated?.pfx_path && <span className="chip">PFX path updated</span>}
            {serverJson.updated?.pfx_pass && <span className="chip">PFX password set</span>}
          </div>

          {/* Per-field updates */}
          {serverJson.updated && (
            <>
              <div className="admin-subhead" style={{ marginTop: 12 }}>Fields Updated</div>
              <div className="table-wrap">
                <table className="policy-table">
                  <thead>
                    <tr>
                      <th>Field</th>
                      <th>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(serverJson.updated).map(([k, v]: [string, any]) => (
                      <tr key={k}>
                        <td>{k}</td>
                        <td>{String(v)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {/* PFX metadata */}
          {serverJson.pfx_meta && (
            <>
              <div className="admin-subhead" style={{ marginTop: 12 }}>PFX Metadata</div>
              <div className="table-wrap">
                <table className="policy-table">
                  <tbody>
                    <tr>
                      <td>Subject</td>
                      <td>{serverJson.pfx_meta.subject || "—"}</td>
                    </tr>
                    <tr>
                      <td>Issuer</td>
                      <td>{serverJson.pfx_meta.issuer || "—"}</td>
                    </tr>
                    <tr>
                      <td>Chain Length</td>
                      <td>{serverJson.pfx_meta.chain_length ?? "—"}</td>
                    </tr>
                    <tr>
                      <td>Has Private Key</td>
                      <td>{String(serverJson.pfx_meta.has_private_key)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </>
          )}

          {/* Paths */}
          {serverJson.paths && (
            <>
              <div className="admin-subhead" style={{ marginTop: 12 }}>Paths</div>
              <div className="table-wrap">
                <table className="policy-table">
                  <tbody>
                    <tr>
                      <td>INI</td>
                      <td><code>{serverJson.paths.ini}</code></td>
                    </tr>
                    <tr>
                      <td>Saved PFX</td>
                      <td><code>{serverJson.paths.pfx_saved_to || "—"}</code></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </>
          )}

          {/* Raw JSON (collapsible) */}
          <details style={{ marginTop: 8 }}>
            <summary>Raw response</summary>
            <pre className="log-pre" style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(serverJson, null, 2)}
            </pre>
          </details>
        </div>
      )}
    </div>
  );
}



