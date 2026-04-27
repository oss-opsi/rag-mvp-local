"use client";

import * as React from "react";
import {
  Activity,
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Clock,
  Database,
  Edit3,
  Loader2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  XCircle,
  Zap,
} from "lucide-react";
import { Topbar } from "@/components/topbar";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { useToast } from "@/components/ui/use-toast";
import { useAppShell } from "@/components/app-shell-context";
import { api } from "@/lib/api-client";
import { cn, formatDateTime } from "@/lib/utils";
import type {
  QdrantCollectionStat,
  RefreshJob,
  RefreshJobStatus,
  Schedule,
} from "@/lib/types";

// ---------------------------------------------------------------------------
// Constantes
// ---------------------------------------------------------------------------

const PUBLIC_SOURCES = [
  { id: "boss", label: "BOSS" },
  { id: "urssaf", label: "URSSAF" },
  { id: "dsn_info", label: "DSN-info" },
  { id: "service_public", label: "Service-public" },
] as const;

const STATUS_META: Record<
  RefreshJobStatus,
  { label: string; cls: string }
> = {
  queued: {
    label: "En file",
    cls: "bg-muted text-muted-foreground",
  },
  running: {
    label: "En cours",
    cls: "bg-info/10 text-info",
  },
  success: {
    label: "Succès",
    cls: "bg-success/10 text-success",
  },
  error: {
    label: "Erreur",
    cls: "bg-danger/10 text-danger",
  },
  cancelled: {
    label: "Annulé",
    cls: "bg-warning/10 text-warning",
  },
};

const COLLECTIONS_TO_OPTIMIZE = [
  "knowledge_base",
  "referentiels_opsidium",
];

const POLL_CURRENT_MS = 10_000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function sourceLabel(source: string): string {
  if (source.startsWith("reembed_")) {
    const tail = source.replace("reembed_", "");
    if (tail === "all") return "Re-embed toutes sources";
    return `Re-embed ${tail.replace("_", "-")}`;
  }
  if (source === "optimize_qdrant") return "Optimize Qdrant";
  if (source === "integrity_check") return "Vérification intégrité";
  const m = PUBLIC_SOURCES.find((s) => s.id === source);
  return m ? m.label : source;
}

function describeCron(expr: string): string {
  // Conversion humaine de quelques formes courantes — sinon affiche brut.
  const fields = expr.trim().split(/\s+/);
  if (fields.length !== 5) return expr;
  const [m, h, dom, mon, dow] = fields;
  // Quotidien : "M H * * *"
  if (dom === "*" && mon === "*" && dow === "*") {
    return `Tous les jours à ${h.padStart(2, "0")}:${m.padStart(2, "0")}`;
  }
  // Hebdomadaire : "M H * * D"
  if (dom === "*" && mon === "*" && dow !== "*") {
    const days: Record<string, string> = {
      "0": "dimanche",
      "1": "lundi",
      "2": "mardi",
      "3": "mercredi",
      "4": "jeudi",
      "5": "vendredi",
      "6": "samedi",
      "7": "dimanche",
    };
    const name = days[dow] || `jour ${dow}`;
    return `Tous les ${name}s à ${h.padStart(2, "0")}:${m.padStart(2, "0")}`;
  }
  // Mensuel : "M H D * *"
  if (mon === "*" && dow === "*" && dom !== "*") {
    return `Le ${dom} de chaque mois à ${h.padStart(2, "0")}:${m.padStart(2, "0")}`;
  }
  return expr;
}

