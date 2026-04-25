import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ username: string }> }
): Promise<Response> {
  const { username } = await params;
  return proxyJson(`/admin/users/${encodeURIComponent(username)}`, {
    method: "DELETE",
  });
}
