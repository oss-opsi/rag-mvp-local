import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

type Ctx = { params: Promise<{ id: string }> };

export async function GET(_req: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  return proxyJson(`/ingestion-jobs/${encodeURIComponent(id)}`);
}
