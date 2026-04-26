"use client";

import * as React from "react";
import { Loader2, RefreshCw, ShieldCheck, ShieldAlert, CheckCircle2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/components/ui/use-toast";
import { api } from "@/lib/api-client";
import type {
  LegifranceCredsState,
  SourceState,
  SourcesStatus,
} from "@/lib/types";

const POLL_INTERVAL_MS = 4000;

function formatRelative(epoch: number | null | undefined): string {
  if (!epoch) return "—";
  const d = new Date(epoch * 1000);
  return d.toLocaleString("fr-FR", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

function statusBadge(state: SourceState) {
  if (state.status === "available") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900/30 dark:text-green-300">
        <CheckCircle2 className="h-3 w-3" /> disponible
      </span>
    );
  }
  if (state.status === "needs_credentials") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-300">
        <ShieldAlert className="h-3 w-3" /> credentials manquants
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
      planifié
    </span>
  );
}

function lastRunBadge(state: SourceState) {
  const lr = state.last_run;
  if (!lr) return null;
  const color =
    lr.status === "running"
      ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300"
      : lr.status === "done"
      ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
      : lr.status === "done_with_errors"
      ? "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
      : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300";
  const label =
    lr.status === "running"
      ? "en cours"
      : lr.status === "done"
      ? "terminé"
      : lr.status === "done_with_errors"
      ? "terminé avec erreurs"
      : "échec";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      {lr.status === "running" ? (
        <Loader2 className="h-3 w-3 animate-spin" />
      ) : null}
      {label}
    </span>
  );
}

