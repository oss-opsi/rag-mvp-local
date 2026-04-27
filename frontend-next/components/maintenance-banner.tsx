"use client";

import * as React from "react";
import { AlertTriangle } from "lucide-react";

const POLL_MS = 15_000;

/**
 * Bandeau jaune affiché sur la page chat quand le backend est en pause
 * maintenance (flag ``chat_paused`` posé par une planification avec
 * pause_chat_during_refresh=True).
 *
 * Polling 15s — invisible si le flag est à false.
 */
export function MaintenanceBanner() {
  const [paused, setPaused] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    const fetchStatus = async () => {
      try {
        const res = await fetch("/api/maintenance-status", {
          cache: "no-store",
        });
        if (!res.ok) return;
        const data = (await res.json()) as { chat_paused?: boolean };
        if (!cancelled) setPaused(!!data.chat_paused);
      } catch {
        // ignore — ne pas afficher de faux positif sur erreur réseau
      }
    };
    void fetchStatus();
    const t = window.setInterval(() => void fetchStatus(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, []);

  if (!paused) return null;

  return (
    <div
      role="status"
      className="flex items-center gap-2 border-b border-warning/25 bg-warning-soft px-4 py-2 text-xs font-medium text-warning"
    >
      <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
      <span>
        Maintenance en cours, chat indisponible le temps du rafraîchissement
        des sources publiques.
      </span>
    </div>
  );
}
