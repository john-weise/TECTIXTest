// src/pages/Login.tsx
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import CyberBackground from "../components/CyberBackground";
import TwoFactorModal from "../components/TwoFactor";
import "../styles/Login.css";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // PLEX Warning Modal state (kept)
  const [bannerOpen, setBannerOpen] = useState(true);
  const [acknowledged, setAcknowledged] = useState(false);

  // 2FA state
  const [twoFactorRequired, setTwoFactorRequired] = useState(false);
  const [twoFactorError, setTwoFactorError] = useState("");
  const [twoFactorLoading, setTwoFactorLoading] = useState(false);

  const navigate = useNavigate();

  const handleAcknowledge = () => {
    setAcknowledged(true);
    setBannerOpen(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setTwoFactorError("");

    // Require acknowledgement before login
    if (!acknowledged) {
      setBannerOpen(true);
      setError("Please acknowledge the PLEX Notice to continue.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username, password }),
      });

      const data = await res.json();

      if (res.ok && data.success) {
        // Full login (no 2FA) – go straight to dashboard.
        window.location.href = "/dashboard";
        return;
      }

      if (res.ok && data.two_factor_required) {
        // Password is correct; 2FA step required.
        setTwoFactorRequired(true);
        setLoading(false);
        return;
      }

      // Any other failure
      setError(data.error || "Invalid username or password.");
      setLoading(false);
    } catch (err) {
      console.error("[Login Error]", err);
      setError("Unable to login. Please try again.");
      setLoading(false);
    }
  };

  const handleTwoFactorSubmit = async (code: string) => {
    setTwoFactorError("");
    setTwoFactorLoading(true);
    try {
      const res = await fetch("/api/login/2fa", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ code }),
      });

      const data = await res.json();

      if (res.ok && data.success) {
        // 2FA complete – now you're logged in.
        window.location.href = "/dashboard";
        return;
      }

      setTwoFactorError(data.error || "Invalid 2FA code.");
      setTwoFactorLoading(false);
    } catch (err) {
      console.error("[2FA Error]", err);
      setTwoFactorError("Unable to verify 2FA. Please try again.");
      setTwoFactorLoading(false);
    }
  };

  const handleTwoFactorClose = () => {
    // Let the user back out of 2FA and try again.
    setTwoFactorRequired(false);
    setTwoFactorError("");
    setTwoFactorLoading(false);
  };

  return (
    <div className="login-wrapper">
      {/* Subtle brand background */}
      <CyberBackground intensity="quiet" />

      {/* PLEX Warning Modal */}
      {bannerOpen && (
        <div
          className="usg-modal-overlay"
          role="dialog"
          aria-modal="true"
          aria-labelledby="usg-title"
        >
          <div className="usg-modal">
            <div className="usg-modal-bar" aria-hidden="true" />
            <h2 id="usg-title" className="usg-title">
              PLEX Information System Notice
            </h2>
            <p className="usg-intro">
              You are accessing a PLEX Information System for authorized use only.
              By using this IS (including any device attached to it), you consent to:
            </p>
            <ul className="usg-list">
              <li>PLEX monitoring, interception, and search for security and compliance purposes.</li>
              <li>Inspection and seizure of data stored on this IS at any time.</li>
              <li>Communications/data on this IS are not private and may be disclosed for authorized PLEX purposes.</li>
              <li>Security measures (e.g., authentication/access controls) protect PLEX interests.</li>
              <li className="usg-small">
                Privileged communications (attorney, psychotherapist, clergy) remain protected as described in the User Agreement.
              </li>
            </ul>
            <div className="usg-actions">
              <button
                type="button"
                className="login-button usg-button"
                onClick={handleAcknowledge}
                autoFocus
                aria-label="Acknowledge PLEX Warning"
              >
                I Acknowledge
              </button>
            </div>
          </div>
        </div>
      )}

      <form className="login-form" onSubmit={handleSubmit} aria-describedby="usg-desc">
        <img src="/logo.png" alt="PLEX Logo" className="login-logo" />

        <h1 className="login-title">TECTIX</h1>
        <p className="login-subtitle">Secure Access Portal</p>

        {error && <div className="login-error">{error}</div>}

        <input
          type="text"
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="login-input"
          required
          autoComplete="username"
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="login-input"
          required
          autoComplete="current-password"
        />

        <button type="submit" className="login-button" disabled={loading}>
          {loading ? "Authenticating..." : "Log In"}
        </button>
      </form>

      {/* 2FA Modal */}
      {twoFactorRequired && (
        <TwoFactorModal
          open={twoFactorRequired}
          loading={twoFactorLoading}
          error={twoFactorError}
          onSubmit={handleTwoFactorSubmit}
          onClose={handleTwoFactorClose}
        />
      )}
    </div>
  );
}

