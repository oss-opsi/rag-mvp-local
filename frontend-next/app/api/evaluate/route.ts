import { fetchBackend } from "@/lib/api-server";

export const runtime = "nodejs";
export const maxDuration = 600;

/**
 * Proxy the multipart RAGAS evaluation request to the backend.
 * Body: FormData with `file` (CSV: question,ground_truth) + `openai_api_key`.
 */
export async function POST(request: Request): Promise<Response> {
  // Streaming proxy : pas de request.formData() (limite 10 MB côté Next.js).
  // Pas de Content-Length : node:fetch passe en chunked sur un body stream,
  // forwarder les deux casse le parsing multipart côté uvicorn.
  const contentType = request.headers.get("content-type") || "";
  const headers: Record<string, string> = {};
  if (contentType) headers["content-type"] = contentType;

  const res = await fetchBackend("/evaluate", {
    method: "POST",
    body: request.body,
    headers,
    timeoutMs: 600_000,
  });

  const text = await res.text();
  return new Response(text, {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") || "application/json",
    },
  });
}
