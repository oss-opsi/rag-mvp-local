import { proxyJson } from "@/lib/api-server";

export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  return proxyJson("/admin/schedules");
}

export async function POST(req: Request): Promise<Response> {
  const body = await req.text();
  return proxyJson("/admin/schedules", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
  });
}
