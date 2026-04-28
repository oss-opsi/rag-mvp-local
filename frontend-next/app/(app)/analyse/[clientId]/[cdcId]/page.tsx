"use client";

import * as React from "react";
import { useParams, useRouter, notFound } from "next/navigation";
import { Loader2, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { NotificationsBell } from "@/components/notifications-bell";
import { useToast } from "@/components/ui/use-toast";
import { api } from "@/lib/api-client";
import { CdcReport } from "../../components/cdc-report";
import {
  StatusPill,
  buildReportFromDetail,
  normalizeSummary,
} from "../../_helpers";
import type {
  AnalysisJob,
  CdcDetail,
  Report,
  Requirement,
  AnalysisSummary,
} from "@/lib/types";

export default function CdcReportPage() {
  const params = useParams<{ clientId: string; cdcId: string }>();
  const router = useRouter();
  const { toast } = useToast();
  const clientIdNum = Number(params.clientId);
  const cdcIdNum = Number(params.cdcId);
  if (
    !Number.isFinite(clientIdNum) ||
    clientIdNum <= 0 ||
    !Number.isFinite(cdcIdNum) ||
    cdcIdNum <= 0
  ) {
    return notFound();
  }

  const [cdcDetail, setCdcDetail] = React.useState<CdcDetail | null>(null);
  const [report, setReport] = React.useState<Report | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [analysing, setAnalysing] = React.useState(false);

  const reload = React.useCallback(async () => {
    setLoading(true);
    try {
      const detail = await api.cdc(cdcIdNum);
      setCdcDetail(detail);
      setReport(buildReportFromDetail(detail));
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur de chargement";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [cdcIdNum, toast]);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  // Polling fin du job en cours (3s) — démarre quand on détecte un job
  // queued/running pour ce CDC.
  const pollingRef = React.useRef<{ jobId: number; cancelled: boolean } | null>(
    null,
  );

  const finishAnalyseFromJob = React.useCallback(
    async (job: AnalysisJob) => {
      if (job.status === "done" && job.report) {
        const rpt = job.report;
        const requirements: Requirement[] = rpt.requirements || [];
        const summary: AnalysisSummary = normalizeSummary(
          rpt.summary,
          requirements,
        );
        setReport({
          filename: rpt.filename,
          summary,
          requirements,
          pipeline_version: rpt.pipeline_version,
          analysis_id: rpt.analysis_id ?? job.analysis_id ?? undefined,
          cdc_id: rpt.cdc_id ?? job.cdc_id,
        });
        await reload();
        toast({ title: "Analyse terminée" });
      } else if (job.status === "error") {
        toast({
          title: "Erreur d'analyse",
          description: job.error || "Échec de l'analyse.",
          variant: "destructive",
        });
      }
    },
    [reload, toast],
  );

  const pollAnalysisJob = React.useCallback(
    async (jobId: number) => {
      const ref = { jobId, cancelled: false };
      pollingRef.current = ref;
      const POLL_INTERVAL_MS = 3000;
      const MAX_CONSECUTIVE_ERRORS = 5;
      let consecutiveErrors = 0;
      while (!ref.cancelled) {
        try {
          const job = await api.analysisJob(jobId);
          if (ref.cancelled) return;
          consecutiveErrors = 0;
          if (job.status === "done" || job.status === "error") {
            await finishAnalyseFromJob(job);
            return;
          }
        } catch (err) {
          consecutiveErrors += 1;
          if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
            const msg = err instanceof Error ? err.message : "Erreur de polling";
            toast({
              title: "Suivi de l'analyse interrompu",
              description: `${msg} (${MAX_CONSECUTIVE_ERRORS} échecs consécutifs). L'analyse continue en arrière-plan — rafraîchissez la page pour reprendre le suivi.`,
              variant: "destructive",
            });
            return;
          }
        }
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      }
    },
    [finishAnalyseFromJob, toast],
  );

  // Bouton Réanalyser lié à l'état réel du batch backend (poll 5s).
  React.useEffect(() => {
    let cancelled = false;
    let trackingJobId: number | null = null;
    const STATUS_POLL_MS = 5000;

    const tick = async () => {
      try {
        const jobs = await api.analysisJobs({
          statusFilter: "queued,running",
          cdcId: cdcIdNum,
        });
        if (cancelled) return;
        if (jobs.length > 0) {
          const job = jobs[0]!;
          if (!analysing) setAnalysing(true);
          if (trackingJobId !== job.id) {
            trackingJobId = job.id;
            void pollAnalysisJob(job.id).finally(() => {
              trackingJobId = null;
            });
          }
        } else {
          if (analysing) setAnalysing(false);
        }
      } catch {
        // silencieux
      }
    };

    void tick();
    const interval = window.setInterval(() => void tick(), STATUS_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      if (pollingRef.current) pollingRef.current.cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cdcIdNum, pollAnalysisJob]);

  const handleAnalyse = async (force = false) => {
    setAnalysing(true);
    const t = toast({
      title: "Analyse en cours",
      description:
        "Le traitement tourne en arrière-plan. Vous pouvez fermer ou naviguer ailleurs, le rapport s'affichera à votre retour.",
    });
    try {
      const job = await api.analyseCdc(cdcIdNum, force);
      if (job.status === "done" || job.status === "error") {
        await finishAnalyseFromJob(job);
      } else {
        await pollAnalysisJob(job.id);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur d'analyse";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      t.dismiss();
      setAnalysing(false);
    }
  };

  const handleDeleteCdc = async () => {
    try {
      await api.deleteCdc(cdcIdNum);
      toast({ title: "CDC supprimé" });
      router.push(`/analyse/${clientIdNum}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur suppression CDC";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Chargement du CDC...
      </div>
    );
  }

  if (!cdcDetail) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        CDC introuvable.
      </div>
    );
  }

  // Pas d'analyse encore — page intermédiaire avec bouton "Lancer l'analyse"
  if (!report) {
    return (
      <div className="flex h-full flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-soft px-4 md:px-6">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.push(`/analyse/${clientIdNum}`)}
              aria-label="Retour à la liste des CDCs"
              className="h-8 shrink-0 px-2 text-muted-foreground hover:text-foreground"
            >
              <span className="ml-1 hidden md:inline">← CDCs</span>
              <span className="md:hidden">←</span>
            </Button>
            <div className="min-w-0 truncate text-sm font-semibold tracking-tight">
              {cdcDetail.cdc.filename}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <StatusPill status={cdcDetail.status} />
            <NotificationsBell />
          </div>
        </header>
        <div className="flex flex-1 items-center justify-center p-6 md:p-10">
          <div className="max-w-md text-center">
            <h2 className="mb-2 text-lg font-semibold tracking-tight">
              Analyse non réalisée
            </h2>
            <p className="mb-6 text-sm text-muted-foreground">
              Lancez l&apos;analyse automatique pour extraire les exigences et
              évaluer leur couverture face au corpus indexé.
            </p>
            <Button
              size="lg"
              onClick={() => void handleAnalyse(false)}
              disabled={analysing}
            >
              {analysing ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Play className="mr-2 h-4 w-4" />
              )}
              {analysing ? "Analyse en cours..." : "Lancer l'analyse"}
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <CdcReport
      cdcId={cdcIdNum}
      analysisId={report.analysis_id ?? cdcDetail.analysis?.id ?? null}
      filename={report.filename}
      summary={report.summary}
      requirements={report.requirements}
      pipelineVersion={report.pipeline_version || cdcDetail.pipeline_version}
      onBack={() => router.push(`/analyse/${clientIdNum}`)}
      onReanalyse={() => handleAnalyse(true)}
      onDelete={handleDeleteCdc}
      onRefresh={reload}
      reanalysing={analysing}
    />
  );
}
