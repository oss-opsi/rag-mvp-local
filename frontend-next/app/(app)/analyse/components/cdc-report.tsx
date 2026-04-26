"use client";

import * as React from "react";
import {
  Search,
  RefreshCw,
  Trash2,
  Download,
  Loader2,
  ChevronDown,
  BarChart3,
  ArrowDownNarrowWide,
} from "lucide-react";
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
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { CoverageDonut } from "@/components/coverage-donut";
import { ConfidenceGauge } from "@/components/confidence";
import { RequirementRow } from "@/components/requirement-row";
import { RequirementSheet } from "@/components/requirement-sheet";
import { useToast } from "@/components/ui/use-toast";
import { api } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type {
  AnalysisSummary,
  Requirement,
  RequirementFeedback,
  RequirementStatus,
} from "@/lib/types";
import { QualityDashboard } from "./quality-dashboard";

type StatusFilter = "all" | RequirementStatus;
type GroupMode = "flat" | "domain";
type ViewMode = "report" | "quality";

const SIRH_DOMAIN_ORDER = [
  "Paie",
  "DSN",
  "GTA",
  "Absences/Congés",
  "Contrats/Administration",
  "Portail/Self-service",
  "Intégrations/Interfaces",
  "Réglementaire",
  "Autre",
];

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

const GROUP_BY_KEY = "tellme.cdcGroupBy";

function loadGroupMode(): GroupMode {
  if (typeof window === "undefined") return "flat";
  const v = window.localStorage.getItem(GROUP_BY_KEY);
  return v === "domain" ? "domain" : "flat";
}

function avgConfidence(reqs: Requirement[]): number | null {
  let sum = 0;
  let n = 0;
  for (const r of reqs) {
    if (typeof r.confidence === "number" && Number.isFinite(r.confidence)) {
      sum += r.confidence;
      n += 1;
    }
  }
  return n > 0 ? sum / n : null;
}

function domainOrderIndex(domain: string): number {
  const idx = SIRH_DOMAIN_ORDER.indexOf(domain);
  return idx === -1 ? SIRH_DOMAIN_ORDER.length : idx;
}

