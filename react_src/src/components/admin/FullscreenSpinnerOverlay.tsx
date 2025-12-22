import React from "react";

/** Subtle pinwheel spinner: white arc on grey ring, spinning. */
const Spinner = ({ size = 32 }: { size?: number }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    aria-hidden="true"
    style={{ display: "block" }}
  >
    {/* Grey ring */}
    <circle
      cx="12"
      cy="12"
      r="9"
      stroke="#555"
      strokeWidth="3"
      fill="none"
      opacity={0.6}
    />
    {/* White arc that spins */}
    <path
      d="M12 3 A9 9 0 0 1 21 12"
      stroke="#fff"
      strokeWidth="3"
      strokeLinecap="round"
      fill="none"
    >
      <animateTransform
        attributeName="transform"
        type="rotate"
        from="0 12 12"
        to="360 12 12"
        dur="0.8s"
        repeatCount="indefinite"
      />
    </path>
  </svg>
);

type FullscreenSpinnerOverlayProps = {
  visible: boolean;
  title?: string;
  subtitle?: string;
};

const FullscreenSpinnerOverlay: React.FC<FullscreenSpinnerOverlayProps> = ({
  visible,
  title = "Working…",
  subtitle = "Please wait a moment.",
}) => {
  if (!visible) return null;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.55)",
        backdropFilter: "blur(3px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 9999,
      }}
      aria-label={title}
      aria-busy="true"
    >
      <div
        style={{
          background: "rgba(15, 15, 20, 0.96)",
          borderRadius: 16,
          padding: "20px 24px",
          minWidth: 260,
          maxWidth: 320,
          boxShadow: "0 18px 40px rgba(0,0,0,0.55)",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 12,
          border: "1px solid rgba(255,255,255,0.04)",
        }}
      >
        <Spinner size={36} />
        <div
          style={{
            fontSize: 16,
            fontWeight: 500,
            letterSpacing: 0.4,
          }}
        >
          {title}
        </div>
        {subtitle && (
          <div
            style={{
              fontSize: 12,
              opacity: 0.7,
              textAlign: "center",
            }}
          >
            {subtitle}
          </div>
        )}
      </div>
    </div>
  );
};

export default FullscreenSpinnerOverlay;
