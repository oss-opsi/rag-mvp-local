"use client";

import * as React from "react";
import { LeftRail } from "@/components/left-rail";
import { ContextPanelProvider } from "@/components/context-panel";
import { AppShellProvider } from "@/components/app-shell-context";
import { MobileNavBar } from "@/components/mobile-nav-bar";
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
      </div>
      <Toaster />
    </AppShellProvider>
  );
}
