"use client";

import * as React from "react";
import { Bell, Loader2, Check, X } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { api } from "@/lib/api-client";
import { cn, formatDateTime } from "@/lib/utils";
import type { AppNotification } from "@/lib/types";

const POLL_MS = 30_000;

/**
 * Bandeau cloche notifications (Page Admin Planificateur).
 *
 * Affiche le nombre de notifications non-lues (badge rouge) et, au clic, la
 * liste des 10 dernières notifications. Un clic sur une notification la marque
 * lue ; un bouton "Tout marquer comme lu" est aussi disponible.
 *
 * Le composant fait du polling léger (30s) pour rester réactif sans
 * consommer trop de ressources.
 */
export function NotificationsBell() {
  const [count, setCount] = React.useState(0);
  const [items, setItems] = React.useState<AppNotification[]>([]);
  const [open, setOpen] = React.useState(false);
  const [loading, setLoading] = React.useState(false);

  const reloadCount = React.useCallback(async () => {
    try {
      const data = await api.listUnreadNotifications();
      setCount(data.unread_count || 0);
    } catch {
      // pas bloquant — l'admin n'a peut-être pas accès, on garde 0
    }
  }, []);

  const reloadItems = React.useCallback(async () => {
    setLoading(true);
    try {
      const all = await api.listNotifications(10);
      setItems(all);
      const unread = all.filter((n) => !n.read_at).length;
      setCount(unread);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void reloadCount();
    const t = window.setInterval(() => void reloadCount(), POLL_MS);
    return () => window.clearInterval(t);
  }, [reloadCount]);

  React.useEffect(() => {
    if (open) void reloadItems();
  }, [open, reloadItems]);

  const handleMarkOne = async (id: number) => {
    try {
      await api.markNotificationRead(id);
      await reloadItems();
    } catch {
      // ignore
    }
  };

  const handleMarkAll = async () => {
    try {
      await api.markAllNotificationsRead();
      await reloadItems();
    } catch {
      // ignore
    }
  };

  const handleDelete = async (id: number) => {
    // Optimistic UI : on retire localement avant l'AR backend.
    setItems((prev) => prev.filter((n) => n.id !== id));
    try {
      await api.deleteNotification(id);
      await reloadItems();
    } catch {
      // En cas d'échec, on recharge pour resynchroniser.
      await reloadItems();
    }
  };

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={`Notifications (${count} non-lues)`}
          className={cn(
            "relative flex h-9 w-9 items-center justify-center rounded-md",
            "text-muted-foreground hover:bg-muted hover:text-foreground",
            "transition-colors",
          )}
        >
          <Bell className="h-4 w-4" />
          {count > 0 ? (
            <span
              className={cn(
                "absolute -right-1 -top-1 inline-flex h-4 min-w-[16px]",
                "items-center justify-center rounded-full bg-danger px-1",
                "text-[10px] font-semibold text-danger-foreground",
              )}
            >
              {count > 99 ? "99+" : count}
            </span>
          ) : null}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        sideOffset={6}
        className="w-[360px] p-0"
      >
        <div className="flex items-center justify-between border-b border-border px-3 py-2">
          <span className="text-sm font-semibold">Notifications</span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void handleMarkAll()}
            disabled={count === 0}
          >
            <Check className="mr-1 h-3.5 w-3.5" />
            Tout marquer lu
          </Button>
        </div>
        <ScrollArea className="max-h-80">
          {loading ? (
            <div className="flex items-center gap-2 px-3 py-6 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              Chargement…
            </div>
          ) : items.length === 0 ? (
            <div className="px-3 py-6 text-center text-xs text-muted-foreground">
              Aucune notification.
            </div>
          ) : (
            <ul className="divide-y divide-soft">
              {items.map((n) => (
                <li
                  key={n.id}
                  className={cn(
                    "group relative flex items-start gap-2 px-3 py-2.5 text-xs",
                    !n.read_at && "bg-accent-soft/40",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => void handleMarkOne(n.id)}
                    className="flex min-w-0 flex-1 items-start gap-2 text-left"
                  >
                    <span
                      className={cn(
                        "mt-1 inline-block h-2 w-2 shrink-0 rounded-full",
                        n.level === "error"
                          ? "bg-danger"
                          : n.level === "warn"
                            ? "bg-warning"
                            : "bg-success",
                      )}
                      aria-hidden
                    />
                    <div className="min-w-0 flex-1">
                      <div className="font-medium text-foreground">
                        {n.title}
                      </div>
                      {n.body ? (
                        <div className="mt-0.5 text-muted-foreground">
                          {n.body}
                        </div>
                      ) : null}
                      <div className="mt-1 text-[10px] text-muted-foreground">
                        {formatDateTime(n.created_at)}
                      </div>
                    </div>
                  </button>
                  <button
                    type="button"
                    aria-label="Supprimer la notification"
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleDelete(n.id);
                    }}
                    className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-all hover:bg-danger-soft hover:text-danger group-hover:opacity-100 focus-visible:opacity-100"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </ScrollArea>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
