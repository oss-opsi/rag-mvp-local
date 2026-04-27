"use client";

import * as React from "react";
import { Plus, Trash2 } from "lucide-react";
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
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { Client } from "@/lib/types";

export function ClientsSidebar({
  clients,
  selectedId,
  onSelect,
  onCreate,
  onDelete,
  cdcCounts,
}: {
  clients: Client[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  onCreate: (name: string) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  cdcCounts: Record<number, number>;
}) {
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [newName, setNewName] = React.useState("");
  const [creating, setCreating] = React.useState(false);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      await onCreate(newName.trim());
      setNewName("");
      setDialogOpen(false);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-soft px-4 py-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Workspace
          </div>
          <h2 className="mt-0.5 text-sm font-semibold tracking-tight">
            Clients
          </h2>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button size="icon" variant="ghost" aria-label="Nouveau client">
              <Plus className="h-4 w-4" />
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Nouveau client</DialogTitle>
            </DialogHeader>
            <div className="space-y-2">
              <Label htmlFor="client-name">Nom du client</Label>
              <Input
                id="client-name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleCreate();
                }}
                placeholder="Ex. Société ACME"
              />
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setDialogOpen(false)}
                disabled={creating}
              >
                Annuler
              </Button>
              <Button
                onClick={handleCreate}
                disabled={creating || !newName.trim()}
              >
                {creating ? "Création..." : "Créer"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <ScrollArea className="flex-1">
        <ul className="flex flex-col gap-1 p-2">
          {clients.length === 0 ? (
            <li className="px-4 py-6 text-center text-xs text-muted-foreground">
              Aucun client. Créez-en un pour commencer.
            </li>
          ) : null}
          {clients.map((c) => {
            const count = cdcCounts[c.id] ?? 0;
            const active = selectedId === c.id;
            return (
              <li key={c.id}>
                <div
                  className={cn(
                    "group relative flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition-all",
                    active
                      ? "bg-accent-soft text-accent shadow-tinted-sm"
                      : "text-muted-foreground hover:bg-card hover:text-foreground hover:shadow-tinted-sm",
                  )}
                >
                  {active ? (
                    <span
                      className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-accent"
                      aria-hidden
                    />
                  ) : null}
                  <button
                    type="button"
                    onClick={() => onSelect(c.id)}
                    className="flex min-w-0 flex-1 items-center justify-between gap-2 text-left"
                  >
                    <span className="truncate font-medium">{c.name}</span>
                    <span
                      className={cn(
                        "inline-flex h-5 min-w-[24px] items-center justify-center rounded-full px-1.5 text-[10px] font-semibold tabular-nums",
                        active
                          ? "bg-card text-accent shadow-tinted-sm"
                          : "border border-soft bg-muted/40 text-muted-foreground",
                      )}
                    >
                      {count}
                    </span>
                  </button>
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        size="icon"
                        variant="ghost"
                        aria-label="Supprimer le client"
                        className="h-7 w-7 opacity-0 transition-opacity group-hover:opacity-100 hover:text-danger focus-visible:opacity-100"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Supprimer le client ?</AlertDialogTitle>
                        <AlertDialogDescription>
                          Cette action supprimera le client « {c.name} » et
                          tous les CDCs associés. Elle est irréversible.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Annuler</AlertDialogCancel>
                        <AlertDialogAction
                          onClick={() => void onDelete(c.id)}
                          className="bg-danger text-danger-foreground hover:bg-danger/90"
                        >
                          Supprimer
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </li>
            );
          })}
        </ul>
      </ScrollArea>
    </div>
  );
}
