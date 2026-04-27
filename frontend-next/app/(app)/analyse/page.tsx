"use client";

import * as React from "react";
import { Loader2, Play, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { UploadDropzone } from "@/components/upload-dropzone";
import { ContextPanel } from "@/components/context-panel";
import { NotificationsBell } from "@/components/notifications-bell";
import { useToast } from "@/components/ui/use-toast";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api-client";
import { PipelineBadges } from "@/components/pipeline-badges";
import { ClientsSidebar } from "./components/clients-sidebar";
import { CdcReport } from "./components/cdc-report";
import type {
  AnalysisJob,
  Cdc,
  CdcDetail,
  Client,
  ClientCdcsResponse,
  Report,
  Requirement,
  AnalysisSummary,
} from "@/lib/types";

type CdcsState = {
  clientId: number;
  pipelineVersion: string;
  cdcs: Cdc[];
};

export default function AnalysePage() {
  const { toast } = useToast();

  const [clients, setClients] = React.useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = React.useState<number | null>(null);
  const [cdcsByClient, setCdcsByClient] = React.useState<Record<number, CdcsState>>({});
  const [selectedCdcId, setSelectedCdcId] = React.useState<number | null>(null);
  const [cdcDetail, setCdcDetail] = React.useState<CdcDetail | null>(null);
  const [report, setReport] = React.useState<Report | null>(null);

  const [loadingClients, setLoadingClients] = React.useState(true);
  const [loadingCdcs, setLoadingCdcs] = React.useState(false);
  const [loadingDetail, setLoadingDetail] = React.useState(false);
  const [analysing, setAnalysing] = React.useState(false);
  const [uploading, setUploading] = React.useState(false);

  const reloadClients = React.useCallback(async () => {
    setLoadingClients(true);
    try {
      const list = await api.clients();
      setClients(list);
      if (list.length > 0 && selectedClientId === null) {
        setSelectedClientId(list[0]!.id);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur chargement clients";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setLoadingClients(false);
    }
  }, [selectedClientId, toast]);

  const reloadCdcs = React.useCallback(
    async (clientId: number): Promise<ClientCdcsResponse | null> => {
      setLoadingCdcs(true);
      try {
        const data = await api.clientCdcs(clientId);
        setCdcsByClient((prev) => ({
          ...prev,
          [clientId]: {
            clientId,
            pipelineVersion: data.pipeline_version,
            cdcs: data.cdcs,
          },
        }));
        return data;
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Erreur chargement CDCs";
        toast({ title: "Erreur", description: msg, variant: "destructive" });
        return null;
      } finally {
        setLoadingCdcs(false);
      }
    },
    [toast]
  );

  const reloadCdcDetail = React.useCallback(
    async (cdcId: number): Promise<CdcDetail | null> => {
      setLoadingDetail(true);
      try {
        const detail = await api.cdc(cdcId);
        setCdcDetail(detail);
        setReport(buildReportFromDetail(detail));
        return detail;
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Erreur chargement CDC";
        toast({ title: "Erreur", description: msg, variant: "destructive" });
        return null;
      } finally {
        setLoadingDetail(false);
      }
    },
    [toast]
  );

  // Initial load
  React.useEffect(() => {
    void reloadClients();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load CDCs when client changes
  React.useEffect(() => {
    if (selectedClientId === null) return;
    void reloadCdcs(selectedClientId);
    setSelectedCdcId(null);
    setCdcDetail(null);
    setReport(null);
  }, [selectedClientId, reloadCdcs]);

  // Load CDC detail when selection changes
  React.useEffect(() => {
    if (selectedCdcId === null) {
      setCdcDetail(null);
      setReport(null);
      return;
    }
    void reloadCdcDetail(selectedCdcId);
  }, [selectedCdcId, reloadCdcDetail]);

  const currentState = selectedClientId !== null ? cdcsByClient[selectedClientId] : undefined;
  const currentCdcs = currentState?.cdcs ?? [];
  const cdcCounts = React.useMemo<Record<number, number>>(() => {
    const out: Record<number, number> = {};
    for (const s of Object.values(cdcsByClient)) {
      out[s.clientId] = s.cdcs.length;
    }
    return out;
  }, [cdcsByClient]);

  const handleCreateClient = async (name: string) => {
    try {
      const c = await api.createClient(name);
      await reloadClients();
      setSelectedClientId(c.id);
      toast({ title: "Client créé", description: name });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur création client";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  const handleDeleteClient = async (id: number) => {
    try {
      await api.deleteClient(id);
      if (selectedClientId === id) {
        setSelectedClientId(null);
        setSelectedCdcId(null);
      }
      await reloadClients();
      toast({ title: "Client supprimé" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur suppression client";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  const handleUploadCdc = async (file: File) => {
    if (selectedClientId === null) return;
    setUploading(true);
    try {
      const created = await api.uploadCdc(selectedClientId, file);
      const refreshed = await reloadCdcs(selectedClientId);
      const found =
        refreshed?.cdcs.find((c) => c.id === created.id) ||
        refreshed?.cdcs[refreshed.cdcs.length - 1];
      if (found) setSelectedCdcId(found.id);
      toast({ title: "CDC importé", description: file.name });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur d'upload";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteCdc = async () => {
    if (selectedCdcId === null) return;
    try {
      await api.deleteCdc(selectedCdcId);
      setSelectedCdcId(null);
      if (selectedClientId !== null) await reloadCdcs(selectedClientId);
      toast({ title: "CDC supprimé" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur suppression CDC";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  // Réf. du job en cours pour permettre l'annulation logique du polling
  // (changement de CDC, démontage du composant).
  const pollingRef = React.useRef<{
    jobId: number;
    cdcId: number;
    cancelled: boolean;
  } | null>(null);

  const finishAnalyseFromJob = React.useCallback(
    async (job: AnalysisJob) => {
      if (job.status === "done" && job.report) {
        const rpt = job.report;
        const requirements: Requirement[] = rpt.requirements || [];
        const summary: AnalysisSummary = normalizeSummary(
          rpt.summary,
          requirements
        );
        setReport({
          filename: rpt.filename,
          summary,
          requirements,
          pipeline_version: rpt.pipeline_version,
          analysis_id: rpt.analysis_id ?? job.analysis_id ?? undefined,
          cdc_id: rpt.cdc_id ?? job.cdc_id,
        });
        if (selectedClientId !== null) await reloadCdcs(selectedClientId);
        await reloadCdcDetail(job.cdc_id);
        toast({ title: "Analyse terminée" });
      } else if (job.status === "error") {
        toast({
          title: "Erreur d'analyse",
          description: job.error || "Échec de l'analyse.",
          variant: "destructive",
        });
      }
    },
    [reloadCdcs, reloadCdcDetail, selectedClientId, toast]
  );

  const pollAnalysisJob = React.useCallback(
    async (jobId: number, cdcId: number) => {
      const ref = { jobId, cdcId, cancelled: false };
      pollingRef.current = ref;
      const POLL_INTERVAL_MS = 3000;
      const MAX_CONSECUTIVE_ERRORS = 5; // tolérer les coupures réseau passagères
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
            const msg =
              err instanceof Error ? err.message : "Erreur de polling";
            toast({
              title: "Suivi de l'analyse interrompu",
              description: `${msg} (${MAX_CONSECUTIVE_ERRORS} échecs consécutifs). L'analyse continue en arrière-plan — rafraîchissez la page pour reprendre le suivi.`,
              variant: "destructive",
            });
            return;
          }
          // Erreur transitoire : on backoff puis on réessaye au tour suivant.
        }
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      }
    },
    [finishAnalyseFromJob, toast]
  );

  const handleAnalyse = async (force = false) => {
    if (selectedCdcId === null) return;
    setAnalysing(true);
    const t = toast({
      title: "Analyse en cours",
      description:
        "Le traitement tourne en arrière-plan. Vous pouvez fermer ou "
        + "naviguer ailleurs, le rapport s'affichera à votre retour.",
    });
    try {
      const job = await api.analyseCdc(selectedCdcId, force);
      if (job.status === "done" && job.report) {
        await finishAnalyseFromJob(job);
      } else if (job.status === "error") {
        await finishAnalyseFromJob(job);
      } else {
        await pollAnalysisJob(job.id, selectedCdcId);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur d'analyse";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      t.dismiss();
      setAnalysing(false);
    }
  };

  // À la sélection d'un CDC, reprendre un éventuel job actif (queued/running)
  // pour ce CDC. Permet de retrouver l'analyse en cours après un refresh ou
  // une navigation.
  React.useEffect(() => {
    if (selectedCdcId === null) return;
    let cancelled = false;
    (async () => {
      try {
        const jobs = await api.analysisJobs({
          statusFilter: "queued,running",
          cdcId: selectedCdcId,
        });
        if (cancelled) return;
        if (jobs.length > 0) {
          const job = jobs[0]!;
          setAnalysing(true);
          toast({
            title: "Analyse en cours",
            description: "Reprise du suivi de l'analyse en arrière-plan.",
          });
          await pollAnalysisJob(job.id, selectedCdcId);
          if (!cancelled) setAnalysing(false);
        }
      } catch {
        // silencieux : pas bloquant
      }
    })();
    return () => {
      cancelled = true;
      if (pollingRef.current) pollingRef.current.cancelled = true;
    };
  }, [selectedCdcId, pollAnalysisJob, toast]);

  // Context panel: clients list
  const contextPanelContent = (
    <ContextPanel>
      <ClientsSidebar
        clients={clients}
        selectedId={selectedClientId}
        onSelect={setSelectedClientId}
        onCreate={handleCreateClient}
        onDelete={handleDeleteClient}
        cdcCounts={cdcCounts}
      />
    </ContextPanel>
  );

  // Render work area
  if (loadingClients) {
    return (
      <>
        {contextPanelContent}
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Chargement...
        </div>
      </>
    );
  }

  if (selectedClientId === null) {
    return (
      <>
        {contextPanelContent}
        <div className="flex h-full flex-col">
          <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border px-4 md:px-6">
            <div className="text-sm font-semibold">
              Analyse
              <span className="mx-1.5 text-muted-foreground">—</span>
              <span className="font-normal text-muted-foreground">
                Aucun client sélectionné
              </span>
            </div>
            <NotificationsBell />
          </header>
          <div className="flex flex-1 items-center justify-center p-6 md:p-10">
            <div className="max-w-md text-center">
              <h2 className="mb-2 text-lg font-semibold">
                Sélectionnez un client
              </h2>
              <p className="text-sm text-muted-foreground">
                Choisissez un client dans le panneau de gauche ou créez-en un
                nouveau pour commencer à analyser des cahiers des charges.
              </p>
            </div>
          </div>
        </div>
      </>
    );
  }

  // Client selected but no CDC selected: show list of CDCs or upload zone
  if (selectedCdcId === null) {
    return (
      <>
        {contextPanelContent}
        <div className="flex h-full flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border px-4 md:px-6">
          <div className="min-w-0 flex-1 truncate text-sm font-semibold">
            Analyse
            <span className="mx-1.5 text-muted-foreground">—</span>
            <span className="font-normal text-muted-foreground">
              {clients.find((c) => c.id === selectedClientId)?.name ||
                "Client"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <PipelineBadges
              version={currentState?.pipelineVersion}
              compact
              className="hidden md:flex"
            />
            <NotificationsBell />
          </div>
        </header>

        <div className="flex-1 overflow-auto p-4 md:p-6">
          {loadingCdcs ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Chargement des CDCs...
            </div>
          ) : currentCdcs.length === 0 ? (
            <div className="mx-auto max-w-xl">
              <h2 className="mb-3 text-lg font-semibold">
                Importer un cahier des charges
              </h2>
              <p className="mb-4 text-sm text-muted-foreground">
                Formats acceptés : PDF, DOCX, TXT, MD. Taille maximale 50 Mo.
              </p>
              <UploadDropzone
                accept=".pdf,.docx,.txt,.md"
                disabled={uploading}
                onFile={(f) => void handleUploadCdc(f)}
                title={
                  uploading ? "Import en cours..." : "Déposez le CDC ici"
                }
              />
            </div>
          ) : (
            <div>
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-lg font-semibold">
                  Cahiers des charges ({currentCdcs.length})
                </h2>
                <label
                  className={cn(
                    "inline-flex cursor-pointer items-center gap-2 rounded-md border border-border bg-background px-3 py-1.5 text-sm hover:bg-muted",
                    uploading && "pointer-events-none opacity-60"
                  )}
                >
                  <Upload className="h-4 w-4" />
                  {uploading ? "Import..." : "Ajouter un CDC"}
                  <input
                    type="file"
                    className="hidden"
                    accept=".pdf,.docx,.txt,.md"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) void handleUploadCdc(f);
                      e.target.value = "";
                    }}
                  />
                </label>
              </div>
              <ul className="grid gap-2">
                {currentCdcs.map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedCdcId(c.id)}
                      className="group flex w-full min-w-0 items-center gap-3 rounded-2xl border border-soft bg-card px-4 py-3 text-left shadow-tinted-sm transition-all hover:-translate-y-0.5 hover:border-accent/30 hover:shadow-tinted-md"
                    >
                      <span className="min-w-0 flex-1 truncate text-sm font-medium">
                        {c.filename}
                      </span>
                      <StatusPill status={c.status} />
                      {typeof c.coverage_percent === "number" ? (
                        <Badge variant="secondary" className="tabular-nums">
                          {c.coverage_percent.toFixed(0)}%
                        </Badge>
                      ) : null}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        </div>
      </>
    );
  }

  // CDC selected
  if (loadingDetail) {
    return (
      <>
        {contextPanelContent}
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Chargement du CDC...
        </div>
      </>
    );
  }

  if (!cdcDetail) {
    return (
      <>
        {contextPanelContent}
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          CDC introuvable.
        </div>
      </>
    );
  }

  if (!report) {
    // No analysis yet — show "launch" button
    return (
      <>
        {contextPanelContent}
        <div className="flex h-full flex-col">
          <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border px-4 md:px-6">
            <div className="min-w-0 flex-1 truncate text-sm font-semibold">
              Analyse
              <span className="mx-1.5 text-muted-foreground">—</span>
              <span className="font-normal text-muted-foreground">
                {cdcDetail.cdc.filename}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <StatusPill status={cdcDetail.status} />
              <NotificationsBell />
            </div>
          </header>
          <div className="flex flex-1 items-center justify-center p-6 md:p-10">
            <div className="max-w-md text-center">
              <h2 className="mb-2 text-lg font-semibold">Analyse non réalisée</h2>
              <p className="mb-6 text-sm text-muted-foreground">
                Lancez l'analyse automatique pour extraire les exigences et
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
      </>
    );
  }

  return (
    <>
      {contextPanelContent}
      <CdcReport
        cdcId={selectedCdcId}
        analysisId={report.analysis_id ?? cdcDetail.analysis?.id ?? null}
        filename={report.filename}
        summary={report.summary}
        requirements={report.requirements}
        pipelineVersion={report.pipeline_version || currentState?.pipelineVersion}
        onReanalyse={() => handleAnalyse(true)}
        onDelete={handleDeleteCdc}
        onRefresh={async () => {
          if (selectedCdcId !== null) {
            await reloadCdcDetail(selectedCdcId);
          }
        }}
        reanalysing={analysing}
      />
    </>
  );
}

function normalizeSummary(
  raw: Partial<AnalysisSummary> | null | undefined,
  requirements: Requirement[]
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
  return { total, covered, partial, missing, ambiguous, coverage_percent: coverage_percent as number };
}

function buildReportFromDetail(detail: CdcDetail): Report | null {
  const a = detail.analysis;
  if (!a) return null;
  const report = a.report || {};
  const requirements: Requirement[] = Array.isArray(report.requirements)
    ? (report.requirements as Requirement[])
    : [];
  // Prefer report.summary, then fall back to flat columns on the analysis row.
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
    requirements
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

function StatusPill({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string }> = {
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
  const m = map[status] || {
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
