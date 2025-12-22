// src/components/LoadingScreen.tsx
import React, { useEffect, useState, useRef } from "react";

interface Props {
  jobId: string;
  /** Called when the server signals completion (DONE/SUCCESS) or when user presses Close */
  onDone: () => void;
  maxLines?: number;        // cap (default 200)
  className?: string;       // extra classes for inner log area
}

const THEME = {
  black: "#0B0B0B",
  nearBlack: "rgba(10,11,14,0.88)",
  white: "#FFFFFF",
  gold: "#f15722",
  goldSoft: "#f15722",
  goldGlow: "#f15722",
  green: "#58D68D",               // success indicator
  grayEdge: "#2a2d33",
  panelBorder: "#2a2d33",
  logText: "#E6E6E6",
};

const LoadingScreen: React.FC<Props> = ({
  jobId,
  onDone,
  maxLines = 200,
  className,
}) => {
  const [lines, setLines] = useState<string[]>([]);
  const [completed, setCompleted] = useState(false);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const STORAGE_KEY = `log-${jobId}`;

  // reconnect support
  const reconnectTimerRef = useRef<number | null>(null);
  const backoffMsRef = useRef<number>(1000); // start at 1s, double up to 15s
  const onDoneCalledRef = useRef<boolean>(false);

  // Restore saved lines from sessionStorage
  useEffect(() => {
    if (!jobId) return;
    const cached = sessionStorage.getItem(STORAGE_KEY);
    if (cached) {
      try {
        setLines(JSON.parse(cached));
      } catch {
        setLines(["Running script…"]);
      }
    } else {
      setLines(["Running script…"]);
    }
    // reset completion/connection flags per new job
    setCompleted(false);
    setConnected(false);
    onDoneCalledRef.current = false;
    backoffMsRef.current = 1000;

    // cleanup any pending reconnect timers on job switch
    if (reconnectTimerRef.current) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, [jobId]);

  // Persist lines to sessionStorage
  useEffect(() => {
    if (!jobId) return;
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(lines));
    } catch {
      /* ignore quota errors */
    }
  }, [jobId, lines]);

  // Auto-scroll to bottom when lines update
  useEffect(() => {
    if (scrollerRef.current) {
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
    }
  }, [lines]);

  // Helper to append lines safely
  const pushLines = (incoming: string | string[]) => {
    const parts = (Array.isArray(incoming) ? incoming : [incoming])
      .flatMap((s) => (s ?? "").split("\n"))
      .map((p) => p.trimEnd())
      .filter(Boolean);

    if (!parts.length) return;

    setLines((prev) => {
      const merged = prev.concat(parts);
      return merged.length > maxLines
        ? merged.slice(merged.length - maxLines)
        : merged;
    });
  };

  const finalize = () => {
    if (onDoneCalledRef.current) return;
    onDoneCalledRef.current = true;
    setCompleted(true);
    try {
      esRef.current?.close();
    } catch {}
    esRef.current = null;
    onDone();
  };

  // Bind to SSE stream with auto-reconnect & completion detection
  useEffect(() => {
    if (!jobId) return;

    const open = () => {
      // clear any pending timer
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }

      try {
        // Native EventSource supports withCredentials in modern browsers
        const es = new EventSource(`/stream_output/${encodeURIComponent(jobId)}`, { withCredentials: true } as any);
        esRef.current = es;

        es.onopen = () => {
          setConnected(true);
          // reset backoff on successful connect
          backoffMsRef.current = 1000;
        };

        es.onmessage = (e: MessageEvent) => {
          const data = (e.data || "") as string;

          // Handle completion markers
          if (data === "[DONE]") {
            // Stream completed; finalize immediately
            finalize();
            return;
          }

          // Optional fast-path: consider success marker as completion
          if (data.includes("[SUCCESS] File ready at:")) {
            pushLines(data);
            finalize();
            return;
          }

          // Otherwise, just append logs
          pushLines(data);
        };

        // Server also emits an explicit "done" event
        const doneHandler = () => finalize();
        es.addEventListener("done", doneHandler as EventListener);

        es.onerror = () => {
          setConnected(false);
          // If already completed, no need to reconnect
          if (completed || onDoneCalledRef.current) {
            try { es.close(); } catch {}
            esRef.current = null;
            return;
          }
          // Backoff & reconnect
          const wait = backoffMsRef.current;
          backoffMsRef.current = Math.min(wait * 2, 15000);
          if (reconnectTimerRef.current) {
            window.clearTimeout(reconnectTimerRef.current);
          }
          reconnectTimerRef.current = window.setTimeout(() => {
            open();
          }, wait);
        };

        // Cleanup listener on unmount / job change
        return () => {
          es.removeEventListener("done", doneHandler as EventListener);
        };
      } catch (e) {
        // If constructor throws, schedule a retry
        setConnected(false);
        const wait = backoffMsRef.current;
        backoffMsRef.current = Math.min(wait * 2, 15000);
        reconnectTimerRef.current = window.setTimeout(open, wait);
      }
    };

    open();

    return () => {
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      try {
        esRef.current?.close();
      } catch {}
      esRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]); // backoff & handlers re-bound per new job

  return (
    // Fills parent; make sure parent has position: relative.
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "auto",
        background: "transparent",
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "flex-start",
        padding: "16px",
      }}
    >
      <div
        style={{
          width: "100%",
          background: THEME.nearBlack,
          border: `1px solid ${THEME.panelBorder}`,
          borderRadius: 12,
          overflow: "hidden",
          boxShadow: "0 12px 40px rgba(0,0,0,0.55)",
        }}
      >
        {/* Gold accent bar */}
        <div
          style={{
            height: 6,
            background: `linear-gradient(90deg, rgba(255,199,44,0.35), ${THEME.gold} 35%, rgba(255,199,44,0.35))`,
          }}
        />

        {/* Header / Status Bar */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            justifyContent: "space-between",
            padding: "10px 12px",
            background: completed ? "rgba(60,160,90,0.18)" : THEME.goldSoft,
            borderBottom: `1px solid ${THEME.grayEdge}`,
            color: THEME.white,
            fontFamily:
              "system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif",
            fontSize: 13,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span
              style={{
                display: "inline-block",
                width: 10,
                height: 10,
                borderRadius: "50%",
                background: completed ? THEME.green : THEME.gold,
                boxShadow: completed
                  ? "0 0 10px rgba(88,214,141,0.8)"
                  : `0 0 10px ${THEME.goldGlow}`,
              }}
            />
            <strong>{completed ? "Completed" : "Running…"}</strong>
            <span
              style={{
                marginLeft: 10,
                opacity: 0.8,
                fontFamily:
                  "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
                fontSize: 12,
              }}
              aria-live="polite"
            >
              {connected ? "connected" : "reconnecting…"}
            </span>
          </div>

          <button
            type="button"
            onClick={finalize}
            style={{
              appearance: "none",
              background: THEME.gold,
              color: THEME.black,
              border: "none",
              borderRadius: 8,
              fontWeight: 800,
              padding: "6px 12px",
              cursor: "pointer",
            }}
          >
            Close
          </button>
        </div>

        {/* Scrollable log */}
        <div
          ref={scrollerRef}
          className={className || ""}
          style={{
            maxHeight: "60vh",
            overflowY: "auto",
            whiteSpace: "pre-wrap",
            background: "transparent",
            fontFamily:
              "'Fira Code', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
            fontSize: "14px",
            lineHeight: 1.5,
            color: "#00FF14",
            padding: 12,
          }}
        >
          {lines.map((line, idx) => (
            <div key={idx}>{line}</div>
          ))}

          {/* Cursor only while running */}
          {!completed && (
            <>
              <span
                style={{
                  display: "inline-block",
                  width: 8,
                  height: "1.1em",
                  background: THEME.gold,
                  marginLeft: 4,
                  verticalAlign: "bottom",
                  animation: "blink 1s step-start infinite",
                }}
              />
              <style>{`@keyframes blink { 50% { opacity: 0; } }`}</style>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default LoadingScreen;

