import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function DELETE(): Promise<Response> {
  return proxyJson("/collection", { method: "DELETE" });
}
