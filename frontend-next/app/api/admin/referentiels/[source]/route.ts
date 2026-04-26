import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ source: string }> }
): Promise<Response> {
  const { source } = await params;
  return proxyJson(
    `/admin/referentiels/${encodeURIComponent(source)}`,
    { method: "DELETE" }
  );
}
