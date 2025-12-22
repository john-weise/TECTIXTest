/* eslint-disable no-console */
import React, { useEffect, useMemo, useState } from "react";
import ReadinessGauge from "../ReadinessGauge";
import TestTable, {
  TestRow,
  Filter,
  SortKey,
  SortDir,
  SectionFilter,
} from "../TestTable";
import ComplianceTimeChart from "./ComplianceTimeChart";
import type { CompliancePoint } from "../../types/monitoring";

import "../../styles/Reporting.css"; // reuse existing styles

/* ---------- Types from the backend summary endpoint ---------- */
type Readiness = {
  status_column: string | null;
  pass: number;
  fail: number;
  concern: number;
  neutral: number;
  considered: number;
  score_pct: number | null;
  formula: string;
};

type DataFramePayload = {
  system_id: number;
  source: string;
  shape: [number, number];
  columns: string[];
  dtypes: Record<string, string>;
  records: Array<Record<string, any>>;
};

type ApiSummary = {
  job_id: string;
  system_id: number | null;
  system_name?: string | null;
  ran_at_epoch: number;
  ran_at_iso: string;
  dataframe: DataFramePayload;
  dataframe_truncated: boolean;
  readiness: Readiness;
};

type ComplianceSeriesResponse = {
  system_id: number;
  has_data: boolean;
  first_ts_iso: string | null;
  last_ts_iso: string | null;
  points: CompliancePoint[];
};

type Props = {
  systemId: number;
  open: boolean;
  onClose: () => void;
};

const preferredStatusKeys = ["result", "status", "outcome", "test_status"];

/* ------------------------- Helpers -------------------------- */

function useDebugFlag() {
  return useMemo(() => {
    try {
      const p = new URLSearchParams(window.location.search);
      if (p.has("debug")) {
        const v = (p.get("debug") || "").toLowerCase();
        return !(v === "0" || v === "false" || v === "off");
      }
      return true;
    } catch {
      return true;
    }
  }, []);
}

type RowStatus = "pass" | "fail" | "concern" | "neutral";
function normalizeStatus(v: any): RowStatus {
  if (v === null || v === undefined) return "neutral";
  if (typeof v === "boolean") return v ? "pass" : "fail";
  const s = String(v).trim().toLowerCase();
  if (/\bpass(ed)?\b|ok|success|compliant|true|green/.test(s)) return "pass";
  if (/\bfail(ed)?\b|non\s*compliant|not compliant|false|red|error|critical/.test(s))
    return "fail";
  if (/\bconcern|warning|warn|yellow|partial|medium|high\b/.test(s)) return "concern";
  if (/^\s*$|^n\/?a$|^na$|^skip(ped)?$/i.test(s)) return "neutral";
  return "concern";
}

function pickKey(columns: string[], candidates: string[]) {
  const lowerMap = new Map(columns.map((c) => [c.toLowerCase(), c]));
  for (const c of candidates) {
    const hit = lowerMap.get(c.toLowerCase());
    if (hit) return hit;
  }
  return null;
}

function statusFromRow(row: Record<string, any>, explicit?: string | null): RowStatus {
  if (explicit) {
    const key = Object.keys(row).find(
      (rk) => rk.toLowerCase() === explicit.toLowerCase()
    );
    if (key) {
      return normalizeStatus(row[key]);
    }
  }
  for (const k of preferredStatusKeys) {
    const key = Object.keys(row).find((rk) => rk.toLowerCase() === k.toLowerCase());
    if (key) {
      const cand = normalizeStatus(row[key]);
      if (cand !== "neutral") return cand;
    }
  }
  for (const rk of Object.keys(row)) {
    const cand = normalizeStatus(row[rk]);
    if (cand !== "neutral") return cand;
  }
  return "neutral";
}

function computeRecommendation(r?: Readiness) {
  if (!r || !Number.isFinite(r.score_pct) || r.considered === 0) {
    return {
      label: "Manual Review",
      className: "pill pill-concern",
      reason: "No recognizable status/results.",
    };
  }
  if (r.fail > 0) {
    return {
      label: "FAIL",
      className: "pill pill-fail",
      reason: `${r.fail} fail${r.fail === 1 ? "" : "s"} present.`,
    };
  }
  if (r.concern > 0) {
    return {
      label: "Manual Review",
      className: "pill pill-concern",
      reason: `${r.concern} concern(s) present.`,
    };
  }
  return {
    label: "PASS",
    className: "pill pill-pass",
    reason: "All considered tests passed.",
  };
}

