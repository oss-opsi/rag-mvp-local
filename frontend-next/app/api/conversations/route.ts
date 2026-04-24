import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  return proxyJson("/conversations");
}

export async function POST(request: Request): Promise<Response> {
  const body = await request.text();
  return proxyJson("/conversations", {
    method: "POST",
    body,
    headers: { "Content-Type": "application/json" },
  });
}
