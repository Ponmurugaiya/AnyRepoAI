/**
 * Generic empty-state placeholder.
 */
interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
}

export function EmptyState({ icon = "📂", title, description }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center gap-3">
      <span className="text-5xl" aria-hidden="true">{icon}</span>
      <p className="text-gray-200 font-medium text-lg">{title}</p>
      {description && <p className="text-gray-500 text-sm max-w-xs">{description}</p>}
    </div>
  );
}
