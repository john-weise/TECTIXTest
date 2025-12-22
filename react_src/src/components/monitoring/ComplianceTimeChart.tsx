// src/components/monitoring/ComplianceTimeChart.tsx
import React from "react";
import type { CompliancePoint } from "../../types/monitoring";

type Props = {
  points: CompliancePoint[];
  height?: number;
};

type RangeId = "1W" | "1M" | "3M" | "6M" | "1Y" | "ALL";

const DAY_SEC = 24 * 60 * 60;

const RANGES: { id: RangeId; label: string; days: number | null }[] = [
  { id: "1W", label: "1W", days: 7 },
  { id: "1M", label: "1M", days: 30 },
  { id: "3M", label: "3M", days: 90 },
  { id: "6M", label: "6M", days: 180 },
  { id: "1Y", label: "1Y", days: 365 },
  { id: "ALL", label: "ALL", days: null },
];

type SvgPoint = { x: number; y: number; score: number };
type XTick = { x: number; label: string; key: string };

type ChartMemo = {
  windowed: CompliancePoint[];
  pointsForSvg: SvgPoint[];
  linePath: string;
  areaPath: string;
  xTicks: XTick[];
  trendingUp: boolean;
};

export default function ComplianceTimeChart({ points, height = 220 }: Props) {
  const [rangeId, setRangeId] = React.useState<RangeId>("6M");
  const [hoverIdx, setHoverIdx] = React.useState<number | null>(null);

  // Filter + sort points with real scores.
  const scored = React.useMemo(
    () =>
      (points || [])
        .filter((p) => p.score !== null && Number.isFinite(p.score as number))
        .sort((a, b) => a.ts_epoch - b.ts_epoch),
    [points]
  );

  // Gradient id must be created via hook.
  const gradId = React.useMemo(
    () => `compliance-grad-${Math.random().toString(36).slice(2)}`,
    []
  );

  // Reset hover when range or underlying points change.
  React.useEffect(() => {
    setHoverIdx(null);
  }, [rangeId, scored.length]);

  // --- Utility formatters ----------------------------------------------------

  const clampScore = (s: number) => Math.max(0, Math.min(100, s));

  const formatTooltipTs = (iso: string) => {
    try {
      const dt = new Date(iso);
      return dt.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    } catch {
      return iso;
    }
  };

  const formatXAxisLabelForRange = (rid: RangeId, epochSeconds: number) => {
    const dt = new Date(epochSeconds * 1000);
    // Short ranges: show month + day
    if (rid === "1W" || rid === "1M") {
      return dt.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      });
    }
    // Longer ranges: show month only
    return dt.toLocaleDateString(undefined, {
      month: "short",
    });
  };

  // --- Geometry + windowing (range selection) -------------------------------

  const width = 380;
  const paddingLeft = 40;
  const paddingRight = 16;
  const paddingTop = 18;
  const paddingBottom = 28;
  const plotWidth = width - paddingLeft - paddingRight;
  const plotHeight = height - paddingTop - paddingBottom;

  // Compute the active window, SVG points, paths, and X ticks in one memo.
  const chartMemo = React.useMemo<ChartMemo>(() => {
    // No data at all – return safe defaults so rest of component can decide.
    if (scored.length === 0) {
      return {
        windowed: [],
        pointsForSvg: [],
        linePath: "",
        areaPath: "",
        xTicks: [],
        trendingUp: true,
      };
    }

    const earliest = scored[0];
    const latest = scored[scored.length - 1];
    const lastEpoch = latest.ts_epoch;
    const rangeMeta = RANGES.find((r) => r.id === rangeId) ?? RANGES[3];

    // 1) Decide the *display* window for the x-axis
    //    - For fixed ranges: [lastEpoch - rangeDays, lastEpoch]
    //    - For ALL: full history [earliest, latest]
    let displayMinEpoch: number;
    let displayMaxEpoch: number;

    if (rangeMeta.days != null) {
      displayMaxEpoch = lastEpoch;
      displayMinEpoch = lastEpoch - rangeMeta.days * DAY_SEC;
    } else {
      // ALL
      displayMinEpoch = earliest.ts_epoch;
      displayMaxEpoch = lastEpoch;
    }

    // 2) Select which points to actually draw
    let windowedPoints = scored;
    if (rangeMeta.days != null) {
      const cutoff = displayMinEpoch;
      const subset = scored.filter((p) => p.ts_epoch >= cutoff);

      // Smart fallback:
      // - 0 pts: just last point
      // - 1 pt but more history: last 2 pts
      if (subset.length === 0) {
        windowedPoints = [latest];
      } else if (subset.length === 1 && scored.length > 1) {
        windowedPoints = scored.slice(-2);
      } else {
        windowedPoints = subset;
      }
    }

    // 3) Geometry for the selected window.
    const spanX = Math.max(1, displayMaxEpoch - displayMinEpoch);

    const pointsSvg: SvgPoint[] = [];
    let line = "";
    let area = "";

    windowedPoints.forEach((pt, idx) => {
      const tNorm = (pt.ts_epoch - displayMinEpoch) / spanX; // [0, 1] across selected window
      const sNorm = clampScore(pt.score as number) / 100; // [0, 1]

      const x = paddingLeft + tNorm * plotWidth;
      const y = paddingTop + (1 - sNorm) * plotHeight;

      const score = clampScore(pt.score as number);
      pointsSvg.push({ x, y, score });

      if (idx === 0) {
        line = `M ${x} ${y}`;
        area = `M ${x} ${y}`;
      } else {
        line += ` L ${x} ${y}`;
        area += ` L ${x} ${y}`;
      }
    });

    const baselineY = paddingTop + plotHeight;
    if (pointsSvg.length > 1) {
      const last = pointsSvg[pointsSvg.length - 1];
      const first = pointsSvg[0];
      area += ` L ${last.x} ${baselineY} L ${first.x} ${baselineY} Z`;
    }

    // 4) X-axis ticks (different density per range).
    let tickCount: number;
    switch (rangeId) {
      case "1W":
        tickCount = 7; // each day
        break;
      case "1M":
        tickCount = 5; // about weekly
        break;
      case "3M":
        tickCount = 4; // monthly-ish
        break;
      case "6M":
        tickCount = 6; // monthly-ish
        break;
      case "1Y":
        tickCount = 12; // each month
        break;
      case "ALL":
      default: {
        // Dynamic: about 8–12 ticks based on span in months
        const approxMonths = spanX / (30 * DAY_SEC);
        tickCount = Math.round(approxMonths);
        if (!Number.isFinite(tickCount) || tickCount < 2) tickCount = 4;
        tickCount = Math.min(12, Math.max(3, tickCount));
        break;
      }
    }

    const steps = Math.max(2, tickCount);
    const xTicks: XTick[] = [];

    for (let i = 0; i < steps; i += 1) {
      const frac = steps === 1 ? 0 : i / (steps - 1);
      const tEpoch = displayMinEpoch + spanX * frac;
      const tNorm = (tEpoch - displayMinEpoch) / spanX;
      const x = paddingLeft + tNorm * plotWidth;
      const label = formatXAxisLabelForRange(rangeId, tEpoch);
      xTicks.push({
        x,
        label,
        key: `${rangeId}-${tEpoch}-${i}`,
      });
    }

    const firstScore = clampScore(windowedPoints[0].score as number);
    const lastScore = clampScore(
      windowedPoints[windowedPoints.length - 1].score as number
    );

    return {
      windowed: windowedPoints,
      pointsForSvg: pointsSvg,
      linePath: line,
      areaPath: area,
      xTicks,
      trendingUp: lastScore >= firstScore,
    };
  }, [scored, rangeId, paddingLeft, paddingTop, plotWidth, plotHeight]);

  const { windowed, pointsForSvg, linePath, areaPath, xTicks, trendingUp } =
    chartMemo;

  const hasData = windowed.length > 0;

  // If still no data after memo (no runs yet), render empty state.
  if (!hasData) {
    return (
      <div
        style={{
          width: "100%",
          height,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          background:
            "radial-gradient(circle at top, rgba(148,163,184,0.16), transparent 55%)",
          borderRadius: 12,
          border: "1px dashed rgba(148,163,184,0.4)",
          color: "#e5e7eb",
          fontSize: 13,
          boxSizing: "border-box",
          padding: "12px 16px",
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 4 }}>
          No scans performed for this system yet
        </div>
        <div style={{ fontSize: 12, color: "#9ca3af", textAlign: "center" }}>
          As scans complete over time, compliance will be plotted here.
        </div>
      </div>
    );
  }

  // --- Colors based on trend -------------------------------------------------

  const lineColor = trendingUp ? "#22c55e" : "#f97373"; // green / red
  const areaTop = trendingUp ? "rgba(34,197,94,0.16)" : "rgba(248,113,113,0.16)";
  const areaBottom = "rgba(15,23,42,0)";

  // --- Hover handling --------------------------------------------------------

  const activeIdx = hoverIdx ?? windowed.length - 1;
  const activePoint = windowed[activeIdx];
  const activeSvgPoint = pointsForSvg[activeIdx];
  const activeScore = clampScore(activePoint.score as number);
  const activeScoreLabel = `${activeScore}%`;
  const activeTsLabel = formatTooltipTs(activePoint.ts_iso);

  const handleMouseMove = (evt: React.MouseEvent<SVGRectElement, MouseEvent>) => {
    const { left } = evt.currentTarget.getBoundingClientRect();
    const x = evt.clientX - left;

    if (!pointsForSvg.length) return;

    let nearestIdx = 0;
    let nearestDist = Math.abs(pointsForSvg[0].x - x);

    for (let i = 1; i < pointsForSvg.length; i += 1) {
      const d = Math.abs(pointsForSvg[i].x - x);
      if (d < nearestDist) {
        nearestDist = d;
        nearestIdx = i;
      }
    }

    setHoverIdx(nearestIdx);
  };

  const handleMouseLeave = () => {
    setHoverIdx(null);
  };

  // Tooltip positioning (keep it inside plot).
  const tooltip =
    activeSvgPoint && activePoint
      ? (() => {
          const tooltipWidth = 110;
          const tooltipHeight = 32;
          const rawX = activeSvgPoint.x;
          const clampedX = Math.min(
            Math.max(rawX, paddingLeft + tooltipWidth / 2),
            width - paddingRight - tooltipWidth / 2
          );
          const topY = paddingTop - tooltipHeight - 4;

          return {
            groupX: clampedX - tooltipWidth / 2,
            groupY: Math.max(topY, 4),
            width: tooltipWidth,
            height: tooltipHeight,
          };
        })()
      : null;

  return (
    <div
      style={{
        width: "100%",
        height,
        background: "radial-gradient(circle at top, #020617, #020617 55%)",
        borderRadius: 12,
        border: "1px solid rgba(148,163,184,0.35)",
        boxShadow: "0 12px 40px rgba(0,0,0,0.6)",
        padding: "10px 12px 8px 12px",
        boxSizing: "border-box",
        color: "#e5e7eb",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      {/* Header bar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 4,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 13,
              fontWeight: 600,
              letterSpacing: 0.02,
              opacity: 0.9,
            }}
          >
            Compliance Over Time
          </div>
          <div
            style={{
              fontSize: 11,
              color: "#9ca3af",
              marginTop: 2,
            }}
          >
            {hoverIdx !== null ? "Selected score " : "Latest score "}
            <span style={{ color: lineColor, fontWeight: 600 }}>
              {activeScoreLabel}
            </span>
            <span style={{ marginLeft: 6, color: "#6b7280" }}>
              {activeTsLabel}
            </span>
          </div>
        </div>

        {/* Range chips */}
        <div
          style={{
            display: "flex",
            gap: 4,
            fontSize: 10,
            backgroundColor: "rgba(15,23,42,0.9)",
            borderRadius: 999,
            padding: "3px 4px",
          }}
        >
          {RANGES.map((r) => {
            const active = r.id === rangeId;
            return (
              <button
                key={r.id}
                type="button"
                onClick={() => setRangeId(r.id)}
                style={{
                  border: "none",
                  outline: "none",
                  cursor: "pointer",
                  padding: "4px 8px",
                  borderRadius: 999,
                  backgroundColor: active
                    ? "rgba(148,163,184,0.35)"
                    : "transparent",
                  color: active ? "#f9fafb" : "#9ca3af",
                  fontSize: 10,
                  fontWeight: active ? 600 : 500,
                  letterSpacing: 0.04,
                  transition: "background-color 120ms ease-out, color 120ms ease-out",
                }}
              >
                {r.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Chart body */}
      <div style={{ flex: 1, minHeight: 0 }}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="Compliance score over time"
          style={{ width: "100%", height: "100%" }}
        >
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={areaTop} />
              <stop offset="100%" stopColor={areaBottom} />
            </linearGradient>
          </defs>

          {/* Transparent background to catch events */}
          <rect x={0} y={0} width={width} height={height} fill="transparent" />

          {/* Y-axis grid (0 / 50 / 100) */}
          {[0, 50, 100].map((tick) => {
            const y = paddingTop + (1 - tick / 100) * plotHeight;
            return (
              <g key={tick}>
                <line
                  x1={paddingLeft}
                  x2={width - paddingRight}
                  y1={y}
                  y2={y}
                  stroke="rgba(148,163,184,0.18)"
                  strokeWidth={0.75}
                  strokeDasharray="2 4"
                />
                <text
                  x={paddingLeft - 8}
                  y={y + 3}
                  textAnchor="end"
                  fontSize={9}
                  fill="#6b7280"
                >
                  {tick}%
                </text>
              </g>
            );
          })}

          {/* Filled area */}
          {areaPath && <path d={areaPath} fill={`url(#${gradId})`} stroke="none" />}

          {/* Line path */}
          {linePath && (
            <path
              d={linePath}
              fill="none"
              stroke={lineColor}
              strokeWidth={2}
              strokeLinecap="round"
              style={{
                transition: "stroke 180ms ease-out",
              }}
            />
          )}

          {/* Points (small circles) */}
          {pointsForSvg.map((pt, idx) => {
            const isActive = idx === activeIdx;
            return (
              <circle
                key={idx}
                cx={pt.x}
                cy={pt.y}
                r={isActive ? 3.5 : 2}
                fill={isActive ? lineColor : "#f9fafb"}
                stroke="#020617"
                strokeWidth={1}
              />
            );
          })}

          {/* X-axis ticks & labels */}
          {xTicks.map((tick) => (
            <g key={tick.key}>
              {/* small vertical tick at baseline */}
              <line
                x1={tick.x}
                x2={tick.x}
                y1={paddingTop + plotHeight}
                y2={paddingTop + plotHeight + 4}
                stroke="rgba(107,114,128,0.7)"
                strokeWidth={0.75}
              />
              <text
                x={tick.x}
                y={height - 8}
                textAnchor="middle"
                fontSize={9}
                fill="#9ca3af"
              >
                {tick.label}
              </text>
            </g>
          ))}

          {/* Hover vertical line + tooltip (Apple-style) */}
          {activeSvgPoint && (
            <>
              <line
                x1={activeSvgPoint.x}
                x2={activeSvgPoint.x}
                y1={paddingTop}
                y2={paddingTop + plotHeight}
                stroke="rgba(156,163,175,0.6)"
                strokeWidth={0.75}
                strokeDasharray="3 4"
              />

              {tooltip && (
                <g transform={`translate(${tooltip.groupX}, ${tooltip.groupY})`}>
                  <rect
                    width={tooltip.width}
                    height={tooltip.height}
                    rx={6}
                    ry={6}
                    fill="rgba(15,23,42,0.98)"
                    stroke="rgba(148,163,184,0.7)"
                    strokeWidth={0.5}
                  />
                  <text
                    x={tooltip.width / 2}
                    y={13}
                    textAnchor="middle"
                    fontSize={11}
                    fill="#f9fafb"
                  >
                    {activeScoreLabel}
                  </text>
                  <text
                    x={tooltip.width / 2}
                    y={25}
                    textAnchor="middle"
                    fontSize={9}
                    fill="#9ca3af"
                  >
                    {activeTsLabel}
                  </text>
                </g>
              )}
            </>
          )}

          {/* Interaction layer: captures mouse and drives hover state */}
          <rect
            x={paddingLeft}
            y={paddingTop}
            width={plotWidth}
            height={plotHeight}
            fill="transparent"
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
          />
        </svg>
      </div>
    </div>
  );
}

