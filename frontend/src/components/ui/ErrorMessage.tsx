/**
 * Inline error message block.
 */
interface ErrorMessageProps {
  message: string;
  onDismiss?: () => void;
}

export function ErrorMessage({ message, onDismiss }: ErrorMessageProps) {
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-lg border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-300"
    >
      <span aria-hidden="true" className="mt-0.5 shrink-0">⚠</span>
      <span className="flex-1">{message}</span>
      {onDismiss && (
        <button
          onClick={onDismiss}
          aria-label="Dismiss error"
          className="shrink-0 text-red-500 hover:text-red-300 transition-colors"
        >
          ✕
        </button>
      )}
    </div>
  );
}
