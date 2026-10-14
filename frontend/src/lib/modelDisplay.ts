const MODEL_DISPLAY_NAMES: Record<string, string> = {
  "claude-4-6-opus": "Claude Opus 4.6",
  "claude-4-6-sonnet": "Claude Sonnet 4.6",
  "claude-4-5-haiku": "Claude Haiku 4.5",
  "claude-opus-4-6": "Claude Opus 4.6",
  "claude-sonnet-4-6": "Claude Sonnet 4.6",
  "claude-sonnet-4-5": "Claude Sonnet 4.5",
  "claude-haiku-4-5": "Claude Haiku 4.5",
  "gpt-5.4": "GPT-5.4",
  "gpt-5": "GPT-5",
  "gpt-5-mini": "GPT-5 Mini",
  "gpt-5-nano": "GPT-5 Nano",
  "gpt-4o": "GPT-4o",
  "gpt-4o-mini": "GPT-4o Mini",
  "gemini-3-flash": "Gemini 3 Flash",
  "gemini-2.5-flash": "Gemini 2.5 Flash",
  "gemini-2.5-pro": "Gemini 2.5 Pro",
  "gemini-1.5-flash": "Gemini 1.5 Flash",
  "gemini-1.5-pro": "Gemini 1.5 Pro",
};

export function formatAiModelName(model: string | null | undefined): string {
  const normalized = String(model ?? "").trim();
  if (!normalized) {
    return "Unknown";
  }
  return MODEL_DISPLAY_NAMES[normalized] ?? normalized;
}
