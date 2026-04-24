import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function DELETE(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const source = url.searchParams.get("source") ?? "";
  const qs = source ? `?source=${encodeURIComponent(source)}` : "";
  return proxyJson(`/collection/document${qs}`, { method: "DELETE" });
}
