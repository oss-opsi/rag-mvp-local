"use client";

import * as React from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { QuerySource } from "@/lib/types";

type SourceScope = "private" | "kb";

function dedupeSources(sources: QuerySource[]): QuerySource[] {
  const seen = new Set<string>();
  const out: QuerySource[] = [];
  for (const s of sources) {
    const key = `${s.source ?? ""}::${s.url_canonique ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(s);
  }
  return out;
}

function SourceItem({ source }: { source: QuerySource }) {
  const url = source.url_canonique;
  const title = source.source;
  if (url) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="block truncate text-xs text-accent underline-offset-2 hover:underline"
        title={title}
      >
        {title}
      </a>
    );
  }
  return (
    <span className="block truncate text-xs text-muted-foreground" title={title}>
      {title}
    </span>
  );
}

function SourcesPill({
  label,
  count,
  scope,
  open,
  onToggle,
  items,
}: {
  label: string;
  count: number;
  scope: SourceScope;
  open: boolean;
  onToggle: () => void;
  items: QuerySource[];
}) {
  const pillClasses =
    scope === "private"
      ? "border-transparent bg-accent/15 text-accent hover:bg-accent/25"
      : "border-border bg-background text-foreground hover:bg-muted";
  return (
    <div className="flex flex-col">
      <button
        type="button"
        role="button"
        aria-expanded={open}
        onClick={onToggle}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          pillClasses,
        )}
      >
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 transition-transform",
            open && "rotate-90",
          )}
          aria-hidden="true"
        />
        <span>
          {label} ({count})
        </span>
      </button>
      {open ? (
        <ul className="mt-1.5 flex flex-col gap-1 pl-5">
          {items.map((s, i) => (
            <li key={`${s.source}-${i}`} className="min-w-0">
              <SourceItem source={s} />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function SourcesPanel({ sources }: { sources: QuerySource[] }) {
  const [openPrivate, setOpenPrivate] = React.useState(false);
  const [openKb, setOpenKb] = React.useState(false);

  const privateItems = React.useMemo(
    () => dedupeSources(sources.filter((s) => s.scope === "private")),
    [sources],
  );
  const kbItems = React.useMemo(
    () => dedupeSources(sources.filter((s) => s.scope === "kb")),
    [sources],
  );

  if (privateItems.length === 0 && kbItems.length === 0) {
    return null;
  }

  return (
    <div className="mt-2 flex flex-wrap items-start gap-2">
      {privateItems.length > 0 ? (
        <SourcesPill
          label="Documents privés"
          count={privateItems.length}
          scope="private"
          open={openPrivate}
          onToggle={() => setOpenPrivate((v) => !v)}
          items={privateItems}
        />
      ) : null}
      {kbItems.length > 0 ? (
        <SourcesPill
          label="Sources publiques"
          count={kbItems.length}
          scope="kb"
          open={openKb}
          onToggle={() => setOpenKb((v) => !v)}
          items={kbItems}
        />
      ) : null}
    </div>
  );
}
