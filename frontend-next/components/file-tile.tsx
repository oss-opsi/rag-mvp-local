"use client";

import * as React from "react";
import { CheckCircle2, Trash2 } from "lucide-react";
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
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Tuile v4 d'un document indexé : card rounded-2xl avec ombre tintée, icône
 * de type colorée en chip soft, statut « indexé » en pastille avec border.
 */
export function FileTile({
  filename,
  chunks,
  onDelete,
}: {
  filename: string;
  chunks: number;
  onDelete?: () => void;
}) {
  const ext = getExt(filename);
  return (
    <div className="group relative flex items-start gap-3 rounded-2xl border border-soft bg-card p-3.5 shadow-tinted-sm transition-all hover:-translate-y-0.5 hover:border-accent/30 hover:shadow-tinted-md">
      <FileIcon ext={ext} />
      <div className="min-w-0 flex-1">
        <p
          className="break-words text-sm font-semibold leading-snug tracking-tight line-clamp-2"
          title={filename}
        >
          {filename}
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <span className="tabular-nums">{chunks} chunks</span>
          <span className="h-1 w-1 rounded-full bg-border" aria-hidden />
          <span className="inline-flex items-center gap-1 rounded-full border border-success/25 bg-success-soft px-2 py-0.5 text-[11px] font-medium text-success">
            <CheckCircle2 className="h-3 w-3" />
            Indexé
          </span>
        </div>
      </div>
      {onDelete ? (
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Supprimer"
              className="h-7 w-7 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Supprimer {filename} ?</AlertDialogTitle>
              <AlertDialogDescription>
                Tous les chunks associés seront retirés de l&apos;index.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Annuler</AlertDialogCancel>
              <AlertDialogAction
                onClick={onDelete}
                className="bg-danger text-danger-foreground hover:bg-danger/90"
              >
                Supprimer
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      ) : null}
    </div>
  );
}

function getExt(filename: string): string {
  const m = filename.toLowerCase().match(/\.([a-z0-9]+)$/);
  if (!m) return "FIC";
  const ext = m[1];
  if (ext === "pdf") return "PDF";
  if (ext === "doc" || ext === "docx") return "DOC";
  if (ext === "txt") return "TXT";
  if (ext === "md") return "MD";
  return ext.toUpperCase().slice(0, 4);
}

const ICON_STYLES: Record<string, string> = {
  PDF: "bg-gradient-to-br from-danger-soft to-warning-soft text-danger",
  DOC: "bg-gradient-to-br from-accent-soft to-violet-soft text-accent",
  TXT: "bg-muted/60 text-muted-foreground",
  MD: "bg-muted/60 text-muted-foreground",
};

function FileIcon({ ext }: { ext: string }) {
  const style = ICON_STYLES[ext] ?? "bg-muted/60 text-muted-foreground";
  return (
    <div
      className={cn(
        "flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-[10px] font-bold tracking-wider",
        style,
      )}
      aria-hidden
    >
      {ext}
    </div>
  );
}
