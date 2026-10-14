import SoonSection from "@/components/results/SoonSection";

/**
 * This summary card never had a data source: it was a static blurb with a chip
 * that looked like a status. The real alert rules live in Advanced project
 * controls further down the settings page and are untouched; only this
 * unbuilt summary carries the SOON treatment.
 */
export default function MonitoringSummaryCard() {
  return (
    <section className="rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-5">
      <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[14.5px] font-bold tracking-[-0.01em]">
        Monitoring
      </h3>
      <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)">
        Automated visibility alerts and threshold notifications. Detailed alert rules stay available
        in Advanced project controls below.
      </p>
      <SoonSection
        className="mt-4"
        title="Monitoring summary"
        note="A summary of your alerts is not built yet. It will show up here once it is ready."
      />
    </section>
  );
}
