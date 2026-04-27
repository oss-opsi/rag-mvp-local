import { NextRequest, NextResponse } from "next/server";

const PUBLIC_PATHS = ["/login", "/mockup"];
const PUBLIC_API = ["/api/auth/login"];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  // Let through public paths
  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"))) {
    return NextResponse.next();
  }
  if (PUBLIC_API.some((p) => pathname === p)) {
    return NextResponse.next();
  }

  const token = req.cookies.get("session_token")?.value;

  // For API routes (other than /api/auth/login), return 401 if missing
  if (pathname.startsWith("/api/")) {
    if (!token) {
      return NextResponse.json({ detail: "Non authentifié" }, { status: 401 });
    }
    return NextResponse.next();
  }

  if (!token) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|public/).*)",
  ],
};
