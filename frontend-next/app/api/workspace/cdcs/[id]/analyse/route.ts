import { fetchBackend } from "@/lib/api-server";

export const runtime = "nodejs";
// L'endpoint backend est désormais asynchrone : il met le job en file et
// répond immédiatement (202). On garde un timeout court pour la requête.
export const maxDuration = 60;

type Ctx = { params: Promise<{ id: string }> };

export async function POST(request: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  // Streaming proxy : pas de request.formData() (limite 10 MB côté Next.js).
  const contentType = request.headers.get("content-type") || "";
  const contentLength = request.headers.get("content-length") || "";
  const headers: Record<string, string> = {};
  if (contentType) headers["content-type"] = contentType;
  if (contentLength) headers["content-length"] = contentLength;

  const res = await fetchBackend(
    `/workspace/cdcs/${encodeURIComponent(id)}/analyse`,
    {
      method: "POST",
      body: request.body,
      headers,
      timeoutMs: 60_000,
    }
  );
  const text = await res.text();
  return new Response(text, {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") || "application/json",
    },
  });
}
