import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function PUT(req: Request): Promise<Response> {
  const body = await req.text();
  return proxyJson("/auth/password", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body,
  });
}
