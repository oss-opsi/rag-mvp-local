"use client";

import * as React from "react";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { SourcesPanel } from "@/components/chat/sources-panel";
import { MarkdownContent } from "@/components/chat/markdown-content";
import { api } from "@/lib/api-client";
import { useToast } from "@/components/ui/use-toast";
import type { ChatMessage, MessageFeedback } from "@/lib/types";

function TypingDots() {
  return (
    <div role="status" aria-label="Rédaction de la réponse en cours">
      <div className="flex items-center gap-1.5 py-1">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent [animation:typing-bounce_1.2s_ease-in-out_infinite]" />
        <span
          className="inline-block h-1.5 w-1.5 rounded-full bg-accent [animation:typing-bounce_1.2s_ease-in-out_infinite]"
          style={{ animationDelay: "0.15s" }}
        />
        <span
          className="inline-block h-1.5 w-1.5 rounded-full bg-accent [animation:typing-bounce_1.2s_ease-in-out_infinite]"
          style={{ animationDelay: "0.3s" }}
        />
        <span className="ml-2 text-[12px] text-muted-foreground">
          Tell me rédige sa réponse…
        </span>
      </div>
      <div className="mt-3 space-y-2" aria-hidden="true">
        <div className="skeleton-line h-3 w-[92%]" />
        <div className="skeleton-line h-3 w-[78%]" />
        <div className="skeleton-line h-3 w-[60%]" />
      </div>
    </div>
  );
}

function FeedbackButtons({
  messageId,
  initial,
}: {
  messageId: number;
  initial?: MessageFeedback | null;
}) {
  const [feedback, setFeedback] = React.useState<MessageFeedback | null>(
    initial ?? null,
  );
  const [busy, setBusy] = React.useState(false);
  const { toast } = useToast();

  const apply = async (rating: 1 | -1) => {
    if (busy) return;
    setBusy(true);
    const previous = feedback;
    try {
      // Toggle off si on reclique sur le même pouce.
      if (feedback?.rating === rating) {
        setFeedback(null);
        await api.clearMessageFeedback(messageId);
      } else {
        setFeedback({ rating, comment: previous?.comment ?? null });
        await api.setMessageFeedback(messageId, rating, previous?.comment ?? null);
      }
    } catch (err) {
      // rollback
      setFeedback(previous);
      const msg =
        err instanceof Error ? err.message : "Impossible d'enregistrer le feedback";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setBusy(false);
    }
  };

  const isUp = feedback?.rating === 1;
  const isDown = feedback?.rating === -1;

  return (
    <div className="mt-2 flex items-center gap-1 opacity-70 transition-opacity hover:opacity-100">
      <button
        type="button"
        onClick={() => void apply(1)}
        disabled={busy}
        aria-label="Réponse utile"
        title="Réponse utile"
        className={cn(
          "flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground transition-all hover:bg-success-soft hover:text-success",
          isUp && "border border-success/25 bg-success-soft text-success",
        )}
      >
        <ThumbsUp className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        onClick={() => void apply(-1)}
        disabled={busy}
        aria-label="Réponse à améliorer"
        title="Réponse à améliorer"
        className={cn(
          "flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground transition-all hover:bg-danger-soft hover:text-danger",
          isDown && "border border-danger/25 bg-danger-soft text-danger",
        )}
      >
        <ThumbsDown className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

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
          "flex min-w-0 max-w-[80%] flex-col gap-2 px-4 py-3 text-sm",
          isUser
            ? "rounded-2xl rounded-br-md bg-gradient-to-br from-accent to-accent-hover text-accent-foreground shadow-user-bubble"
            : "rounded-2xl rounded-bl-md border border-soft bg-gradient-to-br from-card to-accent-soft/40 text-foreground shadow-tinted-sm",
        )}
      >
        {isUser ? (
          <div className="whitespace-pre-wrap break-words leading-relaxed [overflow-wrap:anywhere]">
            {message.content}
          </div>
        ) : (
          <div className="min-w-0">
            {streaming && !message.content ? (
              <TypingDots />
            ) : (
              <>
                <MarkdownContent>{message.content || ""}</MarkdownContent>
                {streaming ? (
                  <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-foreground align-baseline" />
                ) : null}
              </>
            )}
          </div>
        )}
        {!isUser && message.sources && message.sources.length > 0 ? (
          <SourcesPanel sources={message.sources} />
        ) : null}
        {/* Boutons de feedback : visibles seulement sur les réponses
            assistant terminées (avec id retourné par le backend). */}
        {!isUser && !streaming && message.id && message.content ? (
          <FeedbackButtons messageId={message.id} initial={message.feedback} />
        ) : null}
      </div>
    </div>
  );
}
