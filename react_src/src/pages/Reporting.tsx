/* eslint-disable no-console */
import React, { useEffect, useMemo, useState } from "react";
import CyberBackground from "../components/CyberBackground";
import TopNav from "../components/TopNav";

import ReadinessGauge from "../components/ReadinessGauge";
import TestTable, {
  TestRow,
  Filter,
  SortKey,
  SortDir,
  SectionFilter,
} from "../components/TestTable";

import "../styles/Reporting.css";

/* ---------- Types from the backend summary endpoint ---------- */
type Readiness = {
  status_column: string | null;
  pass: number;
  fail: number;
  concern: number;
  neutral: number; // backend calls it "neutral" — we display as "Not Applicable"
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
  /** Optional: best-effort system name provided by backend */
  system_name?: string | null;
  ran_at_epoch: number;
  ran_at_iso: string;
  dataframe: DataFramePayload;
  dataframe_truncated: boolean;
  readiness: Readiness;
};

type SessionInfo = { authenticated: boolean; user?: string; is_admin?: boolean };

/* ------------------------- Helpers -------------------------- */

const preferredStatusKeys = ["result", "status", "outcome", "test_status"];

// enable console dump by default; override with ?debug=0 or ?debug=false/off
function useDebugFlag() {
  return useMemo(() => {
    try {
      const p = new URLSearchParams(window.location.search);
      if (p.has("debug")) {
        const v = (p.get("debug") || "").toLowerCase();
        return !(v === "0" || v === "false" || v === "off");
      }
      return true; // default ON
    } catch {
      return true; // safest default
    }
  }, []);
}

