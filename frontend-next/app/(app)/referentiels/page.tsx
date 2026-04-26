"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  FileText,
  Loader2,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { Topbar } from "@/components/topbar";
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
import { UploadDropzone } from "@/components/upload-dropzone";
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
          <div className="flex max-w-md flex-col items-center gap-3 rounded-lg border border-border bg-muted/30 p-8 text-center">
            <ShieldAlert className="h-8 w-8 text-muted-foreground" />
            <div className="text-base font-medium">Accès réservé</div>
            <p className="text-sm text-muted-foreground">
              Cette section est réservée aux administrateurs Opsidium. Elle
              contient les référentiels de méthodologie interne utilisés pour
              l'analyse des cahiers des charges client.
            </p>
            <Button variant="outline" onClick={() => router.push("/documents")}>
              Retour à l'indexation
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
        <div>
          <h1 className="text-xl font-semibold">Référentiels Opsidium</h1>
        </div>

        <UploadDropzone
          accept={ACCEPT}
          disabled={uploading}
          onFile={handleUpload}
          title={
            uploading
              ? "Indexation en cours…"
              : "Déposer vos documents"
          }
          hint="Formats admis : PDF, DOCX, XLSX, XLS"
        />

        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Référentiels indexés
            </h2>
            {!loading && docs.length > 0 ? (
              <Badge variant="secondary">{docs.length}</Badge>
            ) : null}
          </div>

          {loading ? (
            <div className="flex items-center gap-2 rounded-lg border border-border p-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Chargement…
            </div>
          ) : docs.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
              Aucun référentiel indexé pour le moment.
            </div>
          ) : (
            <ul className="divide-y divide-border rounded-lg border border-border">
              {docs.map((d) => (
                <li
                  key={d.source}
                  className="flex items-center justify-between gap-3 px-4 py-3"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">
                        {d.source}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {d.chunks} {d.chunks > 1 ? "chunks" : "chunk"} indexé
                        {d.chunks > 1 ? "s" : ""}
                      </div>
                    </div>
                  </div>
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-danger hover:bg-danger/10 hover:text-danger"
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
                          <strong>{d.source}</strong> sera retiré de l'index.
                          Les futures analyses de cahiers des charges ne s'y
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
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
