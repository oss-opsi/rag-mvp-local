import { fetchBackend } from "@/lib/api-server";

export const runtime = "nodejs";
export const maxDuration = 60;

type Ctx = { params: Promise<{ id: string }> };

export async function GET(_req: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  const res = await fetchBackend(
    `/workspace/analyses/${encodeURIComponent(id)}/feedback/export`,
    { method: "GET", timeoutMs: 60_000 },
  );
  const headers = new Headers();
  const ct = res.headers.get("content-type");
  if (ct) headers.set("content-type", ct);
  const cd = res.headers.get("content-disposition");
  if (cd) headers.set("content-disposition", cd);
  return new Response(res.body, { status: res.status, headers });
}
