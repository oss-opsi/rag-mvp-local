"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Logo monogramme Ω de Tell me — pastille gradient accent → teal.
 * Variantes : `square` (sidebar 36px), `lg` (login 56px), `inline` (titre).
 */
export function BrandMark({
  size = 36,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex items-center justify-center rounded-xl font-semibold text-white shadow-sm",
        className
      )}
      style={{
        width: size,
        height: size,
        fontSize: Math.round(size * 0.55),
        background:
          "linear-gradient(135deg, hsl(var(--accent)) 0%, hsl(var(--success)) 100%)",
      }}
    >
      Ω
    </span>
  );
}

export function BrandWordmark({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2", className)}>
      <BrandMark size={28} />
      <span className="text-base font-semibold tracking-tight text-foreground">
        Tell me
      </span>
    </span>
  );
}
