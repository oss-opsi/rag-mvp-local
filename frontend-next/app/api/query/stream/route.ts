import { fetchBackend } from "@/lib/api-server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

/**
 * Proxy SSE pour /query/stream.
 *
 * Le pipeline RAG (reranker bge-m3 sur CPU) peut bloquer ~30–40 s avant
 * d'émettre le premier token. Sans activité réseau, certains navigateurs
 * (Safari notamment) coupent la requête avec "TypeError: Load failed".
 *
 * On envoie donc un heartbeat SSE (ligne de commentaire ":\n\n") toutes
 * les 5 secondes côté proxy pour garder la connexion vivante jusqu'à
 * l'arrivée des premiers tokens en provenance du backend.
 */
export async function POST(request: Request): Promise<Response> {
  const body = await request.text();
  const upstream = await fetchBackend("/query/stream", {
    method: "POST",
    body,
    headers: { "Content-Type": "application/json" },
    timeoutMs: 300_000,
  });

  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => "");
    return new Response(text || "Erreur streaming", {
      status: upstream.status || 500,
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  }

  const encoder = new TextEncoder();
  const reader = upstream.body.getReader();

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      let closed = false;
      // Heartbeat immédiat puis toutes les 5 s.
      // Une ligne SSE commençant par ":" est un commentaire, ignoré
      // par les clients EventSource et notre parser custom.
      controller.enqueue(encoder.encode(": keep-alive\n\n"));
      const heartbeat = setInterval(() => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(": keep-alive\n\n"));
        } catch {
          // controller already closed, nothing to do
        }
      }, 5000);

      const pump = async () => {
        try {
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            if (value) controller.enqueue(value);
          }
        } catch (err) {
          try {
            const msg =
              err instanceof Error ? err.message : "stream error";
            controller.enqueue(
              encoder.encode(`data: [ERROR]${msg}\n\ndata: [DONE]\n\n`)
            );
          } catch {
            // ignore
          }
        } finally {
          closed = true;
          clearInterval(heartbeat);
          try {
            controller.close();
          } catch {
            // already closed
          }
        }
      };

      void pump();
    },
    cancel(reason) {
      // Client a coupé : annule le upstream pour libérer le backend.
      try {
        void reader.cancel(reason);
      } catch {
        // ignore
      }
    },
  });

  return new Response(stream, {
    status: 200,
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}
