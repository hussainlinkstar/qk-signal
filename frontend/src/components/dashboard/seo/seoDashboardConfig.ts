import { Database, Search, Smartphone, Zap, type LucideIcon } from "lucide-react";
import type { ScoreBreakdown } from "@/types/aiStrategist";

export type ScoreCardConfig = {
  key: keyof ScoreBreakdown;
  label: string;
  description: string;
  Icon: LucideIcon;
  metricHints: string[];
};

export const SCORE_CARD_CONFIG: ScoreCardConfig[] = [
  {
    key: "seo",
    label: "SEO Score",
    description: "Overall discoverability and optimization status.",
    Icon: Search,
    metricHints: [
      "On-page signals: title tags, meta descriptions, heading structure.",
      "Content quality and semantic relevance to target queries.",
      "Technical health such as crawlability and internal linking.",
    ],
  },
  {
    key: "speed",
    label: "Speed",
    description: "Page performance and Core Web Vitals quality.",
    Icon: Zap,
    metricHints: [
      "Largest Contentful Paint (LCP) for loading experience.",
      "Cumulative Layout Shift (CLS) for visual stability.",
      "First Input Delay (FID) / interaction responsiveness.",
    ],
  },
  {
    key: "indexing",
    label: "Indexing",
    description: "How well search engines can discover pages.",
    Icon: Database,
    metricHints: [
      "Robots directives and canonical tags consistency.",
      "Sitemap freshness and coverage of important URLs.",
      "Crawl errors and status code quality.",
    ],
  },
  {
    key: "mobile",
    label: "Mobile",
    description: "Mobile usability and responsive readiness.",
    Icon: Smartphone,
    metricHints: [
      "Responsive viewport and layout adaptability.",
      "Tap target sizing and spacing for usability.",
      "Text readability and performance on small screens.",
    ],
  },
];
