import SignalNotFound from "@/components/signal/SignalNotFound";

// A URL that matches no segment lands here, not in (app)'s boundary - so the
// root boundary must render the approved Signal 404 too, otherwise every
// mistyped app URL fell back to the retired marketing design (SIGV2-1189).
export default function NotFound() {
  return <SignalNotFound />;
}
