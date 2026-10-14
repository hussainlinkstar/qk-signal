import React from "react";
import { SignalLoader } from "./SignalLoader";

export { Skeleton } from "./skeleton";
export { Spinner } from "./spinner";

type SynapseLoaderProps = {
  className?: string;
  /** Primary status text displayed below the animation */
  label?: string;
  /** Optional secondary detail text */
  detail?: string;
};

/**
 * Historically an "Intelligence Engine" neural-network animation; now the
 * single signal-MVP loader (gradient ring + mono caption). The API is kept so
 * existing callers render the on-brand loader without changes.
 */
export function SynapseLoader({ className, label, detail }: SynapseLoaderProps) {
  return <SignalLoader label={label ?? "Processing"} detail={detail} className={className} />;
}