/* ---------- Time helpers ---------- */

function parseTimespanToSeconds(raw?: string | null): number | null {
  if (!raw) return null;
  const dMatch = /^(\d+)\.(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?$/.exec(raw);
  if (dMatch) {
    const days = parseInt(dMatch[1], 10);
    const hh = parseInt(dMatch[2], 10);
    const mm = parseInt(dMatch[3], 10);
    const ss = parseInt(dMatch[4], 10);
    return days * 86400 + hh * 3600 + mm * 60 + ss;
  }
  const hMatch = /^(\d{1,2}):(\d{2}):(\d{2})(?:\.\d+)?$/.exec(raw);
  if (hMatch) {
    const hh = parseInt(hMatch[1], 10);
    const mm = parseInt(hMatch[2], 10);
    const ss = parseInt(hMatch[3], 10);
    return hh * 3600 + mm * 60 + ss;
  }
  const mMatch = /^(\d{1,2}):(\d{2})(?:\.\d+)?$/.exec(raw);
  if (mMatch) {
    const mm = parseInt(mMatch[1], 10);
    const ss = parseInt(mMatch[2], 10);
    return mm * 60 + ss;
  }
  const n = Number(raw);
  return Number.isFinite(n) ? Math.max(0, Math.floor(n)) : null;
}

function humanizeSeconds(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;

  const parts: string[] = [];
  if (h > 0) parts.push(`${h} ${h === 1 ? "hour" : "hours"}`);
  if (m > 0) parts.push(`${m} ${m === 1 ? "minute" : "minutes"}`);
  if (sec > 0 || parts.length === 0)
    parts.push(`${sec} ${sec === 1 ? "second" : "seconds"}`);
  return parts.join(" ");
}

/* ------------------ Debug helpers (light) ------------------ */

function logGroup(label: string, color = "#22c55e") {
  try {
    console.groupCollapsed(`%c${label}`, `color:${color};font-weight:600;`);
    return () => console.groupEnd();
  } catch {
    return () => {};
  }
}

function logKV(obj: Record<string, any>) {
  try {
    Object.entries(obj).forEach(([k, v]) => console.log(`${k}:`, v));
  } catch {}
}

/* ---------------------- Modal ---------------------- */

export default function MonitoringDetailsModal({
  systemId,
  open,
  onClose,
}: Props) {
  const DEBUG = useDebugFlag();

  const [summary, setSummary] = useState<ApiSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  const [series, setSeries] = useState<ComplianceSeriesResponse | null>(null);
  const [seriesError, setSeriesError] = useState<string>("");

  const [filter, setFilter] = useState<Filter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("original");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [sectionFilter, setSectionFilter] = useState<SectionFilter>("all");
  const [search, setSearch] = useState<string>("");

  // Close on ESC
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  // Fetch summary when modal opens or systemId changes
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setLoading(true);
    setError("");
    setSummary(null);

    const url = `/api/continuous_monitoring/system/${encodeURIComponent(
      systemId
    )}/latest?limit=4000`;
    const end = logGroup(`[MonitoringModal] Fetch ${url}`, "#0ea5e9");

    (async () => {
      const t0 = performance.now();
      try {
        if (DEBUG) console.log("→ GET", url);
        const resp = await fetch(url, { credentials: "include" });
        const t1 = performance.now();
        const text = await resp.text();
        const t2 = performance.now();

        if (DEBUG) {
          console.log("HTTP status:", resp.status);
          console.log("Elapsed (network):", `${(t1 - t0).toFixed(1)} ms`);
          console.log("Elapsed (parse text):", `${(t2 - t1).toFixed(1)} ms`);
          console.log("Raw body length:", text.length);
        }

        if (!resp.ok) {
          // Try to parse JSON so we can special-case NO_SCAN_FOR_SYSTEM
          let message = `HTTP ${resp.status}`;
          try {
            const data = text ? JSON.parse(text) : null;

            if (resp.status === 404 && data?.code === "NO_SCAN_FOR_SYSTEM") {
              message = `No stored scan results for system ${systemId} yet. Please manually run the scan policy it is a member of then check back, or wait for the scan policy to trigger.`;
            } else if (data?.error) {
              message = data.error;
            } else if (text) {
              message = text.slice(0, 400);
            }
          } catch {
            if (text) {
              message = text.slice(0, 400);
            }
          }

          if (!alive) return;
          if (DEBUG)
            console.error("[MonitoringModal] fetch error (non-OK):", message);
          setError(message);
          setSummary(null);
          setLoading(false);
          end();
          return;
        }

        const json = JSON.parse(text) as ApiSummary;
        if (!alive) return;
        setSummary(json);
      } catch (e: any) {
        if (!alive) return;
        if (DEBUG) console.error("[MonitoringModal] fetch error:", e);
        setError(e?.message || "Failed to load details.");
        setSummary(null);
      } finally {
        if (alive) setLoading(false);
        end();
      }
    })();

    return () => {
      alive = false;
    };
  }, [open, systemId, DEBUG]);

  // Fetch compliance-over-time series when modal opens or systemId changes
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setSeries(null);
    setSeriesError("");

    // ✅ FIXED: path now matches Flask route
    const url = `/api/continuous_monitoring/system/${encodeURIComponent(
      systemId
    )}/compliance_over_time`;
    const end = logGroup(`[MonitoringModal] Fetch ${url}`, "#a855f7");

    (async () => {
      try {
        if (DEBUG) console.log("→ GET", url);
        const resp = await fetch(url, { credentials: "include" });
        const text = await resp.text();

        if (!resp.ok) {
          let message = `HTTP ${resp.status}`;
          try {
            const data = text ? JSON.parse(text) : null;
            if (data?.error) {
              message = data.error;
            } else if (text) {
              message = text.slice(0, 400);
            }
          } catch {
            if (text) message = text.slice(0, 400);
          }
          if (!alive) return;
          if (DEBUG)
            console.error("[MonitoringModal] series fetch error:", message);
          setSeriesError(message);
          setSeries(null);
          end();
          return;
        }

        const json = JSON.parse(text) as ComplianceSeriesResponse;
        if (!alive) return;
        setSeries(json);
      } catch (e: any) {
        if (!alive) return;
        if (DEBUG) console.error("[MonitoringModal] series fetch error:", e);
        setSeriesError(e?.message || "Failed to load compliance time series.");
        setSeries(null);
      } finally {
        end();
      }
    })();

    return () => {
      alive = false;
    };
  }, [open, systemId, DEBUG]);

  /* --------- Derivations (mostly cloned from Reporting) --------- */

  const cols = summary?.dataframe.columns ?? [];
  const statusHint =
    (summary?.readiness.status_column &&
      pickKey(cols, [summary.readiness.status_column])) ||
    pickKey(cols, preferredStatusKeys) ||
    null;

  const descKey =
    pickKey(cols, [
      "Package Review Check",
      "Check",
      "Test Description",
      "Description",
      "Review Check",
      "Title",
    ]) || null;

  const sectionKey = pickKey(cols, ["Tabs", "Section", "Category"]) || null;

  const itemNameKey =
    pickKey(cols, ["Item Name", "ItemName", "System Name", "SystemName", "Name"]) ||
    pickKey(cols, ["system_name"]);

  const topLevelName = (summary?.system_name ?? "").toString().trim();

  useEffect(() => {
    if (!DEBUG) return;
    const end = logGroup("[MonitoringModal] Derived keys");
    logKV({ statusHint, descKey, sectionKey, itemNameKey, topLevelName, columns: cols });
    end();
  }, [DEBUG, statusHint, descKey, sectionKey, itemNameKey, topLevelName, cols]);

  const itemName = useMemo(() => {
    if (topLevelName) return topLevelName;
    const rec0 = summary?.dataframe.records?.[0];
    if (!rec0) return null;
    if (
      itemNameKey &&
      rec0[itemNameKey] != null &&
      String(rec0[itemNameKey]).trim() !== ""
    ) {
      return String(rec0[itemNameKey]);
    }
    const tryKeys = ["item", "system", "title", "project"];
    for (const k of tryKeys) {
      const key = Object.keys(rec0).find((rk) => rk.toLowerCase().includes(k));
      if (key && rec0[key]) return String(rec0[key]);
    }
    return null;
  }, [summary, itemNameKey, topLevelName]);

  const processingTime = useMemo(() => {
    const rec0 = summary?.dataframe.records?.[0];
    if (!rec0) return null;
    const raw = (rec0["elapsed_raw"] ??
      rec0["elapsed"] ??
      rec0["META_ELAPSED"]) as any;
    let secs = rec0["elapsed_seconds"] as any as number | null;
    if (secs == null) secs = parseTimespanToSeconds(typeof raw === "string" ? raw : null);
    return Number.isFinite(secs) ? humanizeSeconds(Number(secs)) : null;
  }, [summary]);

  useEffect(() => {
    if (!DEBUG) return;
    const end = logGroup("[MonitoringModal] Header signals");
    logKV({
      headerItemName: itemName,
      topLevelSystemName: summary?.system_name ?? null,
      processingTime,
      system_id: summary?.system_id ?? null,
      ran_at_iso: summary?.ran_at_iso ?? null,
    });
    end();
  }, [
    DEBUG,
    itemName,
    processingTime,
    summary?.system_name,
    summary?.system_id,
    summary?.ran_at_iso,
  ]);

  const tableRows: TestRow[] = useMemo(() => {
    if (!summary) return [];
    return (summary.dataframe.records || []).map((r, i) => {
      const rawNum = r["test_num"];
      const parsed =
        typeof rawNum === "number"
          ? rawNum
          : Number.isFinite(Number(rawNum))
          ? Number(rawNum)
          : null;
      const displayIdx = parsed ?? i + 1;

      let testVal = descKey ? r[descKey] : undefined;
      if (testVal == null || String(testVal).trim() === "") {
        const firstText = Object.values(r).find(
          (v) => v != null && typeof v !== "object" && String(v).trim() !== ""
        );
        testVal = firstText ?? "(no description)";
      }

      return {
        idx: displayIdx,
        status: statusFromRow(r, statusHint || undefined),
        test: String(testVal),
        section: sectionKey ? r[sectionKey] : undefined,
      } as TestRow;
    });
  }, [summary, statusHint, descKey, sectionKey]);

  useEffect(() => {
    if (!DEBUG) return;
    const end = logGroup(
      "[MonitoringModal] Table composition & distributions",
      "#0ea5e9"
    );
    try {
      const total = tableRows.length;
      const counts: Record<string, number> = {
        pass: 0,
        fail: 0,
        concern: 0,
        neutral: 0,
      };
      const sectionCounts = new Map<string, number>();

      tableRows.forEach((r) => {
        counts[r.status] = (counts[r.status] || 0) + 1;
        const key = String(r.section ?? "(none)");
        sectionCounts.set(key, (sectionCounts.get(key) || 0) + 1);
      });

      console.table([{ total, ...counts }]);
      console.log("Section distribution:");
      console.table(
        Array.from(sectionCounts.entries())
          .map(([section, count]) => ({ section, count }))
          .sort((a, b) => b.count - a.count)
      );

      if (summary?.readiness) {
        console.log("Readiness:", summary.readiness);
      }
    } catch (e) {
      console.warn("[MonitoringModal] distribution log failure:", e);
    } finally {
      end();
    }
  }, [DEBUG, tableRows, summary?.readiness]);

  const score = Number(summary?.readiness.score_pct ?? 0);
  const rec = computeRecommendation(summary?.readiness);

  const headerTitle = useMemo(() => {
    const idPart = summary?.system_id != null ? `#${summary.system_id}` : null;
    if (idPart && itemName) return `${idPart} — ${itemName}`;
    if (itemName) return itemName;
    return idPart ?? "—";
  }, [summary?.system_id, itemName]);

  // Don't render anything if modal isn't open
  if (!open) return null;

  const chartPoints = series?.points ?? [];

  return (
    <>
      {/* Inline styles for modal layout */}
      <style>{`
        .cm-modal-backdrop {
          position: fixed;
          inset: 0;
          background: rgba(0,0,0,0.65);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 9999;
        }
        .cm-modal-shell {
          width: min(1040px, 100vw - 32px);
          max-height: min(90vh, 900px);
          background: #05060a;
          border-radius: 16px;
          border: 1px solid #374151;
          box-shadow: 0 25px 60px rgba(0,0,0,0.7);
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }
        .cm-modal-header {
          padding: 12px 18px;
          border-bottom: 1px solid #1f2933;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          background: linear-gradient(to right, #020617, #020617, #05101f);
        }
        .cm-modal-title {
          font-size: 15px;
          font-weight: 600;
          color: #e5e7eb;
        }
        .cm-modal-sub {
          font-size: 12px;
          color: #9ca3af;
        }
        .cm-modal-close {
          border: none;
          background: transparent;
          color: #9ca3af;
          cursor: pointer;
          padding: 4px;
          border-radius: 999px;
        }
        .cm-modal-close:hover {
          background: rgba(148,163,184,0.16);
          color: #f9fafb;
        }
        .cm-modal-body {
          padding: 16px 18px 18px;
          overflow-y: auto;
        }
      `}</style>

      <div className="cm-modal-backdrop" onClick={onClose}>
        <div
          className="cm-modal-shell"
          onClick={(e) => e.stopPropagation()} // prevent closing when clicking inside
        >
          <div className="cm-modal-header">
            <div>
              <div className="cm-modal-title">{headerTitle}</div>
              {summary && (
                <div className="cm-modal-sub">
                  Last run: {summary.ran_at_iso} • Job: {summary.job_id}
                </div>
              )}
            </div>
            <button
              type="button"
              className="cm-modal-close"
              aria-label="Close details"
              onClick={onClose}
            >
              ✕
            </button>
          </div>

          <div className="cm-modal-body">
            {loading && <div className="card">Loading latest scan…</div>}
            {!loading && error && <div className="card error">{error}</div>}
            {!loading && !error && !summary && (
              <div className="card error">
                No summary available for this system.
              </div>
            )}

            {!loading && summary && (
              <div className="reporting-page">
                <div className="top-grid">
                  <div className="top-card card">
                    <div className="system-header">
                      <div>
                        <div className="eyebrow">SYSTEM</div>
                        <div className="system-id">{headerTitle}</div>
                      </div>
                    </div>

                    <div className="meta">
                      <div>
                        <span>Processing Time</span>
                        <code>{processingTime ?? "—"}</code>
                      </div>
                      <div>
                        <span>Recommendation</span>
                        <div title={rec.reason} className="meta-pill">
                          <span className={rec.className}>{rec.label}</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="gauge-card card">
                    <ReadinessGauge score={isFinite(score) ? score : 0} />
                    <div className="legends">
                      <div className="chip chip-pass">
                        Pass: {summary.readiness.pass}
                      </div>
                      <div className="chip chip-concern">
                        Concern: {summary.readiness.concern}
                      </div>
                      <div className="chip chip-fail">
                        Fail: {summary.readiness.fail}
                      </div>
                      <div className="chip chip-neutral">
                        Not Applicable: {summary.readiness.neutral}
                      </div>
                    </div>
                  </div>
                </div>

                <TestTable
                  rows={tableRows}
                  statusHint={statusHint}
                  filter={filter}
                  onFilterChange={(v) => {
                    if (DEBUG) console.log("[UI] filter →", v);
                    setFilter(v);
                  }}
                  sectionFilter={sectionFilter}
                  onSectionFilterChange={(v) => {
                    if (DEBUG) console.log("[UI] sectionFilter →", v);
                    setSectionFilter(v);
                  }}
                  search={search}
                  onSearchChange={(v) => {
                    if (DEBUG) console.log("[UI] search →", v);
                    setSearch(v);
                  }}
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onSortKeyChange={(v) => {
                    if (DEBUG) console.log("[UI] sortKey →", v);
                    setSortKey(v);
                  }}
                  onSortDirChange={(v) => {
                    if (DEBUG) console.log("[UI] sortDir →", v);
                    setSortDir(v);
                  }}
                />

                {/* Compliance over time section */}
                <div style={{ marginTop: 18 }}>
                  {seriesError && (
                    <div className="card error" style={{ marginBottom: 8 }}>
                      {seriesError}
                    </div>
                  )}
                  <ComplianceTimeChart points={chartPoints} />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

