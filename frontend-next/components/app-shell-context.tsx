"use client";

import * as React from "react";
import type { User } from "@/lib/types";

type AppShellContextValue = {
  user: User | null;
  setUser: (u: User | null) => void;
};

const AppShellContext = React.createContext<AppShellContextValue | null>(null);

export function AppShellProvider({
  children,
  initialUser = null,
}: {
  children: React.ReactNode;
  initialUser?: User | null;
}) {
  const [user, setUser] = React.useState<User | null>(initialUser);
  const value = React.useMemo(() => ({ user, setUser }), [user]);
  return (
    <AppShellContext.Provider value={value}>
      {children}
    </AppShellContext.Provider>
  );
}

export function useAppShell(): AppShellContextValue {
  const ctx = React.useContext(AppShellContext);
  if (!ctx) throw new Error("useAppShell doit être utilisé dans AppShellProvider");
  return ctx;
}
