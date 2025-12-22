// src/components/ClassificationBanner.tsx
import React from "react";
import "../styles/classification-banner.css";

type Level = "UNCLASSIFIED" | "CUI" | "CONFIDENTIAL" | "SECRET" | "TOP SECRET";

interface Props {
  level: Level;
  sticky?: boolean;  // keep ability to pin to top
  dense?: boolean;   // slim by default
  className?: string;
}

const ClassificationBanner: React.FC<Props> = ({
  level,
  sticky = true,
  dense = true,
  className = "",
}) => {
  const cls = [
    "classification-banner",
    `classification-banner--${level.replace(" ", "").toLowerCase()}`,
    sticky ? "classification-banner--sticky" : "",
    dense ? "classification-banner--dense" : "",
    className,
  ].filter(Boolean).join(" ");

  const labelText =
    level === "CUI" ? "PLEX PROPERITARY - NOTIONAL DATA" : level;

  return (
    <div role="banner" aria-label={`${labelText} banner`} className={cls}>
      <div className="classification-banner__inner">
        <strong className="classification-banner__label">{labelText}</strong>
      </div>
    </div>
  );
};

export default ClassificationBanner;


