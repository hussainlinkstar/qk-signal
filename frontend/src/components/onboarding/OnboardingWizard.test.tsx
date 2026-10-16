import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import "@/i18n";
import OnboardingWizard from "@/components/onboarding/OnboardingWizard";

type WizardProps = React.ComponentProps<typeof OnboardingWizard>;

const renderWizard = (overrides: Partial<WizardProps> = {}) =>
  render(
    <OnboardingWizard
      open
      onClose={vi.fn()}
      onDismiss={vi.fn(async () => undefined)}
      onProjectCreated={vi.fn(async () => ({ id: 55 }))}
      onMarkStepComplete={vi.fn(async () => undefined)}
      onLaunchAudit={vi.fn()}
      {...overrides}
    />
  );

const fillStep1 = (domain = "acme.com") => {
  fireEvent.change(screen.getByPlaceholderText("yourdomain.com"), {
    target: { value: domain },
  });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
};

const advanceToStep3 = async () => {
  fillStep1();
  await screen.findByText("Market & reporting language");
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  await screen.findByText("Competitors to track");
};

const addCompetitor = (domain: string) => {
  fireEvent.click(screen.getByRole("button", { name: "Add competitor" }));
  const input = screen.getByPlaceholderText("competitor-domain.com");
  fireEvent.change(input, { target: { value: domain } });
  fireEvent.keyDown(input, { key: "Enter" });
};

/** The shape the HTTP layer throws: a message plus the status that caused it. */
const httpError = (status: number, message: string) =>
  Object.assign(new Error(message), { status });

