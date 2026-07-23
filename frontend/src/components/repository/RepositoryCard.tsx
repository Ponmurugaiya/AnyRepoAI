"use client";

/**
 * Card for a single repository in the list view.
 * Shows clone status, metadata, and action buttons.
 */
import { useState, useTransition } from "react";
import Link from "next/link";
import { type Repository, apiClient, APIError } from "@/lib/api-client";
import { StatusBadge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { timeAgo, shortSha } from "@/lib/utils";

interface Props {
  repo: Repository;
  onDeleted: () => void;
  onStatusChange: () => void;
}

export function RepositoryCard({ repo, onDeleted, onStatusChange }: Props) {
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [isDeleting, startDelete] = useTransition();
  const [isScanning, startScan] = useTransition();

  function handleDelete() {
    if (!confirm(`Delete ${repo.full_name}? This cannot be undone.`)) return;
    setDeleteError(null);
    startDelete(async () => {
      try {
        await apiClient.repositories.delete(repo.id);
        onDeleted();
      } catch (err) {
        setDeleteError(err instanceof APIError ? err.message : "Delete failed.");
      }
    });
  }

  function handleScan() {
    setScanError(null);
    startScan(async () => {
      try {
        await apiClient.scanner.scan(repo.id);
        onStatusChange();
      } catch (err) {
        setScanError(err instanceof APIError ? err.message : "Scan failed.");
      }
    });
  }

  const canScan = repo.clone_status === "READY";
  const isActive = ["PENDING", "CLONING", "SYNCING"].includes(repo.clone_status);

  return (
    <article className="rounded-xl border border-gray-800 bg-gray-900 p-5 space-y-4 hover:border-gray-700 transition-colors">
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            href={`/repositories/${repo.id}`}
            className="text-base font-semibold text-white hover:text-brand-500 transition-colors truncate block"
          >
            {repo.full_name}
          </Link>
          {repo.description && (
            <p className="text-sm text-gray-400 mt-0.5 line-clamp-2">{repo.description}</p>
          )}
        </div>
        <StatusBadge status={repo.clone_status} />
      </div>

      {/* Metadata row */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
        {repo.language && (
          <span>🔤 {repo.language}</span>
        )}
        {repo.default_branch && (
          <span>🌿 {repo.default_branch}</span>
        )}
        {repo.current_commit && (
          <span className="font-mono">#{shortSha(repo.current_commit)}</span>
        )}
        <span>⭐ {repo.stars.toLocaleString()}</span>
        <span>🍴 {repo.forks.toLocaleString()}</span>
        <span title={new Date(repo.created_at).toLocaleString()}>
          🕑 {timeAgo(repo.created_at)}
        </span>
      </div>

      {/* Active status hint */}
      {isActive && (
        <div className="flex items-center gap-2 text-xs text-yellow-400">
          <Spinner size="sm" className="text-yellow-400" />
          <span>{repo.clone_status === "CLONING" ? "Cloning repository…" : "Processing…"}</span>
        </div>
      )}

      {/* Error hints */}
      {deleteError && <p className="text-xs text-red-400">{deleteError}</p>}
      {scanError && <p className="text-xs text-red-400">{scanError}</p>}

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1">
        <Link
          href={`/repositories/${repo.id}`}
          className="rounded-md border border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-gray-800 transition-colors"
        >
          View details
        </Link>
        {canScan && (
          <button
            onClick={handleScan}
            disabled={isScanning}
            className="inline-flex items-center gap-1.5 rounded-md border border-brand-500/50 px-3 py-1.5 text-xs font-medium text-brand-400 hover:bg-brand-500/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isScanning && <Spinner size="sm" />}
            {isScanning ? "Scanning…" : "Scan files"}
          </button>
        )}
        <button
          onClick={handleDelete}
          disabled={isDeleting}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-red-800/50 px-3 py-1.5 text-xs font-medium text-red-500 hover:bg-red-950/50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isDeleting && <Spinner size="sm" className="text-red-500" />}
          {isDeleting ? "Deleting…" : "Delete"}
        </button>
      </div>
    </article>
  );
}
