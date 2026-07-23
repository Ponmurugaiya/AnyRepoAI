"use client";

/**
 * Full manifest panel: statistics, language bar, and file tree.
 * Handles loading, empty, and error states internally.
 */
import { useCallback, useEffect, useState } from "react";
import { type RepositoryManifest, apiClient, APIError } from "@/lib/api-client";
import { StatGrid } from "./StatGrid";
import { LanguageBar } from "./LanguageBar";
import { FileTree } from "./FileTree";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { EmptyState } from "@/components/ui/EmptyState";
import { timeAgo } from "@/lib/utils";

interface Props {
  repositoryId: string;
  /** Increment to trigger a refresh from the parent. */
  refreshKey?: number;
}

export function ManifestPanel({ repositoryId, refreshKey = 0 }: Props) {
  const [manifest, setManifest] = useState<RepositoryManifest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.scanner.manifest(repositoryId);
      setManifest(data);
    } catch (err) {
      if (err instanceof APIError && err.status === 404) {
        setManifest(null);
        setError(null);
      } else {
        setError(
          err instanceof APIError ? err.message : "Failed to load manifest.",
        );
      }
    } finally {
      setLoading(false);
    }
  }, [repositoryId]);

  useEffect(() => { load(); }, [load, refreshKey]);

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner size="lg" />
      </div>
    );
  }

  if (error) {
    return <ErrorMessage message={error} onDismiss={() => setError(null)} />;
  }

  if (!manifest || manifest.statistics.total_files === 0) {
    return (
      <EmptyState
        icon="🔍"
        title="No scan data yet"
        description='Click "Scan files" to analyse this repository.'
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-white">Scan manifest</h2>
        <span className="text-xs text-gray-500">
          Scanned {timeAgo(manifest.scanned_at)}
        </span>
      </div>

      {/* Stats grid */}
      <StatGrid stats={manifest.statistics} />

      {/* Language breakdown */}
      {manifest.languages.length > 0 && (
        <section className="rounded-xl border border-gray-800 bg-gray-900 p-5 space-y-3">
          <h3 className="text-sm font-semibold text-white">Language breakdown</h3>
          <LanguageBar languages={manifest.languages} />
        </section>
      )}

      {/* Directory tree */}
      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-white">File tree</h3>
        <FileTree nodes={manifest.directory_tree} />
      </section>
    </div>
  );
}
