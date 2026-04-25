"use client";

import * as React from "react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  statusDotClass,
  statusLabel,
  statusPillClass,
} from "@/components/requirement-row";
import { cn } from "@/lib/utils";
import type { Requirement } from "@/lib/types";

export function RequirementSheet({
  requirement,
  open,
  onOpenChange,
}: {
  requirement: Requirement | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex h-full w-full flex-col gap-0 p-0 sm:max-w-xl">
        {requirement ? (
          <>
            <SheetHeader className="border-b border-border p-6 pr-12">
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={cn(
                    "h-2.5 w-2.5 shrink-0 rounded-full",
                    statusDotClass(requirement.status)
                  )}
                  aria-hidden
                />
                <span className="font-mono text-xs text-muted-foreground">
                  {requirement.id}
                </span>
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-xs",
                    statusPillClass(requirement.status)
                  )}
                >
                  {statusLabel(requirement.status)}
                </span>
                {requirement.hyde_used ? (
                  <Badge variant="outline" className="text-[10px]">
                    HyDE
                  </Badge>
                ) : null}
                {requirement.repass_used ? (
                  <Badge variant="outline" className="text-[10px]">
                    re-pass
                  </Badge>
                ) : null}
              </div>
              <SheetTitle className="mt-1 text-xl">{requirement.title}</SheetTitle>
              <SheetDescription>{requirement.category}</SheetDescription>
            </SheetHeader>
            <ScrollArea className="min-h-0 flex-1">
              <div className="flex flex-col gap-5 p-6">
                {requirement.description ? (
                  <section>
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Description
                    </h3>
                    <p className="text-sm text-foreground">
                      {requirement.description}
                    </p>
                  </section>
                ) : null}

                {requirement.criteria && requirement.criteria.length > 0 ? (
                  <section>
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Critères
                    </h3>
                    <ul className="list-disc space-y-1 pl-5 text-sm">
                      {requirement.criteria.map((c, i) => (
                        <li key={i}>{c}</li>
                      ))}
                    </ul>
                  </section>
                ) : null}

                <Separator />

                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Verdict
                  </h3>
                  <p className="whitespace-pre-wrap text-sm text-foreground">
                    {requirement.verdict || "—"}
                  </p>
                </section>

                {requirement.evidence && requirement.evidence.length > 0 ? (
                  <section>
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Preuves
                    </h3>
                    <ul className="list-disc space-y-1 pl-5 text-sm">
                      {requirement.evidence.map((e, i) => (
                        <li key={i}>{e}</li>
                      ))}
                    </ul>
                  </section>
                ) : null}

                {requirement.sources && requirement.sources.length > 0 ? (
                  <section>
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Sources citées
                    </h3>
                    <div className="flex flex-col gap-3">
                      {requirement.sources.map((s, i) => (
                        <div
                          key={i}
                          className="rounded-md border border-border p-3"
                        >
                          <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            <span className="font-medium text-foreground">
                              {s.source}
                            </span>
                            {s.page !== undefined && s.page !== null ? (
                              <span>· page {String(s.page)}</span>
                            ) : null}
                            {typeof s.score === "number" ? (
                              <span>
                                · score{" "}
                                <span className="tabular-nums">
                                  {s.score.toFixed(3)}
                                </span>
                              </span>
                            ) : null}
                          </div>
                          <p className="whitespace-pre-wrap text-sm text-foreground">
                            {s.text}
                          </p>
                        </div>
                      ))}
                    </div>
                  </section>
                ) : null}
              </div>
            </ScrollArea>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
