import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function POST(
  _req: Request,
  { params }: { params: Promise<{ source: string }> },
): Promise<Response> {
  const { source } = await params;
  return proxyJson(
    `/admin/maintenance/reembed/${encodeURIComponent(source)}`,
    { method: "POST" },
  );
}
