"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

type Ctx = {
  target: HTMLElement | null;
  hasContent: boolean;
  setHasContent: (b: boolean) => void;
  mobileOpen: boolean;
  setMobileOpen: (b: boolean) => void;
};

const ContextPanelCtx = React.createContext<Ctx>({
  target: null,
  hasContent: false,
  setHasContent: () => {},
  mobileOpen: false,
  setMobileOpen: () => {},
});

/**
 * Provider posé dans AppShell.
 *
 * Astuce responsive : un seul <aside> sert à la fois de panneau desktop ET de
 * drawer mobile, en jouant sur les classes CSS :
 *
 *  - desktop (≥md) : position relative, dans le flux, largeur 280px.
 *  - mobile (<md)  : position fixed à gauche, h-screen, masqué hors écran via
 *                     translate-x-full ; ouvert via le bouton de MobileNavBar.
 *
 * Pas de re-mount du contenu lors du resize : le DOM target reste le même,
 * seul le wrapper change de visuel via Tailwind. Le portail des pages reste
 * stable.
 */
export function ContextPanelProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [target, setTarget] = React.useState<HTMLElement | null>(null);
  const [hasContent, setHasContent] = React.useState(false);
  const [mobileOpen, setMobileOpen] = React.useState(false);

  const value = React.useMemo<Ctx>(
    () => ({ target, hasContent, setHasContent, mobileOpen, setMobileOpen }),
    [target, hasContent, mobileOpen],
  );

  // Ferme automatiquement le drawer si on repasse en desktop ou si on navigue.
  React.useEffect(() => {
    if (!mobileOpen) return;
    const onResize = () => {
      if (window.matchMedia("(min-width: 768px)").matches) setMobileOpen(false);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [mobileOpen]);

  return (
    <ContextPanelCtx.Provider value={value}>
      <div className="relative flex h-full w-full">
        {/* Overlay mobile derrière le drawer (occupe la zone sous la barre mobile) */}
        <div
          aria-hidden
          onClick={() => setMobileOpen(false)}
          className={cn(
            "absolute inset-0 z-30 bg-black/40 transition-opacity md:hidden",
            mobileOpen
              ? "pointer-events-auto opacity-100"
              : "pointer-events-none opacity-0",
          )}
        />
        <aside
          ref={(el) => {
            if (el && el !== target) setTarget(el);
          }}
          className={cn(
            // Mobile : drawer à gauche, par-dessus le contenu (mais sous la barre mobile)
            "absolute inset-y-0 left-0 z-40 flex w-[280px] max-w-[85vw] shrink-0 flex-col overflow-y-auto border-r border-border bg-background transition-transform duration-200",
            mobileOpen ? "translate-x-0" : "-translate-x-full",
            // Desktop : panneau dans le flux, position relative
            "md:static md:z-auto md:translate-x-0 md:overflow-hidden md:transition-none",
          )}
        />
        <div className="flex h-full min-w-0 flex-1 flex-col">{children}</div>
      </div>
    </ContextPanelCtx.Provider>
  );
}

export function useContextPanel() {
  return React.useContext(ContextPanelCtx);
}

/**
 * Composant utilisé par les pages : enveloppe son enfant et le téléporte
 * dans le panneau contexte. Marque aussi la présence d'un contenu (pour que
 * la barre mobile affiche son bouton « Panneau »).
 */
export function ContextPanel({ children }: { children: React.ReactNode }) {
  const { target, setHasContent } = React.useContext(ContextPanelCtx);

  React.useEffect(() => {
    setHasContent(true);
    return () => setHasContent(false);
  }, [setHasContent]);

  if (!target) return null;
  return createPortal(children, target);
}
