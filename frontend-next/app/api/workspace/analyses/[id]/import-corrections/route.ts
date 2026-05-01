import { fetchBackend } from "@/lib/api-server";

export const runtime = "nodejs";
export const maxDuration = 60;

type Ctx = { params: Promise<{ id: string }> };

export async function POST(request: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  // Streaming proxy : pas de request.formData() (limite 10 MB côté Next.js).
  // Pas de Content-Length : node:fetch passe en chunked sur un body stream,
  // forwarder les deux casse le parsing multipart côté uvicorn.
  const contentType = request.headers.get("content-type") || "";
  const headers: Record<string, string> = {};
  if (contentType) headers["content-type"] = contentType;

  const res = await fetchBackend(
    `/workspace/analyses/${encodeURIComponent(id)}/import-corrections`,
    {
      method: "POST",
      body: request.body,
      headers,
      timeoutMs: 60_000,
    },
  );
  const text = await res.text();
  return new Response(text, {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") || "application/json",
    },
  });
}
