"use client";

import * as React from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ConfidencePill } from "@/components/confidence";
import { cn } from "@/lib/utils";
import type { Requirement, RequirementStatus } from "@/lib/types";

const STATUS_META: Record<RequirementStatus, { label: string; dot: string; pill: string }> = {
  covered: {
    label: "Couvert",
    dot: "bg-success",
    pill: "bg-success/10 text-success",
  },
  partial: {
    label: "Partiel",
    dot: "bg-warning",
    pill: "bg-warning/10 text-warning",
  },
  missing: {
    label: "Manquant",
    dot: "bg-danger",
    pill: "bg-danger/10 text-danger",
  },
  ambiguous: {
    label: "Ambigu",
    dot: "bg-muted-foreground",
    pill: "bg-muted text-muted-foreground",
  },
};

export function statusLabel(status: RequirementStatus): string {
  return STATUS_META[status]?.label ?? status;
}

export function statusDotClass(status: RequirementStatus): string {
  return STATUS_META[status]?.dot ?? "bg-muted-foreground";
}

export function statusPillClass(status: RequirementStatus): string {
  return STATUS_META[status]?.pill ?? "bg-muted text-muted-foreground";
}

export function RequirementRow({
  requirement,
  feedbackVote,
  onClick,
}: {
  requirement: Requirement;
  feedbackVote?: "up" | "down" | null;
  onClick: () => void;
}) {
  const s = requirement.status;
  const meta = STATUS_META[s] ?? STATUS_META.ambiguous;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group flex w-full items-start gap-3 border-b border-border px-4 py-3 text-left transition-colors hover:bg-muted/40",
        "min-h-[64px]"
      )}
    >
      <span className={cn("mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full", meta.dot)} aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-muted-foreground">
            {requirement.id}
          </span>
          <span className="text-base font-medium text-foreground">
            {requirement.title}
          </span>
        </div>
        {requirement.subdomain ? (
          <div className="text-xs text-muted-foreground/80">
            {requirement.subdomain}
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>{requirement.category}</span>
          <span aria-hidden>·</span>
          <span className={cn("rounded px-1.5 py-0.5 text-xs", meta.pill)}>
            {meta.label}
          </span>
          <ConfidencePill value={requirement.confidence} />
          {feedbackVote === "up" ? (
            <span
              className="inline-flex items-center gap-1 rounded bg-accent/10 px-1.5 py-0.5 text-[10px] text-accent"
              title="Vous avez signalé un verdict pertinent"
            >
              <ThumbsUp className="h-3 w-3" aria-hidden />
            </span>
          ) : null}
          {feedbackVote === "down" ? (
            <span
              className="inline-flex items-center gap-1 rounded bg-danger/10 px-1.5 py-0.5 text-[10px] text-danger"
              title="Vous avez signalé un verdict à revoir"
            >
              <ThumbsDown className="h-3 w-3" aria-hidden />
            </span>
          ) : null}
          {requirement.hyde_used ? (
            <Badge variant="outline" className="text-[10px]">
              HyDE
            </Badge>
          ) : null}
          {requirement.repass_used ? (
            <Badge variant="outline" className="text-[10px]">
              re-pass
            </Badge>
          ) : null}
        </div>
        {requirement.description ? (
          <p className="line-clamp-2 text-sm text-muted-foreground">
            {requirement.description}
          </p>
        ) : null}
      </div>
    </button>
  );
}
