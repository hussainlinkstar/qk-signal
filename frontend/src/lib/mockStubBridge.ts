import { NextResponse } from "next/server";

import { isMockPreviewEnabled } from "@/lib/mockPreviewAuth";

type StubModule = {
  handleStubFetch: (
    requestUrl: string,
    init?: { method?: string; headers?: Record<string, string>; body?: string | null }
  ) => Promise<{ status: number; body: string }>;
};

let stubModulePromise: Promise<StubModule> | null = null;

function loadStubModule(): Promise<StubModule> {
  if (!stubModulePromise) {
    // Static specifier required for Vercel/webpack (dynamic path fails with
    // "Cannot find module as expression is too dynamic").
    stubModulePromise = import("../../e2e/visual/stub-backend.mjs") as Promise<StubModule>;
  }
  return stubModulePromise;
}

/**
 * When MOCK_PREVIEW=1, serve the visual stub in-process (Vercel has no separate
 * BACKEND_URL stub service).
 */
export async function tryMockStubProxy(options: {
  method: string;
  apiPath: string;
  search?: string;
  headers?: Headers | Record<string, string>;
  bodyText?: string | null;
}): Promise<NextResponse | null> {
  if (!isMockPreviewEnabled()) {
    return null;
  }

  const search = options.search && options.search !== "?" ? options.search : "";
  const pathname = options.apiPath.startsWith("/api/v1")
    ? options.apiPath
    : `/api/v1${options.apiPath.startsWith("/") ? "" : "/"}${options.apiPath}`;
  const requestUrl = `${pathname}${search}`;

  const headerBag: Record<string, string> = {};
  if (options.headers instanceof Headers) {
    options.headers.forEach((value, key) => {
      headerBag[key] = value;
    });
  } else if (options.headers) {
    Object.assign(headerBag, options.headers);
  }

  try {
    const stub = await loadStubModule();
    const result = await stub.handleStubFetch(requestUrl, {
      method: options.method,
      headers: headerBag,
      body: options.bodyText ?? null,
    });
    return new NextResponse(result.body, {
      status: result.status,
      headers: { "content-type": "application/json" },
    });
  } catch (error) {
    console.error("mock stub bridge failed", error);
    return NextResponse.json(
      { detail: "Mock stub unavailable", error: error instanceof Error ? error.message : String(error) },
      { status: 502 }
    );
  }
}
