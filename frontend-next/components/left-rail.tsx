"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  FileSearch,
  MessageSquare,
  FileText,
  Settings,
  LogOut,
} from "lucide-react";
import { cn, initialsOf } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAppShell } from "@/components/app-shell-context";
import { api } from "@/lib/api-client";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

const NAV: NavItem[] = [
  { href: "/analyse", label: "Analyse d'écarts", icon: FileSearch },
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/documents", label: "Documents indexés", icon: FileText },
];

/**
 * Rail latéral (72px) — masqué sur mobile (<md). Sur mobile il est ouvert via
 * le bouton hamburger de la barre mobile (cf. `MobileNavBar`), qui réutilise
 * <LeftRailContent /> pour afficher la nav dans un Sheet.
 */
export function LeftRail() {
  return (
    <aside className="hidden h-full w-[72px] shrink-0 flex-col items-center border-r border-border bg-background md:flex">
      <LeftRailContent />
    </aside>
  );
}

export function LeftRailContent({
  onNavigate,
}: {
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { user } = useAppShell();

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch {
      // ignore
    }
    onNavigate?.();
    router.push("/login");
    router.refresh();
  };

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex h-full w-full flex-col items-center">
        <div className="flex h-14 w-full items-center justify-center border-b border-border">
          <span className="text-sm font-semibold tracking-tight">Opsidium</span>
        </div>

        <nav className="flex flex-1 flex-col items-center gap-1 py-3">
          {NAV.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href || pathname.startsWith(item.href + "/");
            return (
              <Tooltip key={item.href}>
                <TooltipTrigger asChild>
                  <Link
                    href={item.href}
                    aria-label={item.label}
                    onClick={onNavigate}
                    className={cn(
                      "relative flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground transition-colors",
                      active
                        ? "bg-muted text-foreground"
                        : "hover:bg-muted/50 hover:text-foreground"
                    )}
                  >
                    {active ? (
                      <span className="absolute left-[-14px] top-1/2 h-6 w-[3px] -translate-y-1/2 rounded-r bg-accent" />
                    ) : null}
                    <Icon className="h-5 w-5" />
                  </Link>
                </TooltipTrigger>
                <TooltipContent side="right">{item.label}</TooltipContent>
              </Tooltip>
            );
          })}
        </nav>

        <div className="mb-3">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                aria-label="Menu utilisateur"
                className="flex h-10 w-10 items-center justify-center rounded-full bg-muted text-sm font-medium text-foreground hover:bg-muted/70"
              >
                {initialsOf(user?.name || "?")}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="right" align="end" sideOffset={8}>
              {user ? (
                <>
                  <div className="px-2 py-1.5 text-xs text-muted-foreground">
                    {user.name}
                  </div>
                  <DropdownMenuSeparator />
                </>
              ) : null}
              <DropdownMenuItem asChild>
                <Link
                  href="/settings"
                  onClick={onNavigate}
                  className="flex items-center gap-2"
                >
                  <Settings className="h-4 w-4" />
                  Paramètres
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={(e) => {
                  e.preventDefault();
                  void handleLogout();
                }}
                className="flex items-center gap-2 text-danger focus:text-danger"
              >
                <LogOut className="h-4 w-4" />
                Déconnexion
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </TooltipProvider>
  );
}
