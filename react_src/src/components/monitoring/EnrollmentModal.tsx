//src/components/monitoring/EnrollmentModal.tsx
import React, { useEffect, useMemo, useState } from "react";

/**
 * EnrollmentModal
 * -----------------------------------------------------------------------------
 * Purpose:
 * - Shown when strict enrollment returns a 409 with a list of `missing` system IDs.
 * - Lets the user toggle which IDs to add to the portfolio *now*.
 * - Optional per-ID CSV upload (CSV ONLY). If a CSV is supplied, we:
 *      1) POST /api/admin/systems { system_id, csv_path: null }
 *      2) POST /api/admin/systems/:id/csv  (multipart/form-data with "file")
 *   If no CSV is supplied, we just do (1).
 *
 * Props:
 * - open               : modal visibility
 * - missing            : number[] of system IDs not yet in the portfolio
 * - onClose            : close callback
 * - onAddedAndRetry    : called with the list of added IDs once creation finishes
 *
 * UX:
 * - Red “chips” to toggle selection.
 * - For each selected ID, an inline CSV file input appears (accepts .csv only).
 * - Footer: Cancel / Add & Retry (disabled when nothing selected).
 *
 * Contract with backend:
 * - Create: POST /api/admin/systems JSON { system_id: number, csv_path: null }
 * - Upload: POST /api/admin/systems/:id/csv  (FormData: file=<csv>)
 *
 * Notes:
 * - All calls include { credentials: "include" }.
 * - Very loud console logging for admin diagnostics.
 */

type EnrollmentModalProps = {
  open: boolean;
  missing: number[];
  onClose: () => void;
  onAddedAndRetry: (addedIds: number[]) => Promise<void>;
};

function ModalShell({
  open,
  onClose,
  title,
  children,
  footer,
  busy,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  busy?: boolean;
}) {
  if (!open) return null;
  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={busy ? undefined : onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.55)",
        display: "grid",
        placeItems: "center",
        zIndex: 9999,
      }}
    >
      <div
        className="card"
        onClick={(e) => e.stopPropagation()}
        style={{ width: "min(760px, 92vw)", maxHeight: "82vh", overflow: "auto", padding: 16 }}
      >
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0 }}>{title}</h3>
          <button onClick={busy ? undefined : onClose} title="Close" aria-label="Close modal">
            ×
          </button>
        </div>
        <div style={{ marginTop: 12 }}>{children}</div>
        {footer && <div className="row end" style={{ marginTop: 16 }}>{footer}</div>}
      </div>
    </div>
  );
}

