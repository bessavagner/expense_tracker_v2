interface EmptyStateProps {
  emoji: string;
  title: string;
  description: string;
  actionHref?: string;
  actionLabel?: string;
}

export default function EmptyState({ emoji, title, description, actionHref, actionLabel }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-8 text-center">
      <span className="text-4xl mb-3">{emoji}</span>
      <p className="font-semibold text-sm text-base-content">{title}</p>
      <p className="text-xs text-base-content/60 mt-1">{description}</p>
      {actionHref && actionLabel && (
        <a href={actionHref} className="btn btn-xs btn-accent mt-3">{actionLabel}</a>
      )}
    </div>
  );
}
