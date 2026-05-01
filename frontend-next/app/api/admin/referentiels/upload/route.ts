import { fetchBackend } from "@/lib/api-server";

export const runtime = "nodejs";
// Indexation synchrone (chunking + embeddings) — 5 min de marge.
export const maxDuration = 300;

export async function POST(request: Request): Promise<Response> {
  // Streaming proxy : on transmet le body brut au backend sans appeler
  // request.formData() (qui plante au-delà de 10 MB par défaut côté
  // Next.js). Le backend FastAPI parse le multipart lui-même.
  const contentType = request.headers.get("content-type") || "";
  const contentLength = request.headers.get("content-length") || "";
  const headers: Record<string, string> = {};
  if (contentType) headers["content-type"] = contentType;
  if (contentLength) headers["content-length"] = contentLength;

  const res = await fetchBackend("/admin/referentiels/upload", {
    method: "POST",
    body: request.body,
    headers,
    timeoutMs: 300_000,
  });
  const text = await res.text();
  return new Response(text, {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") || "application/json",
    },
  });
}
