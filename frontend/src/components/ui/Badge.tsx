/**
 * Status badge with optional animated dot.
 */
import { statusColor, statusDotColor } from "@/lib/utils";

interface BadgeProps {
  status: string;
  pulse?: boolean;
}

export function StatusBadge({ status }: BadgeProps) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block w-2 h-2 rounded-full ${statusDotColor(status)}`} />
      <span className={`text-xs font-medium uppercase tracking-wide ${statusColor(status)}`}>
        {status}
      </span>
    </span>
  );
}
