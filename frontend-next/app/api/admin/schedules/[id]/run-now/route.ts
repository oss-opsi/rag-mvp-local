import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function POST(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  return proxyJson(`/admin/schedules/${encodeURIComponent(id)}/run-now`, {
    method: "POST",
  });
}
