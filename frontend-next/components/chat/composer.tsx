"use client";

import * as React from "react";
import { Send, StopCircle, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  disabled,
  streaming,
  deepSearch = false,
  onDeepSearchChange,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  disabled?: boolean;
  streaming?: boolean;
  deepSearch?: boolean;
  onDeepSearchChange?: (v: boolean) => void;
}) {
  const textareaRef = React.useRef<HTMLTextAreaElement | null>(null);

  React.useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 220) + "px";
  }, [value]);

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!disabled && value.trim()) onSubmit();
    }
  };

  const toggleDeepSearch = () => {
    if (onDeepSearchChange) onDeepSearchChange(!deepSearch);
  };

  return (
    <div className="border-t border-soft bg-background px-4 py-4 md:px-6">
      {onDeepSearchChange ? (
        <div className="mx-auto mb-2 flex max-w-3xl flex-col gap-1">
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant={deepSearch ? "default" : "outline"}
              onClick={toggleDeepSearch}
              aria-pressed={deepSearch}
              className="h-7 gap-1.5 px-2.5 text-xs"
            >
              <Sparkles className="h-3.5 w-3.5" />
              Recherche approfondie
            </Button>
            <span className="text-[11px] text-muted-foreground">
              {deepSearch ? "Activée" : "Désactivée"}
            </span>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Améliore la pertinence des résultats mais peut prendre 1 à 3 minutes.
          </p>
        </div>
      ) : null}
      <div
        className={cn(
          "flex items-end gap-2 rounded-2xl border border-border bg-card p-2 shadow-tinted-sm transition-all",
          "focus-within:border-accent/50 focus-within:shadow-tinted-md",
        )}
      >
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Posez votre question…"
          rows={1}
          className="min-h-[28px] flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-muted-foreground"
        />
        {streaming && onStop ? (
          <Button
            type="button"
            size="icon"
            variant="outline"
            onClick={onStop}
            aria-label="Interrompre"
          >
            <StopCircle className="h-4 w-4" />
          </Button>
        ) : (
          <Button
            type="button"
            size="icon"
            onClick={onSubmit}
            disabled={disabled || !value.trim()}
            aria-label="Envoyer"
          >
            <Send className="h-4 w-4" />
          </Button>
        )}
      </div>
      <div className="mt-2 text-center text-[11px] text-muted-foreground">
        k=10 · HyDE activé · reranker {deepSearch ? "activé" : "désactivé"}
      </div>
    </div>
  );
}
