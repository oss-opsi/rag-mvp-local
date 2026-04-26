"use client";

import * as React from "react";
import { Loader2, RefreshCw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
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

/**
 * Carte « Sources publiques » — réservée aux admins.
 *
 * Affiche les 4 connecteurs sources publiques (BOSS, DSN-info, URSSAF,
 * service-public.fr) + Légifrance (en pause). Pour chaque source disponible :
 *  - statut + label + domaines métier
 *  - dernier run (durée, fiches lues, chunks indexés, erreurs)
 *  - bouton « Rafraîchir » (purge + ré-indexe la source)
 *  - bouton « Supprimer » (purge seule, retire la source de la KB)
 *
 * Lot 2bis : seul service_public est disponible — les autres affichent un
 * libellé « bientôt disponible » désactivé.
 */

type SourceStatus = "available" | "planned" | "paused";

interface LastRun {
  started_at?: number;
  duration_s?: number;
  fetched?: number;
  chunks?: number;
  upserted?: number;
  purged?: number;
  errors?: string[];
}

interface SourceItem {
  id: string;
  label: string;
  status: SourceStatus;
  domaine: string[];
  last_run: LastRun | null;
}

interface SourcesStatusResponse {
  kb_collection: string;
  kb_exists: boolean;
  vectors_count: number;
  sources: SourceItem[];
}

const STATUS_LABEL: Record<SourceStatus, string> = {
  available: "Disponible",
  planned: "Bientôt disponible",
  paused: "En pause",
};

const STATUS_CLASS: Record<SourceStatus, string> = {
  available:
    "bg-green-50 text-green-700 ring-1 ring-green-200 dark:bg-green-900/30 dark:text-green-300 dark:ring-green-800",
  planned:
    "bg-muted text-muted-foreground ring-1 ring-border",
  paused:
    "bg-amber-50 text-amber-700 ring-1 ring-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:ring-amber-800",
};

function formatDuration(seconds?: number): string {
  if (!seconds && seconds !== 0) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds - m * 60);
  return `${m} min ${s} s`;
}

