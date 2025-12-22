// src/components/ChecklistProcessingSpinner.tsx
import React from "react";

type Props = {
  jobId?: string;
  jobCompleted?: boolean; // still accepted but we don't use it now
};

const FIRST_PHRASE = "Connecting to eMASS";

const PHRASES: string[] = [
  "Scanning system artifacts",
  "Correlating control evidence",
  "Interpolating compliance gaps",
  "Validating Plan of Actions & Milestones",
  "Scoring inherited controls",
  "Reconciling data with ATO baselines",
  "Enumerating residual risks",
  "Normalizing assessment artifacts",
  "Cross-walking controls to frameworks",
  "Aggregating test coverage metrics",
  "Verifying compensating controls",
  "Assessing control maturity levels",
  "Calibrating readiness thresholds",
  "Mapping findings to risk register",
  "Clustering similar observations",
  "Linking tests to security objectives",
  "Reconciling SSP implementation details",
  "Evaluating monitoring effectiveness",
  "Tuning continuous monitoring signals",
  "Stitching evidence timelines together",
  "Checking control inheritance chains",
  "Summarizing assessor observations",
  "Aligning artifacts to schema",
  "Deriving mission impact scores",
  "Synthesizing authorization narrative",
  "Pre-warming reporting dashboards",
  "Extracting metadata from uploaded datasets",
  "Tracing control coverage across subsystems",
  "Ranking findings by mission criticality",
  "Triaging open POA&Ms for impact",
  "Assembling control implementation story",
  "Aligning tests with NIST control families",
  "Reconciling inherited vs. system controls",
  "Flagging evidence gaps for follow-up",
  "Evaluating segregation of duties",
  "Comparing current posture to prior runs",
  "Calculating overall readiness index",
  "Refining risk scenario groupings",
  "Auto-tagging artifacts by control family",
  "Coalescing duplicate assessment findings",
  "Highlighting high-value remediation items",
  "Modeling authorization boundary context",
  "Validating assessment scoping assumptions",
  "Projecting compliance trajectory",
  "Generating assessor briefing notes",
  "Curating content for mission review board",
];

const STATUS_STEPS: string[] = [
  "Initializing engine",
  "Ingesting uploaded data",
  "Running policy checks",
  "Correlating results with control catalog",
  "Building mission checklist view",
  "Finalizing outputs",
];

