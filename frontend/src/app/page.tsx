/**
 * Home page — landing/entry point for the Codebase Intelligence Platform.
 *
 * This is a placeholder. The full UI (repository input, analysis dashboard,
 * chat interface) will be built in subsequent milestones.
 */
export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <div className="max-w-2xl w-full text-center space-y-6">
        {/* Logo / wordmark placeholder */}
        <div className="flex items-center justify-center gap-3">
          <div
            className="w-10 h-10 rounded-lg bg-brand-500 flex items-center justify-center"
            aria-hidden="true"
          >
            <span className="text-white font-bold text-lg">CI</span>
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Codebase Intelligence
          </h1>
        </div>

        <p className="text-gray-400 text-lg">
          AI-powered codebase analysis and retrieval. Paste a GitHub repository
          URL to explore code structure, dependencies, and semantics.
        </p>

        {/* Repository URL input — full implementation coming in next milestone */}
        <div className="flex gap-2">
          <input
            type="url"
            placeholder="https://github.com/owner/repository"
            aria-label="GitHub repository URL"
            className={[
              "flex-1 rounded-lg border border-gray-700 bg-gray-900",
              "px-4 py-3 text-white placeholder-gray-500",
              "focus:outline-none focus:ring-2 focus:ring-brand-500",
              "transition-colors",
            ].join(" ")}
            disabled
          />
          <button
            type="button"
            disabled
            className={[
              "rounded-lg bg-brand-500 px-5 py-3 font-semibold text-white",
              "hover:bg-brand-600 disabled:opacity-50 disabled:cursor-not-allowed",
              "transition-colors focus:outline-none focus:ring-2 focus:ring-brand-500",
            ].join(" ")}
            aria-label="Analyze repository"
          >
            Analyze
          </button>
        </div>

        <p className="text-sm text-gray-600">
          Repository analysis coming soon — infrastructure foundation is ready.
        </p>
      </div>
    </main>
  );
}
