export type JsonRequestMethod = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

export class HttpRequestError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "HttpRequestError";
    this.status = status;
  }
}

type ValidationErrorDetail = {
  loc?: unknown;
  msg?: unknown;
};

// FastAPI validation `loc` arrays open with the request part the field came
// from ("body", "query", ...). Those are framework internals, not something a
// customer can act on, so they are stripped before the field name is shown.
const FRAMEWORK_LOC_PREFIXES = new Set(["body", "query", "path", "response", "headers", "cookie"]);

function humanizeValidationField(loc: unknown): string {
  if (!Array.isArray(loc)) {
    return "";
  }

  const parts = loc
    .map((part) => (typeof part === "string" ? part : ""))
    .filter(Boolean)
    .filter((part, index) => !(index === 0 && FRAMEWORK_LOC_PREFIXES.has(part)));

  const last = parts[parts.length - 1]?.replace(/_/g, " ").trim() ?? "";
  return last ? last[0].toUpperCase() + last.slice(1) : "";
}

// Pydantic's default messages describe the schema type, not the action the
// customer should take, so the common shapes are rewritten in plain English.
// Custom validator messages (value_error) are already human-authored and pass
// through unchanged.
const PYDANTIC_MESSAGE_RULES: [RegExp, (match: RegExpMatchArray) => string][] = [
  [
    /^String should have at most (\d+) characters/i,
    (match) => `must be at most ${match[1]} characters`,
  ],
  [
    /^String should have at least (\d+) characters/i,
    (match) => `must be at least ${match[1]} characters`,
  ],
  [/^Input should be (.+)$/i, (match) => `must be ${match[1]}`],
  [/^Field required$/i, () => "is required"],
];

function formatValidationDetail(detail: ValidationErrorDetail): string {
  const field = humanizeValidationField(detail.loc);
  const message = typeof detail.msg === "string" ? detail.msg.trim() : "";

  if (!message) {
    return field ? `${field} is invalid.` : "Validation error";
  }

  for (const [pattern, map] of PYDANTIC_MESSAGE_RULES) {
    const match = message.match(pattern);
    if (match) {
      const mapped = map(match);
      return field ? `${field} ${mapped}.` : `This field ${mapped}.`;
    }
  }

  return message;
}

export const withJsonContentType = (headers: HeadersInit = {}): HeadersInit => {
  const normalized: Record<string, string> = {};

  if (headers instanceof Headers) {
    headers.forEach((value, key) => {
      normalized[key] = value;
    });
  } else if (Array.isArray(headers)) {
    headers.forEach(([key, value]) => {
      normalized[key] = value;
    });
  } else {
    Object.entries(headers).forEach(([key, value]) => {
      if (value !== undefined) {
        normalized[key] = String(value);
      }
    });
  }

  const hasContentType = Object.keys(normalized).some(
    (key) => key.toLowerCase() === "content-type"
  );
  if (!hasContentType) {
    normalized["Content-Type"] = "application/json";
  }
  return normalized;
};

export const parseErrorDetail = async (
  response: Response,
  fallbackMessage: string
): Promise<string> => {
  const payload = (await response.json().catch(() => null)) as {
    detail?: string | ValidationErrorDetail[];
    error?: string;
    message?: string;
  } | null;

  if (typeof payload?.detail === "string" && payload.detail.trim()) {
    return payload.detail;
  }

  if (Array.isArray(payload?.detail)) {
    const formatted = payload.detail
      .map((item) => formatValidationDetail(item))
      .filter(Boolean)
      .join(" | ");

    if (formatted) {
      return formatted;
    }
  }

  if (typeof payload?.error === "string" && payload.error.trim()) {
    return payload.error;
  }

  if (typeof payload?.message === "string" && payload.message.trim()) {
    return payload.message;
  }

  return fallbackMessage;
};

export async function requestJson<T>({
  endpoint,
  method,
  headers = {},
  body,
  errorMessage,
}: {
  endpoint: string;
  method: JsonRequestMethod;
  headers?: HeadersInit;
  body?: unknown;
  errorMessage: string;
}): Promise<T> {
  const response = await fetch(endpoint, {
    method,
    headers: body === undefined ? headers : withJsonContentType(headers),
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    throw new HttpRequestError(response.status, await parseErrorDetail(response, errorMessage));
  }

  if (response.status === 204) {
    return undefined as unknown as T;
  }

  return (await response.json()) as T;
}

export async function requestVoid({
  endpoint,
  method,
  headers = {},
  body,
  errorMessage,
}: {
  endpoint: string;
  method: "POST" | "PATCH" | "PUT" | "DELETE";
  headers?: HeadersInit;
  body?: unknown;
  errorMessage: string;
}): Promise<void> {
  const response = await fetch(endpoint, {
    method,
    headers: body === undefined ? headers : withJsonContentType(headers),
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    throw new HttpRequestError(response.status, await parseErrorDetail(response, errorMessage));
  }
}
