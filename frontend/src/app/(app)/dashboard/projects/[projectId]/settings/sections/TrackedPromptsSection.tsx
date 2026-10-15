"use client";

import React from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";

import SettingsSection from "./SettingsSection";

/**
 * Section 3. Tracked prompts ship today, so this card points at them instead
 * of claiming they are unbuilt (SIGV2-1114).
 *
 * The card used to render a SOON treatment saying "Choosing your own questions
 * is not built yet". Both halves of that were false: the Prompts tab of the
 * AIO detail page (`ai-answers/page.tsx`, tab id `prompts`) renders the
 * tracked-prompt table from the visibility summary feed, and
 * `VisibilityQueryManager` on the monitoring page creates, edits and deletes
 * the customer's own prompts. The `?tab=` parameter on the AIO detail page
 * makes the Prompts tab directly linkable.
 */
export default function TrackedPromptsSection({
  projectId,
  /**
   * SIGV2-1039: the approved Product Settings tab puts "Tracked prompts"
   * inside the Tracked-competitors card as a second heading, not in a card of
   * its own, so `bare` drops the card shell and renders the inner heading
   * instead. The standalone card is kept for any other caller.
   */
  bare = false,
}: {
  projectId: string;
  bare?: boolean;
}) {
  const { t } = useTranslation();

  const body = (
    <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border-0 bg-[#EEF1F6] px-[18px] py-4">
      <p className="m-0 max-w-[62ch] text-[12.5px] leading-[1.5] text-(--t-3)">
        {t("signalProjectSettings.prompts.liveNote")}
      </p>
      <Link
        href={`/dashboard/projects/${projectId}/ai-answers?tab=prompts`}
        className="inline-flex h-8 flex-none items-center rounded-full border-0 bg-[#EEF1F6] px-[15px] text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] max-md:min-h-11"
      >
        {t("signalProjectSettings.prompts.viewAction")}
      </Link>
    </div>
  );

  if (bare) {
    return (
      <div id="prompts" className="mt-5">
        <h3 className="m-0 font-(family-name:--disp) text-[14.5px] font-bold tracking-[-0.01em]">
          {t("signalProjectSettings.prompts.heading")}
        </h3>
        <p className="mt-1 mb-4 text-[12.5px] leading-[1.5] text-(--t-3)">
          {t("signalProjectSettings.prompts.description")}
        </p>
        {body}
      </div>
    );
  }

  return (
    <SettingsSection
      id="prompts"
      title={t("signalProjectSettings.prompts.heading")}
      description={t("signalProjectSettings.prompts.description")}
    >
      {body}
    </SettingsSection>
  );
}
