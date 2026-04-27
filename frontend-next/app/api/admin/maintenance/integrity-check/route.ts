import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function POST(): Promise<Response> {
  return proxyJson("/admin/maintenance/integrity-check", { method: "POST" });
}
