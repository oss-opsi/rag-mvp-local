"use client";

import * as React from "react";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function UploadDropzone({
  accept,
  disabled,
  onFile,
  title = "Déposez votre fichier ici",
  hint = "ou cliquez pour parcourir",
  className,
}: {
  accept?: string;
  disabled?: boolean;
  onFile: (file: File) => void;
  title?: string;
  hint?: string;
  className?: string;
}) {
  const [dragOver, setDragOver] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement | null>(null);

  const openPicker = () => {
    if (disabled) return;
    inputRef.current?.click();
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (disabled) return;
    const f = e.dataTransfer.files?.[0];
    if (f) onFile(f);
  };

  return (
    <div
      className={cn(
        "group relative flex flex-col items-center justify-center gap-4 overflow-hidden rounded-2xl border-2 border-dashed p-10 text-center transition-all",
        dragOver && !disabled
          ? "border-accent bg-accent-soft/60 shadow-tinted-md"
          : "border-soft bg-gradient-to-b from-card to-surface-2 hover:border-accent/30 hover:shadow-tinted-sm",
        disabled && "opacity-60",
        className,
      )}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
      role="button"
      tabIndex={0}
      onClick={openPicker}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openPicker();
        }
      }}
    >
      <span
        className={cn(
          "flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-accent to-violet text-white shadow-tinted-md transition-transform",
          dragOver && !disabled ? "scale-110" : "group-hover:scale-105",
        )}
        aria-hidden
      >
        <Upload className="h-6 w-6" />
      </span>
      <div>
        <div className="text-base font-semibold tracking-tight">{title}</div>
        <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        onClick={(e) => {
          e.stopPropagation();
          openPicker();
        }}
      >
        Choisir un fichier
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        disabled={disabled}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}
