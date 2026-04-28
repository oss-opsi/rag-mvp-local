"use client";

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter, notFound } from "next/navigation";
import { ChevronLeft, ChevronRight, Loader2, Upload } from "lucide-react";

const LAST_CLIENT_KEY = "tellme.analyse.lastClientId";
import { Button } from "@/components/ui/button";
import { UploadDropzone } from "@/components/upload-dropzone";
import { NotificationsBell } from "@/components/notifications-bell";
import { PipelineBadges } from "@/components/pipeline-badges";
import { useToast } from "@/components/ui/use-toast";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api-client";
import { StatusPill, CoverageBadge } from "../_helpers";
import type { Cdc, Client } from "@/lib/types";

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

  const reload = React.useCallback(async () => {
    setLoading(true);
    try {
      const [allClients, data] = await Promise.all([
        api.clients(),
        api.clientCdcs(clientIdNum),
      ]);
      const c = allClients.find((x) => x.id === clientIdNum);
      if (!c) {
        // Client supprimé ou introuvable → retour à la liste.
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

  // Mémorise le dernier client visité pour l'auto-redirect depuis /analyse.
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
      // Naviguer directement vers le rapport (URL = source de vérité).
      router.push(`/analyse/${clientIdNum}/${created.id}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur d'upload";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setUploading(false);
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

      <div className="flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-5 md:p-6">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-accent">
              Cahiers des charges
            </div>
            <h1 className="mt-0.5 text-xl font-semibold tracking-tight">
              {client?.name || "Client"}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Sélectionnez un CDC pour afficher son rapport, ou importez-en un
              nouveau.
            </p>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Chargement…
            </div>
          ) : cdcs.length === 0 ? (
            <div>
              <h2 className="mb-3 text-base font-semibold tracking-tight">
                Importer un cahier des charges
              </h2>
              <p className="mb-4 text-sm text-muted-foreground">
                Formats acceptés : PDF, DOCX, TXT, MD, XLSX, XLS. Taille maximale 50 Mo.
              </p>
              <UploadDropzone
                accept=".pdf,.docx,.txt,.md,.xlsx,.xls"
                disabled={uploading}
                onFile={(f) => void handleUploadCdc(f)}
                title={uploading ? "Import en cours…" : "Déposez le CDC ici"}
              />
            </div>
          ) : (
            <div>
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-base font-semibold tracking-tight">
                  {cdcs.length} CDC{cdcs.length > 1 ? "s" : ""}
                </h2>
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-[11px] text-muted-foreground">
                    PDF · DOCX · XLSX · XLS · TXT · MD · 50 Mo max
                  </span>
                  <label
                    className={cn(
                      "inline-flex cursor-pointer items-center gap-2 rounded-md border border-soft bg-card px-3 py-1.5 text-sm transition-colors hover:bg-accent-soft hover:text-accent",
                      uploading && "pointer-events-none opacity-60",
                    )}
                  >
                    <Upload className="h-4 w-4" />
                    {uploading ? "Import…" : "Ajouter un CDC"}
                    <input
                      type="file"
                      className="hidden"
                      accept=".pdf,.docx,.txt,.md,.xlsx,.xls"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) void handleUploadCdc(f);
                        e.target.value = "";
                      }}
                    />
                  </label>
                </div>
              </div>
              <ul className="grid gap-3">
                {cdcs.map((c) => (
                  <li key={c.id}>
                    <Link
                      href={`/analyse/${clientIdNum}/${c.id}`}
                      className="group flex items-center gap-3 rounded-2xl border border-soft bg-card p-4 shadow-tinted-sm transition-all hover:-translate-y-0.5 hover:border-accent/30 hover:shadow-tinted-md"
                    >
                      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-danger-soft to-warning-soft text-[10px] font-bold tracking-wider text-danger">
                        {(c.filename.split(".").pop() || "FIC").toUpperCase().slice(0, 4)}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-semibold tracking-tight">
                          {c.filename}
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          <StatusPill status={c.status} />
                        </div>
                      </div>
                      <CoverageBadge percent={c.coverage_percent} size="sm" />
                      <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground transition-all group-hover:translate-x-0.5 group-hover:text-accent" />
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
