import type { Metadata } from "next";

export const metadata: Metadata = {
  // Sign-in, registration and password recovery are utility pages: thin, near
  // duplicates of each other, and worthless as search landing pages. Left
  // indexable they compete with the marketing pages that should rank instead.
  // follow stays on, unlike the authenticated app, so crawlers still traverse
  // the links back out to those pages.
  robots: { index: false, follow: true },
};

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return children;
}
