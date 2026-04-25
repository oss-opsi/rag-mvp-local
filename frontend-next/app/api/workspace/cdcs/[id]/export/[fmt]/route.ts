import { fetchBackend } from "@/lib/api-server";

export const runtime = "nodejs";

type Ctx = { params: Promise<{ id: string; fmt: string }> };

export async function GET(_req: Request, ctx: Ctx): Promise<Response> {
  const { id, fmt } = await ctx.params;
  const res = await fetchBackend(
    `/workspace/cdcs/${encodeURIComponent(id)}/export/${encodeURIComponent(fmt)}`,
  );

  // On error, surface the JSON body so the client can show a toast.
  if (!res.ok) {
    const body = await res.text();
    const ct = res.headers.get("content-type") || "application/json";
    return new Response(body, {
      status: res.status,
      headers: { "content-type": ct },
    });
  }

  // Forward the binary/text payload + filename.
  const contentType = res.headers.get("content-type") || "application/octet-stream";
  const disposition =
    res.headers.get("content-disposition") || "attachment";
  const buf = await res.arrayBuffer();
  return new Response(buf, {
    status: 200,
    headers: {
      "content-type": contentType,
      "content-disposition": disposition,
    },
  });
}
