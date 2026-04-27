"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BookMarked,
  CalendarClock,
  LayoutGrid,
  MessageCircle,
  FileSearch,
  LineChart,
  Users,
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
import { BrandMark } from "@/components/brand-logo";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

// Tell me v4.5 — page d'accueil = Chat. Indexation passe en admin.
const PRIMARY_NAV: NavItem[] = [
  { href: "/chat", label: "Chat", icon: MessageCircle },
  { href: "/analyse", label: "Analyse d'écarts", icon: FileSearch },
  { href: "/ragas", label: "RAGAS", icon: LineChart },
];

const SECONDARY_NAV: NavItem[] = [
  { href: "/users", label: "Utilisateurs", icon: Users },
  { href: "/settings", label: "Paramètres", icon: Settings },
];

// Admin-only — injecté conditionnellement dans la nav secondaire.
const ADMIN_NAV: NavItem[] = [
  { href: "/documents", label: "Indexation", icon: LayoutGrid },
  { href: "/referentiels", label: "Référentiels", icon: BookMarked },
  { href: "/scheduler", label: "Planificateur", icon: CalendarClock },
];

/**
 * Rail latéral (80px) — masqué sur mobile (<md). Sur mobile il est ouvert via
 * le bouton hamburger de la barre mobile (cf. `MobileNavBar`), qui réutilise
 * <LeftRailContent /> pour afficher la nav dans un Sheet.
 */
export function LeftRail() {
  return (
    <aside className="hidden h-full w-[80px] shrink-0 flex-col items-center border-r border-border bg-background md:flex">
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
  const isAdmin = user?.role === "admin";
  const secondaryNav = isAdmin ? [...ADMIN_NAV, ...SECONDARY_NAV] : SECONDARY_NAV;

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

  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(href + "/");

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex h-full w-full flex-col items-center">
        {/* Logo Ω */}
        <div className="flex h-16 w-full items-center justify-center border-b border-border">
          <Link
            href="/chat"
            onClick={onNavigate}
            aria-label="Tell me — Accueil"
            className="rounded-xl outline-none ring-offset-background transition-transform hover:scale-105 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
          >
            <BrandMark size={36} />
          </Link>
        </div>

        {/* Navigation principale */}
        <nav className="flex flex-1 flex-col items-center gap-1 py-3">
          {PRIMARY_NAV.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.href);
            return (
              <Tooltip key={item.href}>
                <TooltipTrigger asChild>
                  <Link
                    href={item.href}
                    aria-label={item.label}
                    onClick={onNavigate}
                    className={cn(
                      "relative flex h-11 w-11 items-center justify-center rounded-lg text-muted-foreground transition-colors",
                      active
                        ? "bg-accent/10 text-accent"
                        : "hover:bg-muted hover:text-foreground"
                    )}
                  >
                    {active ? (
                      <span className="absolute left-[-16px] top-1/2 h-6 w-[3px] -translate-y-1/2 rounded-r bg-accent" />
                    ) : null}
                    <Icon className="h-5 w-5" />
                  </Link>
                </TooltipTrigger>
                <TooltipContent side="right">{item.label}</TooltipContent>
              </Tooltip>
            );
          })}

          {/* Séparateur */}
          <div className="my-2 h-px w-8 bg-border" aria-hidden />

          {/* Navigation secondaire */}
          {secondaryNav.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.href);
            return (
              <Tooltip key={item.href}>
                <TooltipTrigger asChild>
                  <Link
                    href={item.href}
                    aria-label={item.label}
                    onClick={onNavigate}
                    className={cn(
                      "relative flex h-11 w-11 items-center justify-center rounded-lg text-muted-foreground transition-colors",
                      active
                        ? "bg-accent/10 text-accent"
                        : "hover:bg-muted hover:text-foreground"
                    )}
                  >
                    {active ? (
                      <span className="absolute left-[-16px] top-1/2 h-6 w-[3px] -translate-y-1/2 rounded-r bg-accent" />
                    ) : null}
                    <Icon className="h-5 w-5" />
                  </Link>
                </TooltipTrigger>
                <TooltipContent side="right">{item.label}</TooltipContent>
              </Tooltip>
            );
          })}
        </nav>

        {/* Avatar utilisateur */}
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
                    {user.role === "admin" ? (
                      <span className="ml-1 rounded bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-accent">
                        admin
                      </span>
                    ) : null}
                  </div>
                  <DropdownMenuSeparator />
                </>
              ) : null}
              <DropdownMenuItem asChild>
                <Link
                  href="/users"
                  onClick={onNavigate}
                  className="flex items-center gap-2"
                >
                  <Users className="h-4 w-4" />
                  Mon compte
                </Link>
              </DropdownMenuItem>
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
