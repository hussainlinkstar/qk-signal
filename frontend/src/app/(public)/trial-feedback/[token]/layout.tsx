import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Trial Feedback, Qiko Signal",
  description: "Share your feedback about your Qiko Signal trial experience.",
  robots: { index: false, follow: false },
};

export default function TrialFeedbackLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
