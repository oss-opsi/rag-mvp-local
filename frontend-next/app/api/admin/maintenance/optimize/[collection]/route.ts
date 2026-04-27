import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function POST(
  _req: Request,
  { params }: { params: Promise<{ collection: string }> },
): Promise<Response> {
  const { collection } = await params;
  return proxyJson(
    `/admin/maintenance/optimize/${encodeURIComponent(collection)}`,
    { method: "POST" },
  );
}
