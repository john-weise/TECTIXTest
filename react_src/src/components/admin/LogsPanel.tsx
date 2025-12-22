// src/components/admin/LogsPanel.tsx
import React, { useEffect, useMemo, useState } from "react";
import { LogInfo, TailResponse, SearchResponse } from "../../types/admin";

/**
 * LogsPanel
 * - Shows log info (GET /api/admin/logs/info)
 * - Tails logs (GET /api/admin/logs/tail)
 * - Searches logs (POST /api/admin/logs/search)
 */
export default function LogsPanel() {
  const [logInfo, setLogInfo] = useState<LogInfo | null>(null);
  const [tailBytes, setTailBytes] = useState<number>(200_000);
  const [tail, setTail] = useState<TailResponse | null>(null);
  const [tailLoading, setTailLoading] = useState(false);
  const [searchPattern, setSearchPattern] = useState<string>("");
  const [caseSensitive, setCaseSensitive] = useState<boolean>(false);
  const [contextLines, setContextLines] = useState<number>(0);
  const [searchResults, setSearchResults] = useState<SearchResponse | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    void fetchLogInfo();
    void fetchTail(tailBytes);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fmtBytes = (n?: number) =>
    typeof n === "number"
      ? (n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n >= 1e3 ? `${(n / 1e3).toFixed(1)} KB` : `${n} B`)
      : "—";

  const mtimeStr = useMemo(() => {
    if (!logInfo?.mtime) return "—";
    const d = new Date(logInfo.mtime * 1000);
    return d.toLocaleString();
  }, [logInfo?.mtime]);

  const fetchLogInfo = async () => {
    setError("");
    try {
      const r = await fetch("/api/admin/logs/info", { credentials: "include" });
      if (!r.ok) throw new Error(`info HTTP ${r.status}`);
      const data: LogInfo = await r.json();
      setLogInfo(data);
    } catch (e: any) {
      setError(`Failed to load log info: ${e.message || e}`);
    }
  };

  const fetchTail = async (bytes: number) => {
    setTailLoading(true);
    setError("");
    try {
      const r = await fetch(`/api/admin/logs/tail?bytes=${encodeURIComponent(bytes)}`, {
        credentials: "include",
      });
      if (!r.ok) throw new Error(`tail HTTP ${r.status}`);
      const data: TailResponse = await r.json();
      setTail(data);
    } catch (e: any) {
      setError(`Failed to tail log: ${e.message || e}`);
    } finally {
      setTailLoading(false);
    }
  };

  const doSearch = async () => {
    setSearchLoading(true);
    setError("");
    setSearchResults(null);
    try {
      const r = await fetch("/api/admin/logs/search", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pattern: searchPattern,
          case_sensitive: caseSensitive,
          context: contextLines,
          max_bytes: 2_000_000,
          max_matches: 200,
          per_line_limit: 20_000,
          timeout_s: 1.0,
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data?.error || `search HTTP ${r.status}`);
      setSearchResults(data as SearchResponse);
    } catch (e: any) {
      setError(`Search failed: ${e.message || e}`);
    } finally {
      setSearchLoading(false);
    }
  };

  const downloadLog = () => {
    const url = "/api/admin/logs/download";
    const a = document.createElement("a");
    a.href = url;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  return (
    <>
      <h2 className="section-title">System Logs</h2>
      <div className="gold-rule" aria-hidden="true" />

      {error && <div className="error-banner">{error}</div>}

      {/* Log meta + actions */}
      <div className="card">
        <div className="card-row">
          <div className="meta">
            <div><strong>Path:</strong> {logInfo?.path ?? "—"}</div>
            <div><strong>Exists:</strong> {logInfo?.exists ? "yes" : "no"}</div>
            <div><strong>Size:</strong> {fmtBytes(logInfo?.size_bytes)}</div>
            <div><strong>Modified:</strong> {mtimeStr}</div>
          </div>
          <div className="actions">
            <button className="secondary-button" onClick={() => fetchLogInfo()}>
              Refresh Info
            </button>
            <button className="secondary-button" onClick={downloadLog} disabled={!logInfo?.exists}>
              Download Log
            </button>
          </div>
        </div>
      </div>

      {/* Tail viewer */}
      <div className="card">
        <h3 className="admin-subhead">Tail</h3>
        <div className="row">
          <label className="inline">
            Last&nbsp;
            <input
              type="number"
              min={1000}
              max={2_000_000}
              step={1000}
              value={tailBytes}
              onChange={(e) =>
                setTailBytes(Math.max(1000, Math.min(2_000_000, Number(e.target.value || 0))))
              }
              style={{ width: 120 }}
            />
            &nbsp;bytes
          </label>
          <button className="generate-button" onClick={() => fetchTail(tailBytes)} disabled={tailLoading}>
            {tailLoading ? "Loading…" : "Refresh"}
          </button>
        </div>
        <div className="log-viewer" role="region" aria-label="Log Tail">
          {tail?.lines?.length ? (
            <pre className="log-pre">
              {tail.lines.map((ln, i) => (
                <div key={i} className="log-line">
                  {ln}
                </div>
              ))}
            </pre>
          ) : (
            <div className="user-empty">No tail loaded.</div>
          )}
        </div>
        {tail?.truncated && <div className="hint">Showing last part of the requested slice.</div>}
      </div>

      {/* Search */}
      <div className="card">
        <h3 className="admin-subhead">Search</h3>
        <div className="row">
          <input
            type="text"
            placeholder='Pattern (supports "*" and "?" wildcards)'
            value={searchPattern}
            onChange={(e) => setSearchPattern(e.target.value)}
            className="admin-input"
            style={{ flex: 1, minWidth: 280 }}
          />
          <label className="checkbox-label" title="Case sensitive">
            <input
              type="checkbox"
              checked={caseSensitive}
              onChange={(e) => setCaseSensitive(e.target.checked)}
            />
            <span>Case sensitive</span>
          </label>
          <label className="inline" title="Lines of context before/after each hit">
            Context&nbsp;
            <input
              type="number"
              min={0}
              max={5}
              value={contextLines}
              onChange={(e) => setContextLines(Math.max(0, Math.min(5, Number(e.target.value || 0))))}
              style={{ width: 64 }}
            />
          </label>
          <button
            className="generate-button"
            onClick={doSearch}
            disabled={!searchPattern.trim() || searchLoading}
          >
            {searchLoading ? "Searching…" : "Search"}
          </button>
        </div>

        {searchResults && (
          <>
            <div className="meta" style={{ marginTop: 8 }}>
              <strong>Matches:</strong> {searchResults.hit_count}
              {searchResults.truncated && <span className="hint"> (truncated)</span>}
            </div>
            <div className="log-viewer" role="region" aria-label="Search Results">
              {searchResults.hits.length ? (
                <pre className="log-pre">
                  {searchResults.hits.map((h, idx) => {
                    const before = h.before || [];
                    const after = h.after || [];
                    const [s, e] = h.match;
                    const pre = h.line.slice(0, s);
                    const mid = h.line.slice(s, e);
                    const post = h.line.slice(e);
                    return (
                      <div key={idx} className="log-hit-block">
                        {before.map((b, i) => (
                          <div key={`b-${i}`} className="log-line faded">{b}</div>
                        ))}
                        <div className="log-line">
                          <span className="line-no">[{h.line_no}] </span>
                          <span>{pre}</span>
                          <mark className="hit">{mid}</mark>
                          <span>{post}</span>
                        </div>
                        {after.map((a, i) => (
                          <div key={`a-${i}`} className="log-line faded">{a}</div>
                        ))}
                      </div>
                    );
                  })}
                </pre>
              ) : (
                <div className="user-empty">No matches.</div>
              )}
            </div>
          </>
        )}
      </div>
    </>
  );
}
