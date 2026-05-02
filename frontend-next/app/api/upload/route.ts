import { fetchBackend } from "@/lib/api-server";

export const runtime = "nodejs";
export const maxDuration = 900;

export async function POST(request: Request): Promise<Response> {
  // On évite request.formData() (>10 MB côté Next.js) ET le streaming via
  // node:fetch (corrompt le multipart côté uvicorn). On bufferise le body.
  const contentType = request.headers.get("content-type") || "";
  const headers: Record<string, string> = {};
  if (contentType) headers["content-type"] = contentType;

  const buffer = await request.arrayBuffer();
  const res = await fetchBackend("/upload", {
    method: "POST",
    body: buffer,
    headers,
    timeoutMs: 900_000,
  });

  const text = await res.text();
  return new Response(text, {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") || "application/json",
    },
  });
}
