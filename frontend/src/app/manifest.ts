import type { MetadataRoute } from "next";

import { BASE_PATH } from "@/lib/basePath";

// PWA manifest generated dynamically so paths honour the configurable app base
// path (NEXT_PUBLIC_BASE_PATH, e.g. /signal) and work at the root as well.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Qiko Signal",
    short_name: "Qiko Signal",
    description: "AI visibility intelligence platform for SEO and AIO teams.",
    start_url: `${BASE_PATH}/dashboard`,
    scope: `${BASE_PATH}/`,
    display: "standalone",
    background_color: "#020617",
    theme_color: "#020617",
    icons: [
      { src: `${BASE_PATH}/icon-192.png`, sizes: "192x192", type: "image/png" },
      { src: `${BASE_PATH}/icon-512.png`, sizes: "512x512", type: "image/png" },
      { src: `${BASE_PATH}/icon.svg`, sizes: "any", type: "image/svg+xml" },
    ],
  };
}
