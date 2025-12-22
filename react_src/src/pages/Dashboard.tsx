// src/pages/Dashboard.tsx
import React, { useEffect, useRef, useState } from "react";
import CyberBackground from "../components/CyberBackground";
import TopNav from "../components/TopNav";
import WelcomeModal from "../components/WelcomeModal";
import ChecklistProcessingSpinner from "../components/ChecklistProcessingSpinner";
import TwoFactorEnrollModal from "../components/TwoFactorEnrollModal";
import "../styles/Dashboard.css";
import { useNavigate } from "react-router-dom";

const DEBUG_FORCE_DONE = false;
const REDIRECT_BASE_MS = 60_000; // 1 minute
const REDIRECT_JITTER_MS = 20_000; // +/- 20 seconds

type SessionPayload = {
  authenticated: boolean;
  user?: string;
  is_admin?: boolean;
  is_default_admin?: boolean;
  needs_password_reset?: boolean;
  show_welcome?: boolean;
  twofa_enabled?: boolean; // NEW
};

export default function Dashboard() {
  const [file, setFile] = useState<File | null>(null);
  const [systemId, setSystemId] = useState<string>("");
  const [jobId, setJobId] = useState<string>("");
  const [isAdmin, setIsAdmin] = useState<boolean>(false);

  const [processing, setProcessing] = useState<boolean>(false);
  const [done, setDone] = useState<boolean>(false);
  const [jobCompleted, setJobCompleted] = useState<boolean>(false);
  const [error, setError] = useState<string>("");

  const [sess, setSess] = useState<SessionPayload | null>(null);
  const [showWelcome, setShowWelcome] = useState<boolean>(false);
  const [showTwofaEnroll, setShowTwofaEnroll] = useState<boolean>(false); // NEW

  const pollTimerRef = useRef<number | null>(null);
  const debugTimerRef = useRef<number | null>(null);
  const redirectTimerRef = useRef<number | null>(null);

  const navigate = useNavigate();

  const markCompleteAndScheduleRedirect = React.useCallback(() => {
    if (!jobId) return;

    setJobCompleted(true);
    setDone(true);

    if (redirectTimerRef.current) {
      window.clearTimeout(redirectTimerRef.current);
      redirectTimerRef.current = null;
    }

    const jitter = (Math.random() * 2 - 1) * REDIRECT_JITTER_MS;
    const delay = REDIRECT_BASE_MS + jitter;

    redirectTimerRef.current = window.setTimeout(() => {
      navigate(`/reporting?job_id=${encodeURIComponent(jobId)}`);
    }, delay);
  }, [jobId, navigate]);

  useEffect(() => {
    (window as any).forceDone = () => {
      console.warn(
        "[DEBUG] forceDone() called — marking job complete & scheduling redirect"
      );
      markCompleteAndScheduleRedirect();
    };
  }, [markCompleteAndScheduleRedirect]);

  // Fetch session info
  useEffect(() => {
    fetch("/api/session", { credentials: "include" })
      .then((res) => res.json())
      .then((data: SessionPayload) => {
        setIsAdmin(data?.is_admin ?? false);
        setSess(data || null);

        if (data?.authenticated && data?.show_welcome) {
          // Default admin welcome flow takes precedence.
          setShowWelcome(true);
          setShowTwofaEnroll(false);
        } else if (data?.authenticated && !data?.twofa_enabled) {
          // Non-default account without 2FA – nudge to enroll.
          setShowTwofaEnroll(true);
        }
      })
      .catch((err) => console.error("Session check failed:", err));
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setError("");
    const selected = e.target.files?.[0] || null;
    if (selected && (selected.type === "text/csv" || selected.name.endsWith(".csv"))) {
      setFile(selected);
    } else {
      setFile(null);
      alert("Please select a CSV file.");
    }
  };

  const handleGenerate = () => {
    if (!file || !systemId.trim()) {
      alert("Please provide a System ID and upload a CSV file.");
      return;
    }

    setError("");
    setProcessing(true);
    setDone(false);
    setJobCompleted(false);
    setJobId("");

    if (redirectTimerRef.current) {
      window.clearTimeout(redirectTimerRef.current);
      redirectTimerRef.current = null;
    }

    const form = new FormData();
    form.append("system_id", systemId.trim());
    form.append("data_file", file);

    fetch("/process", {
      method: "POST",
      credentials: "include",
      body: form,
    })
      .then(async (res) => {
        if (!res.ok) {
          let msg = `Server error: ${res.status}`;
          try {
            const data = await res.json();
            if (data.error) msg = data.error;
          } catch {
            // ignore
          }
          throw new Error(msg);
        }
        const data = await res.json();
        if (!data?.job_id) throw new Error("Missing job_id from server");
        setJobId(data.job_id);
      })
      .catch((err) => {
        console.error("Process failed:", err.message);
        setError(err.message);
        setProcessing(false);
      });
  };

  // Poll for job completion while processing
  useEffect(() => {
    const clearPoll = () => {
      if (pollTimerRef.current) {
        window.clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };

    if (processing && jobId) {
      const poll = async () => {
        try {
          const r = await fetch(`/status/${encodeURIComponent(jobId)}`, {
            credentials: "include",
          });
          if (r.ok) {
            const d = await r.json();
            if (d?.done) {
              console.log(
                "[Dashboard] Job reported done; scheduling redirect delay"
              );
              clearPoll();
              markCompleteAndScheduleRedirect();
              return;
            }
          }
        } catch {
          // transient error, keep polling
        }
        if (processing) {
          pollTimerRef.current = window.setTimeout(poll, 2000);
        }
      };
      poll();
      return clearPoll;
    }

    clearPoll();
    return clearPoll;
  }, [processing, jobId, markCompleteAndScheduleRedirect]);

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === "visible" && processing && jobId && !jobCompleted) {
        fetch(`/status/${encodeURIComponent(jobId)}`, { credentials: "include" })
          .then((r) => (r.ok ? r.json() : null))
          .then((d) => {
            if (d?.done) {
              console.log("[Dashboard] Visibility check: job done");
              markCompleteAndScheduleRedirect();
            }
          })
          .catch(() => {});
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [processing, jobId, jobCompleted, markCompleteAndScheduleRedirect]);

  useEffect(() => {
    if (debugTimerRef.current) {
      window.clearTimeout(debugTimerRef.current);
      debugTimerRef.current = null;
    }

    if (DEBUG_FORCE_DONE && processing && jobId && !jobCompleted) {
      console.warn("[DEBUG] Forcing completion in 10 seconds…");
      debugTimerRef.current = window.setTimeout(() => {
        console.warn("[DEBUG] Forced completion fired.");
        markCompleteAndScheduleRedirect();
      }, 10_000);
    }

    return () => {
      if (debugTimerRef.current) {
        window.clearTimeout(debugTimerRef.current);
        debugTimerRef.current = null;
      }
    };
  }, [processing, jobId, jobCompleted, markCompleteAndScheduleRedirect]);

  useEffect(() => {
    return () => {
      if (redirectTimerRef.current) {
        window.clearTimeout(redirectTimerRef.current);
        redirectTimerRef.current = null;
      }
    };
  }, []);

  return (
    <>
      <CyberBackground intensity="quiet" />
      <TopNav isAdmin={isAdmin} />

      <style>{`
        .dashboard-wrapper { padding-top: 78px; }

        .dashboard-main.dashboard-main--single {
          grid-template-columns: minmax(0, 1.4fr);
        }

        .dashboard-main.dashboard-main--with-runner {
          grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
        }

        .engine-runner-shell {
          display: flex;
          align-items: center;
          justify-content: flex-start;
        }

        .engine-runner-shell > * {
          width: 100%;
        }
      `}</style>

      <div className="dashboard-wrapper">
        <div className="dashboard-background-box" aria-hidden="true">
          <div />
        </div>

        <div
          className={`dashboard-main ${
            processing ? "dashboard-main--with-runner" : "dashboard-main--single"
          }`}
        >
          <section className="left-panel" aria-labelledby="mission-title">
            <h2 id="mission-title" className="section-title">
              Mission Checklist Generator
            </h2>
            <div className="gold-rule" aria-hidden="true" />

            <label htmlFor="systemId" className="field-label">
              System ID
            </label>
            <input
              id="systemId"
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              placeholder="Enter System ID (numbers only)"
              className="system-id-input"
              value={systemId}
              onChange={(e) => {
                setError("");
                setSystemId(e.target.value);
              }}
              aria-describedby="systemIdHelp"
              required
            />
            <div id="systemIdHelp" className="helper-text">
              Use the data System Identifier assigned to your system.
            </div>

            <label htmlFor="dataFile" className="field-label" style={{ marginTop: 12 }}>
              Upload data (CSV)
            </label>
            <input
              id="dataFile"
              type="file"
              accept=".csv"
              onChange={handleFileChange}
              className="file-input"
              aria-describedby="fileHelp"
              required
            />
            <div id="fileHelp" className="helper-text">
              CSV export from data required for generation.
            </div>

            {file && <div className="file-name">Selected: {file.name}</div>}

            <button
              className="generate-button"
              onClick={handleGenerate}
              disabled={!file || processing}
              aria-busy={processing ? "true" : "false"}
            >
              {processing ? "Processing…" : "Generate Checklist"}
            </button>

            {done && jobId && (
              <a
                href={`/download?job_id=${encodeURIComponent(jobId)}`}
                download
                className="download-button"
              >
                Download Checklist
              </a>
            )}

            {error && (
              <div className="error-text" style={{ marginTop: 12 }}>
                {error}
              </div>
            )}
          </section>

          {processing && (
            <div className="engine-runner-shell" aria-label="Checklist engine status">
              <ChecklistProcessingSpinner jobId={jobId} jobCompleted={jobCompleted} />
            </div>
          )}
        </div>
      </div>

      {/* Welcome modal for default admin */}
      {showWelcome && (
        <WelcomeModal
          username={sess?.user ?? "admin"}
          isDefaultAdmin={!!sess?.is_default_admin}
          needsPasswordReset={!!sess?.needs_password_reset}
          onClose={() => {
            setShowWelcome(false);
          }}
        />
      )}

      {/* 2FA enrollment modal for non-default accounts without 2FA */}
      {showTwofaEnroll && !showWelcome && (
        <TwoFactorEnrollModal
          open={showTwofaEnroll}
          onClose={() => setShowTwofaEnroll(false)}
        />
      )}
    </>
  );
}

