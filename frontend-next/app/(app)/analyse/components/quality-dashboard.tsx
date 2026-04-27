"use client";

import * as React from "react";
import {
  Download,
  Loader2,
  RefreshCcw,
  Sparkles,
  Wand2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/use-toast";
import { api } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type {
  AnalysisJob,
  QualityDashboard as QualityDashboardData,
  Requirement,
  RequirementFeedback,
} from "@/lib/types";

const BUCKETS = [
  { label: "0-20%", min: 0, max: 0.2 },
  { label: "20-40%", min: 0.2, max: 0.4 },
  { label: "40-60%", min: 0.4, max: 0.6 },
  { label: "60-80%", min: 0.6, max: 0.8 },
  { label: "80-100%", min: 0.8, max: 1.0001 },
];

const POLL_INTERVAL_MS = 3000;

function bucketColorClass(idx: number): string {
  if (idx >= 4) return "bg-success";
  if (idx >= 3) return "bg-success/70";
  if (idx >= 2) return "bg-warning";
  if (idx >= 1) return "bg-warning/70";
  return "bg-danger";
}

function computeDistribution(requirements: Requirement[]): number[] {
  const counts = new Array(BUCKETS.length).fill(0);
  for (const r of requirements) {
    if (typeof r.confidence !== "number" || !Number.isFinite(r.confidence)) continue;
    const v = Math.max(0, Math.min(1, r.confidence));
    for (let i = 0; i < BUCKETS.length; i++) {
      const b = BUCKETS[i]!;
      if (v >= b.min && v < b.max) {
        counts[i]! += 1;
        break;
      }
    }
  }
  return counts;
}

function avgConfidence(requirements: Requirement[]): number | null {
  let sum = 0;
  let n = 0;
  for (const r of requirements) {
    if (typeof r.confidence === "number" && Number.isFinite(r.confidence)) {
      sum += r.confidence;
      n += 1;
    }
  }
  return n > 0 ? sum / n : null;
}

function feedbackThisMonth(feedbackList: RequirementFeedback[]): number {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth();
  let n = 0;
  for (const f of feedbackList) {
    if (f.vote !== "up") continue;
    const iso = f.updated_at || f.created_at;
    if (!iso) continue;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) continue;
    if (d.getFullYear() === y && d.getMonth() === m) n += 1;
  }
  return n;
}

