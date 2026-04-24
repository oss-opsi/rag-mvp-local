"use client";

import * as React from "react";
import { Loader2, Play, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { UploadDropzone } from "@/components/upload-dropzone";
import { useProvideContextPanel } from "@/components/context-panel";
import { useToast } from "@/components/ui/use-toast";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api-client";
import { PipelineBadges } from "@/components/pipeline-badges";
import { ClientsSidebar } from "./components/clients-sidebar";
import { CdcReport } from "./components/cdc-report";
import type {
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
        if (detail.analysis) {
          const a = detail.analysis;
          const rpt: Report = {
            filename: detail.cdc.filename,
            summary: a.summary,
            requirements: a.requirements,
            pipeline_version: a.pipeline_version,
            analysis_id: a.id,
            cdc_id: detail.cdc.id,
          };
          setReport(rpt);
        } else {
          setReport(null);
        }
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

  const handleAnalyse = async (force = false) => {
    if (selectedCdcId === null) return;
    setAnalysing(true);
    const t = toast({
      title: "Analyse en cours",
      description:
        "Cela peut prendre plusieurs minutes, ne fermez pas l'onglet.",
    });
    try {
      const rpt = await api.analyseCdc(selectedCdcId, force);
      // Normalize possible requirement shape
      const requirements: Requirement[] = rpt.requirements || [];
      const summary: AnalysisSummary = rpt.summary;
      setReport({
        filename: rpt.filename,
        summary,
        requirements,
        pipeline_version: rpt.pipeline_version,
        analysis_id: rpt.analysis_id,
        cdc_id: rpt.cdc_id,
      });
      if (selectedClientId !== null) await reloadCdcs(selectedClientId);
      await reloadCdcDetail(selectedCdcId);
      toast({ title: "Analyse terminée" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur d'analyse";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      t.dismiss();
      setAnalysing(false);
    }
  };

  // Context panel: clients list
  useProvideContextPanel(
    <ClientsSidebar
      clients={clients}
      selectedId={selectedClientId}
      onSelect={setSelectedClientId}
      onCreate={handleCreateClient}
      onDelete={handleDeleteClient}
      cdcCounts={cdcCounts}
    />
  );

  // Render work area
  if (loadingClients) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Chargement...
      </div>
    );
  }

  if (selectedClientId === null) {
    return (
      <div className="flex h-full flex-col">
        <header className="flex h-14 shrink-0 items-center border-b border-border px-6">
          <h1 className="text-base font-semibold">Analyse d'écarts</h1>
        </header>
        <div className="flex flex-1 items-center justify-center p-10">
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
    );
  }

  // Client selected but no CDC selected: show list of CDCs or upload zone
  if (selectedCdcId === null) {
    return (
      <div className="flex h-full flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-6">
          <h1 className="text-base font-semibold">
            {clients.find((c) => c.id === selectedClientId)?.name ||
              "Client"}{" "}
            — CDCs
          </h1>
          <PipelineBadges
            version={currentState?.pipelineVersion}
            compact
            className="hidden md:flex"
          />
        </header>

        <div className="flex-1 overflow-auto p-6">
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
              <ScrollArea className="rounded-md border border-border">
                <ul>
                  {currentCdcs.map((c) => (
                    <li
                      key={c.id}
                      className="flex h-11 items-center justify-between gap-3 border-b border-border px-4 last:border-b-0"
                    >
                      <button
                        type="button"
                        onClick={() => setSelectedCdcId(c.id)}
                        className="flex min-w-0 flex-1 items-center gap-3 text-left"
                      >
                        <span className="truncate text-sm font-medium">
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
              </ScrollArea>
            </div>
          )}
        </div>
      </div>
    );
  }

  // CDC selected
  if (loadingDetail) {
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

  if (!report) {
    // No analysis yet — show "launch" button
    return (
      <div className="flex h-full flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-6">
          <h1 className="truncate text-base font-semibold">
            {cdcDetail.cdc.filename}
          </h1>
          <StatusPill status={cdcDetail.status} />
        </header>
        <div className="flex flex-1 items-center justify-center p-10">
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
    );
  }

  return (
    <CdcReport
      filename={report.filename}
      summary={report.summary}
      requirements={report.requirements}
      pipelineVersion={report.pipeline_version || currentState?.pipelineVersion}
      onReanalyse={() => handleAnalyse(true)}
      onDelete={handleDeleteCdc}
      reanalysing={analysing}
    />
  );
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    pending: { label: "En attente", cls: "bg-muted text-muted-foreground" },
    uploaded: { label: "Importé", cls: "bg-muted text-muted-foreground" },
    parsing: { label: "Parsing", cls: "bg-warning/10 text-warning" },
    analysing: { label: "Analyse", cls: "bg-warning/10 text-warning" },
    analyzed: { label: "Analysé", cls: "bg-success/10 text-success" },
    error: { label: "Erreur", cls: "bg-danger/10 text-danger" },
  };
  const m = map[status] || { label: status, cls: "bg-muted text-muted-foreground" };
  return (
    <span className={cn("rounded px-2 py-0.5 text-xs font-medium", m.cls)}>
      {m.label}
    </span>
  );
}
