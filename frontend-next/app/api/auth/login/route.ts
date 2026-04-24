import { NextResponse } from "next/server";
import { BACKEND_URL } from "@/lib/api-server";

export const runtime = "nodejs";

const COOKIE_MAX_AGE = 60 * 60 * 24 * 30; // 30 days

export async function POST(request: Request): Promise<Response> {
  let body: unknown = null;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { detail: "Corps de requête invalide" },
      { status: 400 }
    );
  }

  const res = await fetch(`${BACKEND_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
    cache: "no-store",
  });

  const text = await res.text();
  let data: { user_id?: number; name?: string; token?: string; detail?: string } = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = {};
  }

  if (!res.ok || !data.token) {
    return NextResponse.json(
      { detail: data.detail || "Identifiants invalides" },
      { status: res.status || 401 }
    );
  }

  const response = NextResponse.json({
    user_id: data.user_id,
    name: data.name,
  });
  response.cookies.set("session_token", data.token, {
    httpOnly: true,
    sameSite: "lax",
    secure: false,
    path: "/",
    maxAge: COOKIE_MAX_AGE,
  });
  return response;
}
