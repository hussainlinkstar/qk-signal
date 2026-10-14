import { SkelCard, SkelPagehead, SkelRow } from "@/components/signal/SignalSkeleton";

export default function AdminLoading() {
  // Admin list shape: a pagehead then table rows.
  return (
    <div className="flex flex-col gap-5">
      <SkelPagehead />
      <SkelCard />
      <SkelRow />
      <SkelRow />
      <SkelRow />
    </div>
  );
}
