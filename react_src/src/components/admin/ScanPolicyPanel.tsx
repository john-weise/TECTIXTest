// src/components/admin/ScanPolicyPanel.tsx
import React, { useEffect, useMemo, useState } from "react";
import EnrollmentModal from "../monitoring/EnrollmentModal";
import type { SystemSummary } from "../../types/admin"; // NEW

/* ---------- Types (mirror backend) ---------- */
type Frequency = "daily" | "weekly" | "biweekly" | "monthly";
type DayOfWeek =
  | "Monday" | "Tuesday" | "Wednesday" | "Thursday" | "Friday" | "Saturday" | "Sunday";

type ScanPolicyOut = {
  id: number;
  name: string;
  frequency: Frequency;
  time_of_day: string;
  day_of_week?: DayOfWeek | null;
  week_of_month?: number | null;
  last_run_epoch?: number | null;
  systems: number[];
  created_at?: string | null;
  updated_at?: string | null;
};

type PolicyCreatePayload = {
  name: string;
  frequency: Frequency;
  time_of_day: string;
  day_of_week?: DayOfWeek | null;
  week_of_month?: number | null;
};

type PolicyUpdatePayload = Partial<PolicyCreatePayload>;

/* ---------- Helpers ---------- */
const weekdays: DayOfWeek[] = [
  "Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday",
];
const weekOrdinals = [1,2,3,4,5];

function fmtTime(hhmmss?: string | null) {
  return hhmmss ? hhmmss.slice(0, 5) : "";
}
function fmtEpoch(epoch?: number | null) {
  if (epoch == null) return "—";
  const d = new Date(epoch * 1000);
  return d.toISOString().replace(".000", "").replace("T", " ").replace("Z", "Z");
}

/** Loud, forgiving fetch that insists on JSON back */
async function jsonFetch<T = any>(url: string, opts: RequestInit = {}): Promise<T> {
  const finalOpts: RequestInit = {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...opts,
  };
  console.log("[jsonFetch] →", url, finalOpts);
  const res = await fetch(url, finalOpts);
  const ct = res.headers.get("content-type") || "";

  if (ct.includes("application/json")) {
    const body = await res.json().catch(() => ({}));
    console.log("[jsonFetch] ←", res.status, body);
    if (!res.ok) throw new Error(body?.error || body?.message || `HTTP ${res.status}`);
    return body as T;
  } else {
    const text = await res.text();
    console.log("[jsonFetch] ←(text)", res.status, ct, text.slice(0, 500));
    if (!res.ok) throw new Error(text || `HTTP ${res.status}`);
    throw new Error(`Expected JSON but got ${ct || "unknown"} (HTTP ${res.status})`);
  }
}

/* ---------- Chip Input (orange pills) ---------- */
function SystemChipsInput({
  value, onChange, disabled,
  placeholder = "Type IDs like 114, 221, …",
}: {
  value: number[];
  onChange: (next: number[]) => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  const [buf, setBuf] = useState("");

  const pillStyle: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "2px 10px",
    borderRadius: 9999,
    background: "#ff7a00",   // orange pill
    color: "white",
    fontWeight: 600,
  };

  const addFromBuffer = () => {
    const raw = buf.trim();
    if (!raw) return;
    const parts = raw.split(/[,\s]+/).filter(Boolean);
    const ints = parts
      .filter((p) => /^\d+$/.test(p))
      .map((p) => parseInt(p, 10))
      .filter((n) => Number.isFinite(n));
    if (ints.length === 0) return;
    const set = new Set(value);
    ints.forEach((n) => set.add(n));
    onChange(Array.from(set));
    setBuf("");
  };

  const remove = (n: number) => onChange(value.filter((x) => x !== n));

  return (
    <div>
      <label style={{ display: "block", marginBottom: 6, fontWeight: 600 }}>
        Systems to enroll (type IDs, press comma or Enter)
      </label>
      <div style={{
        display: "flex",
        gap: 8,
        flexWrap: "wrap",
        padding: 8,
        borderRadius: 8,
        border: "1px solid rgba(255,255,255,0.15)",
        background: "rgba(255,255,255,0.03)",
      }}>
        {value.map((id) => (
          <span key={id} style={pillStyle}>
            {id}
            <button
              type="button"
              onClick={() => remove(id)}
              aria-label={`Remove ${id}`}
              style={{
                border: 0,
                background: "transparent",
                color: "white",
                cursor: "pointer",
                fontSize: 14,
                lineHeight: 1,
              }}
              disabled={disabled}
            >
              ×
            </button>
          </span>
        ))}
        <input
          value={buf}
          onChange={(e) => setBuf(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              addFromBuffer();
            } else if (e.key === "Backspace" && buf === "" && value.length > 0) {
              onChange(value.slice(0, -1));
            }
          }}
          style={{
            minWidth: 200,
            flex: 1,
            border: "none",
            outline: "none",
            background: "transparent",
            color: "inherit",
            padding: "6px 4px",
          }}
        />
      </div>
    </div>
  );
}

