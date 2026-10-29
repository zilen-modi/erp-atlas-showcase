import { NextResponse, type NextRequest } from "next/server";

// Pages need a signed-in person. This only checks the cookie is there; the API checks it's valid
// (and the layout sends anyone whose session has ended back to /login). The path is passed on so the
// layout can tell the sign-in page from the rest.
export function middleware(req: NextRequest) {
  const path = req.nextUrl.pathname;
  if (path !== "/login" && !req.cookies.get("atlas_session")) {
    const url = req.nextUrl.clone();
    const next = path + req.nextUrl.search;
    url.pathname = "/login";
    url.search = next !== "/" ? `?next=${encodeURIComponent(next)}` : "";
    return NextResponse.redirect(url);
  }
  const headers = new Headers(req.headers);
  headers.set("x-atlas-path", path + req.nextUrl.search);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: ["/((?!api/|_next/|icon\\.svg|apple-icon\\.png|favicon\\.ico).*)"],
};
