import { fetchBackend, proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";
export const maxDuration = 900;

type Ctx = { params: Promise<{ id: string }> };

export async function GET(_req: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  return proxyJson(`/workspace/clients/${encodeURIComponent(id)}/cdcs`);
}

export async function POST(request: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  // On évite request.formData() (>10 MB côté Next.js) ET le streaming via
  // node:fetch (corrompt le multipart côté uvicorn). On bufferise le body
  // en mémoire route handler, OK jusqu'à 60 MB depuis que le middleware
  // tourne en runtime nodejs.
  const contentType = request.headers.get("content-type") || "";
  const headers: Record<string, string> = {};
  if (contentType) headers["content-type"] = contentType;

  const buffer = await request.arrayBuffer();
  const res = await fetchBackend(
    `/workspace/clients/${encodeURIComponent(id)}/cdcs`,
    {
      method: "POST",
      body: buffer,
      headers,
      timeoutMs: 900_000,
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
