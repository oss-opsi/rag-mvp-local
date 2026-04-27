import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function POST(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  return proxyJson(`/notifications/${encodeURIComponent(id)}/read`, {
    method: "POST",
  });
}
