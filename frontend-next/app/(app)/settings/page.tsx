"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { LogOut, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
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
import { ContextPanel } from "@/components/context-panel";
import { useAppShell } from "@/components/app-shell-context";
import { useToast } from "@/components/ui/use-toast";
import { LlmModelsCard } from "@/components/llm-models-card";
import { api } from "@/lib/api-client";
import type { ApiKeyInfo } from "@/lib/types";

export default function SettingsPage() {
  const router = useRouter();
  const { toast } = useToast();
  const { user } = useAppShell();
  const isAdmin = user?.role === "admin";

  const [keyInfo, setKeyInfo] = React.useState<ApiKeyInfo | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [editing, setEditing] = React.useState(false);
  const [newKey, setNewKey] = React.useState("");
  const [saving, setSaving] = React.useState(false);

  const reload = React.useCallback(async () => {
    setLoading(true);
    try {
      const info = await api.getApiKey();
      setKeyInfo(info);
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

  const handleSave = async () => {
    if (!newKey.trim()) return;
    setSaving(true);
    try {
      await api.setApiKey(newKey.trim());
      setNewKey("");
      setEditing(false);
      await reload();
      toast({ title: "Clé API enregistrée" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    try {
      await api.deleteApiKey();
      await reload();
      toast({ title: "Clé API supprimée" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch {
      // ignore
    }
    router.push("/login");
    router.refresh();
  };

  return (
    <div className="flex h-full flex-col">
      <ContextPanel>
        <div className="flex h-full flex-col">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">Paramètres</h2>
          </div>
          <nav className="flex flex-col py-2 text-sm">
            <a
              href="#compte"
              className="px-4 py-2 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            >
              Compte
            </a>
            <a
              href="#api-key"
              className="px-4 py-2 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            >
              Clé API OpenAI
            </a>
            <a
              href="#pipeline"
              className="px-4 py-2 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            >
              Pipeline
            </a>
            {isAdmin ? (
              <a
                href="#llm-models"
                className="px-4 py-2 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
              >
                Modèles LLM
              </a>
            ) : null}
          </nav>
        </div>
      </ContextPanel>
      <header className="flex h-14 shrink-0 items-center border-b border-border px-4 md:px-6">
        <div className="text-sm font-semibold">
          Paramètres
          {user?.name ? (
            <>
              <span className="mx-1.5 text-muted-foreground">—</span>
              <span className="font-normal text-muted-foreground">
                {user.name}
              </span>
            </>
          ) : null}
        </div>
      </header>

      <div className="flex-1 overflow-auto">
        <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-5 md:p-6">
          <section
            id="compte"
            className="rounded-lg border border-border bg-background p-5"
          >
            <h2 className="mb-3 text-lg font-semibold">Compte</h2>
            <div className="mb-4 grid grid-cols-[120px_1fr] gap-2 text-sm">
              <div className="text-muted-foreground">Nom</div>
              <div className="font-medium">{user?.name || "—"}</div>
              <div className="text-muted-foreground">Identifiant</div>
              <div className="font-mono">{user?.user_id ?? "—"}</div>
            </div>
            <Separator className="my-4" />
            <Button variant="outline" onClick={() => void handleLogout()}>
              <LogOut className="mr-2 h-4 w-4" />
              Déconnexion
            </Button>
          </section>

          <section
            id="api-key"
            className="rounded-lg border border-border bg-background p-5"
          >
            <h2 className="mb-3 text-lg font-semibold">Clé API OpenAI</h2>
            <p className="mb-4 text-sm text-muted-foreground">
              Cette clé est utilisée pour les appels OpenAI (génération et
              ré-analyse). Elle est chiffrée côté serveur.
            </p>

            {loading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> Chargement...
              </div>
            ) : keyInfo?.has_key && !editing ? (
              <div className="flex flex-wrap items-center gap-3">
                <code className="rounded bg-muted px-2 py-1 font-mono text-xs">
                  {keyInfo.masked || "••••••••"}
                </code>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setEditing(true)}
                >
                  Remplacer
                </Button>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button variant="destructive" size="sm">
                      Supprimer
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Supprimer la clé API ?</AlertDialogTitle>
                      <AlertDialogDescription>
                        Vous ne pourrez plus lancer d'analyse tant qu'une clé
                        n'aura pas été reconfigurée.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Annuler</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => void handleDelete()}
                        className="bg-danger text-danger-foreground hover:bg-danger/90"
                      >
                        Supprimer
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="openai-key">Nouvelle clé</Label>
                  <Input
                    id="openai-key"
                    type="password"
                    value={newKey}
                    onChange={(e) => setNewKey(e.target.value)}
                    placeholder="sk-..."
                    autoComplete="off"
                  />
                </div>
                <div className="flex gap-2">
                  <Button
                    onClick={() => void handleSave()}
                    disabled={saving || !newKey.trim()}
                  >
                    {saving ? "Enregistrement..." : "Enregistrer"}
                  </Button>
                  {keyInfo?.has_key ? (
                    <Button
                      variant="outline"
                      onClick={() => {
                        setEditing(false);
                        setNewKey("");
                      }}
                    >
                      Annuler
                    </Button>
                  ) : null}
                </div>
              </div>
            )}
          </section>

          <section
            id="pipeline"
            className="rounded-lg border border-border bg-background p-5"
          >
            <h2 className="mb-3 text-lg font-semibold">Pipeline</h2>
            <p className="mb-3 text-sm text-muted-foreground">
              Le pipeline d'analyse combine HyDE, un re-pass sur les exigences
              ambiguës, le modèle d'embedding bge-m3, le reranker v2-m3, et un
              chunker sémantique version 2. Les modèles LLM utilisés sont
              configurables par un administrateur.
            </p>
            <PipelineBadges />
          </section>

          {isAdmin ? (
            <section
              id="llm-models"
              className="rounded-lg border border-border bg-background p-5"
            >
              <h2 className="mb-1 text-lg font-semibold">Modèles LLM</h2>
              <p className="mb-4 text-xs text-muted-foreground">
                Réservé aux administrateurs.
              </p>
              <LlmModelsCard />
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}
