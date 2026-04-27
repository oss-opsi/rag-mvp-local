import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

type Ctx = { params: Promise<{ id: string; req_id: string }> };

export async function PUT(req: Request, ctx: Ctx): Promise<Response> {
  const { id, req_id } = await ctx.params;
  const body = await req.text();
  return proxyJson(
    `/workspace/analyses/${encodeURIComponent(id)}/requirements/${encodeURIComponent(
      req_id,
    )}/correction`,
    {
      method: "PUT",
      body,
      headers: { "content-type": "application/json" },
    },
  );
}

export async function DELETE(_req: Request, ctx: Ctx): Promise<Response> {
  const { id, req_id } = await ctx.params;
  return proxyJson(
    `/workspace/analyses/${encodeURIComponent(id)}/requirements/${encodeURIComponent(
      req_id,
    )}/correction`,
    { method: "DELETE" },
  );
}
