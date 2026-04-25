"use client";

import * as React from "react";
import { Search, RefreshCw, Trash2, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuCheckboxItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { CoverageDonut } from "@/components/coverage-donut";
import { RequirementRow } from "@/components/requirement-row";
import { RequirementSheet } from "@/components/requirement-sheet";
import { cn } from "@/lib/utils";
import type {
  AnalysisSummary,
  Requirement,
  RequirementStatus,
} from "@/lib/types";

type StatusFilter = "all" | RequirementStatus;

const STATUS_CHIPS: { key: StatusFilter; label: string; chipClass: string }[] = [
  { key: "all", label: "Tous", chipClass: "bg-muted text-foreground" },
  { key: "covered", label: "Couverts", chipClass: "bg-success/10 text-success" },
  { key: "partial", label: "Partiels", chipClass: "bg-warning/10 text-warning" },
  { key: "missing", label: "Manquants", chipClass: "bg-danger/10 text-danger" },
  {
    key: "ambiguous",
    label: "Ambigus",
    chipClass: "bg-muted text-muted-foreground",
  },
];

export function CdcReport({
  filename,
  summary,
  requirements,
  pipelineVersion,
  onReanalyse,
  onDelete,
  reanalysing,
}: {
  filename: string;
  summary: AnalysisSummary | Partial<AnalysisSummary> | null | undefined;
  requirements: Requirement[];
  pipelineVersion?: string;
  onReanalyse: () => void | Promise<void>;
  onDelete: () => void | Promise<void>;
  reanalysing?: boolean;
}) {
  const [statusFilter, setStatusFilter] = React.useState<StatusFilter>("all");
  const [search, setSearch] = React.useState("");
  const [selectedCategories, setSelectedCategories] = React.useState<Set<string>>(
    new Set()
  );
  const [activeReq, setActiveReq] = React.useState<Requirement | null>(null);
  const [sheetOpen, setSheetOpen] = React.useState(false);

  const categories = React.useMemo(() => {
    const set = new Set<string>();
    for (const r of requirements) {
      if (r.category) set.add(r.category);
    }
    return Array.from(set).sort();
  }, [requirements]);

  const filtered = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    return requirements.filter((r) => {
      if (statusFilter !== "all" && r.status !== statusFilter) return false;
      if (selectedCategories.size > 0 && !selectedCategories.has(r.category))
        return false;
      if (q && !`${r.id} ${r.title} ${r.description}`.toLowerCase().includes(q))
        return false;
      return true;
    });
  }, [requirements, statusFilter, search, selectedCategories]);

  const toggleCategory = (cat: string) => {
    setSelectedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  const openRow = (r: Requirement) => {
    setActiveReq(r);
    setSheetOpen(true);
  };

  const coveragePercent =
    typeof summary?.coverage_percent === "number" ? summary.coverage_percent : 0;
  const safeSummary = {
    total: summary?.total ?? 0,
    covered: summary?.covered ?? 0,
    partial: summary?.partial ?? 0,
    missing: summary?.missing ?? 0,
    ambiguous: summary?.ambiguous ?? 0,
    coverage_percent: coveragePercent,
  };
  const statusBadgeVariant = (() => {
    if (coveragePercent >= 70) return "success" as const;
    if (coveragePercent >= 40) return "warning" as const;
    return "destructive" as const;
  })();

  return (
    <div className="flex h-full flex-col">
      <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-background px-4 md:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="truncate text-base font-semibold">{filename}</h1>
          <Badge variant={statusBadgeVariant}>
            {coveragePercent.toFixed(0)}% couvert
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled
            title="Export bientôt disponible"
          >
            <Download className="mr-2 h-4 w-4" />
            Exporter
          </Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <aside className="flex w-full shrink-0 flex-col gap-4 self-start border-b border-border p-4 md:sticky md:top-14 md:w-80 md:border-b-0 md:border-r md:p-6">
          <div className="flex justify-center">
            <CoverageDonut percent={coveragePercent} />
          </div>

          <dl className="grid grid-cols-2 gap-2 text-sm">
            <dt className="text-muted-foreground">Total</dt>
            <dd className="text-right font-semibold tabular-nums">
              {safeSummary.total}
            </dd>
            <dt className="text-success">Couverts</dt>
            <dd className="text-right font-semibold tabular-nums">
              {safeSummary.covered}
            </dd>
            <dt className="text-warning">Partiels</dt>
            <dd className="text-right font-semibold tabular-nums">
              {safeSummary.partial}
            </dd>
            <dt className="text-danger">Manquants</dt>
            <dd className="text-right font-semibold tabular-nums">
              {safeSummary.missing}
            </dd>
            <dt className="text-muted-foreground">Ambigus</dt>
            <dd className="text-right font-semibold tabular-nums">
              {safeSummary.ambiguous}
            </dd>
          </dl>

          <Separator />

          <div className="space-y-1 text-xs">
            <div className="font-medium">
              Pipeline {pipelineVersion || "v3.9.1"}
            </div>
            <div className="text-muted-foreground">HyDE · re-pass</div>
            <div className="text-muted-foreground">bge-m3 · reranker v2-m3</div>
          </div>

          <div className="mt-auto flex flex-col gap-2">
            <Button
              variant="outline"
              onClick={() => void onReanalyse()}
              disabled={reanalysing}
            >
              <RefreshCw
                className={cn(
                  "mr-2 h-4 w-4",
                  reanalysing ? "animate-spin" : ""
                )}
              />
              {reanalysing ? "Analyse en cours..." : "Réanalyser"}
            </Button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="destructive">
                  <Trash2 className="mr-2 h-4 w-4" />
                  Supprimer le CDC
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Supprimer ce CDC ?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Le document « {filename} » et son analyse seront
                    définitivement supprimés.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Annuler</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => void onDelete()}
                    className="bg-danger text-danger-foreground hover:bg-danger/90"
                  >
                    Supprimer
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </aside>

        <section className="flex min-w-0 flex-1 flex-col">
          <div className="sticky top-14 z-10 flex flex-wrap items-center gap-2 border-b border-border bg-background px-4 py-3 md:px-6">
            {STATUS_CHIPS.map((chip) => (
              <button
                key={chip.key}
                type="button"
                onClick={() => setStatusFilter(chip.key)}
                className={cn(
                  "rounded-md px-3 py-1 text-xs font-medium transition-colors",
                  statusFilter === chip.key
                    ? chip.chipClass
                    : "bg-background text-muted-foreground hover:bg-muted/50"
                )}
              >
                {chip.label}
              </button>
            ))}
            <div className="mx-2 h-5 w-px bg-border" aria-hidden />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm">
                  Catégorie{" "}
                  {selectedCategories.size > 0 ? `(${selectedCategories.size})` : ""}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuLabel>Filtrer par catégorie</DropdownMenuLabel>
                {categories.length === 0 ? (
                  <div className="px-2 py-1.5 text-xs text-muted-foreground">
                    Aucune catégorie
                  </div>
                ) : (
                  categories.map((c) => (
                    <DropdownMenuCheckboxItem
                      key={c}
                      checked={selectedCategories.has(c)}
                      onCheckedChange={() => toggleCategory(c)}
                    >
                      {c}
                    </DropdownMenuCheckboxItem>
                  ))
                )}
              </DropdownMenuContent>
            </DropdownMenu>
            <div className="relative ml-auto w-full max-w-xs">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Rechercher..."
                className="pl-8"
              />
            </div>
          </div>

          <div className="flex-1 overflow-auto">
            {filtered.length === 0 ? (
              <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground md:p-10">
                Aucune exigence ne correspond aux filtres.
              </div>
            ) : (
              filtered.map((r) => (
                <RequirementRow
                  key={r.id}
                  requirement={r}
                  onClick={() => openRow(r)}
                />
              ))
            )}
          </div>
        </section>
      </div>

      <RequirementSheet
        requirement={activeReq}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
      />
    </div>
  );
}
