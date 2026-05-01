import { fetchBackend } from "@/lib/api-server";

export const runtime = "nodejs";
// Endpoint backend désormais asynchrone : il met le job en file et
// répond 202 dès que le fichier est posé sur disque. Pas besoin d'une
// fenêtre longue, mais on garde un peu de marge pour l'upload de 50 Mo.
export const maxDuration = 120;

export async function POST(request: Request): Promise<Response> {
  // On évite request.formData() (plante >10 MB côté Next.js) ET le
  // streaming de request.body via node:fetch (corrompt le multipart :
  // observé empiriquement, "Expected boundary character 45 at index 2"
  // côté uvicorn). On matérialise le body en mémoire avant de le renvoyer
  // au backend. Limite UI 50 MB, accepté par Next.js dès que le middleware
  // tourne en runtime nodejs.
  const contentType = request.headers.get("content-type") || "";
  const headers: Record<string, string> = {};
  if (contentType) headers["content-type"] = contentType;

  const buffer = await request.arrayBuffer();
  const res = await fetchBackend("/admin/referentiels/upload", {
    method: "POST",
    body: buffer,
    headers,
    timeoutMs: 120_000,
  });
  const text = await res.text();
  return new Response(text, {
    status: res.status,
    headers: {
      "content-type": res.headers.get("content-type") || "application/json",
    },
  });
}
