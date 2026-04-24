"use client";

import * as React from "react";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Loader2,
  Trash2,
  Upload,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
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
import { UploadDropzone } from "@/components/upload-dropzone";
import { ContextPanel } from "@/components/context-panel";
import { useToast } from "@/components/ui/use-toast";
import { api } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { CollectionInfo, IngestionJob } from "@/lib/types";

const POLL_INTERVAL_MS = 2000;
const COMPLETED_WINDOW_MIN = 5; // keep recently-finished jobs visible 5 min

export default function DocumentsPage() {
  const { toast } = useToast();
  const [info, setInfo] = React.useState<CollectionInfo | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [uploading, setUploading] = React.useState(false);
  const [jobs, setJobs] = React.useState<IngestionJob[]>([]);
  // Track which finished jobs we've already toasted so we don't double-notify.
  const toastedRef = React.useRef<Set<number>>(new Set());

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
      // Fetch the last 20 jobs (all statuses) so we still see recent finished.
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
      (j) => j.status === "queued" || j.status === "running"
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
      // Optimistic insert so the user sees the job instantly.
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
    (j) => j.status === "queued" || j.status === "running"
  );

  return (
    <div className="flex h-full flex-col">
      <ContextPanel>
        <div className="flex h-full flex-col">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">Collection</h2>
          </div>
          <div className="flex flex-1 flex-col gap-4 p-4">
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-md border border-border p-3">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Documents
                </div>
                <div className="mt-1 text-xl font-semibold tabular-nums">
                  {info?.total_documents ?? "—"}
                </div>
              </div>
              <div className="rounded-md border border-border p-3">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Chunks
                </div>
                <div className="mt-1 text-xl font-semibold tabular-nums">
                  {info?.total_chunks ?? "—"}
                </div>
              </div>
            </div>
            {hasActive ? (
              <div className="rounded-md border border-accent/30 bg-accent/5 p-3 text-xs text-muted-foreground">
                <div className="flex items-center gap-2 font-medium text-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Indexation en cours
                </div>
                <p className="mt-1">
                  Vous pouvez continuer à utiliser l'application — le résultat
                  s'affichera ici automatiquement.
                </p>
              </div>
            ) : null}
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="destructive" className="w-full" disabled={loading}>
                  <Trash2 className="mr-2 h-4 w-4" />
                  Tout réindexer
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Réinitialiser la collection ?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Tous les documents et chunks seront supprimés définitivement.
                    Vous devrez ré-importer vos fichiers.
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
      </ContextPanel>
      <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border px-6">
        <h1 className="text-base font-semibold">Documents indexés</h1>
        <label
          className={cn(
            "inline-flex cursor-pointer items-center gap-2 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-foreground hover:bg-accent/90",
            uploading && "pointer-events-none opacity-60"
          )}
        >
          <Upload className="h-4 w-4" />
          {uploading ? "Envoi..." : "Importer"}
          <input
            type="file"
            className="hidden"
            accept=".pdf,.docx,.txt,.md"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void handleUpload(f);
              e.target.value = "";
            }}
          />
        </label>
      </header>

      <div className="flex-1 overflow-auto">
        <div className="flex flex-col gap-6 p-6">
          <PipelineBadges />

          {visibleJobs.length > 0 ? (
            <section>
              <h2 className="mb-3 text-sm font-semibold">
                Indexations{hasActive ? " en cours" : " récentes"}
              </h2>
              <div className="flex flex-col gap-2">
                {visibleJobs.map((j) => (
                  <JobRow key={j.id} job={j} />
                ))}
              </div>
            </section>
          ) : null}

          <section>
            <h2 className="mb-3 text-sm font-semibold">Documents</h2>
            {loading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Chargement...
              </div>
            ) : !info || info.documents.length === 0 ? (
              <div className="mx-auto w-full max-w-xl">
                <p className="mb-3 text-sm text-muted-foreground">
                  Aucun document indexé pour l'instant.
                </p>
                <UploadDropzone
                  accept=".pdf,.docx,.txt,.md"
                  disabled={uploading}
                  onFile={(f) => void handleUpload(f)}
                />
              </div>
            ) : (
              <ScrollArea className="rounded-md border border-border">
                <table className="w-full text-sm">
                  <thead className="border-b border-border bg-muted/40 text-left text-xs uppercase tracking-wider text-muted-foreground">
                    <tr>
                      <th className="px-4 py-2 font-medium">Nom</th>
                      <th className="w-32 px-4 py-2 text-right font-medium">
                        Chunks
                      </th>
                      <th className="w-32 px-4 py-2 text-right font-medium">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {info.documents.map((d) => (
                      <tr
                        key={d.source}
                        className="h-11 border-b border-border last:border-b-0"
                      >
                        <td className="px-4 py-2">
                          <span className="font-medium">{d.source}</span>
                        </td>
                        <td className="px-4 py-2 text-right tabular-nums">
                          {d.chunks}
                        </td>
                        <td className="px-4 py-2 text-right">
                          <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <Button
                                variant="ghost"
                                size="sm"
                                aria-label="Supprimer"
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                              <AlertDialogHeader>
                                <AlertDialogTitle>
                                  Supprimer {d.source} ?
                                </AlertDialogTitle>
                                <AlertDialogDescription>
                                  Tous les chunks associés seront retirés de
                                  l'index.
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>Annuler</AlertDialogCancel>
                                <AlertDialogAction
                                  onClick={() => void handleDelete(d.source)}
                                  className="bg-danger text-danger-foreground hover:bg-danger/90"
                                >
                                  Supprimer
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </ScrollArea>
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
    startedMs ? Date.now() - startedMs : 0
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
            l'application.
          </div>
        ) : null}
      </div>
      <div className="shrink-0">{badge}</div>
    </div>
  );
}
