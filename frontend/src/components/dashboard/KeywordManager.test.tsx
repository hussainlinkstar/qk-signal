import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import KeywordManager from "@/components/dashboard/KeywordManager";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

// `getToken` must be the same function on every render: the real
// AuthContext memoises it, and the fetch callback depends on it.
const authMock = vi.hoisted(() => ({ getToken: vi.fn(async () => "token") }));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({ getToken: authMock.getToken }),
}));

const KEYWORDS = [
  {
    id: 11,
    keyword: "boutique hotel waterfront",
    search_engine: "google",
    language_code: "en",
    location_code: null,
    is_active: true,
    created_at: "2026-09-01T00:00:00.000Z",
  },
];

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => KEYWORDS }) as unknown as Response)
  );
});

describe("KeywordManager", () => {
  // SIGV2-1145: this widget used to carry a second creation form, on a page
  // the approved MVP does not contain, and the approved "Add keyword" button
  // pointed at it. Creation now lives on the approved Keywords tab; what is
  // left here is management of keywords that already exist.
  it("sends creation to the approved Keywords tab and keeps no add form", async () => {
    render(<KeywordManager projectId={42} />);

    await waitFor(() => expect(screen.getByText("boutique hotel waterfront")).toBeInTheDocument());

    expect(screen.getByRole("link", { name: "Add a keyword" })).toHaveAttribute(
      "href",
      "/dashboard/projects/42/google?tab=keywords"
    );
    expect(screen.queryByPlaceholderText(/Add a keyword to track/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /^Add$/ })).toBeNull();
  });

  // The approved table has no row actions, so removal stays on this page
  // rather than being invented into the design (the SIGV2-1142 call).
  it("keeps removal of an existing keyword reachable", async () => {
    render(<KeywordManager projectId={42} />);

    await waitFor(() => expect(screen.getByText("boutique hotel waterfront")).toBeInTheDocument());

    expect(
      screen.getByRole("button", { name: "Remove keyword boutique hotel waterfront" })
    ).toBeInTheDocument();
    expect(screen.getByText("1 keyword tracked")).toBeInTheDocument();
  });
});
