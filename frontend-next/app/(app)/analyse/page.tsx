"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Building2, FileText, Loader2, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NotificationsBell } from "@/components/notifications-bell";
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
import { useToast } from "@/components/ui/use-toast";
import { api } from "@/lib/api-client";
import type { Client } from "@/lib/types";

const LAST_CLIENT_KEY = "tellme.analyse.lastClientId";

export default function ClientsIndexPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { toast } = useToast();

  // ?stay=1 désactive l'auto-redirect (utile quand on revient via le breadcrumb
  // depuis /analyse/[clientId] et qu'on veut volontairement voir la grille).
  const stayHere = searchParams.get("stay") === "1";

  const [clients, setClients] = React.useState<Client[]>([]);
  const [cdcCounts, setCdcCounts] = React.useState<Record<number, number>>({});
  const [loading, setLoading] = React.useState(true);
  const [autoRedirected, setAutoRedirected] = React.useState(false);

  const [createOpen, setCreateOpen] = React.useState(false);
  const [newName, setNewName] = React.useState("");
  const [creating, setCreating] = React.useState(false);

  const reload = React.useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.clients();
      setClients(list);

      // Auto-redirect vers le dernier client visité (ou unique client) :
      //   - 1 seul client → redirect direct
      //   - sinon, si un last-visited valide est en localStorage → redirect
      //   - sauf si ?stay=1 (retour explicite depuis breadcrumb)
      if (!stayHere && !autoRedirected && list.length > 0) {
        let target: number | null = null;
        if (list.length === 1) {
          target = list[0]!.id;
        } else {
          try {
            const raw = window.localStorage.getItem(LAST_CLIENT_KEY);
            const parsed = raw ? Number(raw) : NaN;
            if (
              Number.isFinite(parsed) &&
              list.some((c) => c.id === parsed)
            ) {
              target = parsed;
            }
          } catch {
            /* ignore */
          }
        }
        if (target !== null) {
          setAutoRedirected(true);
          router.replace(`/analyse/${target}`);
          return;
        }
      }

      // Charger les comptes CDC en parallèle (best-effort, silencieux)
      const counts: Record<number, number> = {};
      await Promise.all(
        list.map(async (c) => {
          try {
            const data = await api.clientCdcs(c.id);
            counts[c.id] = (data.cdcs || []).length;
          } catch {
            counts[c.id] = 0;
          }
        }),
      );
      setCdcCounts(counts);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur de chargement";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [autoRedirected, router, stayHere, toast]);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      await api.createClient(newName.trim());
      toast({ title: "Client créé", description: newName.trim() });
      setNewName("");
      setCreateOpen(false);
      await reload();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur création client";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await api.deleteClient(id);
      toast({ title: "Client supprimé" });
      await reload();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur suppression client";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-soft px-4 md:px-6">
        <div className="text-sm font-semibold tracking-tight">
          Analyse d&apos;écarts
          <span className="mx-1.5 text-muted-foreground">—</span>
          <span className="font-normal text-muted-foreground">Clients</span>
        </div>
        <div className="flex items-center gap-2">
          <Dialog open={createOpen} onOpenChange={setCreateOpen}>
            <DialogTrigger asChild>
              <Button size="sm">
                <Plus className="mr-1.5 h-4 w-4" />
                Nouveau client
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
                  autoFocus
                />
              </div>
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => setCreateOpen(false)}
                  disabled={creating}
                >
                  Annuler
                </Button>
                <Button onClick={handleCreate} disabled={creating || !newName.trim()}>
                  {creating ? "Création..." : "Créer"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          <NotificationsBell />
        </div>
      </header>

      <div className="flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-5 md:p-6">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-accent">
              Clients
            </div>
            <h1 className="mt-0.5 text-xl font-semibold tracking-tight">
              {loading
                ? "Chargement…"
                : clients.length === 0
                ? "Aucun client"
                : `${clients.length} client${clients.length > 1 ? "s" : ""}`}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Sélectionnez un client pour accéder à ses cahiers des charges.
            </p>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Chargement des clients…
            </div>
          ) : clients.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-soft bg-muted/20 p-8 text-center">
              <p className="text-sm text-muted-foreground">
                Aucun client pour l&apos;instant. Créez-en un pour démarrer.
              </p>
            </div>
          ) : (
            <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {clients.map((c) => (
                <li key={c.id} className="group relative">
                  <Link
                    href={`/analyse/${c.id}`}
                    className="flex flex-col gap-3 rounded-2xl border border-soft bg-card p-5 shadow-tinted-sm transition-all hover:-translate-y-0.5 hover:border-accent/30 hover:shadow-tinted-md"
                  >
                    <div className="flex items-start gap-3">
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-violet text-white shadow-tinted-sm">
                        <Building2 className="h-5 w-5" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-semibold tracking-tight">
                          {c.name}
                        </div>
                        <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          <span className="inline-flex items-center gap-1">
                            <FileText className="h-3 w-3" />
                            {cdcCounts[c.id] ?? 0} CDC
                            {(cdcCounts[c.id] ?? 0) > 1 ? "s" : ""}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center justify-between border-t border-soft pt-3 text-xs text-muted-foreground">
                      <span>Voir les CDCs →</span>
                    </div>
                  </Link>
                  {/* Bouton supprimer client (visible au hover) */}
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        size="icon"
                        variant="ghost"
                        aria-label="Supprimer le client"
                        className="absolute right-3 top-3 h-7 w-7 text-muted-foreground opacity-0 transition-opacity hover:bg-danger-soft hover:text-danger group-hover:opacity-100 focus-visible:opacity-100"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Supprimer le client ?</AlertDialogTitle>
                        <AlertDialogDescription>
                          Cette action supprimera le client « {c.name} » et tous
                          les CDCs associés. Elle est irréversible.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Annuler</AlertDialogCancel>
                        <AlertDialogAction
                          onClick={() => void handleDelete(c.id)}
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
