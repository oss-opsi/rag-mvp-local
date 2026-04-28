"use client";

import * as React from "react";
import {
  AlertCircle,
  CheckCircle2,
  FileSpreadsheet,
  Loader2,
  Upload,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/use-toast";
import { api } from "@/lib/api-client";
import { cn } from "@/lib/utils";

type ImportResult = Awaited<ReturnType<typeof api.importCorrections>>;

export function ImportCorrectionsDialog({
  open,
  onOpenChange,
  analysisId,
  onApplied,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  analysisId: number | string;
  /** Appelé après import réussi (applied > 0) — le caller peut recharger
   *  les corrections du rapport pour rafraîchir l'UI. Reçoit le résultat. */
  onApplied?: (result: ImportResult) => void | Promise<void>;
}) {
  const { toast } = useToast();
  const [file, setFile] = React.useState<File | null>(null);
  const [dragOver, setDragOver] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [result, setResult] = React.useState<ImportResult | null>(null);
  const inputRef = React.useRef<HTMLInputElement | null>(null);

  // Reset à chaque ouverture
  React.useEffect(() => {
    if (open) {
      setFile(null);
      setResult(null);
      setLoading(false);
      setDragOver(false);
    }
  }, [open]);

  const handleFile = (f: File | null) => {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".xlsx")) {
      toast({
        title: "Format non supporté",
        description: "Seul le format .xlsx exporté depuis le rapport est accepté.",
        variant: "destructive",
      });
      return;
    }
    setFile(f);
    setResult(null);
  };

  const handleSubmit = async () => {
    if (!file) return;
    setLoading(true);
    try {
      const res = await api.importCorrections(analysisId, file);
      setResult(res);
      if (res.applied > 0) {
        toast({
          title: `${res.applied} correction${res.applied > 1 ? "s" : ""} appliquée${res.applied > 1 ? "s" : ""}`,
          description:
            res.ignored.length > 0
              ? `${res.ignored.length} ligne(s) ignorée(s) — voir détails.`
              : undefined,
        });
        if (onApplied) await onApplied(res);
      } else {
        toast({
          title: "Aucune correction appliquée",
          description: "Vérifiez que les colonnes Verdict humain sont remplies dans le fichier.",
          variant: "destructive",
        });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur d'import";
      toast({ title: "Erreur d'import", description: msg, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileSpreadsheet className="h-5 w-5 text-accent" />
            Importer des corrections
          </DialogTitle>
        </DialogHeader>

        {result ? (
          <div className="space-y-4">
            <div className="rounded-2xl border border-success/25 bg-success-soft p-4 shadow-tinted-sm">
              <div className="flex items-center gap-2 text-success">
                <CheckCircle2 className="h-5 w-5" />
                <span className="font-semibold">
                  {result.applied} correction
                  {result.applied > 1 ? "s" : ""} appliquée
                  {result.applied > 1 ? "s" : ""}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Visibles immédiatement dans le rapport (badge « Validé » sur
                les exigences corrigées).
              </p>
            </div>

            {(result.ignored.length > 0 || result.errors.length > 0) && (
              <div className="rounded-2xl border border-warning/25 bg-warning-soft/60 p-4">
                <div className="flex items-center gap-2 text-warning">
                  <AlertCircle className="h-4 w-4" />
                  <span className="text-sm font-semibold">
                    {result.ignored.length + result.errors.length} ligne(s)
                    ignorée(s)
                  </span>
                </div>
                <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto text-xs text-muted-foreground">
                  {[...result.ignored, ...result.errors]
                    .slice(0, 20)
                    .map((row, i) => (
                      <li key={i} className="flex gap-1.5">
                        <span className="font-mono">
                          {row.requirement_id ||
                            (row as { raw_id?: string }).raw_id ||
                            "?"}
                        </span>
                        <span>·</span>
                        <span>{row.reason}</span>
                      </li>
                    ))}
                  {result.ignored.length + result.errors.length > 20 && (
                    <li className="italic">
                      … et{" "}
                      {result.ignored.length + result.errors.length - 20}{" "}
                      autre(s)
                    </li>
                  )}
                </ul>
              </div>
            )}

            <DialogFooter>
              <Button onClick={() => onOpenChange(false)} className="w-full">
                Fermer
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Déposez le fichier <code className="rounded-md border border-soft bg-muted/40 px-1 py-0.5 font-mono text-xs">.xlsx</code>{" "}
              que vous avez exporté depuis ce rapport et complété (3 colonnes
              à droite : <strong>Verdict humain</strong>,{" "}
              <strong>Description corrigée</strong>,{" "}
              <strong>Notes internes</strong>).
            </p>

            <div
              role="button"
              tabIndex={0}
              onClick={() => !loading && inputRef.current?.click()}
              onKeyDown={(e) => {
                if ((e.key === "Enter" || e.key === " ") && !loading) {
                  e.preventDefault();
                  inputRef.current?.click();
                }
              }}
              onDragOver={(e) => {
                e.preventDefault();
                if (!loading) setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                if (loading) return;
                const f = e.dataTransfer.files?.[0];
                if (f) handleFile(f);
              }}
              className={cn(
                "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed p-8 text-center transition-all",
                dragOver
                  ? "border-accent bg-accent-soft/60 shadow-tinted-md"
                  : "border-soft bg-muted/20 hover:border-accent/30 hover:bg-card",
                loading && "opacity-60",
              )}
            >
              <span
                className={cn(
                  "flex h-12 w-12 items-center justify-center rounded-2xl text-white shadow-tinted-md transition-transform",
                  dragOver
                    ? "bg-gradient-to-br from-accent to-violet scale-110"
                    : "bg-gradient-to-br from-accent to-violet",
                )}
                aria-hidden
              >
                <Upload className="h-5 w-5" />
              </span>
              {file ? (
                <div>
                  <div className="text-sm font-medium">{file.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {(file.size / 1024).toFixed(1)} Ko · cliquez pour changer
                  </div>
                </div>
              ) : (
                <div>
                  <div className="text-sm font-medium">
                    Glissez-déposez le fichier .xlsx
                  </div>
                  <div className="text-xs text-muted-foreground">
                    ou cliquez pour parcourir
                  </div>
                </div>
              )}
              <input
                ref={inputRef}
                type="file"
                className="hidden"
                accept=".xlsx"
                disabled={loading}
                onChange={(e) => {
                  const f = e.target.files?.[0] || null;
                  handleFile(f);
                  e.target.value = "";
                }}
              />
            </div>

            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={loading}
              >
                Annuler
              </Button>
              <Button
                onClick={() => void handleSubmit()}
                disabled={!file || loading}
              >
                {loading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Import en cours…
                  </>
                ) : (
                  "Importer les corrections"
                )}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
