import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ username: string }> }
): Promise<Response> {
  const { username } = await params;
  const body = await req.text();
  return proxyJson(`/admin/users/${encodeURIComponent(username)}/password`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body,
  });
}
