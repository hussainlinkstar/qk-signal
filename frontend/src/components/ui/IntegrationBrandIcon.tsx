import React from "react";

import BrandMark, { type BrandMarkId } from "@/components/ui/BrandMark";

export type IntegrationBrand = Extract<BrandMarkId, "google" | "bing" | "jira" | "slack" | "teams">;

type Props = {
  provider: IntegrationBrand;
  className?: string;
};

export default function IntegrationBrandIcon({ provider, className }: Props) {
  return <BrandMark brand={provider} className={className} />;
}
