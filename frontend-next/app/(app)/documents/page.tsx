"use client";

import * as React from "react";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Loader2,
  RefreshCw,
  Upload,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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
import { PipelineBadges } from "@/components/pipeline-badges";
import { PipelineInfoCard } from "@/components/pipeline-info-card";
import { UploadDropzone } from "@/components/upload-dropzone";
import { ContextPanel } from "@/components/context-panel";
import { Topbar } from "@/components/topbar";
import { FileTile } from "@/components/file-tile";
import { useToast } from "@/components/ui/use-toast";
import { useAppShell } from "@/components/app-shell-context";
import { api } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { CollectionInfo, IngestionJob } from "@/lib/types";

const POLL_INTERVAL_MS = 2000;
const COMPLETED_WINDOW_MIN = 5; // keep recently-finished jobs visible 5 min

export default function DocumentsPage() {
  const { toast } = useToast();
  const { user } = useAppShell();
  const [info, setInfo] = React.useState<CollectionInfo | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [uploading, setUploading] = React.useState(false);
  const [jobs, setJobs] = React.useState<IngestionJob[]>([]);
  // Track which finished jobs we've already toasted so we don't double-notify.
  const toastedRef = React.useRef<Set<number>>(new Set());
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  const username = user?.name || user?.user_id || "moi";
  const initial = (username.charAt(0) || "·").toUpperCase();

  const reload = React.useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.collectionInfo();
      setInfo(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  const reloadJobs = React.useCallback(async () => {
    try {
      const list = await api.ingestionJobs();
      setJobs(list);
      return list;
    } catch {
      // Silent — polling shouldn't spam toasts on transient errors.
      return null;
    }
  }, []);

  // Initial load
  React.useEffect(() => {
    void reload();
    void reloadJobs();
  }, [reload, reloadJobs]);

  // Polling: while any job is active, poll every 2s. Otherwise stop.
  React.useEffect(() => {
    const hasActive = jobs.some(
      (j) => j.status === "queued" || j.status === "running",
    );
    if (!hasActive) return;
    const t = window.setInterval(() => {
      void reloadJobs();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(t);
  }, [jobs, reloadJobs]);

  // Detect newly-finished jobs → toast + refresh the documents list once.
  React.useEffect(() => {
    let changed = false;
    for (const j of jobs) {
      if (j.status !== "done" && j.status !== "error") continue;
      if (toastedRef.current.has(j.id)) continue;
      toastedRef.current.add(j.id);
      changed = true;
      if (j.status === "done") {
        toast({
          title: "Indexation terminée",
          description: `${j.filename} — ${j.chunk_count ?? 0} fragments`,
        });
      } else {
        toast({
          title: "Échec d'indexation",
          description: `${j.filename} : ${j.error || "Erreur inconnue"}`,
          variant: "destructive",
        });
      }
    }
    if (changed) void reload();
  }, [jobs, reload, toast]);

  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      const res = await api.uploadDocument(file);
      toast({
        title: "Mis en file d'indexation",
        description: `${file.name} — suivi ci-dessous`,
      });
      const optimistic: IngestionJob = {
        id: res.job_id,
        user_id: "",
        filename: res.filename,
        status: res.status,
        chunk_count: null,
        error: null,
        created_at: new Date().toISOString(),
        started_at: null,
        finished_at: null,
      };
      setJobs((prev) => {
        if (prev.some((j) => j.id === optimistic.id)) return prev;
        return [optimistic, ...prev];
      });
      void reloadJobs();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur upload";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (source: string) => {
    try {
      await api.deleteDocument(source);
      await reload();
      toast({ title: "Document supprimé", description: source });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  const handleReset = async () => {
    try {
      await api.resetCollection();
      await reload();
      toast({ title: "Collection réinitialisée" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  const openPicker = () => {
    if (uploading) return;
    fileInputRef.current?.click();
  };

  // Jobs to show: all active + finished within COMPLETED_WINDOW_MIN minutes.
  const visibleJobs = React.useMemo(() => {
    const now = Date.now();
    return jobs.filter((j) => {
      if (j.status === "queued" || j.status === "running") return true;
      const ts = j.finished_at ? Date.parse(j.finished_at) : now;
      return now - ts < COMPLETED_WINDOW_MIN * 60_000;
    });
  }, [jobs]);

  const hasActive = jobs.some(
    (j) => j.status === "queued" || j.status === "running",
  );

  const docs = info?.documents ?? [];
  const totalDocs = info?.total_documents ?? docs.length;
  const totalChunks =
    info?.total_chunks ?? docs.reduce((sum, d) => sum + (d.chunks || 0), 0);

  return (
    <div className="flex h-full flex-col">
      {/* ──────────── Context panel (gauche) ──────────── */}
      <ContextPanel>
        <div className="flex h-full flex-col">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Collections (1)
            </h2>
          </div>
          <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-4">
            {/* Carte client active */}
            <div className="flex items-center gap-3 rounded-md border border-accent/40 bg-accent/5 p-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-sm font-semibold text-accent-foreground">
                {initial}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{username}</p>
                <p className="text-xs text-muted-foreground tabular-nums">
                  {totalDocs} docs · {totalChunks} chunks
                </p>
              </div>
            </div>

            {/* Infos pipeline */}
            <div>
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Infos pipeline
              </h3>
              <PipelineInfoCard />
            </div>

            {/* Indexation en cours */}
            {hasActive ? (
              <div className="rounded-md border border-warning/30 bg-warning/5 p-3 text-xs text-muted-foreground">
                <div className="flex items-center gap-2 font-medium text-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-warning" />
                  Indexation en cours
                </div>
                <p className="mt-1">
                  Vous pouvez continuer à utiliser l&apos;application — le
                  résultat s&apos;affichera ici automatiquement.
                </p>
              </div>
            ) : null}

            {/* Action destructive en bas */}
            <div className="mt-auto">
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    variant="outline"
                    className="w-full text-danger hover:bg-danger/5 hover:text-danger"
                    disabled={loading}
                  >
                    Réinitialiser la collection
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>
                      Réinitialiser la collection ?
                    </AlertDialogTitle>
                    <AlertDialogDescription>
                      Tous les documents et chunks seront supprimés
                      définitivement. Vous devrez ré-importer vos fichiers.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Annuler</AlertDialogCancel>
                    <AlertDialogAction
                      onClick={() => void handleReset()}
                      className="bg-danger text-danger-foreground hover:bg-danger/90"
                    >
                      Confirmer
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          </div>
        </div>
      </ContextPanel>

      {/* ──────────── Topbar ──────────── */}
      <Topbar
        breadcrumb={
          <>
            Indexation <span className="mx-1.5 text-muted-foreground">—</span>
            <span className="font-normal text-muted-foreground">
              {username}
            </span>
          </>
        }
      >
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void reload();
            void reloadJobs();
          }}
          disabled={loading}
          title="Actualiser la liste des documents et des indexations"
          aria-label="Actualiser"
        >
          <RefreshCw
            className={cn(
              "h-3.5 w-3.5 sm:mr-1.5",
              loading && "animate-spin",
            )}
          />
          <span className="hidden sm:inline">Actualiser</span>
        </Button>
        <Button
          size="sm"
          onClick={openPicker}
          disabled={uploading}
          aria-label="Importer"
        >
          <Upload className="h-3.5 w-3.5 sm:mr-1.5" />
          <span className="hidden sm:inline">
            {uploading ? "Envoi..." : "Importer"}
          </span>
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          accept=".pdf,.docx,.txt,.md"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void handleUpload(f);
            e.target.value = "";
          }}
        />
      </Topbar>

      {/* ──────────── Zone de travail ──────────── */}
      <div className="flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-5 md:p-6">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">
              Ajouter des documents
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              PDF, DOCX, TXT, MD — 200 Mo max par fichier
            </p>
          </div>

          <UploadDropzone
            accept=".pdf,.docx,.txt,.md"
            disabled={uploading}
            onFile={(f) => void handleUpload(f)}
            title="Glisser-déposer vos fichiers ici"
            hint="ou cliquez pour parcourir"
          />

          <PipelineBadges compact />

          {/* Jobs actifs / récents */}
          {visibleJobs.length > 0 ? (
            <section>
              <h3 className="mb-3 text-sm font-semibold">
                Indexations{hasActive ? " en cours" : " récentes"}
              </h3>
              <div className="flex flex-col gap-2">
                {visibleJobs.map((j) => (
                  <JobRow key={j.id} job={j} />
                ))}
              </div>
            </section>
          ) : null}

          {/* Documents indexés — grille */}
          <section>
            <div className="mb-3 flex items-baseline justify-between">
              <h3 className="text-sm font-semibold">
                Documents indexés
                {docs.length > 0 ? (
                  <span className="ml-2 text-xs font-normal text-muted-foreground tabular-nums">
                    {docs.length}
                  </span>
                ) : null}
              </h3>
            </div>
            {loading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Chargement...
              </div>
            ) : docs.length === 0 ? (
              <div className="rounded-md border border-dashed border-border bg-muted/20 p-8 text-center">
                <p className="text-sm text-muted-foreground">
                  Aucun document indexé pour l&apos;instant. Déposez un fichier
                  ci-dessus pour démarrer.
                </p>
              </div>
            ) : (
              <div
                className={cn(
                  "grid gap-3",
                  "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
                )}
              >
                {docs.map((d) => (
                  <FileTile
                    key={d.source}
                    filename={d.source}
                    chunks={d.chunks}
                    onDelete={() => void handleDelete(d.source)}
                  />
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function JobRow({ job }: { job: IngestionJob }) {
  const startedMs = job.started_at ? Date.parse(job.started_at) : null;
  const [elapsed, setElapsed] = React.useState<number>(() =>
    startedMs ? Date.now() - startedMs : 0,
  );
  const isRunning = job.status === "running";
  React.useEffect(() => {
    if (!isRunning || !startedMs) return;
    const t = window.setInterval(() => {
      setElapsed(Date.now() - startedMs);
    }, 1000);
    return () => window.clearInterval(t);
  }, [isRunning, startedMs]);

  const sec = Math.max(0, Math.floor(elapsed / 1000));
  const mm = Math.floor(sec / 60);
  const ss = String(sec % 60).padStart(2, "0");
  const elapsedLabel = `${mm}:${ss}`;

  const badge = (() => {
    switch (job.status) {
      case "queued":
        return (
          <Badge variant="secondary" className="gap-1">
            <Clock className="h-3 w-3" />
            En file
          </Badge>
        );
      case "running":
        return (
          <Badge variant="warning" className="gap-1">
            <Loader2 className="h-3 w-3 animate-spin" />
            Indexation · {elapsedLabel}
          </Badge>
        );
      case "done":
        return (
          <Badge variant="success" className="gap-1">
            <CheckCircle2 className="h-3 w-3" />
            Terminé · {job.chunk_count ?? 0} fragments
          </Badge>
        );
      case "error":
        return (
          <Badge variant="destructive" className="gap-1">
            <AlertCircle className="h-3 w-3" />
            Erreur
          </Badge>
        );
    }
  })();

  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-border bg-background px-4 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{job.filename}</div>
        {job.status === "error" && job.error ? (
          <div className="mt-0.5 truncate text-xs text-danger">{job.error}</div>
        ) : job.status === "running" ? (
          <div className="mt-0.5 text-xs text-muted-foreground">
            Calcul des embeddings en cours — vous pouvez continuer à utiliser
            l&apos;application.
          </div>
        ) : null}
      </div>
      <div className="shrink-0">{badge}</div>
    </div>
  );
}