export default function EnrollmentModal({
  open,
  missing,
  onClose,
  onAddedAndRetry,
}: EnrollmentModalProps) {
  const [selected, setSelected] = useState<number[]>([]);
  const [filesById, setFilesById] = useState<Record<number, File | null>>({});
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string>("");

  useEffect(() => {
    setSelected(missing);
    setFilesById({});
    setBusy(false);
    setStatus("");
  }, [missing, open]);

  const toggle = (id: number) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const chip = (active: boolean): React.CSSProperties => ({
    display: "inline-flex",
    alignItems: "center",
    padding: "6px 10px",
    borderRadius: 9999,
    fontWeight: 700,
    cursor: "pointer",
    userSelect: "none",
    border: active ? "1px solid rgba(255,0,0,0.9)" : "1px solid rgba(255,255,255,0.2)",
    background: active ? "rgba(255,0,0,0.15)" : "rgba(255,255,255,0.05)",
    color: active ? "#ff4d4f" : "inherit",
  });

  const handleFileChange = (id: number, f: File | null) => {
    if (f && !/\.csv$/i.test(f.name)) {
      alert("Please select a .csv file");
      return;
    }
    setFilesById((prev) => ({ ...prev, [id]: f }));
  };

  const selectedSorted = useMemo(
    () => [...selected].sort((a, b) => a - b),
    [selected]
  );

  const addSelected = async () => {
    if (selected.length === 0) return;
    setBusy(true);
    setStatus("Adding systems to portfolio…");

    const addedIds: number[] = [];
    try {
      for (const id of selectedSorted) {
        // 1) Create/Upsert system (no CSV path yet)
        {
          const res = await fetch("/api/admin/systems", {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ system_id: id, csv_path: null }),
          });
          const j = await res.json().catch(() => ({}));
          console.log("[EnrollmentModal][Create] ←", id, res.status, j);
          if (!res.ok) {
            throw new Error(j?.error || `Create system ${id} failed (HTTP ${res.status})`);
          }
        }

        // 2) Optional CSV upload
        const file = filesById[id];
        if (file) {
          const form = new FormData();
          form.append("file", file);
          const res = await fetch(`/api/admin/systems/${encodeURIComponent(id)}/csv`, {
            method: "POST",
            credentials: "include",
            body: form,
          });
          const j = await res.json().catch(() => ({}));
          console.log("[EnrollmentModal][Upload] ←", id, res.status, j);
          if (!res.ok) {
            throw new Error(j?.error || `Upload CSV for ${id} failed (HTTP ${res.status})`);
          }
        }

        addedIds.push(id);
      }

      setStatus("Added. Re-enrolling…");
      await onAddedAndRetry(addedIds);
      setStatus("Done.");
      onClose();
    } catch (e: any) {
      console.error("[EnrollmentModal] addSelected error", e);
      setStatus(`Error: ${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell
      open={open}
      onClose={busy ? () => {} : onClose}
      title="Add missing systems to portfolio"
      busy={busy}
      footer={
        <>
          <button onClick={onClose} disabled={busy}>Cancel</button>
          <button
            onClick={addSelected}
            className="generate-button"
            disabled={busy || selected.length === 0}
            title={selected.length === 0 ? "Select at least one system" : "Add & retry enrollment"}
          >
            {busy ? "Working…" : `Add ${selected.length} & Retry`}
          </button>
        </>
      }
    >
      {missing.length === 0 ? (
        <div className="hint">No missing systems detected.</div>
      ) : (
        <>
          <p style={{ marginTop: 0 }}>
            The following system IDs aren’t in the portfolio yet. Toggle the red bubbles to select which ones to add now. You can
            optionally attach a CSV per system (CSV only). We’ll add them and retry the enrollment automatically.
          </p>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
            {missing.map((id) => {
              const active = selected.includes(id);
              return (
                <span
                  key={id}
                  onClick={() => toggle(id)}
                  style={chip(active)}
                  title={active ? "Selected" : "Click to select"}
                >
                  {id}
                </span>
              );
            })}
          </div>

          {/* Per-selected system CSV uploaders */}
          {selectedSorted.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <h4 style={{ margin: "0 0 8px 0" }}>Optional CSV uploads</h4>
              <div style={{ display: "grid", gap: 10 }}>
                {selectedSorted.map((id) => (
                  <div
                    key={id}
                    className="row"
                    style={{
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 12,
                      border: "1px dashed var(--border-color, #2a2a2a)",
                      borderRadius: 8,
                      padding: "8px 10px",
                      background: "rgba(255,255,255,0.02)",
                    }}
                  >
                    <div style={{ fontWeight: 600 }}>
                      System <code>{id}</code>
                    </div>
                    <label
                      className="inline"
                      style={{ display: "inline-flex", alignItems: "center", gap: 8 }}
                      title="Attach a CSV (optional)"
                    >
                      <input
                        type="file"
                        accept=".csv,text/csv"
                        onChange={(e) => handleFileChange(id, e.target.files?.[0] || null)}
                        disabled={busy}
                      />
                      {filesById[id] ? (
                        <span className="hint">{filesById[id]?.name}</span>
                      ) : (
                        <span className="hint">No file chosen</span>
                      )}
                    </label>
                  </div>
                ))}
              </div>
            </div>
          )}

          {status && <div className="hint" style={{ marginTop: 12 }}>{status}</div>}
        </>
      )}
    </ModalShell>
  );
}
