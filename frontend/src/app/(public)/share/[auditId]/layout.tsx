import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Shared Entity Assessment Report",
  description: "View a shared Qiko Signal assessment report in read-only mode.",
  robots: { index: false, follow: false },
};

export default function SharedAuditLayout({ children }: { children: React.ReactNode }) {
  return children;
}
