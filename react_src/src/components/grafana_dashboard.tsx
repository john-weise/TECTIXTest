// src/components/grafana_dashboard.tsx
//
// Thin wrapper component for embedding Grafana inside the TECTIX UI.
//
// Notes
// -----
// - We do NOT talk to Grafana directly via cluster DNS from the browser.
//   The browser only ever sees the same-origin `/grafana/` endpoint.
// - Nginx + Flask handle auth (`auth_request` + /internal/nginx_auth),
//   and Nginx injects X-WEBAUTH-USER for Grafana auth proxy.
// - This component is intentionally dumb: it just iframes `/grafana/`
//   and shows a lightweight loading / error state.
// Single, obvious entrypoint path for Grafana behind the TECTIX gateway.
// Auth is enforced server-side via the user’s existing session cookie.
import React, { useState } from "react";

import "../styles/Dashboard.css";


const GRAFANA_PATH = "/grafana/";
/**
 * Compute the Grafana URL used by the iframe.
 *
 * We avoid env vars and instead derive the URL from the current origin,
 * so this works in dev (127.0.0.1) and in prod (changing domains) without
 * hard-coding any hostnames.
 */
const computeGrafanaUrl = (): string => {
  if (typeof window !== "undefined" && window.location) {
    return `${window.location.origin}${GRAFANA_PATH}`;
  }

  // Fallback for non-browser environments; the iframe will just
  // attempt to load the relative path.
  return GRAFANA_PATH;
};

const GrafanaDashboard: React.FC = () => {
  const [isLoaded, setIsLoaded] = useState(false);
  const [hasError, setHasError] = useState(false);

  const grafanaUrl = computeGrafanaUrl();

  return (
    <div className="grafana-embed-container">
      {/* Loading / error banner */}
      {!isLoaded && !hasError && (
        <div className="grafana-embed-status">
          <span className="grafana-embed-status-text">
            Loading Grafana executive dashboards…
          </span>
        </div>
      )}

      {hasError && (
        <div className="grafana-embed-status grafana-embed-status--error">
          <span className="grafana-embed-status-text">
            Unable to load Grafana. Check your network connection and ensure the
            {` ${GRAFANA_PATH} `}endpoint is reachable through the TECTIX gateway.
          </span>
          <code className="grafana-embed-url">{grafanaUrl}</code>
        </div>
      )}

      {/* Core iframe embed */}
      <iframe
        title="Grafana Executive Dashboards"
        src={grafanaUrl}
        className="grafana-embed-frame"
        onLoad={() => {
          setIsLoaded(true);
          setHasError(false);
        }}
        onError={() => {
          setHasError(true);
        }}
        frameBorder={0}
        // allowFullScreen is recognized by TS as boolean, allow="fullscreen" is the HTML attrib.
        allow="fullscreen"
      />

      {/* Convenience link for people who want a full-tab view */}
      <div className="grafana-embed-footer">
        <a
          href={grafanaUrl}
          target="_blank"
          rel="noreferrer"
          className="grafana-embed-link"
        >
          Open Grafana in a new tab
        </a>
      </div>
    </div>
  );
};

export default GrafanaDashboard;

