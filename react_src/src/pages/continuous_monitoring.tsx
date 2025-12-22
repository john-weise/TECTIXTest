// src/pages/continuous_monitoring.tsx
import React, { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import TopNav from "../components/TopNav";
import ClassificationBanner from "../components/ClassificationBanner";
import CyberBackground from "../components/CyberBackground";
import MonitoringGauge from "../components/monitoring/MonitoringGauge";
import MonitoringDetailsModal from "../components/monitoring/MonitoringDetailsModal";
import type { ContinuousMonitoringItem } from "../types/monitoring";
import "../styles/Dashboard.css";
import "../styles/AdminPanel.css";

// Visual knobs
const CARD_MIN_PX = 260; // min card width before wrapping
const GRID_GAP_PX = 16;  // gap between cards
const MAX_COLS = 6;      // cap the grid at 6 columns

// Auto-refresh options (milliseconds; 0 = off)
const AUTO_REFRESH_OPTIONS = [
  { label: "Off", value: 0 },
  { label: "Every 5 minutes", value: 5 * 60 * 1000 },
  { label: "Every 10 minutes", value: 10 * 60 * 1000 },
  { label: "Every hour", value: 60 * 60 * 1000 },
];

export default function ContinuousMonitoringPage() {
  const [items, setItems] = useState<ContinuousMonitoringItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [activeSystemId, setActiveSystemId] = useState<number | null>(null);
  const [autoRefreshMs, setAutoRefreshMs] = useState<number>(0);

  const navigate = useNavigate();

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const resp = await fetch("/api/monitoring/continuous", {
        credentials: "include",
      });
      if (!resp.ok) {
        let msg = `HTTP ${resp.status}`;
        try {
          const j = await resp.json();
          if (j?.error) msg = j.error;
        } catch {
          // best-effort error body parse
        }
        throw new Error(msg);
      }
      const data: ContinuousMonitoringItem[] = await resp.json();
      data.sort((a, b) => a.system_id - b.system_id);
      setItems(data);
    } catch (e: any) {
      setError(`Failed to load monitoring data: ${e?.message || e}`);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  // Auto-refresh loop, honoring the selected interval.
  useEffect(() => {
    if (!autoRefreshMs) return;

    const id = window.setInterval(() => {
      void fetchData();
    }, autoRefreshMs);

    return () => {
      window.clearInterval(id);
    };
  }, [autoRefreshMs, fetchData]);

  const hasItems = items.length > 0;

  return (
    <div className="with-class-banner">
      <ClassificationBanner
        level="CUI"
        sticky={false}
        className="classification-banner--fixed"
      />
      <div aria-hidden="true" style={{ height: 44 }} />

      {/* Page-scoped styles */}
      <style>{`
        .classification-banner--fixed {
          position: fixed; top: 0; left: 0; right: 0; z-index: 10000;
        }
        .with-class-banner .top-nav--floating { top: 44px; }

        /* Background stays behind everything */
        .dashboard-background-box { position: fixed; inset: 0; z-index: 0; }

        /* Foreground wrapper sits above background */
        .monitoring-foreground { position: relative; z-index: 1; color: #e5e7eb; }

        /* Centered container for the grid view; capped to <= MAX_COLS columns */
        .monitoring-container {
          --card-min: ${CARD_MIN_PX}px;
          --gap: ${GRID_GAP_PX}px;
          --max-cols: ${MAX_COLS};
          max-width: min(100%, calc(var(--max-cols) * var(--card-min) + (var(--max-cols) - 1) * var(--gap)));
          margin: 0 auto;
          padding: 0 16px 24px;
          box-sizing: border-box;
          width: 100%;
        }

        .monitoring-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin: 0 0 12px 0;
          gap: 12px;
          flex-wrap: wrap;
        }

        .monitoring-header-left {
          display: flex;
          align-items: center;
          gap: 12px;
          flex-wrap: wrap;
        }

        .auto-refresh-control {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          font-size: 12px;
          color: #9ca3af;
          padding: 4px 8px;
          border-radius: 999px;
          background: rgba(15,23,42,0.8);
          border: 1px solid #1f2937;
        }

        .auto-refresh-select {
          background: transparent;
          border: none;
          color: #e5e7eb;
          font-size: 12px;
          padding: 2px 4px;
          outline: none;
          cursor: pointer;
        }

        .auto-refresh-select option {
          background: #020617;
          color: #e5e7eb;
        }

        .monitoring-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(var(--card-min), 1fr));
          gap: var(--gap);
          width: 100%;
          margin-top: 16px;
        }

        /* Full-viewport empty state, centered */
        .monitoring-hero-empty {
          min-height: calc(100dvh - 44px); /* safe viewport height minus banner spacer */
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 24px 16px;
          box-sizing: border-box;
        }
        .monitoring-hero-card {
          padding: 32px 28px;
          border: 1px dashed var(--border-color, #2a2a2a);
          background: rgba(255,255,255,0.02);
          border-radius: 12px;
          max-width: 720px;
          width: 100%;
          text-align: center;
          box-shadow: 0 6px 30px rgba(0,0,0,0.35);
        }
        .monitoring-hero-title {
          font-size: clamp(20px, 2.6vw, 28px);
          font-weight: 700;
          margin: 0 0 10px 0;
        }
        .monitoring-hero-sub {
          color: #d6d6d6;
          margin: 0 0 20px 0;
          line-height: 1.5;
        }
        .monitoring-hero-accent {
          color: #f87171; font-weight: 700;
        }
        .monitoring-hero-actions {
          display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;
        }
      `}</style>

      {/* Background */}
      <div className="dashboard-background-box">
        <CyberBackground />
      </div>

      {/* Foreground content */}
      <div className="monitoring-foreground">
        <TopNav isAdmin={true} />

        {hasItems ? (
          <div className="monitoring-container">
            <div className="monitoring-header">
              <div className="monitoring-header-left">
                <h2 className="section-title" style={{ margin: 0 }}>
                  Continuous Monitoring
                </h2>
                <div className="auto-refresh-control">
                  <span>Auto-refresh</span>
                  <select
                    className="auto-refresh-select"
                    value={autoRefreshMs}
                    onChange={(e) => setAutoRefreshMs(Number(e.target.value))}
                  >
                    {AUTO_REFRESH_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="actions" style={{ display: "flex", gap: 8 }}>
                <button
                  className="secondary-button"
                  onClick={() => void fetchData()}
                  disabled={loading}
                >
                  {loading ? "Refreshing…" : "Refresh"}
                </button>
              </div>
            </div>

            {error && (
              <div className="error-banner" style={{ margin: "8px 0" }}>
                {error}
              </div>
            )}

            <div className="monitoring-grid">
              {items.map((it) => (
                <MonitoringGauge
                  key={it.system_id}
                  item={it}
                  onClick={() => setActiveSystemId(it.system_id)}
                />
              ))}
            </div>
          </div>
        ) : (
          <div className="monitoring-hero-empty">
            <div className="monitoring-hero-card">
              <div className="monitoring-hero-title">No Systems Enrolled</div>
              <div className="monitoring-hero-sub">
                To see gauges here, have an Admin enroll systems in{" "}
                <span className="monitoring-hero-accent">
                  Admin → Manage Monitoring Portfolio
                </span>
                .
              </div>

              {error && (
                <div
                  className="error-banner"
                  style={{ margin: "0 auto 16px auto", maxWidth: 640 }}
                >
                  {error}
                </div>
              )}

              <div className="monitoring-hero-actions">
                <button
                  className="generate-button"
                  onClick={() => navigate("/admin")}
                >
                  Go to Admin
                </button>
                <button
                  className="secondary-button"
                  onClick={() => void fetchData()}
                  disabled={loading}
                >
                  {loading ? "Refreshing…" : "Refresh"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {activeSystemId !== null && (
        <MonitoringDetailsModal
          systemId={activeSystemId}
          open={true}
          onClose={() => setActiveSystemId(null)}
        />
      )}
    </div>
  );
}



