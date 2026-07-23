/**
 * Shared utility functions.
 */

/** Format bytes to a human-readable string (e.g. "1.2 MB"). */
export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

/** Truncate a commit SHA to 8 chars. */
export function shortSha(sha: string): string {
  return sha.slice(0, 8);
}

/** Return a relative time string like "3 minutes ago". */
export function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

/** Map a clone_status value to a Tailwind colour class. */
export function statusColor(status: string): string {
  switch (status) {
    case "READY":    return "text-emerald-400";
    case "CLONING":  return "text-yellow-400";
    case "PENDING":  return "text-blue-400";
    case "SYNCING":  return "text-sky-400";
    case "FAILED":   return "text-red-400";
    default:         return "text-gray-400";
  }
}

/** Map a clone_status to a dot-badge colour class. */
export function statusDotColor(status: string): string {
  switch (status) {
    case "READY":    return "bg-emerald-400";
    case "CLONING":  return "bg-yellow-400 animate-pulse";
    case "PENDING":  return "bg-blue-400 animate-pulse";
    case "SYNCING":  return "bg-sky-400 animate-pulse";
    case "FAILED":   return "bg-red-400";
    default:         return "bg-gray-500";
  }
}

/** Map a programming language name to a colour hex for charts. */
export function languageColor(language: string): string {
  const map: Record<string, string> = {
    Python:     "#3b82f6",
    TypeScript: "#06b6d4",
    JavaScript: "#eab308",
    Java:       "#f97316",
    Go:         "#10b981",
    Rust:       "#f43f5e",
    "C++":      "#8b5cf6",
    C:          "#6366f1",
    Ruby:       "#ec4899",
    PHP:        "#a78bfa",
    Kotlin:     "#7c3aed",
    Swift:      "#f59e0b",
    Shell:      "#84cc16",
    HTML:       "#fb923c",
    CSS:        "#38bdf8",
    Markdown:   "#94a3b8",
    JSON:       "#fbbf24",
    YAML:       "#34d399",
    SQL:        "#60a5fa",
    Dockerfile: "#22d3ee",
    Terraform:  "#818cf8",
    Unknown:    "#475569",
  };
  return map[language] ?? "#475569";
}
