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
  const formData = await request.formData();
  const res = await fetchBackend(
    `/workspace/clients/${encodeURIComponent(id)}/cdcs`,
    {
      method: "POST",
      body: formData as unknown as BodyInit,
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