export default function ChecklistProcessingSpinner({
  jobId,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  jobCompleted: _jobCompleted = false,
}: Props) {
  // Phrase sequencing: special first phrase, then random permutation of the rest.
  const [phraseStep, setPhraseStep] = React.useState<number>(0);
  const phraseOrderRef = React.useRef<number[]>([]);
  const [showInitialPhrase, setShowInitialPhrase] = React.useState<boolean>(true);

  // Status sequencing: simple ordered progression.
  const [statusStep, setStatusStep] = React.useState<number>(0);

  // Hold the "Connecting to eMASS" phrase for 8 seconds.
  React.useEffect(() => {
    const id = window.setTimeout(() => {
      setShowInitialPhrase(false);
    }, 8_000); // 8 seconds

    return () => window.clearTimeout(id);
  }, []);

  // Build a random permutation of phrase indices on mount.
  React.useEffect(() => {
    const indices = PHRASES.map((_, i) => i);

    for (let i = indices.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [indices[i], indices[j]] = [indices[j], indices[i]];
    }

    phraseOrderRef.current = indices;
    setPhraseStep(0);
  }, []);

  // Advance phraseStep at a slower, jittered cadence while there’s still unused phrases.
  // We *don’t* advance while we're still showing the initial eMASS phrase.
  React.useEffect(() => {
    if (showInitialPhrase) return;

    const order = phraseOrderRef.current;
    if (order.length <= 1) return;

    // If we've reached the final phrase in the permutation, stop advancing.
    if (phraseStep >= order.length - 1) return;

    const delay = 3000 + Math.random() * 3000; // 3.0s – 6.0s
    const id = window.setTimeout(() => {
      setPhraseStep((prev) => {
        const next = prev + 1;
        return next >= order.length ? prev : next;
      });
    }, delay);

    return () => window.clearTimeout(id);
  }, [phraseStep, showInitialPhrase]);

  // Advance status step slowly from first to last, independent of backend timing.
  React.useEffect(() => {
    if (statusStep >= STATUS_STEPS.length - 1) return;

    const delay = 5500 + Math.random() * 2500; // ~5.5s–8s per status
    const id = window.setTimeout(() => {
      setStatusStep((prev) =>
        prev >= STATUS_STEPS.length - 1 ? prev : prev + 1
      );
    }, delay);

    return () => window.clearTimeout(id);
  }, [statusStep]);

  let currentPhrase: string;
  if (showInitialPhrase) {
    currentPhrase = FIRST_PHRASE;
  } else {
    const currentPhraseIndex =
      phraseOrderRef.current[phraseStep] ?? phraseOrderRef.current[0] ?? 0;
    currentPhrase = PHRASES[currentPhraseIndex] ?? "";
  }

  const statusLabel =
    STATUS_STEPS[Math.min(statusStep, STATUS_STEPS.length - 1)];

  return (
    <div className="checklist-spinner-root">
      {/* Component-scoped styles */}
      <style>{`
        .checklist-spinner-root {
          width: 100%;
          height: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 10px 4px 4px 4px;
          box-sizing: border-box;
        }

        .checklist-spinner-card {
          width: 100%;
          min-height: 180px;
          border-radius: 14px;
          padding: 18px 20px;
          box-sizing: border-box;
          background: radial-gradient(circle at top, #020617 0, #020617 55%, #020617 100%);
          border: 1px solid rgba(148,163,184,0.35);
          box-shadow: 0 18px 40px rgba(0,0,0,0.7);
          display: flex;
          align-items: center;
          gap: 20px;
        }

        .checklist-spinner-left {
          flex: 0 0 auto;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .pinwheel-shell {
          position: relative;
          width: 86px;
          height: 86px;
          border-radius: 999px;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .pinwheel-ring {
          position: relative;
          width: 86px;
          height: 86px;
          border-radius: 999px;
          background:
            radial-gradient(circle, #020617 58%, transparent 59%),
            conic-gradient(
              from 0deg,
              rgba(31,41,55,0.4) 0deg,
              rgba(31,41,55,0.4) 260deg,
              #f97316 280deg,
              #facc15 320deg,
              rgba(31,41,55,0.4) 360deg
            );
          mask-image: radial-gradient(circle, transparent 0, transparent 52%, #000 54%, #000 100%);
          animation: checklist-spin-ring 1.1s linear infinite;
          box-shadow: 0 0 0 1px rgba(15,23,42,0.9);
        }

        .pinwheel-core {
          position: absolute;
          width: 40px;
          height: 40px;
          border-radius: 999px;
          background: radial-gradient(circle at 30% 30%, #facc15, #f97316 55%, #111827 100%);
          box-shadow:
            0 0 0 1px rgba(15,23,42,0.9),
            0 0 18px rgba(248,113,113,0.35);
        }

        .pinwheel-orbit {
          position: absolute;
          inset: 10px;
          border-radius: 999px;
          border: 1px dashed rgba(148,163,184,0.2);
          box-sizing: border-box;
        }

        @keyframes checklist-spin-ring {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }

        .checklist-spinner-right {
          flex: 1 1 auto;
          display: flex;
          flex-direction: column;
          justify-content: center;
          gap: 6px;
          min-width: 0;
        }

        .spinner-eyebrow {
          font-size: 11px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: #9ca3af;
          margin-bottom: 2px;
        }

        .spinner-title {
          font-size: 18px;
          font-weight: 600;
          line-height: 1.3;
          background-image: linear-gradient(
            120deg,
            #f97316 0%,
            #facc15 20%,
            #f97316 40%,
            #facc15 60%,
            #f97316 80%,
            #facc15 100%
          );
          background-size: 220% auto;
          background-position: 0% 50%;
          -webkit-background-clip: text;
          background-clip: text;
          color: transparent;
          animation: spinner-title-wave 2.4s ease-in-out infinite;
          text-shadow: 0 0 20px rgba(0,0,0,0.8);
          max-width: 460px;
        }

        @keyframes spinner-title-wave {
          0%   { background-position: 0% 50%; }
          50%  { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }

        .spinner-sub {
          font-size: 12px;
          color: #9ca3af;
          max-width: 520px;
        }

        .spinner-sub-strong {
          color: #e5e7eb;
          font-weight: 500;
        }

        .spinner-meta {
          margin-top: 6px;
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          font-size: 11px;
          color: #6b7280;
        }

        .spinner-pill {
          padding: 3px 8px;
          border-radius: 999px;
          background-color: rgba(15,23,42,0.9);
          border: 1px solid rgba(55,65,81,0.9);
        }

        .spinner-pill span {
          color: #e5e7eb;
        }

        @media (max-width: 960px) {
          .checklist-spinner-card {
            flex-direction: column;
            align-items: flex-start;
          }
          .checklist-spinner-left {
            margin-bottom: 4px;
          }
        }
      `}</style>

      <div className="checklist-spinner-card">
        <div className="checklist-spinner-left">
          <div className="pinwheel-shell" aria-hidden="true">
            <div className="pinwheel-ring" />
            <div className="pinwheel-orbit" />
            <div className="pinwheel-core" />
          </div>
        </div>

        <div className="checklist-spinner-right">
          <div className="spinner-eyebrow">Checklist engine running</div>
          <div className="spinner-title">{currentPhrase}</div>

          <div className="spinner-sub">
            <span className="spinner-sub-strong">
              Working through your evidence and control mapping.
            </span>{" "}
            This usually takes around a minute. You can keep working in other
            tabs, your report will open automatically when everything is ready.
          </div>

          <div className="spinner-meta">
            {jobId && (
              <div className="spinner-pill">
                Job ID:&nbsp;<span>{jobId}</span>
              </div>
            )}
            <div className="spinner-pill">
              Status:&nbsp;<span>{statusLabel}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

