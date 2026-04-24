import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

type Ctx = { params: Promise<{ id: string }> };

export async function POST(request: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  const body = await request.text();
  return proxyJson(`/conversations/${encodeURIComponent(id)}/messages`, {
    method: "POST",
    body,
    headers: { "Content-Type": "application/json" },
  });
}
