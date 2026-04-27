"use client";

import * as React from "react";
import { NotificationsBell } from "@/components/notifications-bell";
import { cn } from "@/lib/utils";

/**
 * Topbar standardisée : breadcrumb à gauche, actions + cloche notifications
 * à droite. La cloche est rendue ici (plus en overlay fixed) pour ne plus
 * chevaucher les boutons des pages.
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
        "flex h-14 shrink-0 items-center gap-2 border-b border-soft px-4 md:gap-3 md:px-6",
        className,
      )}
    >
      <div className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
        {breadcrumb}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {children}
        <NotificationsBell />
      </div>
    </header>
  );
}
