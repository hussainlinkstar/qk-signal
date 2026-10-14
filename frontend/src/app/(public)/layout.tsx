import type { Metadata } from "next";

export const metadata: Metadata = {
  // Public app pages (shared audit reports, trial feedback), not marketing.
  // Marketing canonicals, JSON-LD and chrome moved to qiko-website-v2 with
  // WEB-1008; the app host must not assert itself as the marketing home.
  robots: { index: false, follow: true },
};

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return <div className="relative flex min-h-screen flex-col overflow-x-hidden">{children}</div>;
}
