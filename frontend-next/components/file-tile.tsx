"use client";

import * as React from "react";
import { Trash2 } from "lucide-react";
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
 * Tuile d'un document indexé, façon mockup Section 7 :
 * [icone type] | nom tronqué | « X chunks · indexé »
 * + bouton de suppression dans un coin.
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
    <div className="group relative flex items-start gap-3 rounded-md border border-border bg-background p-3 transition-colors hover:border-accent/40">
      <FileIcon ext={ext} />
      <div className="min-w-0 flex-1">
        <p
          className="break-words text-sm font-medium leading-snug line-clamp-2"
          title={filename}
        >
          {filename}
        </p>
        <p className="mt-1 text-xs text-muted-foreground tabular-nums">
          {chunks} chunks · <span className="text-success">indexé</span>
        </p>
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
  PDF: "bg-danger/10 text-danger border-danger/20",
  DOC: "bg-accent/10 text-accent border-accent/20",
  TXT: "bg-muted text-muted-foreground border-border",
  MD: "bg-muted text-muted-foreground border-border",
};

function FileIcon({ ext }: { ext: string }) {
  const style = ICON_STYLES[ext] ?? "bg-muted text-muted-foreground border-border";
  return (
    <div
      className={cn(
        "flex h-11 w-11 shrink-0 items-center justify-center rounded-md border text-[10px] font-bold tracking-wider",
        style,
      )}
    >
      {ext}
    </div>
  );
}
