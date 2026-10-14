import ReportLibraryClient from "./ReportLibraryClient";

// The approved Reports screen is the library (Qiko-Signal-MVP-TBR/mockup/
// Signal Reports.html). The generate journey it opens lives at
// /dashboard/reports/generate, and the project-scoped monthly progress
// reporting route is a different thing and stays where it is.
export default function ReportsPage() {
  return <ReportLibraryClient />;
}
