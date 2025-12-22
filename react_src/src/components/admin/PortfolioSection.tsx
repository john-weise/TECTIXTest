// src/components/admin/PortfolioSection.tsx
import React from "react";
import type { SystemSummary } from "../../types/admin";

/** ---- Small formatters -------------------------------------------------- */

/** Format ISO string (or null) to a local human-readable timestamp. */
const fmtLocal = (iso?: string | null) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString();
};

/** Normalize a scan policy label (fallbacks for null/blank). */
const fmtPolicy = (policy?: string | null) => {
  const label = (policy ?? "").trim();
  return label.length > 0 ? label : "—";
};

/** ---- Inline icons (keep dependencies low) ------------------------------ */

/** Small inline SVG: plus icon (used for "Add System"). */
const PlusIcon = ({ size = 18 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>
);

/** Small inline SVG: checkmark (used to indicate true/has CSV). */
const CheckIcon = ({ size = 16 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path
      d="M5 13l4 4L19 7"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

/** Small inline SVG: "X" (used to indicate false/no CSV and delete). */
const XIcon = ({ size = 16 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>
);

/** ---- Props ------------------------------------------------------------- */

type PortfolioSectionProps = {
  systems: SystemSummary[];
  systemsLoading: boolean;
  systemsError: string;

  purgeOnDelete: boolean;
  purgeOnUnset: boolean;
  setPurgeOnDelete: (value: boolean) => void;
  setPurgeOnUnset: (value: boolean) => void;

  showAdd: boolean;
  setShowAdd: (value: boolean) => void;
  newSystemId: string;
  setNewSystemId: (value: string) => void;
  csvFile: File | null;
  setCsvFile: (file: File | null) => void;
  submitting: boolean;
  submitError: string;

  onAddSystem: (e: React.FormEvent) => void;
  onDeleteSystem: (systemId: number) => void;
  onUnsetCsv: (systemId: number) => void;

  fetchSystems: () => void | Promise<void>;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
};

/** ---- Component --------------------------------------------------------- */

const PortfolioSection: React.FC<PortfolioSectionProps> = ({
  systems,
  systemsLoading,
  systemsError,
  purgeOnDelete,
  purgeOnUnset,
  setPurgeOnDelete,
  setPurgeOnUnset,
  showAdd,
  setShowAdd,
  newSystemId,
  setNewSystemId,
  csvFile, // kept for completeness
  setCsvFile,
  submitting,
  submitError,
  onAddSystem,
  onDeleteSystem,
  onUnsetCsv,
  fetchSystems,
  fileInputRef,
}) => {
  return (
    <>
      {systemsError && <div className="error-banner">{systemsError}</div>}

      <div className="card">
        {/* Header row with Add + options */}
        <div
          className="row"
          style={{ justifyContent: "space-between", alignItems: "center" }}
        >
          <h3 className="admin-subhead" style={{ margin: 0 }}>
            Systems
          </h3>
          <div
            className="actions"
            style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}
          >
            {/* Safety toggles for destructive ops */}
            <label
              className="checkbox-label"
              title="Also delete CSV file from disk when deleting a system"
            >
              <input
                type="checkbox"
                checked={purgeOnDelete}
                onChange={(e) => setPurgeOnDelete(e.target.checked)}
              />
              <span>Purge file on delete</span>
            </label>
            <label
              className="checkbox-label"
              title="Delete CSV file from disk when unsetting CSV path"
            >
              <input
                type="checkbox"
                checked={purgeOnUnset}
                onChange={(e) => setPurgeOnUnset(e.target.checked)}
              />
              <span>Purge file on unset</span>
            </label>

            <button
              className="secondary-button"
              onClick={() => fetchSystems()}
              disabled={systemsLoading}
              title="Refresh list"
            >
              {systemsLoading ? "Loading…" : "Refresh"}
            </button>
            <button
              className="generate-button"
              onClick={() => setShowAdd(!showAdd)}
              title="Add system"
              aria-expanded={showAdd}
              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
            >
              <PlusIcon /> <span>Add System</span>
            </button>
          </div>
        </div>

        {/* Collapsible Add form */}
        {showAdd && (
          <form
            className="card"
            onSubmit={onAddSystem}
            style={{
              marginTop: 12,
              background: "rgba(255,255,255,0.02)",
              border: "1px dashed var(--border-color, #2a2a2a)",
            }}
            aria-label="Add System"
          >
            <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
              <label className="inline" style={{ minWidth: 220 }}>
                System ID
                <input
                  type="number"
                  min={0}
                  step={1}
                  placeholder="e.g. 1001"
                  className="admin-input"
                  value={newSystemId}
                  onChange={(e) => setNewSystemId(e.target.value)}
                />
              </label>

              <label className="inline" style={{ minWidth: 320 }}>
                Optional CSV Upload
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,text/csv"
                  className="admin-input"
                  onChange={(e) => setCsvFile(e.target.files?.[0] || null)}
                />
              </label>

              <div style={{ display: "flex", alignItems: "flex-end", gap: 8 }}>
                <button className="generate-button" type="submit" disabled={submitting}>
                  {submitting ? "Saving…" : "Save"}
                </button>
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => {
                    setShowAdd(false);
                    setNewSystemId("");
                    setCsvFile(null);
                    if (fileInputRef.current) fileInputRef.current.value = "";
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
            <div className="hint" style={{ marginTop: 8 }}>
              You can add a system without a CSV. Upload later when ready.
            </div>
            {submitError && (
              <div className="error-banner" style={{ marginTop: 8 }}>
                {submitError}
              </div>
            )}
          </form>
        )}

        {/* Scrollable table container */}
        <div
          className="table-scroll"
          role="region"
          aria-label="Monitoring Portfolio"
          style={{
            maxHeight: 420,
            overflow: "auto",
            border: "1px solid var(--border-color, #2a2a2a)",
            borderRadius: 8,
            marginTop: 12,
          }}
        >
          <table className="admin-table" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th
                  style={{
                    textAlign: "left",
                    padding: "10px 12px",
                    position: "sticky",
                    top: 0,
                    background: "var(--panel, #0b0c0e)",
                  }}
                >
                  System ID
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "10px 12px",
                    position: "sticky",
                    top: 0,
                    background: "var(--panel, #0b0c0e)",
                  }}
                >
                  Has CSV
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "10px 12px",
                    position: "sticky",
                    top: 0,
                    background: "var(--panel, #0b0c0e)",
                  }}
                >
                  Scan Policy
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "10px 12px",
                    position: "sticky",
                    top: 0,
                    background: "var(--panel, #0b0c0e)",
                  }}
                >
                  Date Added
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "10px 12px",
                    position: "sticky",
                    top: 0,
                    background: "var(--panel, #0b0c0e)",
                  }}
                >
                  Last Scanned
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "10px 12px",
                    position: "sticky",
                    top: 0,
                    background: "var(--panel, #0b0c0e)",
                  }}
                >
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {systems.length === 0 && !systemsLoading && (
                <tr>
                  <td
                    colSpan={6}
                    style={{ padding: 16, textAlign: "center", color: "#aaa" }}
                  >
                    No systems found.
                  </td>
                </tr>
              )}
              {systems.map((s) => {
                const hasCsv = !!s.has_csv;
                const policyLabel = fmtPolicy(s.scan_policy);
                const policyTitle =
                  policyLabel === "—"
                    ? "Not enrolled in a scan policy"
                    : `Scan policy: ${policyLabel}`;

                return (
                  <tr key={s.system_id} className="admin-row">
                    <td style={{ padding: "10px 12px" }}>
                      <code>{s.system_id}</code>
                    </td>

                    <td style={{ padding: "10px 12px" }}>
                      {hasCsv ? (
                        <span className="badge badge-ok" title="CSV present">
                          <CheckIcon /> <span style={{ marginLeft: 6 }}>true</span>
                        </span>
                      ) : (
                        <span className="badge badge-warn" title="No CSV">
                          <XIcon /> <span style={{ marginLeft: 6 }}>false</span>
                        </span>
                      )}
                    </td>

                    {/* Scan Policy */}
                    <td style={{ padding: "10px 12px" }} title={policyTitle}>
                      {policyLabel}
                    </td>

                    <td style={{ padding: "10px 12px" }}>{fmtLocal(s.time_added)}</td>

                    <td style={{ padding: "10px 12px" }}>
                      {!hasCsv ? <span className="hint">No CSV</span> : fmtLocal(s.last_scanned)}
                    </td>

                    <td
                      style={{
                        padding: "10px 12px",
                        display: "flex",
                        gap: 8,
                        alignItems: "center",
                      }}
                    >
                      {/* Unset CSV (visible only when CSV exists) */}
                      {hasCsv && (
                        <button
                          className="secondary-button"
                          title="Unset CSV (optional file purge is controlled above)"
                          onClick={() => onUnsetCsv(s.system_id)}
                        >
                          Unset CSV
                        </button>
                      )}

                      {/* Delete system (always available) */}
                      <button
                        className="danger-button"
                        title="Delete system"
                        onClick={() => onDeleteSystem(s.system_id)}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 6,
                        }}
                      >
                        <XIcon /> Delete
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="hint" style={{ marginTop: 8 }}>
          Times are shown in your browser&apos;s local timezone and locale.
        </div>
      </div>
    </>
  );
};

export default PortfolioSection;
