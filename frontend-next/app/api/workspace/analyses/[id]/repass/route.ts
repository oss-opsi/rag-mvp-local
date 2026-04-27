import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";
export const maxDuration = 60;

type Ctx = { params: Promise<{ id: string }> };

export async function POST(request: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  const body = await request.text();
  return proxyJson(
    `/workspace/analyses/${encodeURIComponent(id)}/repass`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body || "{}",
      timeoutMs: 60_000,
    },
  );
}
