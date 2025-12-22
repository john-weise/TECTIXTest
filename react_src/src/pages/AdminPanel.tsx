// src/pages/AdminPanel.tsx
import React, { useEffect, useState } from "react";
import CyberBackground from "../components/CyberBackground";
import TopNav from "../components/TopNav";
import ClassificationBanner from "../components/ClassificationBanner";
import "../styles/AdminPanel.css";
import "../styles/Dashboard.css";

// Admin subcomponents
import AdminSidebar, { AdminSection } from "../components/admin/AdminSidebar";
import UsersPanel from "../components/admin/UsersPanel";
import LogsPanel from "../components/admin/LogsPanel";
import PortfolioPanel from "../components/admin/PortfolioPanel";
import AboutPanel from "../components/admin/AboutPanel";
import ScanPolicyPanel from "../components/admin/ScanPolicyPanel";
import EmassManagement from "../components/admin/EmassManagement";

/**
 * AdminPanel (page)
 * - Hosts the common layout (banner, nav, background)
 * - Renders the active sub-panel selected via the sidebar
 *
 * NOTE: Ensure `AdminSection` in AdminSidebar includes "emass" and the sidebar
 * exposes a corresponding nav item labeled "eMASS Connection Management".
 */
export default function AdminPanel(): React.ReactElement {
  const [section, setSection] = useState<AdminSection>("users");

  // Optional: keep tab title in sync with current section (does not affect styling)
  useEffect(() => {
    const label =
      section === "users" ? "User Management" :
      section === "logs" ? "Logs" :
      section === "portfolio" ? "Portfolio" :
      section === "policies" ? "Scan Policies" :
      section === "about" ? "About" :
      section === "emass" ? "eMASS Connection Management" :
      "Admin";
    document.title = `TECTIX • Admin • ${label}`;
  }, [section]);

  return (
    <div className="with-class-banner">
      {/* ABSOLUTE TOP classification banner */}
      <ClassificationBanner
        level="CUI"
        sticky={false}
        className="classification-banner--fixed"
      />

      {/* Spacer to protect layout if CSS loads late */}
      <div aria-hidden="true" style={{ height: 44 }} />

      {/* Scoped layout adjustments for fixed banner */}
      <style>{`
        .classification-banner--fixed {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          z-index: 10000;
        }
        .with-class-banner .top-nav--floating { top: 44px; }
        .with-class-banner .admin-wrapper { padding-top: calc(78px + 44px); }
      `}</style>

      <div className="admin-wrapper">
        {/* Background FX layer */}
        <div className="dashboard-background-box">
          <CyberBackground />
        </div>

        {/* Top nav adopts floating offset via .top-nav--floating class in your stylesheet */}
        <TopNav isAdmin />

        <div className="admin-main" role="region" aria-label="Admin layout">
          {/* Sidebar */}
          <AdminSidebar section={section} onChange={setSection} />

          {/* Content */}
          <section className="admin-content" role="main" aria-live="polite">
            {section === "users" && <UsersPanel />}
            {section === "about" && <AboutPanel />}
            {section === "logs" && <LogsPanel />}
            {section === "portfolio" && <PortfolioPanel />}
            {section === "policies" && <ScanPolicyPanel />}
            {section === "emass" && <EmassManagement />}
          </section>
        </div>
      </div>
    </div>
  );
}

