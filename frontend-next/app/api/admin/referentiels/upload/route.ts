import { fetchBackend } from "@/lib/api-server";

export const runtime = "nodejs";
// Indexation synchrone (chunking + embeddings) — 5 min de marge.
export const maxDuration = 300;

export async function POST(request: Request): Promise<Response> {
  const formData = await request.formData();
  const res = await fetchBackend("/admin/referentiels/upload", {
    method: "POST",
    body: formData as unknown as BodyInit,
    timeoutMs: 300_000,
  });
  const text = await res.text();
  return new Response(text, {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") || "application/json",
    },
  });
}
