import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  return proxyJson("/admin/settings/legifrance");
}

export async function PUT(req: Request): Promise<Response> {
  const body = await req.text();
  return proxyJson("/admin/settings/legifrance", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body,
  });
}
