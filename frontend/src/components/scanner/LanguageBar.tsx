/**
 * Horizontal stacked language bar (like GitHub's).
 * Each segment is colour-coded by language.
 */
import { type LanguageStats } from "@/lib/api-client";
import { languageColor, formatBytes } from "@/lib/utils";

interface Props {
  languages: LanguageStats[];
}

export function LanguageBar({ languages }: Props) {
  if (languages.length === 0) return null;

  // Only show top 8, group rest as "Other"
  const top = languages.slice(0, 8);
  const rest = languages.slice(8);
  const otherBytes = rest.reduce((s, l) => s + l.total_bytes, 0);
  const otherCount = rest.reduce((s, l) => s + l.file_count, 0);
  const otherPct = rest.reduce((s, l) => s + l.percentage, 0);

  const display = rest.length > 0
    ? [...top, { language: "Other", file_count: otherCount, total_bytes: otherBytes, percentage: otherPct }]
    : top;

  return (
    <div className="space-y-3">
      {/* Stacked bar */}
      <div className="flex h-3 w-full overflow-hidden rounded-full gap-px" aria-hidden="true">
        {display.map((l) => (
          <div
            key={l.language}
            style={{ width: `${l.percentage}%`, backgroundColor: languageColor(l.language) }}
            title={`${l.language} ${l.percentage.toFixed(1)}%`}
          />
        ))}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-x-5 gap-y-2">
        {display.map((l) => (
          <div key={l.language} className="flex items-center gap-1.5 text-xs text-gray-400">
            <span
              className="inline-block w-2.5 h-2.5 rounded-sm flex-shrink-0"
              style={{ backgroundColor: languageColor(l.language) }}
              aria-hidden="true"
            />
            <span className="text-gray-200 font-medium">{l.language}</span>
            <span>{l.percentage.toFixed(1)}%</span>
            <span className="text-gray-600">·</span>
            <span>{l.file_count.toLocaleString()} files</span>
          </div>
        ))}
      </div>
    </div>
  );
}
