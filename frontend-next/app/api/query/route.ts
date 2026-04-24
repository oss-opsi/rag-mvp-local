import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";
export const maxDuration = 300;

export async function POST(request: Request): Promise<Response> {
  const body = await request.text();
  return proxyJson("/query", {
    method: "POST",
    body,
    headers: { "Content-Type": "application/json" },
  });
}
