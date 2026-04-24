import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

type Ctx = { params: Promise<{ id: string }> };

export async function GET(_req: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  return proxyJson(`/conversations/${encodeURIComponent(id)}`);
}

export async function DELETE(_req: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  return proxyJson(`/conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function PATCH(request: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  const body = await request.text();
  return proxyJson(`/conversations/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body,
    headers: { "Content-Type": "application/json" },
  });
}
