import { cn } from "@/lib/utils";

export const DEFAULT_PIPELINE_VERSION = "v3.9.0";

const PILL_BASE =
  "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium";
const VERSION_PILL = "border-accent/25 bg-accent-soft text-accent";
const FEATURE_PILL = "border-soft bg-card text-muted-foreground";

export function PipelineBadges({
  version,
  className,
  compact = false,
}: {
  version?: string;
  className?: string;
  compact?: boolean;
}) {
  const v = version || DEFAULT_PIPELINE_VERSION;
  if (compact) {
    return (
      <div className={cn("flex flex-wrap items-center gap-1", className)}>
        <span className={cn(PILL_BASE, VERSION_PILL)}>Pipeline {v}</span>
        <span className={cn(PILL_BASE, FEATURE_PILL)}>HyDE</span>
        <span className={cn(PILL_BASE, FEATURE_PILL)}>re-pass</span>
        <span className={cn(PILL_BASE, FEATURE_PILL)}>bge-m3</span>
        <span className={cn(PILL_BASE, FEATURE_PILL)}>reranker</span>
      </div>
    );
  }
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      <span className={cn(PILL_BASE, VERSION_PILL)}>Pipeline {v}</span>
      <span className={cn(PILL_BASE, FEATURE_PILL)}>HyDE actif</span>
      <span className={cn(PILL_BASE, FEATURE_PILL)}>Re-pass GPT-4o</span>
      <span className={cn(PILL_BASE, FEATURE_PILL)}>bge-m3</span>
      <span className={cn(PILL_BASE, FEATURE_PILL)}>reranker v2-m3</span>
      <span className={cn(PILL_BASE, FEATURE_PILL)}>Chunker v2</span>
    </div>
  );
}
