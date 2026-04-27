"use client";

import * as React from "react";
import { LeftRail } from "@/components/left-rail";
import { ContextPanelProvider } from "@/components/context-panel";
import { AppShellProvider } from "@/components/app-shell-context";
import { MobileNavBar } from "@/components/mobile-nav-bar";
import { NotificationsBell } from "@/components/notifications-bell";
import { Toaster } from "@/components/ui/toaster";
import type { User } from "@/lib/types";

export function AppShell({
  user,
  children,
}: {
  user: User | null;
  children: React.ReactNode;
}) {
  return (
    <AppShellProvider initialUser={user}>
      <div className="flex h-dvh w-full overflow-hidden bg-background text-foreground">
        <LeftRail />
        <ContextPanelProvider>
          <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
            <MobileNavBar />
            {children}
          </main>
        </ContextPanelProvider>
        {/* Bandeau cloche notifications — Page Admin Planificateur */}
        <div className="pointer-events-none fixed right-3 top-3 z-50 hidden md:block">
          <div className="pointer-events-auto">
            <NotificationsBell />
          </div>
        </div>
      </div>
      <Toaster />
    </AppShellProvider>
  );
}
