/**
 * Grid of key scan statistics.
 */
import { type ScanStatistics } from "@/lib/api-client";
import { formatBytes } from "@/lib/utils";

interface Props {
  stats: ScanStatistics;
}

export function StatGrid({ stats }: Props) {
  const items = [
    { label: "Total files",     value: stats.total_files.toLocaleString(),     icon: "📄" },
    { label: "Source files",    value: stats.source_files.toLocaleString(),    icon: "💻" },
    { label: "Docs",            value: stats.documentation_files.toLocaleString(), icon: "📖" },
    { label: "Ignored",         value: stats.ignored_files.toLocaleString(),   icon: "🚫" },
    { label: "Binary",          value: stats.binary_files.toLocaleString(),    icon: "⚙️" },
    { label: "Hidden",          value: stats.hidden_files.toLocaleString(),    icon: "👁" },
    { label: "Total size",      value: formatBytes(stats.total_bytes),         icon: "💾" },
    { label: "Scan time",       value: `${stats.scan_duration_seconds.toFixed(2)}s`, icon: "⏱" },
  ];

  return (
    <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {items.map((item) => (
        <div
          key={item.label}
          className="rounded-lg border border-gray-800 bg-gray-900 px-4 py-3 space-y-1"
        >
          <dt className="text-xs text-gray-500 flex items-center gap-1.5">
            <span aria-hidden="true">{item.icon}</span>
            {item.label}
          </dt>
          <dd className="text-lg font-semibold text-white">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