export function SourcesPubliquesCard() {
  const { toast } = useToast();
  const [status, setStatus] = React.useState<SourcesStatus | null>(null);
  const [creds, setCreds] = React.useState<LegifranceCredsState | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [editingCreds, setEditingCreds] = React.useState(false);
  const [clientId, setClientId] = React.useState("");
  const [clientSecret, setClientSecret] = React.useState("");
  const [savingCreds, setSavingCreds] = React.useState(false);
  const [testing, setTesting] = React.useState(false);
  const [refreshing, setRefreshing] = React.useState<string | null>(null);

  const reload = React.useCallback(async () => {
    try {
      const [s, c] = await Promise.all([
        api.adminGetSourcesStatus(),
        api.adminGetLegifranceCreds(),
      ]);
      setStatus(s);
      setCreds(c);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({
        title: "Erreur de chargement",
        description: msg,
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  // Poll en cours d'exécution d'un refresh
  const hasRunningRefresh = React.useMemo(
    () => Boolean(status?.sources?.some((s) => s.last_run?.status === "running")),
    [status],
  );

  React.useEffect(() => {
    if (!hasRunningRefresh) return;
    const t = setInterval(() => {
      void reload();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(t);
  }, [hasRunningRefresh, reload]);

  const handleSaveCreds = async () => {
    if (!clientId.trim() || !clientSecret.trim()) return;
    setSavingCreds(true);
    try {
      await api.adminSetLegifranceCreds(clientId.trim(), clientSecret.trim());
      setClientId("");
      setClientSecret("");
      setEditingCreds(false);
      await reload();
      toast({ title: "Credentials Légifrance enregistrés" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setSavingCreds(false);
    }
  };

  const handleTestCreds = async () => {
    setTesting(true);
    try {
      const r = await api.adminTestLegifranceCreds();
      toast({
        title: r.ok ? "Authentification PISTE OK" : "Échec d'authentification",
        description: `${r.message} (env=${r.env})`,
        variant: r.ok ? undefined : "destructive",
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setTesting(false);
    }
  };

  const handleRefresh = async (sourceId: string) => {
    setRefreshing(sourceId);
    try {
      const r = await api.adminRefreshSource(sourceId);
      toast({
        title: "Rafraîchissement",
        description: r.message ?? r.status,
      });
      await reload();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setRefreshing(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Chargement...
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Vue d'ensemble KB */}
      <div className="rounded-md border border-border bg-muted/40 p-3 text-sm">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="text-muted-foreground">Collection :</span>
          <code className="rounded bg-background px-1.5 py-0.5 font-mono text-xs">
            {status?.kb_collection ?? "—"}
          </code>
          <span className="text-muted-foreground">Vecteurs :</span>
          <span className="font-medium">{status?.vectors_count ?? 0}</span>
        </div>
      </div>

      {/* Credentials Légifrance */}
      <div>
        <div className="mb-2 flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold">Credentials Légifrance / PISTE</h3>
        </div>
        <p className="mb-3 text-xs text-muted-foreground">
          OAuth2 client_credentials. Stockés chiffrés côté serveur, jamais
          renvoyés en clair par l'API.
        </p>

        {creds?.client_id_configured && !editingCreds ? (
          <div className="flex flex-wrap items-center gap-3">
            <code className="rounded bg-muted px-2 py-1 font-mono text-xs">
              client_id : {creds.client_id_masked || "••••••••"}
            </code>
            <code className="rounded bg-muted px-2 py-1 font-mono text-xs">
              client_secret :{" "}
              {creds.client_secret_configured ? "••••••••" : "(absent)"}
            </code>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setEditingCreds(true)}
            >
              Remplacer
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void handleTestCreds()}
              disabled={testing}
            >
              {testing ? (
                <>
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> Test...
                </>
              ) : (
                "Tester"
              )}
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="lf-client-id">Client ID</Label>
                <Input
                  id="lf-client-id"
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  autoComplete="off"
                  placeholder="xxxx-xxxx-xxxx"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="lf-client-secret">Client Secret</Label>
                <Input
                  id="lf-client-secret"
                  type="password"
                  value={clientSecret}
                  onChange={(e) => setClientSecret(e.target.value)}
                  autoComplete="off"
                  placeholder="••••••••"
                />
              </div>
            </div>
            <div className="flex gap-2">
              <Button
                onClick={() => void handleSaveCreds()}
                disabled={
                  savingCreds || !clientId.trim() || !clientSecret.trim()
                }
              >
                {savingCreds ? "Enregistrement..." : "Enregistrer"}
              </Button>
              {creds?.client_id_configured ? (
                <Button
                  variant="outline"
                  onClick={() => {
                    setEditingCreds(false);
                    setClientId("");
                    setClientSecret("");
                  }}
                >
                  Annuler
                </Button>
              ) : null}
            </div>
          </div>
        )}
      </div>

      <Separator />

      {/* Liste des sources */}
      <div>
        <h3 className="mb-2 text-sm font-semibold">Sources publiques</h3>
        <div className="flex flex-col gap-3">
          {status?.sources?.map((src) => (
            <div
              key={src.id}
              className="rounded-md border border-border bg-background p-3"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{src.label}</span>
                {statusBadge(src)}
                {lastRunBadge(src)}
              </div>
              {src.domaine?.length ? (
                <div className="mt-1 flex flex-wrap gap-1">
                  {src.domaine.map((d) => (
                    <span
                      key={d}
                      className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground"
                    >
                      {d}
                    </span>
                  ))}
                </div>
              ) : null}
              {src.last_run ? (
                <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground md:grid-cols-4">
                  <div>
                    Démarré : {formatRelative(src.last_run.started_at)}
                  </div>
                  <div>
                    Terminé : {formatRelative(src.last_run.finished_at)}
                  </div>
                  <div>Articles lus : {src.last_run.fetched}</div>
                  <div>
                    Chunks : {src.last_run.chunks} • Indexés :{" "}
                    {src.last_run.upserted}
                  </div>
                  {src.last_run.errors?.length ? (
                    <div className="col-span-2 md:col-span-4 mt-1 flex items-start gap-1 text-amber-700 dark:text-amber-300">
                      <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      <div>
                        {src.last_run.errors.length} erreur(s) — première :{" "}
                        {src.last_run.errors[0]}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}
              <div className="mt-3 flex justify-end">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={
                    refreshing === src.id ||
                    src.last_run?.status === "running" ||
                    src.status !== "available"
                  }
                  onClick={() => void handleRefresh(src.id)}
                >
                  {refreshing === src.id ||
                  src.last_run?.status === "running" ? (
                    <>
                      <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />{" "}
                      Rafraîchissement...
                    </>
                  ) : (
                    <>
                      <RefreshCw className="mr-2 h-3.5 w-3.5" /> Rafraîchir
                    </>
                  )}
                </Button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
