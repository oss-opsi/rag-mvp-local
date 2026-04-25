"use client";

import * as React from "react";
import { Menu, PanelLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetTitle,
} from "@/components/ui/sheet";
import { LeftRailContent } from "@/components/left-rail";
import { useContextPanel } from "@/components/context-panel";
import { BrandWordmark } from "@/components/brand-logo";

/**
 * Barre supérieure spécifique mobile (<md) : 2 boutons fixes pour ouvrir
 * le rail (hamburger) et le panneau de contexte. Sur desktop elle est
 * masquée — le rail et l'aside sont déjà visibles dans le flux.
 *
 * Posée dans AppShell, juste au-dessus des pages, h-12. L'app gagne 48px
 * de hauteur en mobile, ce qui reste largement acceptable pour un viewport
 * 844px.
 */
export function MobileNavBar() {
  const [navOpen, setNavOpen] = React.useState(false);
  const { hasContent, mobileOpen, setMobileOpen } = useContextPanel();

  return (
    <div className="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-border bg-background px-3 md:hidden">
      <Sheet open={navOpen} onOpenChange={setNavOpen}>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Ouvrir le menu"
          onClick={() => setNavOpen(true)}
          className="h-9 w-9"
        >
          <Menu className="h-5 w-5" />
        </Button>
        <SheetContent
          side="left"
          className="w-[96px] max-w-[96px] p-0 sm:max-w-[96px]"
        >
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <LeftRailContent onNavigate={() => setNavOpen(false)} />
        </SheetContent>
      </Sheet>

      <BrandWordmark />

      {hasContent ? (
        <Button
          variant="ghost"
          size="icon"
          aria-label="Ouvrir le panneau de contexte"
          onClick={() => setMobileOpen(!mobileOpen)}
          className="h-9 w-9"
        >
          <PanelLeft className="h-5 w-5" />
        </Button>
      ) : (
        <span className="h-9 w-9" aria-hidden />
      )}
    </div>
  );
}
