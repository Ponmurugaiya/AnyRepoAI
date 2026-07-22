/**
 * Typed API client for communicating with the FastAPI backend.
 *
 * All requests go through this client to ensure consistent error handling,
 * base URL resolution, and response envelope unwrapping.
 */

/** Structured error detail returned by the backend. */
export interface ErrorDetail {
  field: string | null;
  message: string;
  code: string;
}

/** Unified API response envelope matching the backend APIResponse model. */
export interface APIResponse<T = unknown> {
  success: boolean;
  data: T | null;
  message: string;
  errors: ErrorDetail[];
}

/** Configuration for individual API requests. */
interface RequestOptions extends Omit<RequestInit, "body"> {
  params?: Record<string, string | number | boolean>;
  body?: unknown;
}

/** Error thrown when an API call fails. */
export class APIError extends Error {
  constructor(
    public readonly status: number,
    public readonly response: APIResponse,
  ) {
    super(response.message || `API request failed with status ${status}`);
    this.name = "APIError";
  }
}

/**
 * Low-level fetch wrapper that attaches base URL, serializes JSON,
 * and unwraps the APIResponse envelope.
 *
 * @param path - Path relative to the API base URL (e.g., "/health")
 * @param options - Standard fetch options plus typed body and query params
 * @returns The unwrapped `data` payload from the response envelope
 * @throws APIError when the response envelope indicates failure
 */
async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

  const { params, body, headers, ...init } = options;

  // Build query string from params object
  const qs = params
    ? "?" + new URLSearchParams(
        Object.entries(params).map(([k, v]) => [k, String(v)])
      ).toString()
    : "";

  const url = `${baseUrl}${path}${qs}`;

  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  const envelope: APIResponse<T> = await response.json();

  if (!envelope.success || !response.ok) {
    throw new APIError(response.status, envelope);
  }

  return envelope.data as T;
}

/** Platform health status from GET /health. */
export interface HealthStatus {
  status: "healthy" | "degraded";
  version: string;
  environment: string;
  uptime_seconds: number;
  checked_at: string;
  dependencies: {
    postgres: { status: string; error?: string };
    redis: { status: string; error?: string };
    neo4j: { status: string; error?: string };
    qdrant: { status: string; error?: string };
  };
}

/**
 * Typed API client object.
 * Import this anywhere in the frontend to make API calls.
 *
 * @example
 * ```ts
 * import { apiClient } from "@/lib/api-client";
 * const health = await apiClient.health.get();
 * ```
 */
export const apiClient = {
  health: {
    /**
     * Fetch platform health status.
     *
     * @returns HealthStatus with per-dependency statuses.
     */
    get: (): Promise<HealthStatus> => request<HealthStatus>("/health"),
  },
} as const;
