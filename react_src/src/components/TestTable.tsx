import React, { useMemo } from "react";

export type RowStatus = "pass" | "fail" | "concern" | "neutral";

/**
 * TestRow.idx is the displayed test number:
 * - Prefer the engine's real test number (test_num) when available.
 * - Otherwise the caller may pass a sequential index (i+1).
 */
export type TestRow = {
  idx: number;          // displayed test number (prefer real test_num)
  status: RowStatus;    // normalized status
  test: string;         // human-readable test name / description (what the test does)
  details?: string;     // test outcome / message (why it passed/failed)
  section?: string;     // optional section/category (e.g., Tabs)
};

export type Filter = "all" | "pass" | "concern" | "fail" | "neutral";
export type SortKey = "original" | "status" | "test";
export type SortDir = "asc" | "desc";
export type SectionFilter = "all" | "none" | string; // "none" = rows without a section

const STATUS_LABEL: Record<RowStatus, string> = {
  pass: "Pass",
  fail: "Fail",
  concern: "Concern",
  neutral: "N/A", // show literal N/A in the UI
};

export default function TestTable({
  rows,
  statusHint,
  filter,
  onFilterChange,
  sectionFilter,
  onSectionFilterChange,
  search,
  onSearchChange,
  sortKey,
  sortDir,
  onSortKeyChange,
  onSortDirChange,
}: {
  rows: TestRow[];
  statusHint?: string | null;
  filter: Filter;
  onFilterChange: (f: Filter) => void;

  // section filter + search
  sectionFilter: SectionFilter;
  onSectionFilterChange: (s: SectionFilter) => void;
  search: string;
  onSearchChange: (q: string) => void;

  sortKey: SortKey;
  sortDir: SortDir;
  onSortKeyChange: (k: SortKey) => void;
  onSortDirChange: (d: SortDir) => void;
}) {
  // Unique section list for the dropdown (sorted A–Z, case-insensitive).
  const sections = useMemo(() => {
    const s = new Set<string>();
    for (const r of rows) {
      if (r.section && r.section.trim()) s.add(r.section.trim());
    }
    return Array.from(s).sort((a, b) =>
      a.localeCompare(b, undefined, { sensitivity: "base" })
    );
  }, [rows]);

  const filtered = useMemo(() => {
    const needle = (search || "").trim().toLowerCase();

    return rows.filter((r) => {
      // Status filter (includes 'neutral').
      if (filter !== "all" && r.status !== filter) return false;

      // Section filter.
      if (sectionFilter !== "all") {
        if (sectionFilter === "none") {
          if (r.section && r.section.trim()) return false; // only rows with no/blank section
        } else {
          if ((r.section || "").trim() !== sectionFilter) return false;
        }
      }

      // Search filter (match in test name/description, outcome, or section).
      if (needle) {
        const hayTest = (r.test || "").toLowerCase();
        const hayDetails = (r.details || "").toLowerCase();
        const haySection = (r.section || "").toLowerCase();
        if (
          !hayTest.includes(needle) &&
          !hayDetails.includes(needle) &&
          !haySection.includes(needle)
        ) {
          return false;
        }
      }

      return true;
    });
  }, [rows, filter, sectionFilter, search]);

  const sorted = useMemo(() => {
    const out = [...filtered];

    if (sortKey === "original") {
      // "Original" = numeric by displayed test number (idx).
      out.sort((a, b) => (sortDir === "asc" ? a.idx - b.idx : b.idx - a.idx));
    } else if (sortKey === "status") {
      // Severity order; neutral = least severe.
      const rank: Record<RowStatus, number> = { fail: 3, concern: 2, pass: 1, neutral: 0 };
      out.sort((a, b) => {
        const da = rank[a.status], db = rank[b.status];
        return sortDir === "asc" ? da - db : db - da;
      });
    } else if (sortKey === "test") {
      out.sort((a, b) =>
        sortDir === "asc"
          ? a.test.localeCompare(b.test, undefined, { sensitivity: "base" })
          : b.test.localeCompare(a.test, undefined, { sensitivity: "base" })
      );
    }
    return out;
  }, [filtered, sortKey, sortDir]);

  return (
    <div className="table-wrap card">
      <div className="controls controls--table">
        <div className="control-row">
          <label htmlFor="filter">Status</label>
          <select
            id="filter"
            value={filter}
            onChange={(e) => onFilterChange(e.target.value as Filter)}
          >
            <option value="all">All</option>
            <option value="pass">Pass</option>
            <option value="concern">Concern</option>
            <option value="fail">Fail</option>
            {/* N/A (neutral) in the dropdown */}
            <option value="neutral">Not Applicable</option>
          </select>

          <div className="spacer" />

          {/* Section filter */}
          <label htmlFor="sectionFilter">Section</label>
          <select
            id="sectionFilter"
            value={sectionFilter}
            onChange={(e) => onSectionFilterChange(e.target.value as SectionFilter)}
          >
            <option value="all">All sections</option>
            <option value="none">(no section)</option>
            {sections.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>

          <div className="spacer" />

          <label htmlFor="sortKey">Sort</label>
          <select
            id="sortKey"
            value={sortKey}
            onChange={(e) => onSortKeyChange(e.target.value as SortKey)}
          >
            <option value="original">Original order</option>
            <option value="status">Status (severity)</option>
            <option value="test">Test (A–Z)</option>
          </select>

          <select
            aria-label="Sort direction"
            value={sortDir}
            onChange={(e) => onSortDirChange(e.target.value as SortDir)}
          >
            <option value="asc">Asc</option>
            <option value="desc">Desc</option>
          </select>

          <div className="spacer" />

          {/* Search bar */}
          <label htmlFor="search" className="sr-only">Search</label>
          <input
            id="search"
            type="search"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search tests, outcomes, or sections…"
            className="input-search"
          />

          {statusHint ? (
            <div className="hint">
              Status column: <code>{statusHint}</code>
            </div>
          ) : (
            <div className="hint muted">No explicit status column; inferring.</div>
          )}
        </div>
      </div>

      <div className="table-scroll">
        <table className="sheet">
          <thead>
            <tr>
              <th className="col-idx">Test #</th>
              <th className="col-status">Status</th>
              <th>Test description</th>
              <th>Test outcome</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              // Use a composite key to avoid potential duplicate keys if two rows share the same idx.
              <tr key={`${r.idx}-${i}`} className={`row-${r.status}`}>
                <td className="col-idx">{r.idx}</td>
                <td className="col-status">
                  {/* Special-case neutral to show a clean "N/A" badge */}
                  {r.status === "neutral" ? (
                    <span className="pill pill-na">N/A</span>
                  ) : (
                    <span className={`pill pill-${r.status}`}>{STATUS_LABEL[r.status]}</span>
                  )}
                </td>
                <td>
                  <div className="test-line">
                    {/* NOW: test name / description of what is being checked */}
                    <div className="test-title">{r.test || "(no description)"}</div>
                    {r.section && (
                      <div className="test-sub muted">Section: {r.section}</div>
                    )}
                  </div>
                </td>
                <td>
                  {/* Test outcome / message (what actually happened) */}
                  <div className="test-outcome">
                    {r.details && r.details.trim()
                      ? r.details
                      : <span className="muted">—</span>}
                  </div>
                </td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={4} className="muted empty">
                  No rows for this filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}


