import React from "react";

export default function ReadinessGauge({
  score,
  size = 180,
}: {
  score: number;
  size?: number;
}) {
  const s = Math.max(0, Math.min(100, Number.isFinite(score) ? score : 0));
  const stroke = 18;
  const radius = (size - 16) / 2;
  const center = size / 2;
  const circumference = 2 * Math.PI * radius;
  const dash = (s / 100) * circumference;
  const gradId = React.useMemo(() => `grad-${Math.random().toString(36).slice(2)}`, []);

  return (
    <div className="gauge-wrap" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <defs>
          <linearGradient id={gradId} x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#ef4444" />
            <stop offset="50%" stopColor="#f59e0b" />
            <stop offset="100%" stopColor="#22c55e" />
          </linearGradient>
        </defs>

        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.08)"
          strokeWidth={stroke}
        />
        <g transform={`rotate(-90 ${center} ${center})`}>
          <circle
            cx={center}
            cy={center}
            r={radius}
            fill="none"
            stroke={`url(#${gradId})`}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circumference - dash}`}
          />
        </g>
      </svg>
      <div className="gauge-center">
        <div className="gauge-score">{Math.round(s)}%</div>
        <div className="gauge-sub">Readiness</div>
      </div>
    </div>
  );
}
