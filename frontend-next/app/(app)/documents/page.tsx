"use client";

import * as React from "react";
import { Loader2, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
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
import type { CollectionInfo } from "@/lib/types";

export default function DocumentsPage() {
  const { toast } = useToast();
  const [info, setInfo] = React.useState<CollectionInfo | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [uploading, setUploading] = React.useState(false);

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

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      await api.uploadDocument(file);
      await reload();
      toast({ title: "Document indexé", description: file.name });
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
          {uploading ? "Import..." : "Importer"}
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
        <div className="flex flex-col gap-4 p-6">
          <PipelineBadges />

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
        </div>
      </div>
    </div>
  );
}
