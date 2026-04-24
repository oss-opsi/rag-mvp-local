import { fetchBackend } from "@/lib/api-server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

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

  // Pass the ReadableStream directly without buffering.
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}
