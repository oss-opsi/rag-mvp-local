import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  return proxyJson("/admin/referentiels/queue-status", { method: "GET" });
}
