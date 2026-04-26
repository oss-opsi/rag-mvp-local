import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export const DEFAULT_PIPELINE_VERSION = "v3.9.0";

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
        <Badge variant="secondary">Pipeline {v}</Badge>
        <Badge variant="outline">HyDE</Badge>
        <Badge variant="outline">re-pass</Badge>
        <Badge variant="outline">bge-m3</Badge>
        <Badge variant="outline">reranker</Badge>
      </div>
    );
  }
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      <Badge variant="secondary">Pipeline {v}</Badge>
      <Badge variant="outline">HyDE actif</Badge>
      <Badge variant="outline">Re-pass GPT-4o</Badge>
      <Badge variant="outline">bge-m3</Badge>
      <Badge variant="outline">reranker v2-m3</Badge>
      <Badge variant="outline">Chunker v2</Badge>
    </div>
  );
}
