"use client";

import * as React from "react";
import { Plus, Trash2, Pencil, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { MessageBubble } from "@/components/chat/message-bubble";
import { Composer } from "@/components/chat/composer";
import { ContextPanel } from "@/components/context-panel";
import { MaintenanceBanner } from "@/components/maintenance-banner";
import { useToast } from "@/components/ui/use-toast";
import { api } from "@/lib/api-client";
import { cn, formatDateTime } from "@/lib/utils";
import type {
  ChatMessage,
  Conversation,
  ConversationDetail,
  QuerySource,
} from "@/lib/types";

export default function ChatPage() {
  const { toast } = useToast();
  const [conversations, setConversations] = React.useState<Conversation[]>([]);
  const [selectedId, setSelectedId] = React.useState<number | null>(null);
  const [detail, setDetail] = React.useState<ConversationDetail | null>(null);
  const [input, setInput] = React.useState("");
  const [streaming, setStreaming] = React.useState(false);
  const [streamText, setStreamText] = React.useState("");
  const [streamSources, setStreamSources] = React.useState<QuerySource[]>([]);
  const [loadingList, setLoadingList] = React.useState(true);
  const [loadingDetail, setLoadingDetail] = React.useState(false);
  const [deepSearch, setDeepSearch] = React.useState<boolean>(false);
  const [deepSearchActive, setDeepSearchActive] = React.useState(false);

  // Hydrate deepSearch from localStorage once at mount.
  React.useEffect(() => {
    try {
      const v = window.localStorage.getItem("tellme.deepSearch");
      if (v === "true") setDeepSearch(true);
    } catch {
      // ignore (SSR / privacy mode)
    }
  }, []);

  const handleDeepSearchChange = React.useCallback((v: boolean) => {
    setDeepSearch(v);
    try {
      window.localStorage.setItem("tellme.deepSearch", v ? "true" : "false");
    } catch {
      // ignore
    }
  }, []);
  const abortRef = React.useRef<AbortController | null>(null);
  const scrollRef = React.useRef<HTMLDivElement | null>(null);

  const [renameOpen, setRenameOpen] = React.useState(false);
  const [renameValue, setRenameValue] = React.useState("");

  const reloadList = React.useCallback(async () => {
    setLoadingList(true);
    try {
      const list = await api.conversations();
      setConversations(list);
      if (list.length > 0 && selectedId === null) {
        setSelectedId(list[0]!.id);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur chargement conversations";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    } finally {
      setLoadingList(false);
    }
  }, [selectedId, toast]);

  const loadDetail = React.useCallback(
    async (id: number) => {
      setLoadingDetail(true);
      try {
        const d = await api.conversation(id);
        setDetail(d);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Erreur";
        toast({ title: "Erreur", description: msg, variant: "destructive" });
      } finally {
        setLoadingDetail(false);
      }
    },
    [toast]
  );

  React.useEffect(() => {
    void reloadList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    if (selectedId !== null) {
      void loadDetail(selectedId);
    } else {
      setDetail(null);
    }
  }, [selectedId, loadDetail]);

  React.useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [detail?.messages?.length, streamText]);

  const handleNewConversation = async () => {
    try {
      const c = await api.createConversation();
      await reloadList();
      setSelectedId(c.id);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur création";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await api.deleteConversation(id);
      if (selectedId === id) setSelectedId(null);
      await reloadList();
      toast({ title: "Conversation supprimée" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  const handleRename = async () => {
    if (selectedId === null || !renameValue.trim()) return;
    try {
      await api.renameConversation(selectedId, renameValue.trim());
      setRenameOpen(false);
      await reloadList();
      await loadDetail(selectedId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erreur renommage";
      toast({ title: "Erreur", description: msg, variant: "destructive" });
    }
  };

  const handleStop = () => {
    abortRef.current?.abort();
  };

  const handleSend = async () => {
    const question = input.trim();
    if (!question || streaming) return;

    // Ensure a conversation exists
    let convId = selectedId;
    let isNew = false;
    if (convId === null) {
      try {
        const c = await api.createConversation(question.slice(0, 50));
        convId = c.id;
        isNew = true;
        await reloadList();
        setSelectedId(c.id);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Erreur";
        toast({ title: "Erreur", description: msg, variant: "destructive" });
        return;
      }
    }

    // Optimistic user message
    const userMsg: ChatMessage = { role: "user", content: question };
    setDetail((d) =>
      d
        ? { ...d, messages: [...d.messages, userMsg] }
        : {
            id: convId!,
            title: question.slice(0, 50),
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            messages: [userMsg],
          }
    );
    setInput("");
    setStreaming(true);
    setStreamText("");
    setStreamSources([]);
    setDeepSearchActive(deepSearch);

    // Fire and forget: persist user message
    if (convId !== null) {
      api.postMessage(convId, "user", question).catch(() => {
        // ignore persistence error
      });
    }

    const controller = new AbortController();
    abortRef.current = controller;

    let accumulated = "";
    let sources: QuerySource[] = [];

    try {
      const res = await api.queryStream(question, 10, deepSearch, controller.signal, convId);
      if (!res.body) throw new Error("Pas de flux disponible");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let done = false;

      while (!done) {
        const { value, done: d } = await reader.read();
        done = d;
        if (value) buffer += decoder.decode(value, { stream: true });

        // SSE frames separated by "\n\n"
        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          if (!frame.startsWith("data:")) continue;
          // SSE: la spec autorise un seul espace optionnel après 'data:'.
          // On NE doit PAS faire trimStart() sur le payload entier, sinon
          // les tokens du LLM qui commencent par un espace (ex. ' world')
          // perdent leur espace et tous les mots se collent.
          let payload = frame.slice(5);
          if (payload.startsWith(" ")) payload = payload.slice(1);
          if (payload === "[DONE]") {
            done = true;
            break;
          }
          if (payload.startsWith("[SOURCES]")) {
            const json = payload.slice("[SOURCES]".length);
            try {
              const parsed = JSON.parse(json) as QuerySource[];
              sources = Array.isArray(parsed) ? parsed : [];
              setStreamSources(sources);
            } catch {
              // ignore malformed sources
            }
            continue;
          }
          accumulated += payload;
          setStreamText(accumulated);
        }
      }

      const assistantMsg: ChatMessage = {
        role: "assistant",
        content: accumulated,
        sources,
      };
      setDetail((d) =>
        d
          ? { ...d, messages: [...d.messages, assistantMsg] }
          : null
      );

      if (convId !== null) {
        const result = await api.postMessage(convId, "assistant", accumulated, sources);
        if (result?.message_id !== undefined) {
          const newId = result.message_id;
          setDetail((d) => {
            if (!d) return d;
            const msgs = [...d.messages];
            for (let i = msgs.length - 1; i >= 0; i--) {
              if (msgs[i].role === "assistant" && msgs[i].id === undefined) {
                msgs[i] = { ...msgs[i], id: newId };
                break;
              }
            }
            return { ...d, messages: msgs };
          });
        }
      }
      if (isNew) {
        await reloadList();
      }
    } catch (err) {
      if (controller.signal.aborted) {
        // user stopped — keep partial
        const partial: ChatMessage = {
          role: "assistant",
          content: accumulated || "(réponse interrompue)",
          sources,
        };
        setDetail((d) =>
          d ? { ...d, messages: [...d.messages, partial] } : null
        );
      } else {
        const msg = err instanceof Error ? err.message : "Erreur streaming";
        toast({ title: "Erreur", description: msg, variant: "destructive" });
      }
    } finally {
      setStreaming(false);
      setStreamText("");
      setStreamSources([]);
      setDeepSearchActive(false);
      abortRef.current = null;
    }
  };

  const messagesToRender: ChatMessage[] = detail?.messages ?? [];

  return (
    <div className="flex h-full flex-col">
      <MaintenanceBanner />
      <ContextPanel>
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">Conversations</h2>
            <Button
              size="icon"
              variant="ghost"
              aria-label="Nouvelle conversation"
              onClick={() => void handleNewConversation()}
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          <ScrollArea className="flex-1">
            {loadingList ? (
              <div className="p-4 text-xs text-muted-foreground">Chargement...</div>
            ) : conversations.length === 0 ? (
              <div className="p-4 text-center text-xs text-muted-foreground">
                Aucune conversation.
              </div>
            ) : (
              <ul className="py-1">
                {conversations.map((c) => {
                  const active = c.id === selectedId;
                  return (
                    <li key={c.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedId(c.id)}
                        className={cn(
                          "flex w-full flex-col gap-0.5 border-l-2 px-3 py-2 text-left text-sm transition-colors",
                          active
                            ? "border-l-accent bg-muted"
                            : "border-l-transparent hover:bg-muted/50"
                        )}
                      >
                        <span className="truncate font-medium">
                          {c.title || "Sans titre"}
                        </span>
                        <span className="text-[10px] text-muted-foreground">
                          {formatDateTime(c.updated_at)} · {c.message_count} msg
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </ScrollArea>
        </div>
      </ContextPanel>
      <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border px-4 md:px-6">
        <div className="min-w-0 flex-1 truncate text-sm font-semibold">
          Chat
          <span className="mx-1.5 text-muted-foreground">—</span>
          <span className="font-normal text-muted-foreground">
            {detail?.title ||
              (selectedId ? "Conversation" : "Nouvelle conversation")}
          </span>
        </div>
        {selectedId !== null ? (
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              aria-label="Renommer"
              onClick={() => {
                setRenameValue(detail?.title || "");
                setRenameOpen(true);
              }}
            >
              <Pencil className="h-4 w-4" />
            </Button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="ghost" size="icon" aria-label="Supprimer">
                  <Trash2 className="h-4 w-4" />
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Supprimer la conversation ?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Cette action est irréversible.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Annuler</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() =>
                      selectedId !== null && void handleDelete(selectedId)
                    }
                    className="bg-danger text-danger-foreground hover:bg-danger/90"
                  >
                    Supprimer
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        ) : null}
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto overflow-x-hidden">
        <div className="mx-auto flex min-w-0 max-w-3xl flex-col gap-4 px-4 py-4 md:p-6">
          {loadingDetail ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Chargement...
            </div>
          ) : messagesToRender.length === 0 && !streaming ? (
            <div className="py-12 text-center text-sm text-muted-foreground">
              Posez votre première question pour démarrer.
            </div>
          ) : (
            messagesToRender.map((m, i) => (
              <MessageBubble key={i} message={m} />
            ))
          )}

          {streaming ? (
            <>
              {deepSearchActive && !streamText ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Recherche approfondie en cours…
                </div>
              ) : null}
              <MessageBubble
                message={{
                  role: "assistant",
                  content: streamText,
                  sources: streamSources,
                }}
                streaming
              />
            </>
          ) : null}
        </div>
      </div>

      <Composer
        value={input}
        onChange={setInput}
        onSubmit={() => void handleSend()}
        onStop={handleStop}
        streaming={streaming}
        disabled={streaming}
        deepSearch={deepSearch}
        onDeepSearchChange={handleDeepSearchChange}
      />

      <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Renommer la conversation</DialogTitle>
          </DialogHeader>
          <Input
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void handleRename();
            }}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenameOpen(false)}>
              Annuler
            </Button>
            <Button onClick={() => void handleRename()}>Enregistrer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
