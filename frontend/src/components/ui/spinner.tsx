import React from "react";
import { SignalLoader } from "./SignalLoader";

type SpinnerProps = {
  className?: string;
  /** Optional text displayed below the spinner */
  label?: string;
  /** Kept for API compatibility; the signal ring is a single size. */
  size?: "sm" | "md" | "lg";
};

function Spinner({ className, label }: SpinnerProps) {
  return <SignalLoader inline label={label ?? "Loading"} className={className} />;
}

export { Spinner };
