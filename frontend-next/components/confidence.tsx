"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export type ConfidenceTier = "high" | "medium" | "low";

export function confidenceTier(value: number): ConfidenceTier {
  if (value >= 0.8) return "high";
  if (value >= 0.5) return "medium";
  return "low";
}

export function confidenceLabel(value: number): string {
  const t = confidenceTier(value);
  if (t === "high") return "Fiabilité élevée";
  if (t === "medium") return "Fiabilité moyenne";
  return "Fiabilité faible";
}

export function confidenceTextClass(value: number): string {
  const t = confidenceTier(value);
  if (t === "high") return "text-success";
  if (t === "medium") return "text-warning";
  return "text-danger";
}

export function confidenceBgClass(value: number): string {
  const t = confidenceTier(value);
  if (t === "high") return "bg-success";
  if (t === "medium") return "bg-warning";
  return "bg-danger";
}

export function confidenceSoftClass(value: number): string {
  const t = confidenceTier(value);
  if (t === "high") return "bg-success/10 text-success";
  if (t === "medium") return "bg-warning/10 text-warning";
  return "bg-danger/10 text-danger";
}

/**
 * Petite pastille compacte affichant un score de confiance en pourcentage.
 * Renvoie null si la valeur n'est pas un nombre fini.
 */
export function ConfidencePill({
  value,
  className,
}: {
  value: number | null | undefined;
  className?: string;
}) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const pct = Math.round(value * 100);
  return (
    <span
      className={cn(
        "rounded px-1.5 py-0.5 text-xs font-medium tabular-nums",
        confidenceSoftClass(value),
        className,
      )}
      title={confidenceLabel(value)}
    >
      {pct}%
    </span>
  );
}

/**
 * Jauge horizontale (barre arrondie) pour un score de confiance.
 * Si `value` est null/invalide, n'affiche rien.
 */
export function ConfidenceGauge({
  value,
  showLabel = true,
  caption,
  className,
}: {
  value: number | null | undefined;
  showLabel?: boolean;
  caption?: string;
  className?: string;
}) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const clamped = Math.max(0, Math.min(1, value));
  const pct = Math.round(clamped * 100);
  return (
    <div className={cn("w-full", className)}>
      {showLabel ? (
        <div className="mb-1 flex items-center justify-between text-xs">
          <span className="text-muted-foreground">
            {caption || "Confiance"}
          </span>
          <span className={cn("font-semibold tabular-nums", confidenceTextClass(clamped))}>
            {pct}%
          </span>
        </div>
      ) : null}
      <div className="relative h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full transition-all", confidenceBgClass(clamped))}
          style={{ width: `${pct}%` }}
          aria-hidden
        />
      </div>
    </div>
  );
}
