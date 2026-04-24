import { cookies } from "next/headers";

export const BACKEND_URL =
  process.env.BACKEND_URL || "http://backend:8000";

export async function getToken(): Promise<string | null> {
  const store = await cookies();
  const c = store.get("session_token");
  return c?.value ?? null;
}

export type ProxyOptions = {
  method?: string;
  body?: BodyInit | null;
  headers?: Record<string, string>;
  timeoutMs?: number;
};

/**
 * Forward a request to the FastAPI backend with Bearer auth from cookie.
 * Returns the raw Response so the caller can stream / inspect headers.
 */
export async function fetchBackend(
  path: string,
  options: ProxyOptions = {}
): Promise<Response> {
  const token = await getToken();
  const headers: Record<string, string> = { ...(options.headers || {}) };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const controller = new AbortController();
  const timeoutId = options.timeoutMs
    ? setTimeout(() => controller.abort(), options.timeoutMs)
    : null;

  try {
    const init: RequestInit & { duplex?: "half" } = {
      method: options.method || "GET",
      headers,
      body: options.body ?? undefined,
      signal: controller.signal,
      cache: "no-store",
    };
    if (options.body && typeof (options.body as ReadableStream).getReader === "function") {
      init.duplex = "half";
    }
    const url = `${BACKEND_URL}${path}`;
    const res = await fetch(url, init);
    return res;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}

/**
 * Standard JSON proxy — parses JSON response and passes status through.
 */
export async function proxyJson(
  path: string,
  options: ProxyOptions = {}
): Promise<Response> {
  const res = await fetchBackend(path, options);
  const contentType = res.headers.get("content-type") || "";
  const body = await res.text();
  const respHeaders = new Headers();
  if (contentType) respHeaders.set("content-type", contentType);
  return new Response(body, { status: res.status, headers: respHeaders });
}