export function QualityDashboard({
  analysisId,
  requirements,
  onOpenRequirement,
  onAnalysisRefreshed,
}: {
  analysisId: number | string;
  requirements: Requirement[];
  onOpenRequirement?: (requirementId: string) => void;
  onAnalysisRefreshed?: () => void | Promise<void>;
}) {
  const { toast } = useToast();
  const [data, setData] = React.useState<QualityDashboardData | null>(null);
  const [feedbackList, setFeedbackList] = React.useState<RequirementFeedback[]>([]);
  const [loading, setLoading] = React.useState(true);

  // Re-pass state : un seul re-pass à la fois pour cette analyse.
  // - mode "batch" : repassingId = "__batch__"
  // - mode unitaire : repassingId = id de l'exigence
  const [repassingId, setRepassingId] = React.useState<string | null>(null);
  const repassCancelRef = React.useRef<{ cancelled: boolean } | null>(null);

  const [exportingCsv, setExportingCsv] = React.useState(false);

  const reload = React.useCallback(async () => {
    setLoading(true);
    try {
      const [dash, fbs] = await Promise.all([
        api.getQualityDashboard(analysisId),
        api.getAnalysisFeedback(analysisId),
      ]);
      setData(dash);
      setFeedbackList(fbs);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur de chargement";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [analysisId, toast]);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  // Annule tout polling en cours si on change d'analyse ou démonte.
  React.useEffect(() => {
    return () => {
      if (repassCancelRef.current) repassCancelRef.current.cancelled = true;
    };
  }, [analysisId]);

  const requirementsById = React.useMemo(() => {
    const m = new Map<string, Requirement>();
    for (const r of requirements) m.set(r.id, r);
    return m;
  }, [requirements]);

  const distribution = React.useMemo(
    () => computeDistribution(requirements),
    [requirements],
  );
  const maxBucket = Math.max(1, ...distribution);
  const avg = React.useMemo(() => avgConfidence(requirements), [requirements]);

  const totalReqs = requirements.length;
  const totalVotes = data?.total_votes ?? 0;
  const up = data?.up ?? 0;
  const down = data?.down ?? 0;
  const positiveRate = totalVotes > 0 ? Math.round((up / totalVotes) * 100) : null;
  const feedbackCoverage =
    totalReqs > 0 ? Math.round((totalVotes / totalReqs) * 100) : 0;

  // Re-pass candidates : confidence < 0.5 OR has down feedback.
  const downSet = React.useMemo(() => {
    const s = new Set<string>();
    for (const f of feedbackList) {
      if (f.vote === "down") s.add(f.requirement_id);
    }
    return s;
  }, [feedbackList]);

  const repassCandidates = React.useMemo(() => {
    const items: { req: Requirement; reasons: string[] }[] = [];
    for (const r of requirements) {
      const reasons: string[] = [];
      if (typeof r.confidence === "number" && r.confidence < 0.5) {
        reasons.push("confiance faible");
      }
      if (downSet.has(r.id)) reasons.push("feedback négatif");
      if (reasons.length > 0) items.push({ req: r, reasons });
    }
    return items;
  }, [requirements, downSet]);

  const topContested = React.useMemo(() => {
    const list = data?.top_contested || [];
    return list
      .map((c) => ({
        requirement_id: c.requirement_id,
        down_votes: c.down_votes,
        title: requirementsById.get(c.requirement_id)?.title || c.requirement_id,
      }))
      .slice(0, 5);
  }, [data?.top_contested, requirementsById]);

  const domainEntries = React.useMemo(() => {
    const dict = data?.feedback_per_domain || {};
    return Object.entries(dict)
      .map(([domain, v]) => ({ domain, up: v.up || 0, down: v.down || 0 }))
      .sort((a, b) => b.up + b.down - (a.up + a.down));
  }, [data?.feedback_per_domain]);
  const maxDomain = Math.max(
    1,
    ...domainEntries.map((d) => d.up + d.down),
  );

  const upThisMonth = React.useMemo(
    () => feedbackThisMonth(feedbackList),
    [feedbackList],
  );

  const repassBusy = repassingId !== null;
  const candidatesCount = repassCandidates.length;
  const exportDisabled = totalVotes === 0 || exportingCsv;

  // Polling identique à pollAnalysisJob (analyse/page.tsx) : 3 s.
  const pollJob = React.useCallback(
    async (jobId: number): Promise<AnalysisJob | null> => {
      const ref = { cancelled: false };
      repassCancelRef.current = ref;
      while (!ref.cancelled) {
        try {
          const job = await api.analysisJob(jobId);
          if (ref.cancelled) return null;
          if (job.status === "done" || job.status === "error") {
            return job;
          }
        } catch (err) {
          throw err;
        }
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      }
      return null;
    },
    [],
  );

  const launchRepass = React.useCallback(
    async (
      mode: "batch" | "single",
      requirementIds: string[] | undefined,
      label: string,
    ) => {
      const tag = mode === "batch" ? "__batch__" : requirementIds?.[0] || "";
      setRepassingId(tag);
      const t = toast({
        title: "Re-pass en cours",
        description: label,
      });
      try {
        const job = await api.repassAnalysis(analysisId, { requirementIds });
        const final = await pollJob(job.id);
        if (!final) {
          // annulé silencieusement
          return;
        }
        if (final.status === "error") {
          toast({
            title: "Échec du re-pass",
            description: final.error || "Erreur inconnue",
            variant: "destructive",
          });
          return;
        }
        // status === "done"
        toast({ title: "Re-pass terminé", description: label });
        if (onAnalysisRefreshed) {
          await onAnalysisRefreshed();
        }
        await reload();
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Erreur de re-pass";
        toast({ title: "Erreur", description: msg, variant: "destructive" });
      } finally {
        setRepassingId(null);
        // Le toast initial s'efface naturellement après son timeout.
        void t;
      }
    },
    [analysisId, onAnalysisRefreshed, pollJob, reload, toast],
  );

  const handleRepassAll = React.useCallback(() => {
    if (candidatesCount === 0) return;
    void launchRepass(
      "batch",
      undefined,
      `Re-pass GPT-4o sur ${candidatesCount} exigence${candidatesCount > 1 ? "s" : ""}…`,
    );
  }, [candidatesCount, launchRepass]);

  const handleRepassOne = React.useCallback(
    (req: Requirement) => {
      void launchRepass(
        "single",
        [req.id],
        `Re-pass GPT-4o sur ${req.id}…`,
      );
    },
    [launchRepass],
  );

  const handleExportCsv = React.useCallback(async () => {
    if (totalVotes === 0) return;
    setExportingCsv(true);
    try {
      await api.exportFeedbackCsv(analysisId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur d'export";
      toast({ title: "Échec de l'export", description: msg, variant: "destructive" });
    } finally {
      setExportingCsv(false);
    }
  }, [analysisId, totalVotes, toast]);

  if (loading && !data) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Chargement du tableau de bord qualité...
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-background px-4 py-3 md:px-6">
        <h2 className="text-base font-semibold">Tableau de bord qualité</h2>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void handleExportCsv()}
            disabled={exportDisabled}
            title={
              totalVotes === 0
                ? "Aucun feedback à exporter"
                : "Télécharger un CSV (séparateur ;) compatible Excel"
            }
          >
            {exportingCsv ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Download className="mr-2 h-4 w-4" />
            )}
            Exporter le feedback (CSV)
          </Button>
          <Button variant="outline" size="sm" onClick={() => void reload()}>
            <RefreshCcw className="mr-2 h-4 w-4" />
            Rafraîchir
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-6 p-4 md:p-6">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <KpiTile
            label="Taux de feedback positif"
            value={positiveRate !== null ? `${positiveRate}%` : "—"}
            sub={
              totalVotes > 0
                ? `${up} positif${up > 1 ? "s" : ""} / ${totalVotes} avis`
                : "Aucun avis"
            }
          />
          <KpiTile
            label="Verdicts avec avis"
            value={`${totalVotes}/${totalReqs}`}
            sub={`${feedbackCoverage}% des exigences`}
          />
          <KpiTile
            label="Confiance moyenne"
            value={avg !== null ? `${Math.round(avg * 100)}%` : "—"}
            sub={
              avg === null
                ? "Pas de score disponible"
                : avg >= 0.8
                ? "Fiabilité élevée"
                : avg >= 0.5
                ? "Fiabilité moyenne"
                : "Fiabilité faible"
            }
          />
          <KpiTile
            label="Verdicts à re-passer"
            value={String(candidatesCount)}
            sub="Confiance < 50% ou avis négatif"
          />
        </div>

        <section className="rounded-md border border-border bg-background p-4">
          <h3 className="mb-3 text-sm font-semibold">
            Distribution des scores de confiance
          </h3>
          <div className="flex h-40 items-end gap-2">
            {distribution.map((c, i) => {
              const h = Math.round((c / maxBucket) * 100);
              return (
                <div key={i} className="flex flex-1 flex-col items-center gap-1">
                  <div className="relative flex h-full w-full items-end">
                    <div
                      className={cn("w-full rounded-t-md", bucketColorClass(i))}
                      style={{ height: `${Math.max(h, 2)}%` }}
                      aria-label={`${c} exigences entre ${BUCKETS[i]!.label}`}
                    />
                  </div>
                  <div className="text-xs font-semibold tabular-nums">{c}</div>
                  <div className="text-[10px] text-muted-foreground">
                    {BUCKETS[i]!.label}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="rounded-md border border-border bg-background p-4">
          <h3 className="mb-3 text-sm font-semibold">
            Feedback par domaine SIRH
          </h3>
          {domainEntries.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              Aucun feedback enregistré pour cette analyse.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {domainEntries.map((d) => {
                const total = d.up + d.down;
                const widthPct = (total / maxDomain) * 100;
                const upPct = total > 0 ? (d.up / total) * 100 : 0;
                return (
                  <li key={d.domain} className="flex flex-col gap-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-medium">{d.domain}</span>
                      <span className="text-muted-foreground tabular-nums">
                        {d.up} pertinents · {d.down} à revoir
                      </span>
                    </div>
                    <div className="relative h-3 w-full overflow-hidden rounded-md bg-muted">
                      <div
                        className="absolute left-0 top-0 flex h-full"
                        style={{ width: `${widthPct}%` }}
                      >
                        <div
                          className="h-full bg-success"
                          style={{ width: `${upPct}%` }}
                        />
                        <div
                          className="h-full bg-danger"
                          style={{ width: `${100 - upPct}%` }}
                        />
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="rounded-md border border-border bg-background p-4">
          <h3 className="mb-3 text-sm font-semibold">
            Top 5 verdicts contestés
          </h3>
          {topContested.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              Aucun verdict contesté pour l'instant.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {topContested.map((c) => (
                <li
                  key={c.requirement_id}
                  className="flex items-center justify-between gap-3 py-2"
                >
                  <div className="flex min-w-0 flex-col">
                    <span className="font-mono text-xs text-muted-foreground">
                      {c.requirement_id}
                    </span>
                    <span className="truncate text-sm">{c.title}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-danger tabular-nums">
                      {c.down_votes} avis négatifs
                    </span>
                    {onOpenRequirement ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => onOpenRequirement(c.requirement_id)}
                      >
                        Voir l'exigence
                      </Button>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-md border border-border bg-background p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">
              Suggestions de re-pass automatique
            </h3>
            {candidatesCount > 0 ? (
              <Button
                size="sm"
                onClick={handleRepassAll}
                disabled={repassBusy}
                title="Lancer un re-pass GPT-4o sur toutes les exigences à confiance faible ou avec feedback négatif"
              >
                {repassingId === "__batch__" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Wand2 className="mr-2 h-4 w-4" />
                )}
                {`Re-passer toutes les suggestions (${candidatesCount})`}
              </Button>
            ) : null}
          </div>
          {repassBusy ? (
            <div className="mb-3 flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              <span>
                Re-pass en cours.
                {" "}Vous pouvez continuer à consulter le rapport pendant le traitement.
              </span>
            </div>
          ) : null}
          {candidatesCount === 0 ? (
            <p className="text-xs text-muted-foreground">
              Aucun verdict ne nécessite de re-pass à ce stade.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {repassCandidates.slice(0, 20).map(({ req, reasons }) => {
                const isThisRowBusy = repassingId === req.id;
                return (
                  <li
                    key={req.id}
                    className="flex flex-wrap items-center justify-between gap-3 py-2"
                  >
                    <div className="flex min-w-0 flex-col">
                      <span className="font-mono text-xs text-muted-foreground">
                        {req.id}
                      </span>
                      <span className="truncate text-sm">{req.title}</span>
                      <span className="text-xs text-muted-foreground">
                        {reasons.join(" · ")}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      {onOpenRequirement ? (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => onOpenRequirement(req.id)}
                          disabled={repassBusy}
                        >
                          Voir l'exigence
                        </Button>
                      ) : null}
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleRepassOne(req)}
                        disabled={repassBusy}
                      >
                        {isThisRowBusy ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <Wand2 className="mr-2 h-4 w-4" />
                        )}
                        Lancer un re-pass GPT-4o
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="rounded-md border border-border bg-background p-4">
          <div className="flex items-start gap-3">
            <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />
            <div className="flex flex-col gap-1">
              <h3 className="text-sm font-semibold">
                Apprentissage continu activé
              </h3>
              <p className="text-xs text-muted-foreground">
                Vos verdicts validés enrichissent automatiquement les analyses
                suivantes sur les mêmes domaines SIRH (exemples + sources
                priorisées).
              </p>
              <p className="text-xs text-muted-foreground">
                Verdicts validés ce mois-ci sur cette analyse :{" "}
                <span className="font-semibold text-foreground tabular-nums">
                  {upThisMonth}
                </span>
                {down > 0 ? (
                  <>
                    {" "}· avis négatifs pris en compte :{" "}
                    <span className="font-semibold text-foreground tabular-nums">
                      {down}
                    </span>
                  </>
                ) : null}
              </p>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

function KpiTile({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-md border border-border bg-background p-4">
      <div className="text-xs uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {sub ? (
        <div className="mt-1 text-xs text-muted-foreground">{sub}</div>
      ) : null}
    </div>
  );
}
