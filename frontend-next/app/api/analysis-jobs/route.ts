import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function GET(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const qs = url.search; // includes leading '?' or ''
  return proxyJson(`/analysis-jobs${qs}`);
}
