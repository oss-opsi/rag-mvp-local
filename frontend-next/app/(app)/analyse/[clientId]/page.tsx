"use client";

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter, notFound } from "next/navigation";
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Trash2,
} from "lucide-react";
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
import { UploadDropzone } from "@/components/upload-dropzone";
import { FileIcon, getExt } from "@/components/file-tile";
import { NotificationsBell } from "@/components/notifications-bell";
import { PipelineBadges } from "@/components/pipeline-badges";
import { useToast } from "@/components/ui/use-toast";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api-client";
import { StatusPill } from "../_helpers";
import type { Cdc, Client } from "@/lib/types";

const LAST_CLIENT_KEY = "tellme.analyse.lastClientId";

function relativeDate(iso?: string | null): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const ageMs = Date.now() - t;
  const min = Math.round(ageMs / 60_000);
  if (min < 60) return min <= 1 ? "à l'instant" : `il y a ${min} min`;
  const h = Math.round(min / 60);
  if (h < 24) return `il y a ${h} h`;
  const d = Math.round(h / 24);
  if (d < 30) return `il y a ${d} j`;
  return new Date(t).toLocaleDateString("fr-FR");
}

export default function ClientCdcsPage() {
  const params = useParams<{ clientId: string }>();
  const router = useRouter();
  const { toast } = useToast();
  const clientIdNum = Number(params.clientId);
  if (!Number.isFinite(clientIdNum) || clientIdNum <= 0) return notFound();

  const [client, setClient] = React.useState<Client | null>(null);
  const [cdcs, setCdcs] = React.useState<Cdc[]>([]);
  const [pipelineVersion, setPipelineVersion] = React.useState<string | undefined>();
  const [loading, setLoading] = React.useState(true);
  const [uploading, setUploading] = React.useState(false);
  const [deleting, setDeleting] = React.useState<number | null>(null);

  const reload = React.useCallback(async () => {
    setLoading(true);
    try {
      const [allClients, data] = await Promise.all([
        api.clients(),
        api.clientCdcs(clientIdNum),
      ]);
      const c = allClients.find((x) => x.id === clientIdNum);
      if (!c) {
        router.replace("/analyse");
        return;
      }
      setClient(c);
      setCdcs(data.cdcs || []);
      setPipelineVersion(data.pipeline_version);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur de chargement";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [clientIdNum, router, toast]);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  React.useEffect(() => {
    try {
      window.localStorage.setItem(LAST_CLIENT_KEY, String(clientIdNum));
    } catch {
      /* ignore */
    }
  }, [clientIdNum]);

  const handleUploadCdc = async (file: File) => {
    setUploading(true);
    try {
      const created = await api.uploadCdc(clientIdNum, file);
      toast({ title: "CDC importé", description: file.name });
      router.push(`/analyse/${clientIdNum}/${created.id}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur d'upload";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteCdc = async (cdcId: number) => {
    setDeleting(cdcId);
    try {
      await api.deleteCdc(cdcId);
      toast({ title: "CDC supprimé" });
      await reload();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur suppression CDC";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-soft px-4 md:px-6">
        <nav className="flex min-w-0 flex-1 items-center gap-2 text-sm">
          <Link
            href="/analyse?stay=1"
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-muted-foreground transition-colors hover:bg-accent-soft hover:text-accent"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            <span className="hidden md:inline">Clients</span>
          </Link>
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
          <span className="min-w-0 truncate font-semibold tracking-tight">
            {client?.name || (loading ? "…" : "Client")}
          </span>
        </nav>
        <div className="flex items-center gap-2">
          <PipelineBadges
            version={pipelineVersion}
            compact
            className="hidden md:flex"
          />
          <NotificationsBell />
        </div>
      </header>

      <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-6">
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-accent">
              Cahiers des charges
            </div>
            <h1 className="mt-0.5 text-xl font-semibold tracking-tight">
              {client?.name || "Client"}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Cahiers des charges importés pour ce client. Cliquez sur un CDC
              pour afficher son rapport d&apos;analyse.
            </p>
          </div>

          <UploadDropzone
            accept=".pdf,.docx,.txt,.md,.xlsx,.xls"
            disabled={uploading}
            onFile={handleUploadCdc}
            title={
              uploading ? "Import en cours…" : "Déposer un cahier des charges"
            }
            hint="Formats admis : PDF, DOCX, XLSX, XLS, TXT, MD — 50 Mo max"
          />

          <section>
            <div className="mb-3 flex items-baseline justify-between">
              <h2 className="text-sm font-semibold tracking-tight">
                CDCs importés
                {!loading && cdcs.length > 0 ? (
                  <span className="ml-2 text-xs font-normal text-muted-foreground tabular-nums">
                    ({cdcs.length})
                  </span>
                ) : null}
              </h2>
            </div>

            {loading ? (
              <div className="flex items-center gap-2 rounded-2xl border border-soft bg-card p-6 text-sm text-muted-foreground shadow-tinted-sm">
                <Loader2 className="h-4 w-4 animate-spin" />
                Chargement…
              </div>
            ) : cdcs.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-soft bg-muted/20 p-8 text-center text-sm text-muted-foreground">
                Aucun CDC pour ce client. Déposez un document ci-dessus pour
                démarrer.
              </div>
            ) : (
              <ul className="grid gap-3">
                {cdcs.map((c) => {
                  const cov = c.coverage_percent;
                  const covCls =
                    typeof cov === "number"
                      ? cov >= 70
                        ? "border-success/25 bg-success-soft text-success"
                        : cov >= 40
                        ? "border-warning/25 bg-warning-soft text-warning"
                        : "border-danger/25 bg-danger-soft text-danger"
                      : "";
                  return (
                    <li key={c.id}>
                      <Link
                        href={`/analyse/${clientIdNum}/${c.id}`}
                        className="group flex items-center gap-3 rounded-2xl border border-soft bg-card p-3.5 shadow-tinted-sm transition-all hover:-translate-y-0.5 hover:border-accent/30 hover:shadow-tinted-md"
                      >
                        <FileIcon ext={getExt(c.filename)} />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-semibold tracking-tight">
                            {c.filename}
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                            <StatusPill status={c.status} />
                            {typeof cov === "number" ? (
                              <>
                                <span
                                  className="h-1 w-1 rounded-full bg-border"
                                  aria-hidden
                                />
                                <span
                                  className={cn(
                                    "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium tabular-nums",
                                    covCls,
                                  )}
                                >
                                  <CheckCircle2 className="h-3 w-3" />
                                  {cov.toFixed(0)}% couvert
                                </span>
                              </>
                            ) : null}
                            {c.uploaded_at ? (
                              <>
                                <span
                                  className="h-1 w-1 rounded-full bg-border"
                                  aria-hidden
                                />
                                <span>{relativeDate(c.uploaded_at)}</span>
                              </>
                            ) : null}
                          </div>
                        </div>
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              aria-label="Supprimer"
                              onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                              }}
                              className="h-8 w-8 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 hover:text-danger"
                              disabled={deleting === c.id}
                            >
                              {deleting === c.id ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Trash2 className="h-4 w-4" />
                              )}
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>
                                Supprimer ce CDC ?
                              </AlertDialogTitle>
                              <AlertDialogDescription>
                                <strong>{c.filename}</strong> et son analyse
                                seront supprimés. Cette action est
                                irréversible.
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>Annuler</AlertDialogCancel>
                              <AlertDialogAction
                                onClick={() => void handleDeleteCdc(c.id)}
                                className="bg-danger text-danger-foreground hover:bg-danger/90"
                              >
                                Supprimer
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
