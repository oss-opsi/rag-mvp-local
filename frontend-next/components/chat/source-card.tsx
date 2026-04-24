"use client";

import * as React from "react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { QuerySource } from "@/lib/types";
import { cn } from "@/lib/utils";

export function SourceCard({
  source,
  index,
}: {
  source: QuerySource;
  index: number;
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "flex flex-col gap-1 rounded-md border border-border bg-background px-3 py-2 text-left text-xs transition-colors hover:bg-muted/40"
        )}
      >
        <div className="flex items-center gap-2">
          <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">
            #{index + 1}
          </span>
          <span className="truncate font-medium text-foreground">
            {source.source}
          </span>
        </div>
        <div className="flex items-center gap-2 text-muted-foreground">
          {source.page !== undefined && source.page !== null ? (
            <span>page {String(source.page)}</span>
          ) : null}
          {typeof source.score === "number" ? (
            <span className="tabular-nums">score {source.score.toFixed(3)}</span>
          ) : null}
        </div>
      </button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="right" className="flex w-full flex-col sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>{source.source}</SheetTitle>
            <SheetDescription>
              {source.page !== undefined && source.page !== null
                ? `Page ${String(source.page)}`
                : "Extrait"}
              {typeof source.score === "number"
                ? ` · score ${source.score.toFixed(3)}`
                : ""}
            </SheetDescription>
          </SheetHeader>
          <div className="mt-4 flex-1 overflow-auto whitespace-pre-wrap text-sm">
            {source.text}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
