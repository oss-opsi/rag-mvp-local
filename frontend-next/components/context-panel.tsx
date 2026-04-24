"use client";

import * as React from "react";
import { createPortal } from "react-dom";

type Ctx = { target: HTMLElement | null };
const ContextPanelCtx = React.createContext<Ctx>({ target: null });

/**
 * Provider posé dans AppShell. Fournit un <aside> de 280px à droite du rail,
 * et expose son élément DOM via contexte pour que les pages puissent y
 * téléporter leur contenu contextuel.
 */
export function ContextPanelProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const slotRef = React.useRef<HTMLElement | null>(null);
  const [target, setTarget] = React.useState<HTMLElement | null>(null);

  return (
    <ContextPanelCtx.Provider value={{ target }}>
      <div className="flex h-full w-full">
        <aside
          ref={(el) => {
            slotRef.current = el;
            // setState seulement si changement réel
            if (el !== target) setTarget(el);
          }}
          className="flex h-full w-[280px] shrink-0 flex-col border-r border-border bg-background"
        />
        <div className="flex h-full min-w-0 flex-1 flex-col">{children}</div>
      </div>
    </ContextPanelCtx.Provider>
  );
}

/**
 * Composant utilisé par les pages : enveloppe son enfant et le téléporte
 * dans le panneau contexte. Pas de boucle infinie : React rend simplement le
 * portail, les re-renders suivent la logique React normale.
 */
export function ContextPanel({ children }: { children: React.ReactNode }) {
  const { target } = React.useContext(ContextPanelCtx);
  if (!target) return null;
  return createPortal(children, target);
}
