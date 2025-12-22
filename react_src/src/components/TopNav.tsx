// src/components/TopNav.tsx
import React from "react";
import { useNavigate, useLocation } from "react-router-dom";

import "../styles/Login.css";
import "./TopNav.css";

interface TopNavProps {
  isAdmin: boolean;
}

const TopNav: React.FC<TopNavProps> = ({ isAdmin }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const isActive = (path: string) =>
    location.pathname === path || location.pathname.startsWith(path + "/");

  return (
    <nav className="top-nav top-nav--plex top-nav--floating" role="navigation" aria-label="Main">
      <div className="nav-left">
        <img src="/logo.png" alt="TECTIX Logo" className="nav-logo--small" />
        <span className="nav-brand">TECTIX</span>
      </div>

      <div className="nav-right" role="tablist" aria-label="Primary">
        <button
          role="tab"
          aria-selected={isActive("/dashboard")}
          className={`nav-link ${isActive("/dashboard") ? "active" : ""}`}
          onClick={() => navigate("/dashboard")}
        >
          Dashboard
        </button>

        <button
          role="tab"
          aria-selected={isActive("/executive_dashboards")}
          className={`nav-link ${isActive("/executive_dashboards") ? "active" : ""}`}
          onClick={() => navigate("/executive_dashboards")}
        >
          Executive Dashboards
        </button>

        <button
          role="tab"
          aria-selected={isActive("/continuous_monitoring")}
          className={`nav-link ${isActive("/continuous_monitoring") ? "active" : ""}`}
          onClick={() => navigate("/continuous_monitoring")}
        >
          Continuous Monitoring
        </button>

        {isAdmin && (
          <button
            role="tab"
            aria-selected={isActive("/admin")}
            className={`nav-link ${isActive("/admin") ? "active" : ""}`}
            onClick={() => navigate("/admin")}
          >
            Admin
          </button>
        )}

        <button
          role="tab"
          aria-selected={isActive("/account")}
          className={`nav-link ${isActive("/account") ? "active" : ""}`}
          onClick={() => navigate("/account")}
        >
          Account
        </button>

        <button
          className="nav-link nav-link--end"
          onClick={async () => {
            await fetch("/api/logout", { method: "POST", credentials: "include" });
            window.location.href = "/login";
          }}
        >
          Logout
        </button>
      </div>
    </nav>
  );
};

export default TopNav;


