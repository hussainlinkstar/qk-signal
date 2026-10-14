import { SkelCard, SkelChart, SkelPagehead } from "@/components/signal/SignalSkeleton";

export default function ProjectLoading() {
  // Project overview shape: pagehead, a score/chart card, then fix rows.
  return (
    <div className="flex flex-col gap-5">
      <SkelPagehead />
      <SkelChart className="h-[220px]" />
      <div className="grid gap-4 md:grid-cols-2">
        <SkelCard />
        <SkelCard />
      </div>
    </div>
  );
}
