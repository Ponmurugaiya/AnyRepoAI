"use client";

/**
 * Home page — repository dashboard.
 *
 * Shows the URL input for adding repositories and the live list below it.
 * When a new repo is added, the list is refreshed by bumping a key.
 */
import { useState } from "react";
import { AddRepositoryForm } from "@/components/repository/AddRepositoryForm";
import { RepositoryList } from "@/components/repository/RepositoryList";

export default function HomePage() {
  const [listKey, setListKey] = useState(0);

  return (
    <div className="max-w-5xl mx-auto py-10 px-4 space-y-8">

      {/* Hero header */}
      <header className="text-center space-y-2 pointer-events-none select-none">
        <div className="inline-flex items-center justify-center gap-2 mb-1">
          <div
            className="w-9 h-9 rounded-lg bg-brand-500 flex items-center justify-center shrink-0"
          >
            <span className="text-white font-bold text-base">CI</span>
          </div>
          <h1 className="text-2xl font-bold text-white">Codebase Intelligence</h1>
        </div>
        <p className="text-gray-400 text-sm max-w-lg mx-auto">
          Add a GitHub repository URL to clone it, then scan it to explore its
          language breakdown, file tree, and structure metadata.
        </p>
      </header>

      {/* Add repository form */}
      <section className="rounded-xl border border-gray-800 bg-gray-900 p-5 space-y-2">
        <h2 className="text-sm font-semibold text-white">Add repository</h2>
        <AddRepositoryForm onAdded={() => setListKey((k) => k + 1)} />
      </section>

      {/* Repository list */}
      <section className="space-y-4">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
          Repositories
        </h2>
        <RepositoryList key={listKey} />
      </section>

    </div>
  );
}