describe("OnboardingWizard", () => {
  it("renders the approved five-step flow starting at the domain step", () => {
    renderWizard();

    expect(screen.getByText("Set up your first project")).toBeInTheDocument();
    expect(screen.getByText("Step 1 of 5 - the domain to track.")).toBeInTheDocument();
    expect(screen.getByText("The domain to track")).toBeInTheDocument();
    expect(screen.queryByText(/role/i)).not.toBeInTheDocument();
  });

  it("rejects an invalid domain and stays on step 1", () => {
    renderWizard();

    fillStep1("not a domain");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a valid domain");
    expect(screen.getByText("The domain to track")).toBeInTheDocument();
  });

  it("resumes at the persisted step when reopened", () => {
    renderWizard({ initialStep: 3 });

    expect(screen.getByText("Competitors to track")).toBeInTheDocument();
    expect(screen.getByText("Step 3 of 5: Competitors (optional)")).toBeInTheDocument();
    expect(screen.queryByText("The domain to track")).not.toBeInTheDocument();
  });

  it("creates the project from the domain, market and language, then reaches the scan step", async () => {
    const onProjectCreated = vi.fn(async () => ({ id: 55 }));
    const onMarkStepComplete = vi.fn(async () => undefined);
    const onLaunchAudit = vi.fn();
    const onClose = vi.fn();

    renderWizard({ onProjectCreated, onMarkStepComplete, onLaunchAudit, onClose });

    fillStep1("https://www.acme.com/path");
    await screen.findByText("Market & reporting language");

    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Competitors to track");

    expect(onProjectCreated).toHaveBeenCalledWith({
      name: "acme.com",
      domain_url: "acme.com",
      target_country: null,
      language: "en",
    });
    expect(onMarkStepComplete).toHaveBeenCalledWith("first_project");

    // Competitors and GA4 are genuinely optional: Skip / Continue walks past both.
    fireEvent.click(screen.getByRole("button", { name: "Skip / Continue" }));
    await screen.findByText("Connect Google Analytics");
    fireEvent.click(screen.getByRole("button", { name: "Skip / Continue" }));
    await screen.findByText("Your first scan");

    // The Continue action is gone on the last step; the real launch path runs.
    expect(screen.queryByRole("button", { name: "Skip / Continue" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run my first scan" }));
    // SIGV2-1159: the target the wizard collected travels with the launch, so
    // the scan can start without asking for the same details again.
    expect(onLaunchAudit).toHaveBeenCalledWith(55, { url: "acme.com", name: "acme.com" });
    expect(onClose).toHaveBeenCalled();
  });

  it("persists dismissal when the customer skips to the dashboard", async () => {
    const onDismiss = vi.fn(async () => undefined);
    const onClose = vi.fn();

    renderWizard({ initialStep: 5, knownProjectId: 42, onDismiss, onClose });

    fireEvent.click(screen.getByRole("button", { name: "Skip to dashboard" }));

    await waitFor(() => {
      expect(onDismiss).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("dismisses via the set-up-later affordance", async () => {
    const onDismiss = vi.fn(async () => undefined);
    const onClose = vi.fn();

    renderWizard({ onDismiss, onClose });

    fireEvent.click(screen.getByRole("button", { name: /set up later/i }));

    await waitFor(() => {
      expect(onDismiss).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("keeps the entered domain and selections after a failed create", async () => {
    const onProjectCreated = vi.fn(async () => {
      throw new Error("Domain is already tracked by another project.");
    });

    renderWizard({ onProjectCreated });

    fillStep1("acme.com");
    const marketSelect = (await screen.findByDisplayValue("Global")) as HTMLSelectElement;
    fireEvent.change(marketSelect, { target: { value: "US" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Domain is already tracked by another project.");
    // Still on step 2 with every entered value intact.
    expect(screen.getByText("Market & reporting language")).toBeInTheDocument();
    expect(marketSelect.value).toBe("US");

    // Back keeps the domain the user typed.
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect((screen.getByPlaceholderText("yourdomain.com") as HTMLInputElement).value).toBe(
      "acme.com"
    );
  });

  it("issues a single create call for a double submit", async () => {
    let release!: () => void;
    const onProjectCreated = vi.fn(
      () => new Promise<{ id: number }>((resolve) => (release = () => resolve({ id: 55 })))
    );

    renderWizard({ onProjectCreated });

    fillStep1();
    await screen.findByText("Market & reporting language");

    const next = screen.getByRole("button", { name: "Continue" });
    fireEvent.click(next);
    fireEvent.click(next);
    expect(onProjectCreated).toHaveBeenCalledTimes(1);

    release();
    await screen.findByText("Competitors to track");
  });

  it("adds competitors through the chips UI and saves them on Save & continue", async () => {
    const onSaveCompetitor = vi.fn(async () => undefined);

    renderWizard({ onSaveCompetitor });
    await advanceToStep3();

    addCompetitor("rival-one.com");
    addCompetitor("https://rival-two.com/");

    fireEvent.click(screen.getByRole("button", { name: "Save & continue" }));

    await waitFor(() => {
      expect(onSaveCompetitor).toHaveBeenCalledTimes(2);
    });
    expect(onSaveCompetitor).toHaveBeenNthCalledWith(1, 55, "rival-one.com");
    expect(onSaveCompetitor).toHaveBeenNthCalledWith(2, 55, "rival-two.com");
    await screen.findByText("Connect Google Analytics");
  });

  it("keeps a rejected competitor draft and says why", async () => {
    renderWizard({ initialStep: 3 });

    fireEvent.click(screen.getByRole("button", { name: "Add competitor" }));
    const input = screen.getByPlaceholderText("competitor-domain.com");
    fireEvent.change(input, { target: { value: "Nike" } });
    fireEvent.keyDown(input, { key: "Enter" });

    // The text stays in the field and the reason is shown inline.
    expect(input).toHaveValue("Nike");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter a domain, like competitor-domain.com."
    );
    expect(screen.queryByText("nike")).not.toBeInTheDocument();
  });

  it("flags a duplicate competitor instead of dropping it", async () => {
    renderWizard({ initialStep: 3 });

    fireEvent.click(screen.getByRole("button", { name: "Add competitor" }));
    const first = screen.getByPlaceholderText("competitor-domain.com");
    fireEvent.change(first, { target: { value: "rival-one.com" } });
    fireEvent.keyDown(first, { key: "Enter" });

    fireEvent.click(screen.getByRole("button", { name: "Add competitor" }));
    const second = screen.getByPlaceholderText("competitor-domain.com");
    fireEvent.change(second, { target: { value: "https://www.rival-one.com/" } });
    fireEvent.keyDown(second, { key: "Enter" });

    expect(second).toHaveValue("https://www.rival-one.com/");
    expect(screen.getByRole("alert")).toHaveTextContent("rival-one.com is already in the list.");
    // One chip, not two.
    expect(screen.getAllByText("rival-one.com")).toHaveLength(1);
  });

  it("says when the competitor limit is reached", async () => {
    renderWizard({ initialStep: 3 });

    for (const domain of ["a.com", "b.com", "c.com", "d.com", "e.com"]) {
      fireEvent.click(screen.getByRole("button", { name: "Add competitor" }));
      const input = screen.getByPlaceholderText("competitor-domain.com");
      fireEvent.change(input, { target: { value: domain } });
      fireEvent.keyDown(input, { key: "Enter" });
    }
    // The add affordance is gone at the limit rather than failing silently.
    expect(screen.queryByRole("button", { name: "Add competitor" })).not.toBeInTheDocument();
  });

  it("clears the inline reason once the draft becomes valid", async () => {
    renderWizard({ initialStep: 3 });

    fireEvent.click(screen.getByRole("button", { name: "Add competitor" }));
    const input = screen.getByPlaceholderText("competitor-domain.com");
    fireEvent.change(input, { target: { value: "Nike" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a domain");

    fireEvent.change(input, { target: { value: "nike.com" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("nike.com")).toBeInTheDocument();
  });

  it("a Connect GA4 click starts OAuth but never becomes success on its own", async () => {
    const onConnectGa4 = vi.fn();
    const onLoadGa4Status = vi.fn(async () => ({ connected: false, configured: true }));
    const onMarkStepComplete = vi.fn(async () => undefined);

    renderWizard({ onConnectGa4, onLoadGa4Status, onMarkStepComplete, initialStep: 4 });

    expect(onLoadGa4Status).toHaveBeenCalled();
    const connect = await screen.findByRole("button", { name: "Connect GA4" });
    fireEvent.click(connect);

    expect(onConnectGa4).toHaveBeenCalledTimes(1);
    // The click itself is not a connection: the button stays Connect GA4,
    // nothing is marked complete, and no Connected state appears.
    expect(screen.getByRole("button", { name: "Connect GA4" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Connected" })).not.toBeInTheDocument();
    expect(onMarkStepComplete).not.toHaveBeenCalledWith("connect_integration");
  });

  it("reflects a real GA4 connection read back from the connections endpoint", async () => {
    const onLoadGa4Status = vi.fn(async () => ({ connected: true, configured: true }));
    const onMarkStepComplete = vi.fn(async () => undefined);

    renderWizard({ onLoadGa4Status, onMarkStepComplete, initialStep: 4 });

    const connected = await screen.findByRole("button", { name: "Connected" });
    expect(connected).toBeDisabled();
    await waitFor(() => {
      expect(onMarkStepComplete).toHaveBeenCalledWith("connect_integration");
    });
  });

  it("shows an honest not-configured state instead of a dead connect button", async () => {
    const onLoadGa4Status = vi.fn(async () => ({ connected: false, configured: false }));
    const onMarkStepComplete = vi.fn(async () => undefined);

    renderWizard({ onLoadGa4Status, onMarkStepComplete, initialStep: 4 });

    await screen.findByText(/not configured in this environment/);
    expect(screen.queryByRole("button", { name: "Connect GA4" })).not.toBeInTheDocument();
    expect(onMarkStepComplete).not.toHaveBeenCalledWith("connect_integration");
  });

  // -------------------------------------------------------------------------
  // SIGV2-1220: the competitor step had no idea what the customer's plan
  // allows. Starter and Standard could fill the chips in, press the only
  // button there was, and get the backend's raw 402 detail - "Competitive
  // Intelligence is available on Specialist." - presented as a form error,
  // with the wizard stuck on the step.
  // -------------------------------------------------------------------------

  it("tells an ineligible plan that competitors are not included, and offers no chips", async () => {
    const onSaveCompetitor = vi.fn(async () => undefined);

    renderWizard({ initialStep: 3, canTrackCompetitors: false, onSaveCompetitor });

    expect(screen.getByText("Competitor tracking is on Specialist")).toBeInTheDocument();
    expect(screen.getByText(/does not include Competitive Intelligence/)).toBeInTheDocument();
    // Nothing to fill in, so nothing can fail: no chips, no add affordance.
    expect(screen.queryByRole("button", { name: "Add competitor" })).not.toBeInTheDocument();
    expect(onSaveCompetitor).not.toHaveBeenCalled();
  });

  it("skips the competitor step on an ineligible plan without calling the API", async () => {
    const onSaveCompetitor = vi.fn(async () => undefined);

    renderWizard({ initialStep: 3, canTrackCompetitors: false, onSaveCompetitor });

    fireEvent.click(screen.getByRole("button", { name: "Skip / Continue" }));

    await screen.findByText("Connect Google Analytics");
    expect(onSaveCompetitor).not.toHaveBeenCalled();
  });

  it("separates Skip from Save & continue once there is something to save", async () => {
    const onSaveCompetitor = vi.fn(async () => undefined);

    renderWizard({ onSaveCompetitor });
    await advanceToStep3();

    // With nothing entered the step is a plain skip.
    expect(screen.getByRole("button", { name: "Skip / Continue" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save & continue" })).not.toBeInTheDocument();

    addCompetitor("rival-one.com");

    // With entries, saving and skipping are two different requests.
    expect(screen.getByRole("button", { name: "Save & continue" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));

    await screen.findByText("Connect Google Analytics");
    expect(onSaveCompetitor).not.toHaveBeenCalled();
  });

  it("shows the plan notice and keeps everything when saving is refused mid-flow", async () => {
    // The entitlement changed under the customer, or the two surfaces
    // disagree. The raw backend detail is not the message, the project and
    // the entries survive, and Skip still works.
    const onSaveCompetitor = vi.fn(async () => {
      throw httpError(402, "Competitive Intelligence is available on Specialist.");
    });

    renderWizard({ onSaveCompetitor });
    await advanceToStep3();
    addCompetitor("rival-one.com");

    fireEvent.click(screen.getByRole("button", { name: "Save & continue" }));

    expect(await screen.findByText("Competitor tracking is on Specialist")).toBeInTheDocument();
    expect(
      screen.queryByText("Competitive Intelligence is available on Specialist.")
    ).not.toBeInTheDocument();
    // Still on step 3, entry intact.
    expect(screen.getByText("rival-one.com")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Skip / Continue" }));
    await screen.findByText("Connect Google Analytics");
  });

  it("reports a non-plan save failure next to the action and stays put", async () => {
    const onSaveCompetitor = vi.fn(async () => {
      throw httpError(500, "Competitor service is unavailable.");
    });

    renderWizard({ onSaveCompetitor });
    await advanceToStep3();
    addCompetitor("rival-one.com");

    fireEvent.click(screen.getByRole("button", { name: "Save & continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Competitor service is unavailable."
    );
    expect(screen.getByText("Competitors to track")).toBeInTheDocument();
  });

  it("retries only the competitors that are not saved yet", async () => {
    // A partial save used to be unrecoverable: the retry re-posted the
    // competitor that had already landed and the backend answered "Competitor
    // already exists for this project.", so the step could never be passed.
    const onSaveCompetitor = vi.fn(async (_projectId: number, domain: string) => {
      if (domain === "rival-two.com" && onSaveCompetitor.mock.calls.length <= 2) {
        throw httpError(503, "Competitor service is unavailable.");
      }
    });

    renderWizard({ onSaveCompetitor });
    await advanceToStep3();
    addCompetitor("rival-one.com");
    addCompetitor("rival-two.com");

    fireEvent.click(screen.getByRole("button", { name: "Save & continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Competitor service is unavailable."
    );
    expect(onSaveCompetitor).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("button", { name: "Save & continue" }));
    await screen.findByText("Connect Google Analytics");

    // Three calls, not four: rival-one.com was saved and is never re-posted.
    expect(onSaveCompetitor).toHaveBeenCalledTimes(3);
    expect(onSaveCompetitor).toHaveBeenNthCalledWith(3, 55, "rival-two.com");
  });

  // -------------------------------------------------------------------------
  // SIGV2-1220: the GA4 step's connect action leaves the app, so the wizard
  // has to hand over where to come back to, and report what happened on the
  // way back.
  // -------------------------------------------------------------------------

  it("hands the project and step to the connect action so the return can resume", async () => {
    const onConnectGa4 = vi.fn();
    const onLoadGa4Status = vi.fn(async () => ({ connected: false, configured: true }));

    renderWizard({ onConnectGa4, onLoadGa4Status, knownProjectId: 91, initialStep: 4 });

    fireEvent.click(await screen.findByRole("button", { name: "Connect GA4" }));

    expect(onConnectGa4).toHaveBeenCalledWith({ projectId: 91, step: 4 });
  });

  it("keeps progress and offers a retry when the OAuth return reports a failure", async () => {
    const onConnectGa4 = vi.fn();
    const onLoadGa4Status = vi.fn(async () => ({ connected: false, configured: true }));

    renderWizard({
      onConnectGa4,
      onLoadGa4Status,
      initialStep: 4,
      knownProjectId: 91,
      ga4Outcome: { status: "error", message: "access_denied" },
    });

    expect(await screen.findByText(/did not finish connecting/)).toBeInTheDocument();
    expect(screen.getByText(/access_denied/)).toBeInTheDocument();

    // Retry is reachable, and so is skipping on to the scan.
    fireEvent.click(screen.getByRole("button", { name: "Try connecting again" }));
    expect(onConnectGa4).toHaveBeenCalledWith({ projectId: 91, step: 4 });

    fireEvent.click(screen.getByRole("button", { name: "Skip / Continue" }));
    await screen.findByText("Your first scan");
  });

  it("does not claim a connection the connections endpoint has not confirmed", async () => {
    // A success parameter in the URL is not a connection. Only the endpoint's
    // own read is, which is the SIGV2-1202 rule applied to the return.
    const onLoadGa4Status = vi.fn(async () => ({ connected: false, configured: true }));
    const onMarkStepComplete = vi.fn(async () => undefined);

    renderWizard({
      onConnectGa4: vi.fn(),
      onLoadGa4Status,
      onMarkStepComplete,
      initialStep: 4,
      ga4Outcome: { status: "connected", message: null },
    });

    expect(await screen.findByRole("button", { name: "Connect GA4" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Connected" })).not.toBeInTheDocument();
    expect(onMarkStepComplete).not.toHaveBeenCalledWith("connect_integration");
  });

  it("separates a connected account from a chosen Analytics property", async () => {
    const onLoadGa4Status = vi.fn(async () => ({ connected: true, configured: true }));

    renderWizard({ onLoadGa4Status, initialStep: 4 });

    await screen.findByRole("button", { name: "Connected" });
    expect(screen.getByText(/Pick the Analytics property/)).toBeInTheDocument();
  });

  it("falls back to the known project for the first scan when resumed", () => {
    const onLaunchAudit = vi.fn();
    const onClose = vi.fn();

    renderWizard({ initialStep: 5, knownProjectId: 77, onLaunchAudit, onClose });

    fireEvent.click(screen.getByRole("button", { name: "Run my first scan" }));
    // A resumed wizard holds no domain of its own, so it names no target and
    // the caller resolves it from the project it already knows (SIGV2-1159).
    expect(onLaunchAudit).toHaveBeenCalledWith(77, undefined);
  });
});
