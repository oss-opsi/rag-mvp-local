"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { SourceCard } from "@/components/chat/source-card";
import { MarkdownContent } from "@/components/chat/markdown-content";
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
        "flex w-full min-w-0",
        isUser ? "justify-end" : "justify-start"
      )}
    >
      <div
        className={cn(
          "flex min-w-0 max-w-[80%] flex-col gap-2 rounded-lg px-4 py-3 text-sm",
          isUser
            ? "bg-accent text-accent-foreground"
            : "bg-muted text-foreground"
        )}
      >
        {isUser ? (
          <div className="whitespace-pre-wrap break-words leading-relaxed [overflow-wrap:anywhere]">
            {message.content}
          </div>
        ) : (
          <div className="min-w-0">
            <MarkdownContent>{message.content || ""}</MarkdownContent>
            {streaming ? (
              <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-foreground align-baseline" />
            ) : null}
          </div>
        )}
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
