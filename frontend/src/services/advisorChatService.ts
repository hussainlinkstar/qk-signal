import { requestJson } from "@/services/http";

/** A single turn in the advisor-chat transcript sent back to the backend. */
export type AdvisorChatRole = "user" | "assistant";

export type AdvisorChatMessage = {
  role: AdvisorChatRole;
  content: string;
};

export type AdvisorChatRequest = {
  /** The (untrusted) user question — answered closed-world against this audit. */
  message: string;
  /** Prior turns, oldest first, so the backend can keep the thread grounded. */
  history?: AdvisorChatMessage[];
};

export type AdvisorChatResponse = {
  /** The grounded assistant reply (plain text — rendered as React text nodes). */
  reply: string;
  /** Finding/citation ids the reply is grounded on; rendered as small tags. */
  citations: string[];
};

/** A persisted transcript turn returned when hydrating the chat on mount. */
export type AdvisorChatHistoryMessage = {
  role: AdvisorChatRole;
  content: string;
  /** Present on assistant turns the reply was grounded on (may be empty). */
  citations: string[];
};

export type AdvisorChatHistoryResponse = {
  messages: AdvisorChatHistoryMessage[];
};

const advisorChatEndpoint = (auditId: string | number): string =>
  `/api/audits/${auditId}/advisor-chat`;

const advisorChatHistoryEndpoint = (auditId: string | number): string =>
  `/api/audits/${auditId}/advisor-chat/history`;

/**
 * Ask the audit-grounded advisor a question about a specific audit.
 *
 * Proxies to `POST /api/audits/{auditId}/advisor-chat`. The backend gates this
 * on the `has_advisor_recommendations` capability (HTTP 402 when locked) and on
 * audit ownership (HTTP 403). Both surface as an {@link HttpRequestError} whose
 * `status` the caller can branch on.
 */
export async function sendAdvisorChat(
  auditId: string | number,
  payload: AdvisorChatRequest,
  headers: HeadersInit = {}
): Promise<AdvisorChatResponse> {
  return requestJson<AdvisorChatResponse>({
    endpoint: advisorChatEndpoint(auditId),
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to reach the audit advisor.",
  });
}

/**
 * Fetch the persisted advisor-chat transcript for an audit (oldest first).
 *
 * Proxies to `GET /api/audits/{auditId}/advisor-chat/history`. Gated identically
 * to {@link sendAdvisorChat} (402 when locked, 403 for non-owners) — both surface
 * as an {@link HttpRequestError}. Used to hydrate the chat panel on mount so
 * multi-turn context survives a reload.
 */
export async function fetchAdvisorChatHistory(
  auditId: string | number,
  headers: HeadersInit = {}
): Promise<AdvisorChatHistoryResponse> {
  return requestJson<AdvisorChatHistoryResponse>({
    endpoint: advisorChatHistoryEndpoint(auditId),
    method: "GET",
    headers,
    errorMessage: "Unable to load the advisor conversation.",
  });
}
