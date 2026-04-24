"use client";

import * as React from "react";

type ContextPanelContextValue = {
  node: React.ReactNode | null;
  setNode: (n: React.ReactNode | null) => void;
};

const ContextPanelContext = React.createContext<ContextPanelContextValue | null>(
  null
);

export function ContextPanelProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [node, setNode] = React.useState<React.ReactNode | null>(null);
  const value = React.useMemo(() => ({ node, setNode }), [node]);
  return (
    <ContextPanelContext.Provider value={value}>
      {children}
    </ContextPanelContext.Provider>
  );
}

export function ContextPanelSlot({ children }: { children?: React.ReactNode }) {
  const ctx = React.useContext(ContextPanelContext);
  return (
    <aside className="flex h-full w-[280px] shrink-0 flex-col border-r border-border bg-background">
      {ctx?.node ?? children}
    </aside>
  );
}

export function useContextPanel(): ContextPanelContextValue {
  const ctx = React.useContext(ContextPanelContext);
  if (!ctx)
    throw new Error(
      "useContextPanel doit être utilisé dans ContextPanelProvider"
    );
  return ctx;
}

/**
 * Hook helper : publie un noeud React dans le panneau contexte pendant la
 * durée de vie du composant.
 */
export function useProvideContextPanel(node: React.ReactNode): void {
  const ctx = useContextPanel();
  React.useEffect(() => {
    ctx.setNode(node);
    return () => ctx.setNode(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node]);
}