export function CdcReport({
  cdcId,
  analysisId,
  filename,
  summary,
  requirements,
  pipelineVersion,
  onReanalyse,
  onDelete,
  reanalysing,
}: {
  cdcId: number | null;
  analysisId?: number | null;
  filename: string;
  summary: AnalysisSummary | Partial<AnalysisSummary> | null | undefined;
  requirements: Requirement[];
  pipelineVersion?: string;
  onReanalyse: () => void | Promise<void>;
  onDelete: () => void | Promise<void>;
  reanalysing?: boolean;
}) {
  const { toast } = useToast();
  const [statusFilter, setStatusFilter] = React.useState<StatusFilter>("all");
  const [search, setSearch] = React.useState("");
  const [selectedCategories, setSelectedCategories] = React.useState<Set<string>>(
    new Set()
  );
  const [activeReq, setActiveReq] = React.useState<Requirement | null>(null);
  const [sheetOpen, setSheetOpen] = React.useState(false);
  const [exporting, setExporting] = React.useState<"xlsx" | "md" | null>(null);
  const [groupMode, setGroupMode] = React.useState<GroupMode>("flat");
  const [sortByConfidence, setSortByConfidence] = React.useState(false);
  const [openDomains, setOpenDomains] = React.useState<Set<string>>(new Set());
  const [view, setView] = React.useState<ViewMode>("report");
  const [feedbackList, setFeedbackList] = React.useState<RequirementFeedback[]>([]);

  // Charger préférence groupBy depuis localStorage côté client.
  React.useEffect(() => {
    setGroupMode(loadGroupMode());
  }, []);

  React.useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(GROUP_BY_KEY, groupMode);
  }, [groupMode]);

  const reloadFeedback = React.useCallback(async () => {
    if (!analysisId) {
      setFeedbackList([]);
      return;
    }
    try {
      const fbs = await api.getAnalysisFeedback(analysisId);
      setFeedbackList(fbs);
    } catch {
      // silencieux : ne bloque pas l'affichage
    }
  }, [analysisId]);

  React.useEffect(() => {
    void reloadFeedback();
  }, [reloadFeedback]);

  const feedbackByRequirement = React.useMemo(() => {
    const m = new Map<string, RequirementFeedback>();
    for (const f of feedbackList) m.set(f.requirement_id, f);
    return m;
  }, [feedbackList]);

  const handleExport = async (fmt: "xlsx" | "md") => {
    if (cdcId === null) return;
    setExporting(fmt);
    try {
      await api.downloadCdcExport(cdcId, fmt);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur d'export";
      toast({ title: "Échec de l'export", description: msg, variant: "destructive" });
    } finally {
      setExporting(null);
    }
  };

  const categories = React.useMemo(() => {
    const set = new Set<string>();
    for (const r of requirements) {
      if (r.category) set.add(r.category);
    }
    return Array.from(set).sort();
  }, [requirements]);

  const filtered = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = requirements.filter((r) => {
      if (statusFilter !== "all" && r.status !== statusFilter) return false;
      if (selectedCategories.size > 0 && !selectedCategories.has(r.category))
        return false;
      if (q && !`${r.id} ${r.title} ${r.description}`.toLowerCase().includes(q))
        return false;
      return true;
    });
    if (sortByConfidence) {
      return [...list].sort((a, b) => {
        const ca = typeof a.confidence === "number" ? a.confidence : 1;
        const cb = typeof b.confidence === "number" ? b.confidence : 1;
        return ca - cb;
      });
    }
    return list;
  }, [requirements, statusFilter, search, selectedCategories, sortByConfidence]);

  // Counts per status, applied AFTER category + search filters so chips reflect
  // what the user would see after each toggle.
  const counts = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    const base = requirements.filter((r) => {
      if (selectedCategories.size > 0 && !selectedCategories.has(r.category))
        return false;
      if (q && !`${r.id} ${r.title} ${r.description}`.toLowerCase().includes(q))
        return false;
      return true;
    });
    const acc: Record<StatusFilter, number> = {
      all: base.length,
      covered: 0,
      partial: 0,
      missing: 0,
      ambiguous: 0,
    };
    for (const r of base) {
      const k = r.status as RequirementStatus;
      if (k in acc) acc[k] += 1;
    }
    return acc;
  }, [requirements, selectedCategories, search]);

  const groupedByDomain = React.useMemo(() => {
    const groups = new Map<string, Requirement[]>();
    for (const r of filtered) {
      const k = r.category || "Autre";
      const arr = groups.get(k) ?? [];
      arr.push(r);
      groups.set(k, arr);
    }
    return Array.from(groups.entries()).sort(
      (a, b) => domainOrderIndex(a[0]) - domainOrderIndex(b[0]),
    );
  }, [filtered]);

  const overallConfidence = React.useMemo(
    () => avgConfidence(requirements),
    [requirements],
  );

  const toggleCategory = (cat: string) => {
    setSelectedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  const toggleDomain = (d: string) => {
    setOpenDomains((prev) => {
      const next = new Set(prev);
      if (next.has(d)) next.delete(d);
      else next.add(d);
      return next;
    });
  };

  const openRow = (r: Requirement) => {
    setActiveReq(r);
    setSheetOpen(true);
  };

  const openRequirementById = (rid: string) => {
    const r = requirements.find((x) => x.id === rid);
    if (r) {
      setView("report");
      setActiveReq(r);
      setSheetOpen(true);
    }
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
          <div className="flex items-center rounded-md border border-border p-0.5 text-xs">
            <button
              type="button"
              onClick={() => setView("report")}
              className={cn(
                "rounded px-2 py-1 transition-colors",
                view === "report"
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              Rapport
            </button>
            <button
              type="button"
              onClick={() => setView("quality")}
              className={cn(
                "flex items-center gap-1 rounded px-2 py-1 transition-colors",
                view === "quality"
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
              disabled={!analysisId}
              title={
                analysisId ? "Tableau de bord qualité" : "Analyse non disponible"
              }
            >
              <BarChart3 className="h-3.5 w-3.5" />
              Qualité
            </button>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                disabled={cdcId === null || exporting !== null}
                title="Exporter le rapport d'analyse"
              >
                {exporting !== null ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Download className="mr-2 h-4 w-4" />
                )}
                {exporting === "xlsx"
                  ? "Export Excel..."
                  : exporting === "md"
                  ? "Export Markdown..."
                  : "Exporter"}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Format d'export</DropdownMenuLabel>
              <DropdownMenuItem onSelect={() => void handleExport("xlsx")}>
                Excel (.xlsx)
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => void handleExport("md")}>
                Markdown (.md)
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {view === "quality" && analysisId ? (
        <div className="min-h-0 flex-1">
          <QualityDashboard
            analysisId={analysisId}
            requirements={requirements}
            onOpenRequirement={openRequirementById}
          />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col md:flex-row">
          <aside className="flex w-full shrink-0 flex-col gap-4 self-start border-b border-border p-4 md:sticky md:top-14 md:w-80 md:border-b-0 md:border-r md:p-6">
            <div className="flex justify-center">
              <CoverageDonut percent={coveragePercent} />
            </div>

            {overallConfidence !== null ? (
              <div className="rounded-md border border-border p-3">
                <ConfidenceGauge
                  value={overallConfidence}
                  caption={`Confiance moyenne · ${Math.round(overallConfidence * 100)}%`}
                  showLabel
                />
              </div>
            ) : null}

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
                Pipeline {pipelineVersion || "v3.10.0"}
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
                    "flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors",
                    statusFilter === chip.key
                      ? chip.chipClass
                      : "bg-background text-muted-foreground hover:bg-muted/50"
                  )}
                >
                  <span>{chip.label}</span>
                  <span
                    className={cn(
                      "rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums",
                      statusFilter === chip.key
                        ? "bg-background/50"
                        : "bg-muted text-muted-foreground"
                    )}
                  >
                    {counts[chip.key]}
                  </span>
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

              <div className="flex items-center rounded-md border border-border p-0.5 text-xs">
                <button
                  type="button"
                  onClick={() => setGroupMode("flat")}
                  className={cn(
                    "rounded px-2 py-1 transition-colors",
                    groupMode === "flat"
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  Vue plate
                </button>
                <button
                  type="button"
                  onClick={() => setGroupMode("domain")}
                  className={cn(
                    "rounded px-2 py-1 transition-colors",
                    groupMode === "domain"
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  Vue par domaine
                </button>
              </div>

              <Button
                variant={sortByConfidence ? "default" : "outline"}
                size="sm"
                onClick={() => setSortByConfidence((v) => !v)}
                title="Trier les exigences par score de confiance croissant"
              >
                <ArrowDownNarrowWide className="mr-1 h-4 w-4" />
                Trier par confiance croissante
              </Button>

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

            <div className="flex items-center justify-between gap-2 border-b border-border bg-muted/30 px-4 py-2 text-xs text-muted-foreground md:px-6">
              <div>
                <span className="font-semibold tabular-nums text-foreground">
                  {filtered.length}
                </span>{" "}
                exigence{filtered.length > 1 ? "s" : ""} sur{" "}
                <span className="tabular-nums">{requirements.length}</span>
              </div>
              {(statusFilter !== "all" ||
                selectedCategories.size > 0 ||
                search.trim() !== "") && (
                <button
                  type="button"
                  onClick={() => {
                    setStatusFilter("all");
                    setSelectedCategories(new Set());
                    setSearch("");
                  }}
                  className="text-xs font-medium text-accent hover:underline"
                >
                  Réinitialiser les filtres
                </button>
              )}
            </div>

            <div className="flex-1 overflow-auto">
              {filtered.length === 0 ? (
                <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground md:p-10">
                  Aucune exigence ne correspond aux filtres.
                </div>
              ) : groupMode === "flat" ? (
                filtered.map((r) => (
                  <RequirementRow
                    key={r.id}
                    requirement={r}
                    feedbackVote={feedbackByRequirement.get(r.id)?.vote ?? null}
                    onClick={() => openRow(r)}
                  />
                ))
              ) : (
                groupedByDomain.map(([domain, reqs]) => {
                  const isOpen = openDomains.size === 0
                    ? true
                    : openDomains.has(domain);
                  const counts = {
                    covered: reqs.filter((r) => r.status === "covered").length,
                    partial: reqs.filter((r) => r.status === "partial").length,
                    missing: reqs.filter((r) => r.status === "missing").length,
                    ambiguous: reqs.filter((r) => r.status === "ambiguous").length,
                  };
                  return (
                    <div key={domain} className="border-b border-border">
                      <button
                        type="button"
                        onClick={() => toggleDomain(domain)}
                        className="flex w-full items-center gap-3 bg-muted/30 px-4 py-2 text-left transition-colors hover:bg-muted/50 md:px-6"
                      >
                        <ChevronDown
                          className={cn(
                            "h-4 w-4 shrink-0 transition-transform",
                            isOpen ? "" : "-rotate-90",
                          )}
                          aria-hidden
                        />
                        <span className="font-medium">{domain}</span>
                        <span className="text-xs text-muted-foreground">
                          ({reqs.length} exigence{reqs.length > 1 ? "s" : ""})
                        </span>
                        <DomainStatusBar counts={counts} total={reqs.length} />
                      </button>
                      {isOpen
                        ? reqs.map((r) => (
                            <RequirementRow
                              key={r.id}
                              requirement={r}
                              feedbackVote={
                                feedbackByRequirement.get(r.id)?.vote ?? null
                              }
                              onClick={() => openRow(r)}
                            />
                          ))
                        : null}
                    </div>
                  );
                })
              )}
            </div>
          </section>
        </div>
      )}

      <RequirementSheet
        requirement={activeReq}
        analysisId={analysisId ?? null}
        feedback={
          activeReq ? feedbackByRequirement.get(activeReq.id) ?? null : null
        }
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        onFeedbackChange={reloadFeedback}
      />
    </div>
  );
}

function DomainStatusBar({
  counts,
  total,
}: {
  counts: { covered: number; partial: number; missing: number; ambiguous: number };
  total: number;
}) {
  if (total <= 0) return null;
  const seg = (n: number) => `${(n / total) * 100}%`;
  return (
    <div className="ml-auto flex h-2 w-32 overflow-hidden rounded-full bg-muted">
      <div className="h-full bg-success" style={{ width: seg(counts.covered) }} />
      <div className="h-full bg-warning" style={{ width: seg(counts.partial) }} />
      <div className="h-full bg-danger" style={{ width: seg(counts.missing) }} />
      <div
        className="h-full bg-muted-foreground/60"
        style={{ width: seg(counts.ambiguous) }}
      />
    </div>
  );
}
