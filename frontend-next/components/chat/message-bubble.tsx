"use client";

import * as React from "react";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { SourceCard } from "@/components/chat/source-card";
import { MarkdownContent } from "@/components/chat/markdown-content";
import { api } from "@/lib/api-client";
import { useToast } from "@/components/ui/use-toast";
import type { ChatMessage, MessageFeedback } from "@/lib/types";

function TypingDots() {
  return (
    <div
      className="flex items-center gap-1.5 py-1"
      role="status"
      aria-label="Rédaction de la réponse en cours"
    >
      <span className="inline-block h-2 w-2 rounded-full bg-muted-foreground/70 [animation:typing-bounce_1.2s_ease-in-out_infinite]" />
      <span
        className="inline-block h-2 w-2 rounded-full bg-muted-foreground/70 [animation:typing-bounce_1.2s_ease-in-out_infinite]"
        style={{ animationDelay: "0.15s" }}
      />
      <span
        className="inline-block h-2 w-2 rounded-full bg-muted-foreground/70 [animation:typing-bounce_1.2s_ease-in-out_infinite]"
        style={{ animationDelay: "0.3s" }}
      />
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
          "flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-background hover:text-foreground",
          isUp && "bg-background text-success",
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
          "flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-background hover:text-foreground",
          isDown && "bg-background text-danger",
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
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {message.sources.map((s, i) => (
              <SourceCard key={i} source={s} index={i} />
            ))}
          </div>
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
