// src/components/monitoring/MonitoringGauge.tsx
import React from "react";
import type { ContinuousMonitoringItem } from "../../types/monitoring";

type Props = {
  item: ContinuousMonitoringItem;
  size?: number;
  onClick?: () => void;
};

const clamp = (n: number, min = 0, max = 100) => Math.max(min, Math.min(max, n));

const scoreColor = (score: number): string => {
  const clamped = clamp(score, 0, 100);
  const hue = (clamped / 100) * 120; // 0 = red, 120 = green
  return `hsl(${hue}, 100%, 50%)`;
};

export default function MonitoringGauge({ item, size = 160, onClick }: Props) {
  const hasScan = Boolean(item.last_scanned);

  // Normalize score (we’ll animate this).
  const rawScore = hasScan ? clamp(item.score) : 0;

  const radius = size * 0.36;
  const stroke = size * 0.1;
  const circumference = 2 * Math.PI * radius;

  const [animatedScore, setAnimatedScore] = React.useState<number>(rawScore);
  const previousScoreRef = React.useRef<number>(rawScore);

  // Animate score (and thus arc length) when it changes.
  React.useEffect(() => {
    // If no scans yet, snap back to 0 and skip animation.
    if (!hasScan) {
      previousScoreRef.current = 0;
      setAnimatedScore(0);
      return;
    }

    const startScore = previousScoreRef.current;
    const targetScore = rawScore;

    if (startScore === targetScore) {
      setAnimatedScore(targetScore);
      return;
    }

    previousScoreRef.current = targetScore;

    const durationMs = 600;
    const startTime = performance.now();
    let frameId: number;

    const step = (now: number) => {
      const elapsed = now - startTime;
      const t = Math.min(1, elapsed / durationMs);

      // Ease-out cubic: fast at start, gentle at the end.
      const eased = 1 - Math.pow(1 - t, 3);
      const value = startScore + (targetScore - startScore) * eased;

      setAnimatedScore(value);

      if (t < 1) {
        frameId = requestAnimationFrame(step);
      }
    };

    frameId = requestAnimationFrame(step);
    return () => {
      if (frameId) cancelAnimationFrame(frameId);
    };
  }, [rawScore, hasScan]);

  const arcScore = hasScan ? animatedScore : 0;
  const dash = (arcScore / 100) * circumference;
  const color = scoreColor(arcScore);

  const lastStr = item.last_scanned
    ? new Date(item.last_scanned).toLocaleString()
    : "—";

  const statusLabel = item.monitored ? "MONITORED" : "NOT MONITORED";
  const statusColor = item.monitored ? "#4ade80" : "#ef4444";

  // Footer messaging depending on whether we've ever scanned.
  let footerPrimary: string;
  let footerSecondary: string | null;

  if (hasScan) {
    footerPrimary = `Last scanned: ${lastStr}`;
    footerSecondary = item.monitored
      ? "Enrollment active via scan policy."
      : "Not currently enrolled in a scan policy.";
  } else {
    footerPrimary = "No scans performed for system yet.";
    footerSecondary = item.monitored
      ? "Scan policy is configured. The first run will compute readiness."
      : "Enroll this system in a scan policy to begin monitoring.";
  }

  const handleKeyDown: React.KeyboardEventHandler<HTMLDivElement> = (e) => {
    if (!onClick) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onClick();
    }
  };

  const displayScore = hasScan ? Math.round(arcScore) : 0;

  return (
    <div
      className="monitoring-card"
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : -1}
      onClick={onClick}
      onKeyDown={handleKeyDown}
      aria-label={
        hasScan
          ? `System ${item.system_id}, readiness ${displayScore} percent`
          : `System ${item.system_id}, no scans performed yet`
      }
      style={{
        background: "var(--panel, #0b0c0e)",
        border: "1px solid var(--border-color, #2a2a2a)",
        borderRadius: 12,
        padding: 12,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        width: "100%",
        boxSizing: "border-box",
        cursor: onClick ? "pointer" : "default",
        transition: "transform 120ms ease-out, box-shadow 120ms ease-out",
      }}
    >
      {/* Header row */}
      <div
        style={{
          alignSelf: "stretch",
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <div style={{ fontWeight: 600 }}>System {item.system_id}</div>
        <div
          title={item.monitored ? "Monitored by scan policy" : "Not enrolled in scan policy"}
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <span
            aria-label={item.monitored ? "monitored" : "not monitored"}
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: statusColor,
              boxShadow: `0 0 10px ${statusColor}`,
            }}
          />
          <span style={{ fontSize: 12, color: "#a0a0a0" }}>{statusLabel}</span>
        </div>
      </div>

      {/* Gauge */}
      <svg width={size} height={size}>
        <g transform={`translate(${size / 2}, ${size / 2})`}>
          {/* Background ring */}
          <circle
            r={radius}
            fill="none"
            stroke="rgba(255,255,255,0.08)"
            strokeWidth={stroke}
          />

          {/* Foreground arc (hidden if no scans yet) */}
          {hasScan && dash > 0 && (
            <circle
              r={radius}
              fill="none"
              stroke={color}
              strokeWidth={stroke}
              strokeDasharray={`${dash} ${circumference - dash}`}
              strokeLinecap="round"
              transform="rotate(-90)"
            />
          )}

          {/* Center label */}
          <text
            x="0"
            y="0"
            textAnchor="middle"
            dominantBaseline="central"
            fontSize={size * 0.26}
            fontWeight={700}
            fill={hasScan ? color : "#9ca3af"}
          >
            {hasScan ? displayScore : "—"}
          </text>
        </g>
      </svg>

      {/* Footer text */}
      <div
        style={{
          marginTop: 8,
          fontSize: 12,
          color: "#a0a0a0",
          textAlign: "center",
        }}
      >
        <div>{footerPrimary}</div>
        {footerSecondary && (
          <div style={{ marginTop: 2, fontSize: 11, color: "#6b7280" }}>
            {footerSecondary}
          </div>
        )}
      </div>
    </div>
  );
}

