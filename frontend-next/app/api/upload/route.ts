import { fetchBackend } from "@/lib/api-server";

export const runtime = "nodejs";
export const maxDuration = 900;

export async function POST(request: Request): Promise<Response> {
  // Re-forward the multipart body to the backend without buffering the file in memory twice.
  const formData = await request.formData();
  const res = await fetchBackend("/upload", {
    method: "POST",
    body: formData as unknown as BodyInit,
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
