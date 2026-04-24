import { cn } from "@/lib/utils";

/**
 * Carte « Infos pipeline » du mockup (Section 7). Affiche les paramètres
 * d'embedding / chunker / reranker de manière compacte, façon fiche technique.
 */
export function PipelineInfoCard({
  className,
  embeddings = "bge-m3",
  dimension = "1024",
  chunker = "sémantique v2",
  reranker = "actif",
}: {
  className?: string;
  embeddings?: string;
  dimension?: string;
  chunker?: string;
  reranker?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-md border border-accent/20 bg-accent/5 p-3 text-xs",
        className,
      )}
    >
      <Row label="Embeddings" value={embeddings} />
      <Row label="Dimension" value={dimension} />
      <Row label="Chunker" value={chunker} />
      <Row
        label="Reranker"
        value={<span className="text-success">{reranker}</span>}
      />
    </div>
  );
}

function Row({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between py-0.5">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-semibold tabular-nums">{value}</span>
    </div>
  );
}