/* ---------- Main Component ---------- */
export default function ScanPolicyPanel() {
  const [policies, setPolicies] = useState<ScanPolicyOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [editingId, setEditingId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [frequency, setFrequency] = useState<Frequency>("daily");
  const [time, setTime] = useState("02:00");
  const [dayOfWeek, setDayOfWeek] = useState<DayOfWeek | "">("");
  const [weekOfMonth, setWeekOfMonth] = useState<number | "">("");
  const [chips, setChips] = useState<number[]>([]); // systems to enroll/remove

  // Missing systems modal
  const [missingOpen, setMissingOpen] = useState(false);
  const [missingIds, setMissingIds] = useState<number[]>([]);

  // Per-row running state for the ▶️ button
  const [runningIds, setRunningIds] = useState<Set<number>>(new Set());

  const requiresDOW = frequency === "weekly" || frequency === "biweekly" || frequency === "monthly";
  const requiresWOM = frequency === "monthly";

  const valid = useMemo(() => {
    if (!name.trim()) return false;
    if (!time) return false;
    if (requiresDOW && !dayOfWeek) return false;
    if (requiresWOM && !weekOfMonth) return false;
    return true;
  }, [name, time, requiresDOW, dayOfWeek, requiresWOM, weekOfMonth]);

  async function load() {
    try {
      setLoading(true); setError(null);
      const data = await jsonFetch<ScanPolicyOut[]>("/api/policies");
      setPolicies(Array.isArray(data) ? data : []);
    } catch (e: any) {
      setError(e.message || "Failed to load policies");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, []);

  function resetForm() {
    setEditingId(null);
    setName("");
    setFrequency("daily");
    setTime("02:00");
    setDayOfWeek("");
    setWeekOfMonth("");
    setChips([]);
    setMsg(null);
  }

  function startEdit(p: ScanPolicyOut) {
    setEditingId(p.id);
    setName(p.name);
    setFrequency(p.frequency);
    setTime(fmtTime(p.time_of_day));
    setDayOfWeek((p.day_of_week as DayOfWeek) || "");
    setWeekOfMonth(p.week_of_month ?? "");
    setChips([]); // choose what to enroll/remove now
    setMsg(null);
  }

  async function enrollStrict(policyId: number, ids: number[]) {
    console.log("[Enroll] strict attempt", { policyId, ids });
    try {
      const r = await fetch(`/api/policies/${policyId}/systems?strict=1`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ system_ids: ids }),
      });
      const ct = r.headers.get("content-type") || "";
      const body = ct.includes("application/json") ? await r.json() : {};
      console.log("[Enroll] strict ←", r.status, body);

      if (r.status === 409 && body?.missing) {
        setMissingIds(body.missing as number[]);
        setMissingOpen(true);
        return { ok: false, missing: body.missing as number[] };
      }
      if (!r.ok) throw new Error(body?.error || body?.message || `HTTP ${r.status}`);

      setMsg(`Enrolled ${body?.updated ?? ids.length} system(s).`);
      return { ok: true, missing: [] as number[] };
    } catch (e: any) {
      console.error("[Enroll] strict error", e);
      setMsg(`Enroll failed: ${e?.message || e}`);
      return { ok: false, missing: [] as number[] };
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!valid) return;

    const payload: PolicyCreatePayload | PolicyUpdatePayload = {
      name: name.trim(),
      frequency,
      time_of_day: time.length === 5 ? `${time}:00` : time,
      day_of_week: requiresDOW ? (dayOfWeek as DayOfWeek) : null,
      week_of_month: requiresWOM ? (weekOfMonth as number) : null,
    };

    try {
      console.log("[PolicyForm] submit", { editingId, payload, chips });
      if (editingId == null) {
        // create
        const created = await jsonFetch<{ id: number; message: string }>("/api/policies", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        let createdMsg = "Created.";
        if (chips.length > 0) {
          const res = await enrollStrict(created.id, chips);
          if (res.ok) {
            createdMsg += ` Enrolled ${chips.length} system(s).`;
            setChips([]);
          } else if (res.missing?.length) {
            createdMsg += ` Some systems are missing.`;
          }
        }
        setMsg(createdMsg);
        if (!missingOpen) resetForm(); // keep form if modal opens
      } else {
        // update
        await jsonFetch(`/api/policies/${editingId}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        setMsg("Saved.");
        if (chips.length > 0) {
          const res = await enrollStrict(editingId, chips);
          if (res.ok) setChips([]);
        }
      }
      await load();
    } catch (e: any) {
      console.error("[PolicyForm] error", e);
      setMsg(`Error: ${e.message || e}`);
    }
  }

  async function onDelete(p: ScanPolicyOut) {
    if (!window.confirm(`Delete policy "${p.name}"? This will clear its system assignments.`)) return;
    try {
      await jsonFetch(`/api/policies/${p.id}`, { method: "DELETE" });
      setMsg("Deleted.");
      if (editingId === p.id) resetForm();
      await load();
    } catch (e: any) {
      setMsg(`Delete failed: ${e.message || e}`);
    }
  }

  async function removeSelectedFromPolicy() {
    if (editingId == null || chips.length === 0) return;
    try {
      await jsonFetch(`/api/policies/${editingId}/systems`, {
        method: "DELETE",
        body: JSON.stringify({ system_ids: chips }),
      });
      setMsg(`Removed ${chips.length} system(s) from policy.`);
      setChips([]);
      await load();
    } catch (e: any) {
      setMsg(`Remove failed: ${e.message || e}`);
    }
  }

  // NEW: auto-populate chips with all systems that are not enrolled in any scan policy
  async function addAllUnassignedSystemsToChips() {
    try {
      setMsg(null);
      console.log("[ScanPolicyPanel] Fetching unassigned systems from /api/admin/systems");
      const systems = await jsonFetch<SystemSummary[]>("/api/admin/systems");
      const unassigned = systems.filter((s) => !s.scan_policy || !s.scan_policy.trim());
      const ids = unassigned.map((s) => s.system_id);

      if (ids.length === 0) {
        setMsg("All systems are already enrolled in a scan policy.");
        return;
      }

      setChips((prev) => {
        const next = new Set(prev);
        ids.forEach((id) => next.add(id));
        return Array.from(next);
      });

      setMsg(`Added ${ids.length} unassigned system(s) to the enrollment list.`);
    } catch (e: any) {
      console.error("[ScanPolicyPanel] addAllUnassignedSystemsToChips error", e);
      setMsg(`Failed to load unassigned systems: ${e.message || e}`);
    }
  }

  // Run-now button handler (calls POST /api/policies/:id/run)
  async function runPolicyNow(policyId: number, opts?: { blocking?: boolean }) {
    if (runningIds.has(policyId)) return;
    const next = new Set(runningIds); next.add(policyId); setRunningIds(next);
    setMsg(null);

    try {
      const body =
        opts?.blocking === undefined ? undefined : JSON.stringify({ blocking: !!opts.blocking });
      const res = await jsonFetch<{ dispatched: boolean; message?: string }>(
        `/api/policies/${policyId}/run`,
        { method: "POST", body }
      );
      setMsg(res?.message || (res?.dispatched ? "Scan dispatched." : "Nothing to run."));
    } catch (e: any) {
      setMsg(`Run failed: ${e.message || e}`);
    } finally {
      const done = new Set(runningIds); done.delete(policyId); setRunningIds(done);
      // Refresh so "Last Run" updates when backend stamps immediately
      await load();
    }
  }

  // Callback from modal after adding missing systems:
  const handleAddedAndRetry = async (addedIds: number[]) => {
    if (editingId == null) return;
    console.log("[MissingModal] retry enroll after add", { editingId, addedIds });
    await enrollStrict(editingId, addedIds);
    await load();
  };

  return (
    <>
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>{editingId == null ? "Create Scan Policy" : `Edit Policy #${editingId}`}</h3>

        <form onSubmit={onSubmit} className="form-grid">
          <label>
            Policy name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Compliance Blue"
              required
            />
          </label>

          <label>
            Frequency
            <select value={frequency} onChange={(e) => setFrequency(e.target.value as Frequency)}>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="biweekly">Biweekly (14-day cadence)</option>
              <option value="monthly">Monthly (Nth weekday)</option>
            </select>
          </label>

          <label>
            Time (UTC)
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)} required />
          </label>

          {(frequency === "weekly" || frequency === "biweekly" || frequency === "monthly") && (
            <label>
              Day of week
              <select
                value={dayOfWeek}
                onChange={(e) => setDayOfWeek(e.target.value as DayOfWeek)}
                required={requiresDOW}
              >
                <option value="">Select…</option>
                {weekdays.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </label>
          )}

          {frequency === "monthly" && (
            <label>
              Week of month
              <select
                value={weekOfMonth}
                onChange={(e) => setWeekOfMonth(e.target.value ? Number(e.target.value) : "")}
                required={requiresWOM}
              >
                <option value="">Select…</option>
                {weekOrdinals.map((n) => (
                  <option key={n} value={n}>
                    {n === 1 ? "1st" : n === 2 ? "2nd" : n === 3 ? "3rd" : `${n}th`}
                  </option>
                ))}
              </select>
            </label>
          )}

          {/* Systems chip input */}
          <div style={{ gridColumn: "1 / -1" }}>
            <SystemChipsInput value={chips} onChange={setChips} />
            <div className="row" style={{ gap: 8, marginTop: 8 }}>
              {/* NEW button to auto-populate with all systems not in any scan policy */}
              <button
                type="button"
                onClick={addAllUnassignedSystemsToChips}
              >
                Add all unassigned systems
              </button>

              {editingId != null && (
                <>
                  <button
                    type="button"
                    onClick={async () => {
                      if (chips.length === 0 || editingId == null) return;
                      const res = await enrollStrict(editingId, chips);
                      if (res.ok) setChips([]);
                      await load();
                    }}
                    disabled={chips.length === 0}
                  >
                    Enroll
                  </button>
                  <button
                    type="button"
                    className="danger"
                    onClick={removeSelectedFromPolicy}
                    disabled={chips.length === 0}
                  >
                    Remove
                  </button>
                </>
              )}
            </div>
          </div>

          <div className="row" style={{ gap: 8, marginTop: 10 }}>
            <button type="submit" disabled={!valid}>
              {editingId == null ? "Create Policy" : "Save Changes"}
            </button>
            {editingId != null && <button type="button" onClick={resetForm}>Cancel</button>}
          </div>

          {msg && <div className="hint" role="status" style={{ marginTop: 8 }}>{msg}</div>}
        </form>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Existing Policies</h3>

        {loading ? (
          <div className="hint">Loading…</div>
        ) : error ? (
          <div className="card error">Error: {error}</div>
        ) : policies.length === 0 ? (
          /* --------- HERO CARD when empty --------- */
          <div
            style={{
              padding: 24,
              border: "1px dashed rgba(255,255,255,0.25)",
              borderRadius: 12,
              background: "rgba(255,255,255,0.03)",
            }}
          >
            <h4 style={{ marginTop: 0, marginBottom: 6 }}>No policies exist yet</h4>
            <p style={{ margin: 0, opacity: 0.85 }}>
              Use the form above to create your first scan policy — and optionally enroll systems immediately.
            </p>
          </div>
        ) : (
          <div className="table-wrap" style={{ maxHeight: 420, overflow: "auto" }}>
            <table className="policy-table" style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Name</th>
                  <th style={{ textAlign: "left" }}>Frequency</th>
                  <th style={{ textAlign: "left" }}>Time (UTC)</th>
                  <th style={{ textAlign: "left" }}>Last Run</th>
                  <th style={{ textAlign: "left" }}>Systems</th>
                  <th style={{ width: 140 }} />
                </tr>
              </thead>
              <tbody>
                {policies.map((p) => {
                  const noSystems = (p.systems?.length ?? 0) === 0;
                  const isRunning = runningIds.has(p.id);
                  return (
                    <tr key={p.id}>
                      <td>{p.name}</td>
                      <td>
                        {p.frequency}
                        {p.frequency !== "daily" && p.day_of_week ? ` • ${p.day_of_week}` : ""}
                        {p.frequency === "monthly" && p.week_of_month ? ` • ${p.week_of_month}ᵗʰ` : ""}
                      </td>
                      <td>{fmtTime(p.time_of_day)}</td>
                      <td>{fmtEpoch(p.last_run_epoch)}</td>
                      <td>
                        {p.systems?.length ?? 0}
                        {p.systems?.length ? (
                          <details style={{ marginTop: 4 }}>
                            <summary>show</summary>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                              {p.systems.map((id) => (
                                <span key={id} style={{
                                  padding: "2px 8px",
                                  borderRadius: 9999,
                                  background: "rgba(255,255,255,0.08)",
                                  color: "inherit",
                                  fontWeight: 600,
                                }}>{id}</span>
                              ))}
                            </div>
                          </details>
                        ) : null}
                      </td>
                      <td>
                        <div className="row end" style={{ gap: 8 }}>
                          {/* Run-now button */}
                          <button
                            title={noSystems ? "No systems enrolled" : "Run now"}
                            aria-label={`Run policy ${p.name} now`}
                            onClick={() => runPolicyNow(p.id /* , { blocking: false } */)}
                            disabled={noSystems || isRunning}
                          >
                            {isRunning ? "⏳" : "▶️"}
                          </button>

                          {/* Existing edit/delete */}
                          <button title="Edit" onClick={() => startEdit(p)}>✏️</button>
                          <button title="Delete" className="danger" onClick={() => onDelete(p)}>❌</button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Missing systems flow (CSV-only uploader lives inside) */}
      <EnrollmentModal
        open={missingOpen}
        missing={missingIds}
        onClose={() => setMissingOpen(false)}
        onAddedAndRetry={handleAddedAndRetry}
      />
    </>
  );
}

export {};