function elapsedSince(iso: string | null): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000));
  const mm = Math.floor(sec / 60);
  const ss = String(sec % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

function parseProgress(log: string | null): {
  done: number;
  total: number;
} | null {
  if (!log) return null;
  // Cherche un motif "cumul X/Y" (laissé par les connecteurs au fil du fetch)
  // ou "X/Y" au format simple.
  const m = log.match(/cumul\s+(\d+)\s*\/\s*(\d+)/i)
    || log.match(/(\d+)\s*\/\s*(\d+)/);
  if (!m) return null;
  const done = parseInt(m[1], 10);
  const total = parseInt(m[2], 10);
  if (!Number.isFinite(done) || !Number.isFinite(total) || total <= 0) {
    return null;
  }
  return { done, total };
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SchedulerPage() {
  const { toast } = useToast();
  const { user } = useAppShell();
  const isAdmin = user?.role === "admin";

  const [currentJob, setCurrentJob] = React.useState<RefreshJob | null>(null);
  const [schedules, setSchedules] = React.useState<Schedule[]>([]);
  const [jobs, setJobs] = React.useState<RefreshJob[]>([]);
  const [loadingSchedules, setLoadingSchedules] = React.useState(true);
  const [loadingJobs, setLoadingJobs] = React.useState(true);
  const [filterSource, setFilterSource] = React.useState<string>("");
  const [filterStatus, setFilterStatus] = React.useState<string>("");
  const [stats, setStats] = React.useState<QdrantCollectionStat[]>([]);
  const [loadingStats, setLoadingStats] = React.useState(false);

  const [createOpen, setCreateOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<Schedule | null>(null);

  // ----- Helpers de chargement -----
  const reloadCurrent = React.useCallback(async () => {
    try {
      const job = await api.getCurrentJob();
      setCurrentJob(job);
    } catch {
      // ignore
    }
  }, []);

  const reloadSchedules = React.useCallback(async () => {
    setLoadingSchedules(true);
    try {
      const list = await api.listSchedules();
      setSchedules(list);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setLoadingSchedules(false);
    }
  }, [toast]);

  const reloadJobs = React.useCallback(async () => {
    setLoadingJobs(true);
    try {
      const list = await api.listJobs({
        source: filterSource || undefined,
        status: filterStatus || undefined,
        limit: 20,
      });
      setJobs(list);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setLoadingJobs(false);
    }
  }, [filterSource, filterStatus, toast]);

  const reloadStats = React.useCallback(async () => {
    setLoadingStats(true);
    try {
      const data = await api.maintenanceQdrantStats();
      setStats(data.collections || []);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur stats Qdrant", description: msg, variant: "destructive" });
    } finally {
      setLoadingStats(false);
    }
  }, [toast]);

  React.useEffect(() => {
    void reloadCurrent();
    void reloadSchedules();
    void reloadJobs();
    void reloadStats();
  }, [reloadCurrent, reloadSchedules, reloadJobs, reloadStats]);

  // Auto-refresh job en cours toutes les 10s
  React.useEffect(() => {
    const t = window.setInterval(() => {
      void reloadCurrent();
      void reloadJobs();
    }, POLL_CURRENT_MS);
    return () => window.clearInterval(t);
  }, [reloadCurrent, reloadJobs]);

  if (!isAdmin) {
    return (
      <div className="flex h-full flex-col">
        <Topbar breadcrumb={<>Planificateur</>} />
        <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
          Page réservée aux administrateurs.
        </div>
      </div>
    );
  }

  const handleRunSchedule = async (s: Schedule) => {
    try {
      await api.runScheduleNow(s.id);
      toast({ title: "Job ajouté à la file", description: s.label || sourceLabel(s.source) });
      await reloadCurrent();
      await reloadJobs();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  const handleToggleSchedule = async (s: Schedule) => {
    try {
      await api.updateSchedule(s.id, { enabled: !s.enabled });
      await reloadSchedules();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  const handleDeleteSchedule = async (s: Schedule) => {
    try {
      await api.deleteSchedule(s.id);
      toast({ title: "Planification supprimée" });
      await reloadSchedules();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  const handleCancelCurrent = async () => {
    if (!currentJob) return;
    try {
      await api.cancelJob(currentJob.id);
      toast({ title: "Annulation demandée" });
      await reloadCurrent();
      await reloadJobs();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  const handleQuickRun = async (source: string) => {
    try {
      await api.runSourceNow(source);
      toast({ title: "Job ajouté à la file", description: sourceLabel(source) });
      await reloadCurrent();
      await reloadJobs();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  const handleReembed = async (source: string) => {
    try {
      await api.maintenanceReembedSource(source);
      toast({
        title: "Re-embedding ajouté à la file",
        description: sourceLabel(source),
      });
      await reloadCurrent();
      await reloadJobs();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  const handleReembedAll = async () => {
    try {
      await api.maintenanceReembedAll();
      toast({
        title: "Re-embedding global lancé",
        description: "Cela peut prendre 6 à 10 heures.",
      });
      await reloadCurrent();
      await reloadJobs();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  const handleOptimize = async (collection: string) => {
    try {
      await api.maintenanceOptimize(collection);
      toast({ title: "Optimize lancé", description: collection });
      await reloadCurrent();
      await reloadJobs();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  const handleIntegrityCheck = async () => {
    try {
      await api.maintenanceIntegrityCheck();
      toast({ title: "Vérification d'intégrité lancée" });
      await reloadCurrent();
      await reloadJobs();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  return (
    <div className="flex h-full flex-col">
      <Topbar
        breadcrumb={
          <>
            Planificateur{" "}
            <span className="mx-1.5 text-muted-foreground">—</span>
            <span className="font-normal text-muted-foreground">
              cron + jobs + maintenance
            </span>
          </>
        }
      >
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void reloadCurrent();
            void reloadSchedules();
            void reloadJobs();
            void reloadStats();
          }}
        >
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
          Actualiser
        </Button>
      </Topbar>

      <div className="flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-5 md:p-6">
          {/* ----- Section 1 : Job en cours ----- */}
          {currentJob ? (
            <CurrentJobBanner
              job={currentJob}
              onCancel={() => void handleCancelCurrent()}
            />
          ) : null}

          {/* ----- Section 2 : Planifications ----- */}
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold">
                Planifications actives
                {schedules.length > 0 ? (
                  <span className="ml-2 text-xs font-normal text-muted-foreground tabular-nums">
                    {schedules.length}
                  </span>
                ) : null}
              </h2>
              <Button size="sm" onClick={() => setCreateOpen(true)}>
                <Plus className="mr-1.5 h-3.5 w-3.5" />
                Ajouter une planification
              </Button>
            </div>
            <SchedulesTable
              schedules={schedules}
              loading={loadingSchedules}
              onRun={handleRunSchedule}
              onToggle={handleToggleSchedule}
              onEdit={(s) => setEditing(s)}
              onDelete={handleDeleteSchedule}
            />
          </section>

          {/* ----- Section 3 : Lancement manuel rapide ----- */}
          <section className="rounded-lg border border-border bg-background p-5">
            <h2 className="mb-1 text-base font-semibold">
              Lancement manuel rapide
            </h2>
            <p className="mb-3 text-xs text-muted-foreground">
              Déclenche un refresh ponctuel d&apos;une source publique. Si un
              job tourne déjà, le nouveau attend en file (FIFO).
            </p>
            <div className="grid gap-2 sm:grid-cols-2 md:grid-cols-4">
              {PUBLIC_SOURCES.map((s) => (
                <Button
                  key={s.id}
                  variant="outline"
                  onClick={() => void handleQuickRun(s.id)}
                  disabled={!!currentJob}
                >
                  <Zap className="mr-1.5 h-3.5 w-3.5" />
                  Rafraîchir {s.label}
                </Button>
              ))}
            </div>
          </section>

          {/* ----- Section 4 : Historique ----- */}
          <section>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-semibold">
                Historique des jobs (20 derniers)
              </h2>
              <div className="flex items-center gap-2">
                <select
                  value={filterSource}
                  onChange={(e) => setFilterSource(e.target.value)}
                  className="h-8 rounded-md border border-border bg-background px-2 text-xs"
                >
                  <option value="">Toutes sources</option>
                  {PUBLIC_SOURCES.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                  <option value="reembed_all">Re-embed all</option>
                  <option value="optimize_qdrant">Optimize Qdrant</option>
                  <option value="integrity_check">Vérif. intégrité</option>
                </select>
                <select
                  value={filterStatus}
                  onChange={(e) => setFilterStatus(e.target.value)}
                  className="h-8 rounded-md border border-border bg-background px-2 text-xs"
                >
                  <option value="">Tous statuts</option>
                  <option value="queued">En file</option>
                  <option value="running">En cours</option>
                  <option value="success">Succès</option>
                  <option value="error">Erreur</option>
                  <option value="cancelled">Annulé</option>
                </select>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void reloadJobs()}
                  disabled={loadingJobs}
                >
                  <RefreshCw
                    className={cn(
                      "h-3.5 w-3.5",
                      loadingJobs && "animate-spin",
                    )}
                  />
                </Button>
              </div>
            </div>
            <JobsHistoryTable jobs={jobs} loading={loadingJobs} />
          </section>

          {/* ----- Section 5 : Maintenance avancée ----- */}
          <section className="rounded-lg border border-border bg-background p-5">
            <h2 className="mb-1 text-base font-semibold">
              Maintenance avancée
            </h2>
            <p className="mb-4 text-xs text-muted-foreground">
              Re-embedding complet, optimisation Qdrant, vérification
              d&apos;intégrité. Toutes les opérations passent par la file
              FIFO ; un seul job tourne à la fois.
            </p>

            {/* Stats Qdrant */}
            <div className="mb-5 rounded-md border border-border">
              <div className="flex items-center justify-between border-b border-border px-3 py-2">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Database className="h-3.5 w-3.5" />
                  Stats Qdrant
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void reloadStats()}
                  disabled={loadingStats}
                >
                  <RefreshCw
                    className={cn(
                      "mr-1 h-3 w-3",
                      loadingStats && "animate-spin",
                    )}
                  />
                  Rafraîchir stats
                </Button>
              </div>
              <QdrantStatsTable stats={stats} loading={loadingStats} />
            </div>

            {/* Re-embedding */}
            <div className="mb-5">
              <h3 className="mb-1 text-sm font-semibold">
                Re-embedding complet
              </h3>
              <p className="mb-3 text-xs text-muted-foreground">
                À utiliser après un changement de modèle d&apos;embedding ou de
                stratégie de chunking. Très long (~2h par source).
              </p>
              <div className="grid gap-2 sm:grid-cols-2 md:grid-cols-4">
                {PUBLIC_SOURCES.map((s) => (
                  <Button
                    key={s.id}
                    variant="outline"
                    size="sm"
                    onClick={() => void handleReembed(s.id)}
                    disabled={!!currentJob}
                  >
                    Re-embed {s.label}
                  </Button>
                ))}
              </div>
              <div className="mt-2">
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="destructive"
                      size="sm"
                      disabled={!!currentJob}
                    >
                      <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
                      Re-embed TOUTES sources publiques
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>
                        Lancer un re-embedding global ?
                      </AlertDialogTitle>
                      <AlertDialogDescription>
                        Cela va prendre 6 à 10 heures. Le chat sera
                        ralenti pendant l&apos;opération si la pause chat
                        est activée. Confirmer le démarrage ?
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Annuler</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => void handleReembedAll()}
                        className="bg-danger text-danger-foreground hover:bg-danger/90"
                      >
                        Lancer
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            </div>

            {/* Optimize */}
            <div className="mb-5">
              <h3 className="mb-1 text-sm font-semibold">
                Optimisation Qdrant
              </h3>
              <p className="mb-3 text-xs text-muted-foreground">
                Compacte les segments après de nombreux upserts/deletes.
                Opération asynchrone côté Qdrant.
              </p>
              <div className="flex flex-wrap gap-2">
                {COLLECTIONS_TO_OPTIMIZE.map((col) => (
                  <Button
                    key={col}
                    variant="outline"
                    size="sm"
                    onClick={() => void handleOptimize(col)}
                    disabled={!!currentJob}
                  >
                    <Activity className="mr-1.5 h-3.5 w-3.5" />
                    {col}
                  </Button>
                ))}
              </div>
            </div>

            {/* Integrity check */}
            <div>
              <h3 className="mb-1 text-sm font-semibold">
                Vérification d&apos;intégrité
              </h3>
              <p className="mb-3 text-xs text-muted-foreground">
                Compte les points par collection, détecte les chunks sans
                source ou chunk_id valides. Le rapport apparaît dans la
                liste des jobs (clic 🔍).
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void handleIntegrityCheck()}
                disabled={!!currentJob}
              >
                <ShieldCheck className="mr-1.5 h-3.5 w-3.5" />
                Lancer la vérification
              </Button>
            </div>
          </section>
        </div>
      </div>

      {/* ----- Dialog création / édition ----- */}
      <ScheduleEditor
        open={createOpen || editing !== null}
        editing={editing}
        onClose={() => {
          setCreateOpen(false);
          setEditing(null);
        }}
        onSaved={async () => {
          await reloadSchedules();
          setCreateOpen(false);
          setEditing(null);
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sous-composants
// ---------------------------------------------------------------------------

function CurrentJobBanner({
  job,
  onCancel,
}: {
  job: RefreshJob;
  onCancel: () => void;
}) {
  const [, force] = React.useState(0);
  React.useEffect(() => {
    const t = window.setInterval(() => force((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, []);
  const progress = parseProgress(job.log_excerpt);
  const pct = progress
    ? Math.min(100, Math.round((progress.done / progress.total) * 100))
    : null;

  return (
    <div className="rounded-lg border border-info/40 bg-info/5 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-medium text-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-info" />
          [{sourceLabel(job.source)}] en cours · démarré il y a{" "}
          {elapsedSince(job.started_at)}
          {progress
            ? ` · ${progress.done}/${progress.total} chunks (${pct}%)`
            : ""}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={onCancel}
          disabled={job.stop_requested}
        >
          {job.stop_requested ? "Annulation demandée…" : "Annuler"}
        </Button>
      </div>
      {pct !== null ? (
        <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-info/15">
          <div
            className="h-full bg-info transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      ) : null}
    </div>
  );
}

function SchedulesTable({
  schedules,
  loading,
  onRun,
  onToggle,
  onEdit,
  onDelete,
}: {
  schedules: Schedule[];
  loading: boolean;
  onRun: (s: Schedule) => void | Promise<void>;
  onToggle: (s: Schedule) => void | Promise<void>;
  onEdit: (s: Schedule) => void;
  onDelete: (s: Schedule) => void | Promise<void>;
}) {
  if (loading && schedules.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-border bg-background p-4 text-sm text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Chargement…
      </div>
    );
  }
  if (schedules.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
        Aucune planification. Cliquez sur « Ajouter une planification »
        pour démarrer.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Label</th>
            <th className="px-3 py-2 text-left font-medium">Source</th>
            <th className="px-3 py-2 text-left font-medium">Cadence</th>
            <th className="px-3 py-2 text-left font-medium">Prochain run</th>
            <th className="px-3 py-2 text-left font-medium">Pause chat</th>
            <th className="px-3 py-2 text-right font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {schedules.map((s) => (
            <tr key={s.id} className="border-t border-border">
              <td className="px-3 py-2">
                <div className="flex items-center gap-2">
                  <CalendarClock className="h-3.5 w-3.5 text-muted-foreground" />
                  <span
                    className={cn(
                      "font-medium",
                      !s.enabled && "text-muted-foreground line-through",
                    )}
                  >
                    {s.label || `Planif #${s.id}`}
                  </span>
                  {!s.enabled ? (
                    <Badge variant="secondary" className="text-[10px]">
                      désactivée
                    </Badge>
                  ) : null}
                </div>
              </td>
              <td className="px-3 py-2 text-muted-foreground">
                {sourceLabel(s.source)}
              </td>
              <td className="px-3 py-2 text-xs">
                <div className="font-mono">{s.cron_expression}</div>
                <div className="text-muted-foreground">
                  {describeCron(s.cron_expression)}
                </div>
              </td>
              <td className="px-3 py-2 text-xs text-muted-foreground">
                {s.next_run_at ? formatDateTime(s.next_run_at) : "—"}
              </td>
              <td className="px-3 py-2 text-xs">
                {s.pause_chat_during_refresh ? "Oui" : "Non"}
              </td>
              <td className="px-3 py-2">
                <div className="flex justify-end gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    title="Lancer maintenant"
                    onClick={() => void onRun(s)}
                  >
                    <Play className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    title="Modifier"
                    onClick={() => onEdit(s)}
                  >
                    <Edit3 className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    title={s.enabled ? "Désactiver" : "Activer"}
                    onClick={() => void onToggle(s)}
                  >
                    <Pause className="h-3.5 w-3.5" />
                  </Button>
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        variant="ghost"
                        size="sm"
                        title="Supprimer"
                        className="text-danger hover:bg-danger/10 hover:text-danger"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>
                          Supprimer cette planification ?
                        </AlertDialogTitle>
                        <AlertDialogDescription>
                          La planification &quot;{s.label || `#${s.id}`}&quot;
                          sera retirée du planificateur. Les jobs déjà
                          lancés ne sont pas impactés.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Annuler</AlertDialogCancel>
                        <AlertDialogAction
                          onClick={() => void onDelete(s)}
                          className="bg-danger text-danger-foreground hover:bg-danger/90"
                        >
                          Supprimer
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function JobsHistoryTable({
  jobs,
  loading,
}: {
  jobs: RefreshJob[];
  loading: boolean;
}) {
  const [openJob, setOpenJob] = React.useState<RefreshJob | null>(null);

  if (loading && jobs.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-border bg-background p-4 text-sm text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Chargement…
      </div>
    );
  }
  if (jobs.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
        Aucun job pour ces filtres.
      </div>
    );
  }
  return (
    <>
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Date début</th>
              <th className="px-3 py-2 text-left font-medium">Source</th>
              <th className="px-3 py-2 text-left font-medium">Trigger</th>
              <th className="px-3 py-2 text-right font-medium">Durée</th>
              <th className="px-3 py-2 text-right font-medium">Pages</th>
              <th className="px-3 py-2 text-right font-medium">Chunks</th>
              <th className="px-3 py-2 text-left font-medium">Statut</th>
              <th className="px-3 py-2 text-right font-medium" />
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => {
              const meta = STATUS_META[j.status as RefreshJobStatus] || {
                label: j.status,
                cls: "bg-muted text-muted-foreground",
              };
              return (
                <tr key={j.id} className="border-t border-border">
                  <td className="px-3 py-2 text-xs text-muted-foreground">
                    {j.started_at ? formatDateTime(j.started_at) : "—"}
                  </td>
                  <td className="px-3 py-2">{sourceLabel(j.source)}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">
                    {j.trigger}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {j.duration_s !== null ? `${j.duration_s.toFixed(1)}s` : "—"}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {j.pages_fetched ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {j.chunks_indexed ?? "—"}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs",
                        meta.cls,
                      )}
                    >
                      <StatusIcon status={j.status as RefreshJobStatus} />
                      {meta.label}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setOpenJob(j)}
                      title="Détail"
                    >
                      <Search className="h-3.5 w-3.5" />
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <JobDetailDialog
        job={openJob}
        open={openJob !== null}
        onClose={() => setOpenJob(null)}
      />
    </>
  );
}

function StatusIcon({ status }: { status: RefreshJobStatus }) {
  const cls = "h-3 w-3";
  switch (status) {
    case "queued":
      return <Clock className={cls} />;
    case "running":
      return <Loader2 className={cn(cls, "animate-spin")} />;
    case "success":
      return <CheckCircle2 className={cls} />;
    case "error":
      return <XCircle className={cls} />;
    case "cancelled":
      return <AlertTriangle className={cls} />;
  }
}

function JobDetailDialog({
  job,
  open,
  onClose,
}: {
  job: RefreshJob | null;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            Job #{job?.id} — {job ? sourceLabel(job.source) : ""}
          </DialogTitle>
        </DialogHeader>
        {job ? (
          <div className="flex flex-col gap-3 text-sm">
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <div className="text-muted-foreground">Statut</div>
              <div>{STATUS_META[job.status as RefreshJobStatus]?.label || job.status}</div>
              <div className="text-muted-foreground">Trigger</div>
              <div>{job.trigger}</div>
              <div className="text-muted-foreground">Démarré</div>
              <div>{job.started_at ? formatDateTime(job.started_at) : "—"}</div>
              <div className="text-muted-foreground">Terminé</div>
              <div>{job.finished_at ? formatDateTime(job.finished_at) : "—"}</div>
              <div className="text-muted-foreground">Durée</div>
              <div>{job.duration_s !== null ? `${job.duration_s.toFixed(1)}s` : "—"}</div>
              <div className="text-muted-foreground">Pages</div>
              <div>{job.pages_fetched ?? "—"}</div>
              <div className="text-muted-foreground">Chunks indexés</div>
              <div>{job.chunks_indexed ?? "—"}</div>
            </div>
            {job.error_message ? (
              <>
                <Separator />
                <div>
                  <div className="mb-1 text-xs font-semibold text-danger">
                    Erreur
                  </div>
                  <pre className="overflow-x-auto rounded bg-danger/5 p-2 text-xs text-danger">
                    {job.error_message}
                  </pre>
                </div>
              </>
            ) : null}
            {job.log_excerpt ? (
              <>
                <Separator />
                <div>
                  <div className="mb-1 text-xs font-semibold text-muted-foreground">
                    Log
                  </div>
                  <pre className="max-h-72 overflow-auto rounded bg-muted/40 p-2 text-[11px]">
                    {job.log_excerpt}
                  </pre>
                </div>
              </>
            ) : null}
          </div>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Fermer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function QdrantStatsTable({
  stats,
  loading,
}: {
  stats: QdrantCollectionStat[];
  loading: boolean;
}) {
  if (loading && stats.length === 0) {
    return (
      <div className="flex items-center gap-2 px-3 py-3 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" />
        Chargement…
      </div>
    );
  }
  if (stats.length === 0) {
    return (
      <div className="px-3 py-3 text-xs text-muted-foreground">
        Aucune collection détectée.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="bg-muted/30 text-[10px] uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="px-3 py-1.5 text-left font-medium">Collection</th>
            <th className="px-3 py-1.5 text-right font-medium">Points</th>
            <th className="px-3 py-1.5 text-right font-medium">Segments</th>
            <th className="px-3 py-1.5 text-right font-medium">Indexés</th>
            <th className="px-3 py-1.5 text-left font-medium">Statut</th>
          </tr>
        </thead>
        <tbody>
          {stats.map((s) => (
            <tr key={s.name} className="border-t border-border">
              <td className="px-3 py-1.5 font-mono">{s.name}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {s.points ?? "—"}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {s.segments ?? "—"}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums">
                {s.indexed_vectors ?? "—"}
              </td>
              <td className="px-3 py-1.5 text-muted-foreground">
                {s.error ? `erreur : ${s.error}` : s.status || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Editor (création + modification d'une planification)
// ---------------------------------------------------------------------------

type CronMode = "daily" | "weekly" | "monthly" | "expert";

function buildCron(opts: {
  mode: CronMode;
  hour: number;
  minute: number;
  dayOfWeek: number;
  dayOfMonth: number;
  expert: string;
}): string {
  if (opts.mode === "expert") return opts.expert.trim();
  const hh = String(Math.max(0, Math.min(23, opts.hour)));
  const mm = String(Math.max(0, Math.min(59, opts.minute)));
  if (opts.mode === "daily") return `${mm} ${hh} * * *`;
  if (opts.mode === "weekly") {
    const dow = String(Math.max(0, Math.min(6, opts.dayOfWeek)));
    return `${mm} ${hh} * * ${dow}`;
  }
  // monthly
  const dom = String(Math.max(1, Math.min(31, opts.dayOfMonth)));
  return `${mm} ${hh} ${dom} * *`;
}

function ScheduleEditor({
  open,
  editing,
  onClose,
  onSaved,
}: {
  open: boolean;
  editing: Schedule | null;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const { toast } = useToast();
  const [source, setSource] = React.useState<string>("boss");
  const [label, setLabel] = React.useState("");
  const [enabled, setEnabled] = React.useState(true);
  const [pauseChat, setPauseChat] = React.useState(false);
  const [mode, setMode] = React.useState<CronMode>("weekly");
  const [hour, setHour] = React.useState(3);
  const [minute, setMinute] = React.useState(0);
  const [dayOfWeek, setDayOfWeek] = React.useState(0);
  const [dayOfMonth, setDayOfMonth] = React.useState(1);
  const [expert, setExpert] = React.useState("");
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    if (editing) {
      setSource(editing.source);
      setLabel(editing.label || "");
      setEnabled(editing.enabled);
      setPauseChat(editing.pause_chat_during_refresh);
      setMode("expert");
      setExpert(editing.cron_expression);
    } else {
      setSource("boss");
      setLabel("");
      setEnabled(true);
      setPauseChat(false);
      setMode("weekly");
      setHour(3);
      setMinute(0);
      setDayOfWeek(0);
      setDayOfMonth(1);
      setExpert("");
    }
  }, [open, editing]);

  const cron = buildCron({ mode, hour, minute, dayOfWeek, dayOfMonth, expert });
  const offHours = hour < 6 || hour >= 22;

  const handleSave = async () => {
    if (!cron || cron.split(/\s+/).length !== 5) {
      toast({
        title: "Expression cron invalide",
        description: "5 champs attendus (m h jour mois dow).",
        variant: "destructive",
      });
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        await api.updateSchedule(editing.id, {
          cron_expression: cron,
          label,
          pause_chat_during_refresh: pauseChat,
          enabled,
        });
        toast({ title: "Planification mise à jour" });
      } else {
        await api.createSchedule({
          source,
          cron_expression: cron,
          label,
          pause_chat_during_refresh: pauseChat,
          enabled,
        });
        toast({ title: "Planification créée" });
      }
      await onSaved();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {editing ? "Modifier une planification" : "Nouvelle planification"}
          </DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3 text-sm">
          <div className="space-y-1.5">
            <Label htmlFor="src">Source</Label>
            <select
              id="src"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              disabled={!!editing}
              className="flex h-9 w-full rounded-md border border-border bg-background px-3 text-sm"
            >
              <optgroup label="Sources publiques">
                {PUBLIC_SOURCES.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Maintenance">
                <option value="reembed_all">Re-embed toutes sources</option>
                <option value="integrity_check">Vérification intégrité</option>
              </optgroup>
            </select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="label">Label (libre)</Label>
            <Input
              id="label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Ex. BOSS — refresh hebdo"
            />
          </div>

          <div className="space-y-1.5">
            <Label>Cadence</Label>
            <div className="flex flex-wrap gap-1">
              {(["daily", "weekly", "monthly", "expert"] as CronMode[]).map(
                (m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setMode(m)}
                    className={cn(
                      "rounded-md border px-2 py-1 text-xs",
                      mode === m
                        ? "border-accent bg-accent/10 text-accent"
                        : "border-border bg-background text-muted-foreground",
                    )}
                  >
                    {m === "daily"
                      ? "Quotidien"
                      : m === "weekly"
                        ? "Hebdo"
                        : m === "monthly"
                          ? "Mensuel"
                          : "Expert"}
                  </button>
                ),
              )}
            </div>
            {mode !== "expert" ? (
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                {mode === "weekly" ? (
                  <>
                    <span>Le</span>
                    <select
                      value={dayOfWeek}
                      onChange={(e) => setDayOfWeek(Number(e.target.value))}
                      className="h-8 rounded-md border border-border bg-background px-2"
                    >
                      <option value={1}>lundi</option>
                      <option value={2}>mardi</option>
                      <option value={3}>mercredi</option>
                      <option value={4}>jeudi</option>
                      <option value={5}>vendredi</option>
                      <option value={6}>samedi</option>
                      <option value={0}>dimanche</option>
                    </select>
                  </>
                ) : null}
                {mode === "monthly" ? (
                  <>
                    <span>Le jour</span>
                    <Input
                      type="number"
                      min={1}
                      max={31}
                      value={dayOfMonth}
                      onChange={(e) => setDayOfMonth(Number(e.target.value))}
                      className="h-8 w-16"
                    />
                  </>
                ) : null}
                <span>à</span>
                <Input
                  type="number"
                  min={0}
                  max={23}
                  value={hour}
                  onChange={(e) => setHour(Number(e.target.value))}
                  className="h-8 w-16"
                />
                <span>h</span>
                <Input
                  type="number"
                  min={0}
                  max={59}
                  value={minute}
                  onChange={(e) => setMinute(Number(e.target.value))}
                  className="h-8 w-16"
                />
              </div>
            ) : (
              <div className="mt-2 space-y-1">
                <Input
                  value={expert}
                  onChange={(e) => setExpert(e.target.value)}
                  placeholder="0 3 * * 0"
                  className="font-mono"
                />
                <p className="text-[11px] text-muted-foreground">
                  5 champs : minute heure jour mois jour-de-la-semaine.
                </p>
              </div>
            )}
            <div className="mt-1 rounded-md bg-muted/40 px-2 py-1 text-[11px]">
              <span className="text-muted-foreground">Expression :</span>{" "}
              <code>{cron}</code>
            </div>
            {!offHours ? (
              <div className="text-[11px] text-warning">
                Conseil : privilégier les plages de nuit (avant 6h ou après
                22h) ou le week-end pour limiter l&apos;impact sur le chat.
              </div>
            ) : null}
          </div>

          <div className="flex flex-col gap-2 rounded-md border border-border p-3 text-xs">
            <label className="flex items-center justify-between gap-2">
              <span>Pause chat pendant ce refresh</span>
              <input
                type="checkbox"
                checked={pauseChat}
                onChange={(e) => setPauseChat(e.target.checked)}
              />
            </label>
            <label className="flex items-center justify-between gap-2">
              <span>Activer immédiatement</span>
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
            </label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Annuler
          </Button>
          <Button onClick={() => void handleSave()} disabled={saving}>
            {saving ? (
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
            ) : null}
            Enregistrer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
