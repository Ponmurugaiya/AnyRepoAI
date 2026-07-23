"use client";

/**
 * Repository detail page — /repositories/[id]
 *
 * Shows full clone metadata, status, scan trigger, and manifest panel.
 * Polls for status updates while the repository is in a transient state.
 */
import { useCallback, useEffect, useState, useTransition } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { type Repository, apiClient, APIError } from "@/lib/api-client";
import { StatusBadge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { ManifestPanel } from "@/components/scanner/ManifestPanel";
import { timeAgo, shortSha, formatBytes } from "@/lib/utils";

const TRANSIENT = new Set(["PENDING", "CLONING", "SYNCING"]);
const POLL_MS = 3000;

export default function RepositoryDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [repo, setRepo] = useState<Repository | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [manifestKey, setManifestKey] = useState(0);

  const [isScanning, startScan] = useTransition();
  const [isDeleting, startDelete] = useTransition();

  const loadRepo = useCallback(async () => {
    try {
      const data = await apiClient.repositories.get(id);
      setRepo(data);
      setFetchError(null);
    } catch (err) {
      setFetchError(
        err instanceof APIError && err.status === 404
          ? "Repository not found."
          : "Failed to load repository.",
      );
    } finally {
      setLoading(false);
    }
  }, [id]);

  // Initial load
  useEffect(() => { loadRepo(); }, [loadRepo]);

  // Poll while in a transient state
  useEffect(() => {
    if (!repo || !TRANSIENT.has(repo.clone_status)) return;
    const t = setInterval(loadRepo, POLL_MS);
    return () => clearInterval(t);
  }, [repo, loadRepo]);

  function handleScan() {
    setScanError(null);
    startScan(async () => {
      try {
        await apiClient.scanner.scan(id);
        setManifestKey((k) => k + 1);
      } catch (err) {
        setScanError(err instanceof APIError ? err.message : "Scan failed.");
      }
    });
  }

  function handleDelete() {
    if (!confirm(`Delete ${repo?.full_name}? This cannot be undone.`)) return;
    setDeleteError(null);
    startDelete(async () => {
      try {
        await apiClient.repositories.delete(id);
        router.push("/");
      } catch (err) {
        setDeleteError(err instanceof APIError ? err.message : "Delete failed.");
      }
    });
  }

  // ── Loading state ────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex justify-center py-24">
        <Spinner size="lg" />
      </div>
    );
  }

  if (fetchError) {
    return (
      <div className="max-w-2xl mx-auto py-12 space-y-4">
        <ErrorMessage message={fetchError} />
        <Link href="/" className="text-sm text-brand-500 hover:underline">
          ← Back to repositories
        </Link>
      </div>
    );
  }

  if (!repo) return null;

  const canScan = repo.clone_status === "READY";
  const isActive = TRANSIENT.has(repo.clone_status);

  return (
    <div className="max-w-4xl mx-auto py-8 px-4 space-y-8">

      {/* Breadcrumb */}
      <nav className="text-sm text-gray-500">
        <Link href="/" className="hover:text-gray-300 transition-colors">
          Repositories
        </Link>
        <span className="mx-2">›</span>
        <span className="text-gray-200">{repo.full_name}</span>
      </nav>

      {/* Header card */}
      <section className="rounded-xl border border-gray-800 bg-gray-900 p-6 space-y-5">

        {/* Title + status */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="space-y-1 min-w-0">
            <h1 className="text-xl font-bold text-white break-all">{repo.full_name}</h1>
            {repo.description && (
              <p className="text-sm text-gray-400">{repo.description}</p>
            )}
            <a
              href={repo.github_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-brand-500 hover:underline break-all"
            >
              {repo.github_url} ↗
            </a>
          </div>
          <StatusBadge status={repo.clone_status} />
        </div>

        {/* Active hint */}
        {isActive && (
          <div className="flex items-center gap-2 text-sm text-yellow-400">
            <Spinner size="sm" className="text-yellow-400" />
            <span>
              {repo.clone_status === "CLONING"
                ? "Cloning repository from GitHub…"
                : "Processing…"}
            </span>
          </div>
        )}

        {/* Metadata grid */}
        <dl className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
          {[
            { label: "Owner",          value: repo.owner },
            { label: "Repo name",      value: repo.name },
            { label: "Visibility",     value: repo.visibility ?? "—" },
            { label: "Language",       value: repo.language ?? "—" },
            { label: "Default branch", value: repo.default_branch ?? "—" },
            { label: "Commit",         value: repo.current_commit ? shortSha(repo.current_commit) : "—" },
            { label: "Stars",          value: repo.stars.toLocaleString() },
            { label: "Forks",          value: repo.forks.toLocaleString() },
            { label: "Added",          value: timeAgo(repo.created_at) },
          ].map(({ label, value }) => (
            <div key={label} className="rounded-lg border border-gray-800 bg-gray-950 px-3 py-2.5">
              <dt className="text-xs text-gray-500 mb-0.5">{label}</dt>
              <dd className="font-medium text-gray-100 truncate font-mono text-xs">{value}</dd>
            </div>
          ))}
        </dl>

        {/* Errors */}
        {scanError && <ErrorMessage message={scanError} onDismiss={() => setScanError(null)} />}
        {deleteError && <ErrorMessage message={deleteError} onDismiss={() => setDeleteError(null)} />}

        {/* Actions */}
        <div className="flex flex-wrap gap-2 pt-1">
          {canScan && (
            <button
              onClick={handleScan}
              disabled={isScanning}
              className="inline-flex items-center gap-2 rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-brand-500"
            >
              {isScanning && <Spinner size="sm" />}
              {isScanning ? "Scanning…" : "🔍 Scan files"}
            </button>
          )}
          <button
            onClick={handleDelete}
            disabled={isDeleting}
            className="inline-flex items-center gap-2 rounded-lg border border-red-800 px-4 py-2 text-sm font-medium text-red-400 hover:bg-red-950/50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-red-600"
          >
            {isDeleting && <Spinner size="sm" className="text-red-400" />}
            {isDeleting ? "Deleting…" : "🗑 Delete repository"}
          </button>
        </div>
      </section>

      {/* Manifest panel */}
      {repo.clone_status === "READY" && (
        <section>
          <ManifestPanel repositoryId={id} refreshKey={manifestKey} />
        </section>
      )}
    </div>
  );
}
