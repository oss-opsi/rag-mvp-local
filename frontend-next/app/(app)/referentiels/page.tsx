"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle2,
  Loader2,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { Topbar } from "@/components/topbar";
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
import { useToast } from "@/components/ui/use-toast";
import { useAppShell } from "@/components/app-shell-context";

type ReferentielDoc = {
  source: string;
  chunks: number;
};

const ACCEPT = ".pdf,.docx,.xlsx,.xls";
const MAX_BYTES = 50 * 1024 * 1024;
const SUPPORTED_EXT = [".pdf", ".docx", ".xlsx", ".xls"];

export default function ReferentielsPage() {
  const router = useRouter();
  const { toast } = useToast();
  const { user } = useAppShell();
  const isAdmin = user?.role === "admin";

  const [docs, setDocs] = React.useState<ReferentielDoc[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [uploading, setUploading] = React.useState(false);
  const [deleting, setDeleting] = React.useState<string | null>(null);

  const reload = React.useCallback(async () => {
    if (!isAdmin) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const listRes = await fetch("/api/admin/referentiels/list");
      if (!listRes.ok) {
        throw new Error("Lecture des référentiels impossible.");
      }
      const listJson = (await listRes.json()) as { documents: ReferentielDoc[] };
      setDocs(listJson.documents || []);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [isAdmin, toast]);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const handleUpload = async (file: File) => {
    if (uploading) return;

    const lower = file.name.toLowerCase();
    const ok = SUPPORTED_EXT.some((ext) => lower.endsWith(ext));
    if (!ok) {
      toast({
        title: "Format non supporté",
        description: "Formats acceptés : PDF, DOCX, XLSX, XLS.",
        variant: "destructive",
      });
      return;
    }
    if (file.size > MAX_BYTES) {
      toast({
        title: "Fichier trop volumineux",
        description: "Taille maximale : 50 Mo.",
        variant: "destructive",
      });
      return;
    }

    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/admin/referentiels/upload", {
        method: "POST",
        body: fd,
      });
      if (!res.ok) {
        const text = await res.text();
        let detail = "Indexation impossible.";
        try {
          const j = JSON.parse(text);
          if (j?.detail) detail = String(j.detail);
        } catch {
          if (text) detail = text;
        }
        throw new Error(detail);
      }
      const data = (await res.json()) as {
        source: string;
        chunks: number;
      };
      toast({
        title: "Référentiel indexé",
        description: `${data.source} — ${data.chunks} chunks.`,
      });
      await reload();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({
        title: "Échec de l'indexation",
        description: msg,
        variant: "destructive",
      });
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (source: string) => {
    setDeleting(source);
    try {
      const res = await fetch(
        `/api/admin/referentiels/${encodeURIComponent(source)}`,
        { method: "DELETE" }
      );
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || "Suppression impossible.");
      }
      const data = (await res.json()) as { deleted: number };
      toast({
        title: "Référentiel supprimé",
        description: `${source} — ${data.deleted} chunks retirés.`,
      });
      await reload();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({
        title: "Erreur",
        description: msg,
        variant: "destructive",
      });
    } finally {
      setDeleting(null);
    }
  };

  if (!isAdmin) {
    return (
      <div className="flex h-full flex-col">
        <Topbar
          breadcrumb={
            <>
              Référentiels{" "}
              <span className="mx-1.5 text-muted-foreground">—</span>
              <span className="font-normal text-muted-foreground">
                Méthodologie interne Opsidium
              </span>
            </>
          }
        />
        <div className="flex flex-1 items-center justify-center p-8">
          <div className="flex max-w-md flex-col items-center gap-4 rounded-2xl border border-soft bg-card p-8 text-center shadow-tinted-sm">
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-warning-soft to-danger-soft text-warning shadow-tinted-sm">
              <ShieldAlert className="h-6 w-6" />
            </span>
            <div className="space-y-1">
              <div className="text-base font-semibold tracking-tight">
                Accès réservé
              </div>
              <p className="text-sm text-muted-foreground">
                Cette section est réservée aux administrateurs Opsidium. Elle
                contient les référentiels de méthodologie interne utilisés pour
                l&apos;analyse des cahiers des charges client.
              </p>
            </div>
            <Button variant="outline" onClick={() => router.push("/documents")}>
              Retour à l&apos;indexation
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <Topbar breadcrumb="Référentiels" />

      <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-6">
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-accent">
              Méthodologie interne
            </div>
            <h1 className="mt-0.5 text-xl font-semibold tracking-tight">
              Référentiels Opsidium
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Documents méthodologiques utilisés à l&apos;analyse des cahiers des
              charges. Visibles uniquement par les administrateurs.
            </p>
          </div>

          <UploadDropzone
            accept={ACCEPT}
            disabled={uploading}
            onFile={handleUpload}
            title={
              uploading
                ? "Indexation en cours…"
                : "Déposer vos référentiels"
            }
            hint="Formats admis : PDF, DOCX, XLSX, XLS — 50 Mo max"
          />

          <section>
            <div className="mb-3 flex items-baseline justify-between">
              <h2 className="text-sm font-semibold tracking-tight">
                Référentiels indexés
                {!loading && docs.length > 0 ? (
                  <span className="ml-2 text-xs font-normal text-muted-foreground tabular-nums">
                    ({docs.length})
                  </span>
                ) : null}
              </h2>
            </div>

            {loading ? (
              <div className="flex items-center gap-2 rounded-2xl border border-soft bg-card p-6 text-sm text-muted-foreground shadow-tinted-sm">
                <Loader2 className="h-4 w-4 animate-spin" />
                Chargement…
              </div>
            ) : docs.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-soft bg-muted/20 p-8 text-center text-sm text-muted-foreground">
                Aucun référentiel indexé pour le moment. Déposez un document
                ci-dessus pour démarrer.
              </div>
            ) : (
              <ul className="grid gap-3">
                {docs.map((d) => (
                  <li key={d.source}>
                    <div className="group flex items-center gap-3 rounded-2xl border border-soft bg-card p-3.5 shadow-tinted-sm transition-all hover:-translate-y-0.5 hover:border-accent/30 hover:shadow-tinted-md">
                      <FileIcon ext={getExt(d.source)} />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-semibold tracking-tight">
                          {d.source}
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                          <span className="tabular-nums">
                            {d.chunks} {d.chunks > 1 ? "chunks" : "chunk"}
                          </span>
                          <span className="h-1 w-1 rounded-full bg-border" aria-hidden />
                          <span className="inline-flex items-center gap-1 rounded-full border border-success/25 bg-success-soft px-2 py-0.5 text-[11px] font-medium text-success">
                            <CheckCircle2 className="h-3 w-3" />
                            Indexé
                          </span>
                        </div>
                      </div>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label="Supprimer"
                            className="h-8 w-8 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 hover:text-danger"
                            disabled={deleting === d.source}
                          >
                            {deleting === d.source ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <Trash2 className="h-4 w-4" />
                            )}
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>
                              Supprimer ce référentiel ?
                            </AlertDialogTitle>
                            <AlertDialogDescription>
                              <strong>{d.source}</strong> sera retiré de l&apos;index.
                              Les futures analyses de cahiers des charges ne s&apos;y
                              référeront plus. Cette action est irréversible.
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
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
