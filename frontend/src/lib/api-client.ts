/**
 * Typed API client for communicating with the FastAPI backend.
 *
 * All requests go through this module to ensure consistent error handling,
 * base URL resolution, and response envelope unwrapping.
 */

// ── Shared envelope types ──────────────────────────────────────────────────────

export interface ErrorDetail {
  field: string | null;
  message: string;
  code: string;
}

export interface APIResponse<T = unknown> {
  success: boolean;
  data: T | null;
  message: string;
  errors: ErrorDetail[];
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  params?: Record<string, string | number | boolean>;
  body?: unknown;
}

export class APIError extends Error {
  constructor(
    public readonly status: number,
    public readonly response: APIResponse,
  ) {
    super(response.message || `API request failed with status ${status}`);
    this.name = "APIError";
  }
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";
  const { params, body, headers, ...init } = options;

  const qs = params
    ? "?" + new URLSearchParams(
        Object.entries(params).map(([k, v]) => [k, String(v)]),
      ).toString()
    : "";

  const response = await fetch(`${baseUrl}${path}${qs}`, {
    ...init,
    headers: { "Content-Type": "application/json", Accept: "application/json", ...headers },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  const envelope: APIResponse<T> = await response.json();

  if (!envelope.success || !response.ok) {
    throw new APIError(response.status, envelope);
  }

  return envelope.data as T;
}

// ── Domain types ───────────────────────────────────────────────────────────────

export type CloneStatus = "PENDING" | "CLONING" | "READY" | "FAILED" | "SYNCING";

export interface Repository {
  id: string;
  owner: string;
  name: string;
  full_name: string;
  github_url: string;
  default_branch: string | null;
  local_path: string | null;
  current_commit: string | null;
  description: string | null;
  visibility: string | null;
  language: string | null;
  stars: number;
  forks: number;
  clone_status: CloneStatus;
  created_at: string;
  updated_at: string;
  last_synced_at: string | null;
}

export interface RepositoryListResponse {
  items: Repository[];
  total: number;
}

export interface RepositoryCreateResponse {
  id: string;
  status: CloneStatus;
}

export interface LanguageStats {
  language: string;
  file_count: number;
  total_bytes: number;
  percentage: number;
}

export interface ScanStatistics {
  total_files: number;
  scanned_files: number;
  ignored_files: number;
  failed_files: number;
  binary_files: number;
  hidden_files: number;
  total_bytes: number;
  source_files: number;
  documentation_files: number;
  languages_found: string[];
  scan_duration_seconds: number;
}

export interface DirectoryNode {
  name: string;
  path: string;
  is_file: boolean;
  language: string | null;
  size_bytes: number | null;
  children: DirectoryNode[];
}

export interface RepositoryManifest {
  repository_id: string;
  scan_status: string;
  statistics: ScanStatistics;
  languages: LanguageStats[];
  directory_tree: DirectoryNode[];
  scanned_at: string;
}

export interface ScanInitiatedResponse {
  repository_id: string;
  status: string;
  message: string;
}

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

// ── API client ─────────────────────────────────────────────────────────────────

export const apiClient = {
  health: {
    get: (): Promise<HealthStatus> =>
      request<HealthStatus>("/health"),
  },

  repositories: {
    list: (): Promise<RepositoryListResponse> =>
      request<RepositoryListResponse>("/repositories"),

    get: (id: string): Promise<Repository> =>
      request<Repository>(`/repositories/${id}`),

    create: (github_url: string, reclone = false): Promise<RepositoryCreateResponse> =>
      request<RepositoryCreateResponse>("/repositories", {
        method: "POST",
        body: { github_url, reclone },
      }),

    delete: (id: string): Promise<null> =>
      request<null>(`/repositories/${id}`, { method: "DELETE" }),
  },

  scanner: {
    scan: (id: string): Promise<ScanInitiatedResponse> =>
      request<ScanInitiatedResponse>(`/repositories/${id}/scan`, { method: "POST" }),

    manifest: (id: string): Promise<RepositoryManifest> =>
      request<RepositoryManifest>(`/repositories/${id}/manifest`),
  },
} as const;
