import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  return proxyJson("/workspace/clients");
}

export async function POST(request: Request): Promise<Response> {
  const body = await request.text();
  return proxyJson("/workspace/clients", {
    method: "POST",
    body,
    headers: { "Content-Type": "application/json" },
  });
}