type RowStatus = "pass" | "fail" | "concern" | "neutral";
function normalizeStatus(v: any): RowStatus {
  if (v === null || v === undefined) return "neutral";
  if (typeof v === "boolean") return v ? "pass" : "fail";
  const s = String(v).trim().toLowerCase();
  if (/\bpass(ed)?\b|ok|success|compliant|true|green/.test(s)) return "pass";
  if (/\bfail(ed)?\b|non\s*compliant|not compliant|false|red|error|critical/.test(s)) return "fail";
  if (/\bconcern|warning|warn|yellow|partial|medium|high\b/.test(s)) return "concern";
  if (/^\s*$|^n\/?a$|^na$|^skip(ped)?$/i.test(s)) return "neutral"; // shown as "Not Applicable"
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

/**
 * IMPORTANT:
 * - If an explicit status column exists (e.g., "Result"), TRUST IT even if it's "neutral" (N/A).
 * - Only when we DON'T have an explicit column should we skip neutral and keep hunting.
 */
function statusFromRow(row: Record<string, any>, explicit?: string | null) {
  // 1) Use explicit column if present.
  if (explicit) {
    const key = Object.keys(row).find((rk) => rk.toLowerCase() === explicit.toLowerCase());
    if (key) {
      return normalizeStatus(row[key]); // return even if "neutral"
    }
  }

  // 2) Try typical status-like columns (fallback path).
  for (const k of preferredStatusKeys) {
    const key = Object.keys(row).find((rk) => rk.toLowerCase() === k.toLowerCase());
    if (key) {
      const cand = normalizeStatus(row[key]);
      if (cand !== "neutral") return cand;
    }
  }

  // 3) Final fallback: scan values for any pass/fail/concern; neutral = no signal.
  for (const rk of Object.keys(row)) {
    const cand = normalizeStatus(row[rk]);
    if (cand !== "neutral") return cand;
  }

  return "neutral";
}

function computeRecommendation(r?: Readiness) {
  if (!r || !Number.isFinite(r.score_pct) || r.considered === 0) {
    return { label: "Manual Review", className: "pill pill-concern", reason: "No recognizable status/results." };
  }
  if (r.fail > 0) {
    return { label: "FAIL", className: "pill pill-fail", reason: `${r.fail} fail${r.fail === 1 ? "" : "s"} present.` };
  }
  if (r.concern > 0) {
    return { label: "Manual Review", className: "pill pill-concern", reason: `${r.concern} concern(s) present.` };
  }
  return { label: "PASS", className: "pill pill-pass", reason: "All considered tests passed." };
}

/* ---------- Time helpers for “Processing Time” ---------- */

function parseTimespanToSeconds(raw?: string | null): number | null {
  if (!raw) return null;
  // Accept "HH:MM:SS", "HH:MM:SS.sss", possibly days "d.hh:mm:ss" (just in case)
  const dMatch = /^(\d+)\.(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?$/.exec(raw); // d.hh:mm:ss
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
  // If it’s already “42.3” seconds or something numeric-ish
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
  if (sec > 0 || parts.length === 0) parts.push(`${sec} ${sec === 1 ? "second" : "seconds"}`);
  return parts.join(" ");
}

/* -------------------- Debug utilities -------------------- */

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

function sizeOfJSON(obj: any): string {
  try {
    const bytes = new Blob([JSON.stringify(obj)]).size;
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  } catch {
    return "(unknown)";
  }
}

/* --------------------------- Page --------------------------- */

export default function Reporting() {
  const DEBUG = useDebugFlag();

  const [sessionInfo, setSessionInfo] = useState<SessionInfo>({ authenticated: false });

  const [summary, setSummary] = useState<ApiSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const [filter, setFilter] = useState<Filter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("original");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const [sectionFilter, setSectionFilter] = useState<SectionFilter>("all");
  const [search, setSearch] = useState<string>("");

  // TopNav session (lightweight)
  useEffect(() => {
    (async () => {
      const end = logGroup("[Reporting] Session fetch");
      try {
        const t0 = performance.now();
        const resp = await fetch("/api/session", { credentials: "include" });
        const t1 = performance.now();
        const json = await resp.json();

        if (DEBUG) {
          console.log("HTTP status:", resp.status);
          console.log("Elapsed:", `${(t1 - t0).toFixed(1)} ms`);
          console.log("Headers snapshot:", {
            "content-type": resp.headers.get("content-type"),
            "cache-control": resp.headers.get("cache-control"),
          });
          console.log("Body size:", sizeOfJSON(json));
          console.log("Payload:", json);
        }

        setSessionInfo(json);
      } catch (e) {
        if (DEBUG) console.error("[Reporting] /api/session error:", e);
        setSessionInfo({ authenticated: false });
      } finally {
        end();
      }
    })();
  }, [DEBUG]);

  // Fetch the latest summary
  useEffect(() => {
    let alive = true;
    setLoading(true);

    const end = logGroup("[Reporting] Fetch /api/summary/latest");
    const url = `/api/summary/latest?limit=4000`;

    (async () => {
      const t0 = performance.now();
      try {
        if (DEBUG) console.log("→ GET", url);
        const resp = await fetch(url, { credentials: "include" });
        const t1 = performance.now();

        const text = await resp.text(); // capture raw for debugging
        const t2 = performance.now();

        if (DEBUG) {
          console.log("HTTP status:", resp.status);
          console.log("Elapsed (network):", `${(t1 - t0).toFixed(1)} ms`);
          console.log("Elapsed (parse text):", `${(t2 - t1).toFixed(1)} ms`);
          console.log("Headers snapshot:", {
            "content-type": resp.headers.get("content-type"),
            "cache-control": resp.headers.get("cache-control"),
          });
          console.log("Raw body length:", text.length);
        }

        if (!resp.ok) {
          throw new Error(
            `HTTP ${resp.status} — body: ${text.slice(0, 800)}${
              text.length > 800 ? " …(truncated)" : ""
            }`,
          );
        }

        const t3 = performance.now();
        const json = JSON.parse(text) as ApiSummary;
        const t4 = performance.now();

        if (DEBUG) {
          console.log("Elapsed (JSON.parse):", `${(t4 - t3).toFixed(1)} ms`);
          console.log("Body size:", sizeOfJSON(json));
          console.log("Parsed payload keys:", Object.keys(json || {}));
        }

        if (alive) setSummary(json);
      } catch (err) {
        if (alive) setSummary(null);
        if (DEBUG) console.error("[Reporting] fetch error:", err);
      } finally {
        if (alive) setLoading(false);
        end();
      }
    })();

    return () => {
      alive = false;
    };
  }, [DEBUG]);

  // Debug dump (optional, pretty)
  useEffect(() => {
    if (!DEBUG || !summary) return;
    const end = logGroup("[Reporting] /api/summary/latest payload (pretty)");
    try {
      console.log("Raw JSON:", JSON.parse(JSON.stringify(summary)));
      console.table([
        { job_id: summary.job_id, system_id: summary.system_id, ran_at: summary.ran_at_iso },
      ]);
      console.log("readiness:", summary.readiness);
      console.log("dataframe.shape:", summary.dataframe.shape);
      console.log("dataframe.columns:", summary.dataframe.columns);
      console.log("dataframe.dtypes:", summary.dataframe.dtypes);
      console.log("dataframe.source:", summary.dataframe.source);
      if (summary.dataframe.records?.length) {
        console.log("first record:", summary.dataframe.records[0]);
        const preview = summary.dataframe.records.slice(0, 200);
        console.table(preview);
        if (summary.dataframe.records.length > preview.length) {
          console.log(
            `(table preview truncated to ${preview.length} of ${summary.dataframe.records.length} records)`,
          );
        }
      } else {
        console.log("No records in dataframe.");
      }
    } catch (e) {
      console.warn("[Reporting] Debug dump failed:", e);
    } finally {
      end();
    }
  }, [summary, DEBUG]);

  /* ---------------------- Derivations ----------------------- */

  const cols = summary?.dataframe.columns ?? [];
  const statusHint =
    (summary?.readiness.status_column &&
      pickKey(cols, [summary.readiness.status_column])) ||
    pickKey(cols, preferredStatusKeys) ||
    null;

  // Test name / description (what the test does)
  const descKey =
    pickKey(cols, [
      "Test Name",
      "name",
      "Package Review Check",
      "Check",
      "Test Description",
      "Description",
      "Review Check",
      "Title",
    ]) || null;

  const sectionKey = pickKey(cols, ["Tabs", "Section", "Category"]) || null;

  // Message / outcome column (why it passed/failed)
  const messageKey =
    pickKey(cols, ["Message", "message", "Details", "details"]) || null;

  // Item/System name column (dataframe fallback)
  const itemNameKey =
    pickKey(cols, ["Item Name", "ItemName", "System Name", "SystemName", "Name"]) ||
    pickKey(cols, ["system_name"]); // dataframe column fallback if present

  // Prefer backend-provided top-level system_name
  const topLevelName = (summary?.system_name ?? "").toString().trim();

  // Log derived column choices
  useEffect(() => {
    if (!DEBUG) return;
    const end = logGroup("[Reporting] Derived keys");
    logKV({
      statusHint,
      descKey,
      messageKey,
      sectionKey,
      itemNameKey,
      topLevelName,
      columns: cols,
    });
    end();
  }, [DEBUG, statusHint, descKey, messageKey, sectionKey, itemNameKey, topLevelName, cols]);

  const itemName = useMemo(() => {
    if (topLevelName) return topLevelName; // ← prefer top-level from backend
    const rec0 = summary?.dataframe.records?.[0];
    if (!rec0) return null;
    if (itemNameKey && rec0[itemNameKey] != null && String(rec0[itemNameKey]).trim() !== "") {
      return String(rec0[itemNameKey]);
    }
    const tryKeys = ["item", "system", "title", "project"];
    for (const k of tryKeys) {
      const key = Object.keys(rec0).find((rk) => rk.toLowerCase().includes(k));
      if (key && rec0[key]) return String(rec0[key]);
    }
    return null;
  }, [summary, itemNameKey, topLevelName]);

  // Processing time shown in header (humanized)
  const processingTime = useMemo(() => {
    const rec0 = summary?.dataframe.records?.[0];
    if (!rec0) return null;
    const raw = (rec0["elapsed_raw"] ?? rec0["elapsed"] ?? rec0["META_ELAPSED"]) as any;
    let secs = (rec0["elapsed_seconds"] as any as number | null) ?? null;
    if (secs == null) secs = parseTimespanToSeconds(typeof raw === "string" ? raw : null);
    return Number.isFinite(secs) ? humanizeSeconds(Number(secs)) : null;
  }, [summary]);

  // Log header signals
  useEffect(() => {
    if (!DEBUG) return;
    const end = logGroup("[Reporting] Header signals");
    logKV({
      headerItemName: itemName,
      topLevelSystemName: summary?.system_name ?? null,
      processingTime,
      system_id: summary?.system_id ?? null,
      ran_at_iso: summary?.ran_at_iso ?? null,
    });
    end();
  }, [DEBUG, itemName, processingTime, summary?.system_name, summary?.system_id, summary?.ran_at_iso]);

  /**
   * Table rows:
   * - We prefer the engine-provided `test_num` for display and "original" ordering.
   * - If `test_num` is missing/non-numeric, fall back to sequential index (i+1).
   * This lets us show real test numbers without changing <TestTable/>.
   */
  const tableRows: TestRow[] = useMemo(() => {
    if (!summary) return [];
    return (summary.dataframe.records || []).map((r, i) => {
      // Prefer numeric test_num if present; else fallback to sequential index.
      const rawNum = r["test_num"];
      const parsed =
        typeof rawNum === "number"
          ? rawNum
          : Number.isFinite(Number(rawNum))
          ? Number(rawNum)
          : null;
      const displayIdx = parsed ?? i + 1;

      // Test name / description (what the test does)
      let testVal = descKey ? r[descKey] : undefined;
      if (testVal == null || String(testVal).trim() === "") {
        const firstText = Object.values(r).find(
          (v) => v != null && typeof v !== "object" && String(v).trim() !== "",
        );
        testVal = firstText ?? "(no description)";
      }

      // Outcome / message (why it passed/failed)
      const detailsVal =
        messageKey && r[messageKey] != null ? String(r[messageKey]) : undefined;

      return {
        idx: displayIdx, // ← this is what TestTable shows in the "Test #" column
        status: statusFromRow(r, statusHint || undefined),
        test: String(testVal),
        details: detailsVal,
        section: sectionKey ? r[sectionKey] : undefined,
      } as TestRow;
    });
  }, [summary, statusHint, descKey, messageKey, sectionKey]);

  // Log table composition & distributions
  useEffect(() => {
    if (!DEBUG) return;
    const end = logGroup("[Reporting] Table composition & distributions", "#0ea5e9");
    try {
      const total = tableRows.length;
      const counts: Record<string, number> = { pass: 0, fail: 0, concern: 0, neutral: 0 };
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
          .sort((a, b) => b.count - a.count),
      );

      if (summary?.readiness) {
        console.log("Readiness:", summary.readiness);
      }
    } catch (e) {
      console.warn("[Reporting] distribution log failure:", e);
    } finally {
      end();
    }
  }, [DEBUG, tableRows, summary?.readiness]);

  const score = Number(summary?.readiness.score_pct ?? 0);
  const rec = computeRecommendation(summary?.readiness);

  // Header title: "#<id> — <name>"
  const headerTitle = useMemo(() => {
    const idPart = summary?.system_id != null ? `#${summary.system_id}` : null;
    if (idPart && itemName) return `${idPart} — ${itemName}`;
    if (itemName) return itemName;
    return idPart ?? "—";
  }, [summary?.system_id, itemName]);

  // Log UI state changes
  useEffect(() => {
    if (!DEBUG) return;
    const end = logGroup("[Reporting] UI state changes: filter/sort/search/section");
    logKV({ filter, sortKey, sortDir, sectionFilter, search });
    end();
  }, [DEBUG, filter, sortKey, sortDir, sectionFilter, search]);

  /* ------------------------- Render ------------------------- */

  return (
    <>
      {/* Subtle brand background (quiet mesh + sweep) */}
      <CyberBackground intensity="quiet" />

      {/* Floating TopNav */}
      <TopNav isAdmin={!!sessionInfo.is_admin} />

      {/* Ensure content clears the fixed nav; keep this tiny and local */}
      <style>{`
        .reporting-wrapper { padding-top: 78px; }  /* height of TopNav */
        .reporting-page { position: relative; z-index: 0; }
      `}</style>

      <main className="reporting-wrapper">
        {loading && (
          <div className="reporting-page">
            <div className="card">Loading latest summary…</div>
          </div>
        )}

        {!loading && !summary && (
          <div className="reporting-page">
            <div className="card error">
              Couldn’t load summary (are you logged in and have a finished job?).
            </div>
          </div>
        )}

        {!loading && summary && (
          <div className="reporting-page">
            {/* Top: system info + gauge */}
            <div className="top-grid">
              <div className="top-card card">
                <div className="system-header">
                  <div>
                    <div className="eyebrow">SYSTEM</div>
                    <div className="system-id">{headerTitle}</div>
                  </div>

                  {/* Branded Download button */}
                  <a
                    className="plex-btn plex-btn--download"
                    href={`/download?job_id=${encodeURIComponent(summary.job_id)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    download
                    aria-label="Download spreadsheet (.xlsx)"
                  >
                    <svg
                      className="icon"
                      width="16"
                      height="16"
                      viewBox="0 0 24 24"
                      fill="none"
                      aria-hidden="true"
                    >
                      <path
                        d="M12 3v10m0 0l-4-4m4 4l4-4"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                      <path
                        d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                    Download Spreadsheet
                  </a>
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
                  <div className="chip chip-pass">Pass: {summary.readiness.pass}</div>
                  <div className="chip chip-concern">Concern: {summary.readiness.concern}</div>
                  <div className="chip chip-fail">Fail: {summary.readiness.fail}</div>
                  <div className="chip chip-neutral">Not Applicable: {summary.readiness.neutral}</div>
                </div>
              </div>
            </div>

            {/* Tests table */}
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
          </div>
        )}
      </main>
    </>
  );
}


