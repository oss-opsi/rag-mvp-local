import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function POST(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  return proxyJson(`/admin/jobs/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
  });
}
