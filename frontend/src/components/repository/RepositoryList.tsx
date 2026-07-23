"use client";

/**
 * Polling list of all registered repositories.
 * Auto-refreshes every 4 seconds when any repo is in a transient state.
 */
import { useCallback, useEffect, useState } from "react";
import { type Repository, apiClient, APIError } from "@/lib/api-client";
import { RepositoryCard } from "./RepositoryCard";
import { Spinner } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorMessage } from "@/components/ui/ErrorMessage";

const POLL_MS = 4000;
const TRANSIENT = new Set(["PENDING", "CLONING", "SYNCING"]);

export function RepositoryList() {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try {
      const data = await apiClient.repositories.list();
      setRepos(data.items);
      setError(null);
    } catch (err) {
      setError(err instanceof APIError ? err.message : "Failed to load repositories.");
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => { fetch(); }, [fetch]);

  // Poll while any repo is in a transient state
  useEffect(() => {
    const hasTransient = repos.some((r) => TRANSIENT.has(r.clone_status));
    if (!hasTransient) return;
    const id = setInterval(fetch, POLL_MS);
    return () => clearInterval(id);
  }, [repos, fetch]);

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner size="lg" />
      </div>
    );
  }

  if (error) {
    return <ErrorMessage message={error} onDismiss={() => setError(null)} />;
  }

  if (repos.length === 0) {
    return (
      <EmptyState
        icon="📦"
        title="No repositories yet"
        description="Add a GitHub repository URL above to get started."
      />
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-1 lg:grid-cols-2">
      {repos.map((repo) => (
        <RepositoryCard
          key={repo.id}
          repo={repo}
          onDeleted={fetch}
          onStatusChange={fetch}
        />
      ))}
    </div>
  );
}
