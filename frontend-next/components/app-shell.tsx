"use client";

import * as React from "react";
import { LeftRail } from "@/components/left-rail";
import {
  ContextPanelProvider,
  ContextPanelSlot,
} from "@/components/context-panel";
import { AppShellProvider } from "@/components/app-shell-context";
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
      <ContextPanelProvider>
        <div className="flex h-dvh w-full overflow-hidden bg-background text-foreground">
          <LeftRail />
          <ContextPanelSlot />
          <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
            {children}
          </main>
        </div>
        <Toaster />
      </ContextPanelProvider>
    </AppShellProvider>
  );
}
