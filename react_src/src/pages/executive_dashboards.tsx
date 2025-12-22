// src/pages/executive_dashboards.tsx
import React from "react";

import CyberBackground from "../components/CyberBackground";
import TopNav from "../components/TopNav";
import GrafanaDashboard from "../components/grafana_dashboard";

import "../styles/Dashboard.css";
import { useAuth } from "../App";

/**
 * ExecutiveDashboards
 *
 * High-level, read-only dashboards intended for leadership and stakeholders.
 * The Grafana embed is treated as a full-page surface beneath the header.
 */
const ExecutiveDashboards: React.FC = () => {
  const { isAdmin } = useAuth();

  return (
    <div className="dashboard-root executive-root">
      {/* Full-screen animated background (no children) */}
      <CyberBackground intensity="quiet" />

      {/* Shared top navigation */}
      <TopNav isAdmin={isAdmin} />

      <main className="dashboard-page executive-page">
        {/* Header / hero bar */}
        <header className="dashboard-header">
          <div className="dashboard-header-text">
            <span className="dashboard-kicker">Executive View</span>
            <h1 className="dashboard-title">Mission Readiness at a Glance</h1>
            <p className="dashboard-subtitle">
              High-level readiness, risk, and compliance views for leadership.
            </p>
          </div>
        </header>

        {/* Full-bleed Grafana surface */}
        <section className="dashboard-main-card executive-main-card">
          <GrafanaDashboard />
        </section>
      </main>
    </div>
  );
};

export default ExecutiveDashboards;

