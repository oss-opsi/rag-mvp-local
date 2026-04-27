"use client";

import * as React from "react";
import {
  KeyRound,
  Loader2,
  Shield,
  Trash2,
  UserPlus,
  Users as UsersIcon,
} from "lucide-react";
import { Topbar } from "@/components/topbar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import { useToast } from "@/components/ui/use-toast";
import { useAppShell } from "@/components/app-shell-context";
import { api } from "@/lib/api-client";
import { cn, initialsOf } from "@/lib/utils";
import type { AdminUser } from "@/lib/types";

export default function UsersPage() {
  const { toast } = useToast();
  const { user } = useAppShell();
  const isAdmin = user?.role === "admin";

  // ───── Self-service password ─────
  const [currentPwd, setCurrentPwd] = React.useState("");
  const [newPwd, setNewPwd] = React.useState("");
  const [newPwd2, setNewPwd2] = React.useState("");
  const [pwdLoading, setPwdLoading] = React.useState(false);

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPwd.length < 6) {
      toast({
        title: "Mot de passe trop court",
        description: "6 caractères minimum.",
        variant: "destructive",
      });
      return;
    }
    if (newPwd !== newPwd2) {
      toast({
        title: "Confirmation invalide",
        description: "Les deux nouveaux mots de passe ne correspondent pas.",
        variant: "destructive",
      });
      return;
    }
    setPwdLoading(true);
    try {
      await api.changePassword(currentPwd, newPwd);
      toast({ title: "Mot de passe mis à jour" });
      setCurrentPwd("");
      setNewPwd("");
      setNewPwd2("");
    } catch (err) {
      toast({
        title: "Erreur",
        description: err instanceof Error ? err.message : "Erreur",
        variant: "destructive",
      });
    } finally {
      setPwdLoading(false);
    }
  };

  // ───── Admin section ─────
  const [users, setUsers] = React.useState<AdminUser[]>([]);
  const [usersLoading, setUsersLoading] = React.useState(false);
  const [createOpen, setCreateOpen] = React.useState(false);

  const loadUsers = React.useCallback(async () => {
    if (!isAdmin) return;
    setUsersLoading(true);
    try {
      const list = await api.adminListUsers();
      setUsers(list);
    } catch (err) {
      toast({
        title: "Erreur",
        description: err instanceof Error ? err.message : "Erreur",
        variant: "destructive",
      });
    } finally {
      setUsersLoading(false);
    }
  }, [isAdmin, toast]);

  React.useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  // Create user
  const [newU, setNewU] = React.useState({
    username: "",
    name: "",
    email: "",
    password: "",
    role: "user" as "user" | "admin",
  });
  const [creating, setCreating] = React.useState(false);

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newU.username.length < 3) {
      toast({
        title: "Nom invalide",
        description: "3 caractères minimum.",
        variant: "destructive",
      });
      return;
    }
    if (newU.password.length < 6) {
      toast({
        title: "Mot de passe trop court",
        description: "6 caractères minimum.",
        variant: "destructive",
      });
      return;
    }
    setCreating(true);
    try {
      await api.adminCreateUser(newU);
      toast({ title: `Utilisateur « ${newU.username} » créé` });
      setNewU({
        username: "",
        name: "",
        email: "",
        password: "",
        role: "user",
      });
      void loadUsers();
    } catch (err) {
      toast({
        title: "Erreur",
        description: err instanceof Error ? err.message : "Erreur",
        variant: "destructive",
      });
    } finally {
      setCreating(false);
    }
  };

  const handleResetPassword = async (username: string) => {
    const pwd = window.prompt(
      `Nouveau mot de passe pour « ${username} » (6 caractères min.) :`,
    );
    if (!pwd) return;
    if (pwd.length < 6) {
      toast({
        title: "Mot de passe trop court",
        variant: "destructive",
      });
      return;
    }
    try {
      await api.adminResetPassword(username, pwd);
      toast({ title: `Mot de passe de « ${username} » réinitialisé` });
    } catch (err) {
      toast({
        title: "Erreur",
        description: err instanceof Error ? err.message : "Erreur",
        variant: "destructive",
      });
    }
  };

  const handleDelete = async (username: string) => {
    try {
      await api.adminDeleteUser(username);
      toast({ title: `Utilisateur « ${username} » supprimé` });
      void loadUsers();
    } catch (err) {
      toast({
        title: "Erreur",
        description: err instanceof Error ? err.message : "Erreur",
        variant: "destructive",
      });
    }
  };

  const handleToggleRole = async (target: AdminUser) => {
    const next = target.role === "admin" ? "user" : "admin";
    try {
      await api.adminSetRole(target.username, next);
      toast({
        title: `Rôle de « ${target.username} » : ${next}`,
      });
      void loadUsers();
    } catch (err) {
      toast({
        title: "Erreur",
        description: err instanceof Error ? err.message : "Erreur",
        variant: "destructive",
      });
    }
  };

  return (
    <div className="flex h-full flex-col">
      <Topbar
        breadcrumb={
          <>
            Utilisateurs{" "}
            <span className="mx-1.5 text-muted-foreground">—</span>
            <span className="font-normal text-muted-foreground">
              {user?.name || user?.user_id}
            </span>
          </>
        }
      />

      <div className="flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-5 md:p-6">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-accent">
              Comptes & accès
            </div>
            <h1 className="mt-0.5 text-xl font-semibold tracking-tight">
              Utilisateurs
            </h1>
          </div>
          {/* ── Top row : Mon mot de passe + Créer un utilisateur ── */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {/* Mon mot de passe */}
            <section className="rounded-2xl border border-soft bg-card p-5 shadow-tinted-sm">
              <div className="mb-4 flex items-center gap-2">
                <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-accent-soft text-accent">
                  <KeyRound className="h-4 w-4" />
                </span>
                <h2 className="text-base font-semibold tracking-tight">
                  Mon mot de passe
                </h2>
              </div>
              <form onSubmit={handleChangePassword} className="space-y-3">
                <div className="space-y-1.5">
                  <Label htmlFor="cur-pwd">Mot de passe actuel</Label>
                  <Input
                    id="cur-pwd"
                    type="password"
                    autoComplete="current-password"
                    value={currentPwd}
                    onChange={(e) => setCurrentPwd(e.target.value)}
                    required
                    disabled={pwdLoading}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="new-pwd">Nouveau mot de passe</Label>
                  <Input
                    id="new-pwd"
                    type="password"
                    autoComplete="new-password"
                    value={newPwd}
                    onChange={(e) => setNewPwd(e.target.value)}
                    required
                    disabled={pwdLoading}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="new-pwd-2">Confirmation</Label>
                  <Input
                    id="new-pwd-2"
                    type="password"
                    autoComplete="new-password"
                    value={newPwd2}
                    onChange={(e) => setNewPwd2(e.target.value)}
                    required
                    disabled={pwdLoading}
                  />
                </div>
                <Button type="submit" disabled={pwdLoading} className="w-full">
                  {pwdLoading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Mise à jour...
                    </>
                  ) : (
                    "Changer le mot de passe"
                  )}
                </Button>
              </form>
            </section>

            {/* Créer un utilisateur (admin) */}
            <section
              className={cn(
                "rounded-2xl border border-soft bg-card p-5 shadow-tinted-sm",
                !isAdmin && "opacity-60",
              )}
            >
              <div className="mb-4 flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-violet-soft text-violet">
                    <UserPlus className="h-4 w-4" />
                  </span>
                  <h2 className="text-base font-semibold tracking-tight">
                    Créer un utilisateur
                  </h2>
                </div>
                <span className="inline-flex items-center gap-1 rounded-full border border-accent/25 bg-accent-soft px-2.5 py-0.5 text-[11px] font-medium text-accent">
                  Admin
                </span>
              </div>
              {!isAdmin ? (
                <p className="text-sm text-muted-foreground">
                  Seuls les administrateurs peuvent créer de nouveaux comptes.
                </p>
              ) : (
                <form onSubmit={handleCreateUser} className="space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="nu-username">Identifiant</Label>
                      <Input
                        id="nu-username"
                        value={newU.username}
                        onChange={(e) =>
                          setNewU((s) => ({ ...s, username: e.target.value }))
                        }
                        required
                        disabled={creating}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="nu-name">Nom affiché</Label>
                      <Input
                        id="nu-name"
                        value={newU.name}
                        onChange={(e) =>
                          setNewU((s) => ({ ...s, name: e.target.value }))
                        }
                        disabled={creating}
                      />
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="nu-email">Email (optionnel)</Label>
                    <Input
                      id="nu-email"
                      type="email"
                      value={newU.email}
                      onChange={(e) =>
                        setNewU((s) => ({ ...s, email: e.target.value }))
                      }
                      disabled={creating}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="nu-pwd">Mot de passe initial</Label>
                    <Input
                      id="nu-pwd"
                      type="password"
                      value={newU.password}
                      onChange={(e) =>
                        setNewU((s) => ({ ...s, password: e.target.value }))
                      }
                      required
                      disabled={creating}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="nu-role">Rôle</Label>
                    <select
                      id="nu-role"
                      value={newU.role}
                      onChange={(e) =>
                        setNewU((s) => ({
                          ...s,
                          role: e.target.value as "user" | "admin",
                        }))
                      }
                      disabled={creating}
                      className="flex h-9 w-full rounded-md border border-soft bg-card px-3 py-1 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent"
                    >
                      <option value="user">Utilisateur</option>
                      <option value="admin">Administrateur</option>
                    </select>
                  </div>
                  <Button type="submit" disabled={creating} className="w-full">
                    {creating ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Création...
                      </>
                    ) : (
                      "Créer le compte"
                    )}
                  </Button>
                </form>
              )}
            </section>
          </div>

          {/* ── Liste des utilisateurs (admin only) ── */}
          {isAdmin ? (
            <section className="rounded-2xl border border-soft bg-card shadow-tinted-sm">
              <div className="flex items-center justify-between border-b border-soft px-5 py-3">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-accent">
                    Admin
                  </div>
                  <h2 className="mt-0.5 flex items-center gap-2 text-base font-semibold tracking-tight">
                    <UsersIcon className="h-4 w-4 text-accent" />
                    Tous les utilisateurs
                    {users.length > 0 ? (
                      <span className="text-xs font-normal text-muted-foreground tabular-nums">
                        ({users.length})
                      </span>
                    ) : null}
                  </h2>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void loadUsers()}
                  disabled={usersLoading}
                >
                  {usersLoading ? "..." : "Actualiser"}
                </Button>
              </div>

              {usersLoading && users.length === 0 ? (
                <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Chargement...
                </div>
              ) : users.length === 0 ? (
                <div className="py-10 text-center text-sm text-muted-foreground">
                  Aucun utilisateur.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/30 text-[11px] uppercase tracking-wide text-muted-foreground">
                      <tr>
                        <th className="px-5 py-2.5 text-left font-medium">
                          Utilisateur
                        </th>
                        <th className="px-5 py-2.5 text-left font-medium">
                          Email
                        </th>
                        <th className="px-5 py-2.5 text-left font-medium">
                          Rôle
                        </th>
                        <th className="px-5 py-2.5 text-right font-medium">
                          Actions
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.map((u) => {
                        const isSelf = u.username === user?.user_id;
                        return (
                          <tr
                            key={u.username}
                            className="border-t border-soft transition-colors hover:bg-accent-soft/30"
                          >
                            <td className="px-5 py-3">
                              <div className="flex items-center gap-3">
                                <span
                                  className={cn(
                                    "flex h-9 w-9 items-center justify-center rounded-xl text-xs font-semibold text-white shadow-tinted-sm",
                                    u.role === "admin"
                                      ? "bg-gradient-to-br from-accent to-violet"
                                      : "bg-gradient-to-br from-muted-foreground/70 to-muted-foreground",
                                  )}
                                >
                                  {initialsOf(u.name || u.username)}
                                </span>
                                <div>
                                  <div className="font-semibold text-foreground tracking-tight">
                                    {u.name || u.username}
                                    {isSelf ? (
                                      <span className="ml-2 rounded-full border border-soft bg-muted/40 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                                        vous
                                      </span>
                                    ) : null}
                                  </div>
                                  <div className="text-xs text-muted-foreground">
                                    {u.username}
                                  </div>
                                </div>
                              </div>
                            </td>
                            <td className="px-5 py-3 text-muted-foreground">
                              {u.email || "—"}
                            </td>
                            <td className="px-5 py-3">
                              {u.role === "admin" ? (
                                <span className="inline-flex items-center gap-1 rounded-full border border-accent/25 bg-accent-soft px-2.5 py-0.5 text-[11px] font-medium text-accent">
                                  <Shield className="h-3 w-3" />
                                  Admin
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 rounded-full border border-soft bg-muted/40 px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                                  Utilisateur
                                </span>
                              )}
                            </td>
                            <td className="px-5 py-3 text-right">
                              <div className="flex justify-end gap-1">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() =>
                                    void handleResetPassword(u.username)
                                  }
                                  title="Réinitialiser le mot de passe"
                                >
                                  <KeyRound className="h-4 w-4" />
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => void handleToggleRole(u)}
                                  disabled={isSelf && u.role === "admin"}
                                  title={
                                    u.role === "admin"
                                      ? "Rétrograder en utilisateur"
                                      : "Promouvoir admin"
                                  }
                                >
                                  <Shield className="h-4 w-4" />
                                </Button>
                                <AlertDialog>
                                  <AlertDialogTrigger asChild>
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      disabled={isSelf}
                                      className="text-danger hover:bg-danger/10 hover:text-danger"
                                      title="Supprimer"
                                    >
                                      <Trash2 className="h-4 w-4" />
                                    </Button>
                                  </AlertDialogTrigger>
                                  <AlertDialogContent>
                                    <AlertDialogHeader>
                                      <AlertDialogTitle>
                                        Supprimer « {u.username} » ?
                                      </AlertDialogTitle>
                                      <AlertDialogDescription>
                                        Cette action est irréversible. Les
                                        données indexées du compte ne sont pas
                                        supprimées.
                                      </AlertDialogDescription>
                                    </AlertDialogHeader>
                                    <AlertDialogFooter>
                                      <AlertDialogCancel>
                                        Annuler
                                      </AlertDialogCancel>
                                      <AlertDialogAction
                                        onClick={() =>
                                          void handleDelete(u.username)
                                        }
                                        className="bg-danger text-danger-foreground hover:bg-danger/90"
                                      >
                                        Supprimer
                                      </AlertDialogAction>
                                    </AlertDialogFooter>
                                  </AlertDialogContent>
                                </AlertDialog>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}
