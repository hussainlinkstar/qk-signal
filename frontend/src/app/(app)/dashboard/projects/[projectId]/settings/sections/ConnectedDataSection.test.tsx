import type { AnchorHTMLAttributes } from "react";
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ConnectedDataSection, {
  DATA_SOURCE_ORDER,
  type ConnectedDataSectionProps,
  type ProjectDataSourceCatalogState,
  type ProjectDataSourceDraft,
} from "./ConnectedDataSection";
import type { ProjectDataSourceType } from "@/services/workspaceService";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const emptyDraft: ProjectDataSourceDraft = {
  bindingMode: "workspace",
  sourceId: "",
  sourceLabel: "",
  isActive: true,
};

const emptyCatalog: ProjectDataSourceCatalogState = {
  loading: false,
  error: null,
  items: [],
  requiredScopes: [],
  grantedScopes: [],
  missingScopes: [],
  connectedOnOtherWorkspace: false,
};

const perSource = <T,>(value: T) =>
  Object.fromEntries(DATA_SOURCE_ORDER.map((source) => [source, value])) as Record<
    ProjectDataSourceType,
    T
  >;

const buildProps = (
  overrides: Partial<ConnectedDataSectionProps> = {}
): ConnectedDataSectionProps => ({
  assignments: [],
  drafts: perSource(emptyDraft),
  catalogs: perSource(emptyCatalog),
  activeAction: null,
  interactionDisabled: false,
  message: null,
  onDraftChange: vi.fn(),
  onAccountSelect: vi.fn(),
  onRefresh: vi.fn(),
  onSave: vi.fn(),
  onRemove: vi.fn(),
  magicLinkStatus: null,
  loadingMagicLinkStatus: false,
  magicLinkMessage: null,
  magicLinkUrl: null,
  generatingMagicLink: false,
  onGenerateMagicLink: vi.fn(),
  ...overrides,
});

/**
 * SIGV2-1171. Every outcome of this card - a save that worked, a save that was
 * refused, a catalogue that could not be read, an access link that could not
 * be created - used to be printed into the same 12px `--t-3` grey paragraph
 * with `role="status"`. A refusal was therefore indistinguishable from a
 * confirmation and quiet enough to be read as "nothing happened".
 *
 * The tier is the design's own choice for this, not a compromise: the
 * component sheet says "inline for feedback attached to its cause", and the
 * cause is the Save, Refresh or Remove action one row above.
 */
describe("ConnectedDataSection failure presentation", () => {
  it("announces a refused save as a failure at the action", () => {
    render(
      <ConnectedDataSection
        {...buildProps({
          message: { tone: "danger", text: "Signal could not save this source." },
        })}
      />
    );

    const note = screen.getByRole("alert");
    expect(note).toHaveAttribute("data-signal-inline-note", "danger");
    expect(note).toHaveTextContent("Signal could not save this source.");
    expect(note.className).toContain("text-(--bad)");
  });

  it("keeps a confirmation out of the alert channel", () => {
    render(
      <ConnectedDataSection
        {...buildProps({ message: { tone: "success", text: "Google Analytics saved." } })}
      />
    );

    expect(screen.queryByRole("alert")).toBeNull();
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("data-signal-inline-note", "success");
    expect(status).toHaveTextContent("Google Analytics saved.");
  });

  it("renders nothing at all when there is no outcome to report", () => {
    render(<ConnectedDataSection {...buildProps()} />);

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("announces a refused access link at the access-link button", () => {
    render(
      <ConnectedDataSection
        {...buildProps({
          magicLinkMessage: { tone: "danger", text: "Signal could not create an access link." },
        })}
      />
    );

    const note = screen.getByRole("alert");
    expect(note).toHaveTextContent("Signal could not create an access link.");
    expect(note.parentElement).toContainElement(
      screen.getByRole("button", { name: "Create access link" })
    );
  });

  it("marks a scope or catalogue failure as a failure on the row it belongs to", () => {
    render(
      <ConnectedDataSection
        {...buildProps({
          catalogs: {
            ...perSource(emptyCatalog),
            google_analytics_4: {
              ...emptyCatalog,
              error: "insufficient_scope: analytics.readonly",
              missingScopes: ["https://www.googleapis.com/auth/analytics.readonly"],
            },
          },
          assignments: [
            {
              id: "a1",
              source_type: "google_analytics_4",
              source_id: null,
              source_label: null,
              binding_mode: "workspace",
              is_active: false,
              workspace_provider_connected: true,
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
            } as any,
          ],
        })}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Choose a Google Analytics property" }));

    const note = screen.getByText(/needs permission/).closest("[data-signal-inline-note]");
    expect(note).not.toBeNull();
    expect(note).toHaveAttribute("data-signal-inline-note", "warning");
    expect(note).toHaveAttribute("role", "alert");
  });

  // SIGV2-1207: when the grant lives on another accessible workspace the row
  // must say so instead of the bare "connect first" note that told Khuzaima
  // to repeat a connect he had already done.
  it("names the other workspace when the provider is connected elsewhere", () => {
    render(
      <ConnectedDataSection
        {...buildProps({
          catalogs: {
            ...perSource(emptyCatalog),
            google_analytics_4: {
              ...emptyCatalog,
              error: "workspace_provider_not_connected",
              connectedOnOtherWorkspace: true,
            },
          },
        })}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Connect Google Analytics" }));

    expect(
      screen.getByText(/already connected on another of your workspaces/i)
    ).toBeInTheDocument();
  });

  it("keeps the plain connect-first note when no other workspace holds the grant", () => {
    render(
      <ConnectedDataSection
        {...buildProps({
          catalogs: {
            ...perSource(emptyCatalog),
            google_analytics_4: {
              ...emptyCatalog,
              error: "workspace_provider_not_connected",
            },
          },
        })}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Connect Google Analytics" }));

    expect(screen.getByText(/Connect Google Analytics in Connections first/i)).toBeInTheDocument();
    expect(screen.queryByText(/another of your workspaces/i)).not.toBeInTheDocument();
  });
});
