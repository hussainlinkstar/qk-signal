import { asset } from "@/lib/basePath";
import Image from "next/image";

import { cx } from "@/components/ui/utils";

export type BrandLogoId =
  | "google"
  | "google_ai"
  | "google_gemini"
  | "openai"
  | "anthropic"
  | "bing"
  | "perplexity"
  | "xai"
  | "deepseek"
  // `meta`, not `meta_ai`: the measured-engine ids here line up with the
  // backend's visibility provider keys so a provider key can be used as a logo
  // id directly. The asset keeps its `meta-ai.svg` filename, which is the name
  // of the artwork (SIGV2-1163).
  | "meta"
  | "jira"
  | "slack"
  | "teams"
  | "postgresql"
  | "redis"
  | "firecrawl"
  | "stripe";

const BRAND_LOGOS: Record<BrandLogoId, { alt: string; src: string }> = {
  google: { alt: "Google logo", src: "/icons/providers/google.svg" },
  google_ai: { alt: "Google AI logo", src: "/icons/providers/google-ai.svg" },
  google_gemini: { alt: "Google Gemini logo", src: "/icons/providers/google-gemini.svg" },
  openai: { alt: "OpenAI logo", src: "/icons/providers/openai.svg" },
  anthropic: { alt: "Anthropic logo", src: "/icons/providers/anthropic.svg" },
  bing: { alt: "Bing logo", src: "/icons/providers/bing.svg" },
  perplexity: { alt: "Perplexity logo", src: "/icons/providers/perplexity.svg" },
  xai: { alt: "xAI Grok logo", src: "/icons/providers/xai.svg" },
  deepseek: { alt: "DeepSeek logo", src: "/icons/providers/deepseek.svg" },
  meta: { alt: "Meta AI logo", src: "/icons/providers/meta-ai.svg" },
  jira: { alt: "Jira logo", src: "/icons/providers/jira.svg" },
  slack: { alt: "Slack logo", src: "/icons/providers/slack.svg" },
  teams: { alt: "Microsoft Teams logo", src: "/icons/providers/teams.svg" },
  postgresql: { alt: "PostgreSQL logo", src: "/icons/providers/postgresql.svg" },
  redis: { alt: "Redis logo", src: "/icons/providers/redis.svg" },
  firecrawl: { alt: "Firecrawl logo", src: "/icons/providers/firecrawl.svg" },
  stripe: { alt: "Stripe logo", src: "/icons/providers/stripe.svg" },
};

type BrandLogoProps = {
  brand: BrandLogoId;
  className?: string;
  decorative?: boolean;
  imageClassName?: string;
  title?: string;
  variant?: "plain" | "tile";
  width?: number;
  height?: number;
};

export default function BrandLogo({
  brand,
  className,
  decorative = false,
  imageClassName,
  title,
  variant = "plain",
  width = 24,
  height = 24,
}: BrandLogoProps) {
  const logo = BRAND_LOGOS[brand];

  return (
    <span
      className={cx(
        "inline-flex shrink-0 items-center justify-center",
        variant === "tile" &&
          "rounded-lg border border-white/10 bg-white/95 p-1.5 shadow-[0_8px_20px_rgba(0,0,0,0.18)]",
        className
      )}
      title={title}
    >
      <Image
        alt={decorative ? "" : logo.alt}
        aria-hidden={decorative ? true : undefined}
        className={cx("object-contain", imageClassName)}
        height={height}
        src={asset(logo.src)}
        width={width}
      />
    </span>
  );
}
