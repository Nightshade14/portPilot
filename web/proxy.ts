import { NextResponse, type NextRequest } from "next/server";
import { AUTH_COOKIE_NAME, isGateConfigured, verifyCookie } from "./lib/auth";

/**
 * Access gate: requires a valid pp_auth cookie for every page except /login.
 * In development with no PORTPILOT_UI_PASSCODE configured, the gate is open
 * (a banner on /login and the app shell says so).
 */
export default async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (pathname === "/login" || pathname.startsWith("/_next") || pathname.startsWith("/favicon")) {
    return NextResponse.next();
  }

  if (!isGateConfigured()) {
    // Dev-only open gate. Never true when PORTPILOT_UI_PASSCODE is set.
    return NextResponse.next();
  }

  const cookie = request.cookies.get(AUTH_COOKIE_NAME);
  if (cookie && (await verifyCookie(cookie.value))) {
    return NextResponse.next();
  }

  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("next", pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!_next|favicon).*)"],
};
