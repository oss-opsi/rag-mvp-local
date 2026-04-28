import { fetchBackend } from "@/lib/api-server";

export const runtime = "nodejs";
export const maxDuration = 60;

type Ctx = { params: Promise<{ id: string }> };

export async function POST(request: Request, ctx: Ctx): Promise<Response> {
  const { id } = await ctx.params;
  const formData = await request.formData();
  const res = await fetchBackend(
    `/workspace/analyses/${encodeURIComponent(id)}/import-corrections`,
    {
      method: "POST",
      body: formData as unknown as BodyInit,
      timeoutMs: 60_000,
    },
  );
  const text = await res.text();
  return new Response(text, {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") || "application/json",
    },
  });
}
