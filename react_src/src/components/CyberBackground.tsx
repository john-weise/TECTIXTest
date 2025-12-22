import React from "react";
import clsx from "clsx";
import "../styles/CyberBackground.css";

type Intensity = "quiet" | "normal" | "bold";

export default function CyberBackground({
  intensity = "quiet",
  className,
}: { intensity?: Intensity; className?: string }) {
  return (
    <div
      aria-hidden
      className={clsx("plex-bg", "plex-bg--mesh", className)}
      data-intensity={intensity}
    />
  );
}
