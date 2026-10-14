import type {
  LlmCompletionRequest,
  LlmCompletionResponse,
  LlmProvider,
} from "@/services/ai/providers/llmProvider";

const DEFAULT_ENDPOINT = "/api/ai/strategic-insights";

export class HttpLlmProvider implements LlmProvider {
  constructor(private readonly endpoint: string = DEFAULT_ENDPOINT) {}

  async complete(request: LlmCompletionRequest): Promise<LlmCompletionResponse> {
    const response = await fetch(this.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.detail ?? "AI provider request failed.");
    }

    const payload = (await response.json()) as { content?: unknown };

    if (typeof payload.content !== "string") {
      throw new Error("AI provider returned an invalid payload.");
    }

    return { content: payload.content };
  }
}
