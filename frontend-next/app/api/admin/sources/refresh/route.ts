import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function POST(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const source = url.searchParams.get("source") ?? "";
  return proxyJson(`/admin/sources/refresh?source=${encodeURIComponent(source)}`, {
    method: "POST",
  });
}
