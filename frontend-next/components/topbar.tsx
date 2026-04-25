"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Topbar standardisée : breadcrumb à gauche, actions à droite.
 * Reprend le pattern du mockup ui-analysis Section 7 :
 *   [Index — daniel]   [bouton]  [bouton primary]  [avatar]
 *
 * Les pages passent leur breadcrumb + enfants (actions) en props. Height fixée
 * à h-14 pour cohérence avec tout le reste de l'app.
 */
export function Topbar({
  breadcrumb,
  children,
  className,
}: {
  breadcrumb: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex h-14 shrink-0 items-center gap-2 border-b border-border px-4 md:gap-3 md:px-6",
        className,
      )}
    >
      <div className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
        {breadcrumb}
      </div>
      <div className="flex shrink-0 items-center gap-2">{children}</div>
    </header>
  );
}
