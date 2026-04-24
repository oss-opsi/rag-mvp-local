"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { SourceCard } from "@/components/chat/source-card";
import type { ChatMessage } from "@/lib/types";

export function MessageBubble({
  message,
  streaming = false,
}: {
  message: ChatMessage;
  streaming?: boolean;
}) {
  const isUser = message.role === "user";
  return (
    <div
      className={cn(
        "flex w-full",
        isUser ? "justify-end" : "justify-start"
      )}
    >
      <div
        className={cn(
          "flex max-w-[80%] flex-col gap-2 rounded-lg px-4 py-3 text-sm",
          isUser
            ? "bg-accent text-accent-foreground"
            : "bg-muted text-foreground"
        )}
      >
        <div className="whitespace-pre-wrap leading-relaxed">
          {message.content}
          {streaming ? (
            <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-foreground align-baseline" />
          ) : null}
        </div>
        {!isUser && message.sources && message.sources.length > 0 ? (
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {message.sources.map((s, i) => (
              <SourceCard key={i} source={s} index={i} />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
