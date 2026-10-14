"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/auth/custom-auth";

interface UseAdminFetchOptions<T> {
  endpoint: string;
  errorMessage?: string;
  retries?: number;
  retryDelay?: number;
  transform?: (data: unknown) => T;
  enabled?: boolean;
  params?: Record<string, string | number | boolean | undefined>;
}

interface UseAdminFetchResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  retry: () => void;
  isRetrying: boolean;
  refetch: () => void;
}

/**
 * Admin data-fetching hook with retry + exponential backoff.
 *
 * - Auto-fetches on mount when `enabled` (default: true)
 * - 2 retries with exponential backoff (1s, 2s), no retry on 401/403
 * - AbortController cancels in-flight requests on unmount
 * - Returns `retry()` for manual retry button
 */
export function useAdminFetch<T = unknown>(
  options: UseAdminFetchOptions<T>
): UseAdminFetchResult<T> {
  const {
    endpoint,
    errorMessage = "Failed to load data.",
    retries = 2,
    retryDelay = 1000,
    transform,
    enabled = true,
    params,
  } = options;

  const { getToken, isSignedIn } = useAuth();
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRetrying, setIsRetrying] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  const doFetch = useCallback(
    async (attempt = 0) => {
      if (!isSignedIn || !enabled) return;

      // Cancel any in-flight request
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      if (attempt === 0) {
        setLoading(true);
        setError(null);
      } else {
        setIsRetrying(true);
      }

      try {
        const token = await getToken();
        if (!token) {
          throw new Error("Authentication required.");
        }

        // Build URL with params
        let url = endpoint.startsWith("/api/")
          ? endpoint
          : `/api/admin/${endpoint.replace(/^\//, "")}`;

        if (params) {
          const searchParams = new URLSearchParams();
          for (const [key, value] of Object.entries(params)) {
            if (value !== undefined && value !== "") {
              searchParams.set(key, String(value));
            }
          }
          const qs = searchParams.toString();
          if (qs) url += `?${qs}`;
        }

        const response = await fetch(url, {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        });

        if (!response.ok) {
          // No retry on auth errors, these are permanent
          if (response.status === 401 || response.status === 403) {
            const msg =
              response.status === 401
                ? "Session expired. Please log in again."
                : "You do not have permission to access this resource.";
            if (mountedRef.current) {
              setError(msg);
              setLoading(false);
              setIsRetrying(false);
            }
            return;
          }

          const payload = await response.json().catch(() => null);
          throw new Error(payload?.detail ?? `Server error (${response.status})`);
        }

        const json = await response.json();
        if (mountedRef.current) {
          setData(transform ? transform(json) : (json as T));
          setError(null);
          setLoading(false);
          setIsRetrying(false);
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return; // Request was cancelled, ignore
        }

        if (!mountedRef.current) return;

        // Retry with exponential backoff
        if (attempt < retries) {
          const delay = retryDelay * Math.pow(2, attempt);
          setTimeout(() => {
            if (mountedRef.current) {
              doFetch(attempt + 1);
            }
          }, delay);
          return;
        }

        // All retries exhausted
        setError(err instanceof Error ? err.message : errorMessage);
        setLoading(false);
        setIsRetrying(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [isSignedIn, enabled, endpoint, JSON.stringify(params)]
  );

  useEffect(() => {
    mountedRef.current = true;
    doFetch();
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  }, [doFetch]);

  const retry = useCallback(() => {
    doFetch(0);
  }, [doFetch]);

  return { data, loading, error, retry, isRetrying, refetch: retry };
}
