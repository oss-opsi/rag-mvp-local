import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  return proxyJson("/admin/users");
}

export async function POST(req: Request): Promise<Response> {
  const body = await req.text();
  return proxyJson("/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}
