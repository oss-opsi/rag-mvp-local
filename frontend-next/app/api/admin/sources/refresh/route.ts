import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";
// Refresh télécharge potentiellement un ZIP + ré-embedde des centaines de chunks.
// On laisse ~30 min de marge.
export const maxDuration = 1800;

export async function POST(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const source = url.searchParams.get("source") ?? "";
  const purgeFirst = url.searchParams.get("purge_first") ?? "true";
  const qs = `source=${encodeURIComponent(source)}&purge_first=${encodeURIComponent(purgeFirst)}`;
  return proxyJson(`/admin/sources/refresh?${qs}`, { method: "POST" });
}
