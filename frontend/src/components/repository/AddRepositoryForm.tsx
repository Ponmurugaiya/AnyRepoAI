"use client";

/**
 * Form for registering a new GitHub repository.
 * Validates the URL client-side before sending to the API.
 */
import { useState, useTransition } from "react";
import { apiClient, APIError } from "@/lib/api-client";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { Spinner } from "@/components/ui/Spinner";

const GITHUB_URL_RE =
  /^https:\/\/github\.com\/[A-Za-z0-9_.\-]+\/[A-Za-z0-9_.\-]+?(\.git)?$/;

interface Props {
  onAdded: () => void;
}

export function AddRepositoryForm({ onAdded }: Props) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const isValid = GITHUB_URL_RE.test(url.trim());

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const trimmed = url.trim();

    if (!trimmed) {
      setError("Please enter a GitHub repository URL.");
      return;
    }

    if (!isValid) {
      setError("Enter a valid GitHub URL, e.g. https://github.com/owner/repo");
      return;
    }

    startTransition(async () => {
      try {
        await apiClient.repositories.create(trimmed);
        setUrl("");
        onAdded();
      } catch (err) {
        if (err instanceof APIError) {
          setError(err.message);
        } else {
          setError("Unexpected error. Is the backend running?");
        }
      }
    });
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3" noValidate>
      <div className="flex gap-2">
        <input
          type="text"
          value={url}
          onChange={(e) => { setUrl(e.target.value); setError(null); }}
          onPaste={(e) => {
            // Let the paste land, then clear any stale error
            setTimeout(() => setError(null), 0);
          }}
          placeholder="https://github.com/owner/repository"
          aria-label="GitHub repository URL"
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          className={[
            "flex-1 rounded-lg border bg-gray-900 px-4 py-2.5 text-sm text-white",
            "placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-brand-500",
            "transition-colors",
            error ? "border-red-600" : "border-gray-700 hover:border-gray-600",
          ].join(" ")}
        />
        <button
          type="submit"
          disabled={isPending}
          className={[
            "inline-flex items-center gap-2 rounded-lg bg-brand-500 px-5 py-2.5",
            "text-sm font-semibold text-white transition-colors",
            "hover:bg-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-500",
            "disabled:opacity-50 disabled:cursor-not-allowed",
          ].join(" ")}
        >
          {isPending && <Spinner size="sm" />}
          {isPending ? "Adding…" : "Add Repository"}
        </button>
      </div>

      {error && (
        <ErrorMessage message={error} onDismiss={() => setError(null)} />
      )}
    </form>
  );
}
