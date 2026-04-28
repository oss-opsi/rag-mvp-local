"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import type {
  AnalysisSummary,
  CdcDetail,
  Report,
  Requirement,
} from "@/lib/types";

// ---------------------------------------------------------------------------
// Helpers partagés entre les 3 routes /analyse, /analyse/[clientId] et
// /analyse/[clientId]/[cdcId] (refonte v4.6 — routing par URL).
// ---------------------------------------------------------------------------

export function normalizeSummary(
  raw: Partial<AnalysisSummary> | null | undefined,
  requirements: Requirement[],
): AnalysisSummary {
  const s = raw || {};
  const total = Number.isFinite(s.total as number)
    ? (s.total as number)
    : requirements.length;
  const countBy = (st: Requirement["status"]) =>
    requirements.filter((r) => r.status === st).length;
  const covered = Number.isFinite(s.covered as number)
    ? (s.covered as number)
    : countBy("covered");
  const partial = Number.isFinite(s.partial as number)
    ? (s.partial as number)
    : countBy("partial");
  const missing = Number.isFinite(s.missing as number)
    ? (s.missing as number)
    : countBy("missing");
  const ambiguous = Number.isFinite(s.ambiguous as number)
    ? (s.ambiguous as number)
    : countBy("ambiguous");
  let coverage_percent = s.coverage_percent as number | undefined;
  if (!Number.isFinite(coverage_percent as number)) {
    coverage_percent = total > 0 ? (covered / total) * 100 : 0;
  }
  return {
    total,
    covered,
    partial,
    missing,
    ambiguous,
    coverage_percent: coverage_percent as number,
  };
}

export function buildReportFromDetail(detail: CdcDetail): Report | null {
  const a = detail.analysis;
  if (!a) return null;
  const report = a.report || {};
  const requirements: Requirement[] = Array.isArray(report.requirements)
    ? (report.requirements as Requirement[])
    : [];
  const flatSummary: Partial<AnalysisSummary> = {
    total: a.total,
    covered: a.covered,
    partial: a.partial,
    missing: a.missing,
    ambiguous: a.ambiguous,
    coverage_percent: a.coverage_percent,
  };
  const summary = normalizeSummary(
    (report.summary as Partial<AnalysisSummary> | undefined) || flatSummary,
    requirements,
  );
  return {
    filename: (report.filename as string) || detail.cdc.filename,
    summary,
    requirements,
    pipeline_version:
      (report.pipeline_version as string | undefined) ||
      a.pipeline_version ||
      detail.pipeline_version,
    analysis_id: a.id,
    cdc_id: detail.cdc.id,
  };
}

const STATUS_MAP: Record<string, { label: string; cls: string }> = {
  pending: {
    label: "En attente",
    cls: "border-soft bg-muted/40 text-muted-foreground",
  },
  uploaded: {
    label: "Importé",
    cls: "border-soft bg-muted/40 text-muted-foreground",
  },
  parsing: {
    label: "Parsing",
    cls: "border-warning/25 bg-warning-soft text-warning",
  },
  analysing: {
    label: "Analyse",
    cls: "border-warning/25 bg-warning-soft text-warning",
  },
  analyzed: {
    label: "Analysé",
    cls: "border-success/25 bg-success-soft text-success",
  },
  error: {
    label: "Erreur",
    cls: "border-danger/25 bg-danger-soft text-danger",
  },
};

export function StatusPill({ status }: { status: string }) {
  const m = STATUS_MAP[status] || {
    label: status,
    cls: "border-soft bg-muted/40 text-muted-foreground",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-medium",
        m.cls,
      )}
    >
      {m.label}
    </span>
  );
}

export function CoverageBadge({
  percent,
  size = "md",
}: {
  percent: number | null | undefined;
  size?: "sm" | "md";
}) {
  if (typeof percent !== "number" || !Number.isFinite(percent)) return null;
  const cls =
    percent >= 70
      ? "border-success/25 bg-success-soft text-success"
      : percent >= 40
      ? "border-warning/25 bg-warning-soft text-warning"
      : "border-danger/25 bg-danger-soft text-danger";
  const sz = size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-sm";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border font-semibold tabular-nums",
        sz,
        cls,
      )}
    >
      {percent.toFixed(0)}%
    </span>
  );
}
