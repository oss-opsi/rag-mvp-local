import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function GET(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const qs = url.searchParams.toString();
  return proxyJson(qs ? `/notifications?${qs}` : "/notifications");
}