function formatDate(ts?: number): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function PublicSourcesCard(): React.ReactElement {
  const { toast } = useToast();
  const [data, setData] = React.useState<SourcesStatusResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState<Record<string, "refresh" | "purge" | null>>({});

  const reload = React.useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/admin/sources/status", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: SourcesStatusResponse = await res.json();
      setData(json);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const handleRefresh = async (source: SourceItem) => {
    setBusy((b) => ({ ...b, [source.id]: "refresh" }));
    toast({
      title: "Rafraîchissement en cours",
      description: `${source.label} — la collecte et l'indexation peuvent prendre plusieurs minutes.`,
    });
    try {
      const res = await fetch(
        `/api/admin/sources/refresh?source=${encodeURIComponent(source.id)}&purge_first=true`,
        { method: "POST" },
      );
      const json = await res.json();
      if (!res.ok) {
        throw new Error(json?.detail || `HTTP ${res.status}`);
      }
      const r = json?.result || {};
      toast({
        title: "Source rafraîchie",
        description: `${source.label} — ${r.chunks ?? 0} chunks indexés en ${formatDuration(r.duration_s)}.`,
      });
      await reload();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Échec du rafraîchissement", description: msg, variant: "destructive" });
    } finally {
      setBusy((b) => ({ ...b, [source.id]: null }));
    }
  };

  const handlePurge = async (source: SourceItem) => {
    setBusy((b) => ({ ...b, [source.id]: "purge" }));
    try {
      const res = await fetch(
        `/api/admin/sources/purge?source=${encodeURIComponent(source.id)}`,
        { method: "POST" },
      );
      const json = await res.json();
      if (!res.ok) throw new Error(json?.detail || `HTTP ${res.status}`);
      toast({
        title: "Source supprimée",
        description: `${source.label} — ${json.deleted ?? 0} vecteurs retirés de la base.`,
      });
      await reload();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Échec de la suppression", description: msg, variant: "destructive" });
    } finally {
      setBusy((b) => ({ ...b, [source.id]: null }));
    }
  };

  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Chargement des sources...
      </div>
    );
  }

  if (!data) return <div className="text-sm text-muted-foreground">—</div>;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline gap-2 text-xs text-muted-foreground">
        <span>
          Base de connaissances partagée :{" "}
          <code className="rounded bg-muted px-1.5 py-0.5 font-mono">
            {data.kb_collection}
          </code>
        </span>
        <span>•</span>
        <span>
          {data.vectors_count.toLocaleString("fr-FR")} vecteurs indexés au total
        </span>
      </div>

      <div className="flex flex-col gap-3">
        {data.sources.map((s) => {
          const isBusy = busy[s.id] != null;
          const isAvailable = s.status === "available";
          const lr = s.last_run;
          return (
            <div
              key={s.id}
              className="rounded-md border border-border bg-background p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold">{s.label}</span>
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_CLASS[s.status]}`}
                    >
                      {STATUS_LABEL[s.status]}
                    </span>
                  </div>
                  {s.domaine.length > 0 ? (
                    <div className="mt-1 text-xs text-muted-foreground">
                      Domaines : {s.domaine.join(" · ")}
                    </div>
                  ) : null}
                </div>

                <div className="flex shrink-0 items-center gap-2">
                  <Button
                    size="sm"
                    onClick={() => void handleRefresh(s)}
                    disabled={!isAvailable || isBusy}
                    title={
                      isAvailable
                        ? "Supprimer puis ré-indexer cette source"
                        : "Connecteur non encore disponible"
                    }
                  >
                    {busy[s.id] === "refresh" ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <RefreshCw className="mr-2 h-4 w-4" />
                    )}
                    Rafraîchir
                  </Button>

                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!isAvailable || isBusy}
                        title={
                          isAvailable
                            ? "Supprimer cette source de la base de connaissances"
                            : "Connecteur non encore disponible"
                        }
                      >
                        {busy[s.id] === "purge" ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <Trash2 className="mr-2 h-4 w-4" />
                        )}
                        Supprimer
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Supprimer la source {s.label} ?</AlertDialogTitle>
                        <AlertDialogDescription>
                          Tous les vecteurs issus de cette source seront retirés
                          de la base de connaissances partagée. Tu pourras
                          relancer un rafraîchissement à tout moment pour les
                          ré-indexer.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Annuler</AlertDialogCancel>
                        <AlertDialogAction
                          onClick={() => void handlePurge(s)}
                          className="bg-danger text-danger-foreground hover:bg-danger/90"
                        >
                          Supprimer
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </div>

              {lr ? (
                <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground sm:grid-cols-4">
                  <div>
                    <span className="block text-[10px] uppercase tracking-wide">
                      Dernier run
                    </span>
                    <span className="font-medium text-foreground">
                      {formatDate(lr.started_at)}
                    </span>
                  </div>
                  <div>
                    <span className="block text-[10px] uppercase tracking-wide">
                      Durée
                    </span>
                    <span className="font-medium text-foreground">
                      {formatDuration(lr.duration_s)}
                    </span>
                  </div>
                  <div>
                    <span className="block text-[10px] uppercase tracking-wide">
                      Fiches lues
                    </span>
                    <span className="font-medium text-foreground">
                      {lr.fetched ?? 0}
                    </span>
                  </div>
                  <div>
                    <span className="block text-[10px] uppercase tracking-wide">
                      Chunks indexés
                    </span>
                    <span className="font-medium text-foreground">
                      {lr.upserted ?? lr.chunks ?? 0}
                    </span>
                  </div>
                  {lr.errors && lr.errors.length > 0 ? (
                    <div className="col-span-2 sm:col-span-4">
                      <span className="block text-[10px] uppercase tracking-wide text-amber-700 dark:text-amber-400">
                        {lr.errors.length} avertissement(s)
                      </span>
                      <span className="font-mono text-[11px] text-amber-700 dark:text-amber-400">
                        {lr.errors.slice(0, 2).join(" · ")}
                        {lr.errors.length > 2 ? " · ..." : ""}
                      </span>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
