import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

type Ctx = { params: Promise<{ id: string }> };

export async function DELETE(_req: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  return proxyJson(`/workspace/clients/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}
