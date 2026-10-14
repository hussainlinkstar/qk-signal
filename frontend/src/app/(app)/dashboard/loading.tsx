import { SkelCard, SkelPagehead } from "@/components/signal/SignalSkeleton";

export default function DashboardLoading() {
  // Workspace overview shape: a pagehead then the project card grid.
  return (
    <div className="flex flex-col gap-5">
      <SkelPagehead />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <SkelCard />
        <SkelCard />
        <SkelCard />
      </div>
    </div>
  );
}
