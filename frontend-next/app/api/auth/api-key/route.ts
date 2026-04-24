import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  return proxyJson("/auth/api-key");
}

export async function PUT(request: Request): Promise<Response> {
  const body = await request.text();
  return proxyJson("/auth/api-key", {
    method: "PUT",
    body,
    headers: { "Content-Type": "application/json" },
  });
}

export async function DELETE(): Promise<Response> {
  return proxyJson("/auth/api-key", { method: "DELETE" });
}
