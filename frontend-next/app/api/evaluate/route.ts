import { fetchBackend } from "@/lib/api-server";

export const runtime = "nodejs";
export const maxDuration = 600;

/**
 * Proxy the multipart RAGAS evaluation request to the backend.
 * Body: FormData with `file` (CSV: question,ground_truth) + `openai_api_key`.
 */
export async function POST(request: Request): Promise<Response> {
  const formData = await request.formData();
  const res = await fetchBackend("/evaluate", {
    method: "POST",
    body: formData as unknown as BodyInit,
    timeoutMs: 600_000,
  });

  const text = await res.text();
  return new Response(text, {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") || "application/json",
    },
  });
}
