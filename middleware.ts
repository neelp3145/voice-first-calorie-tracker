import { NextRequest, NextResponse } from "next/server";
import { getTokenFromRequest, verifyAuth } from "./lib/auth-server";

const PROTECTED_ROUTES = ["/logger", "/journal", "/profile"];
const AUTH_ROUTES = ["/login", "/signup"];

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Check if accessing protected route
  const isProtected = PROTECTED_ROUTES.some(
    (route) => pathname === route || pathname.startsWith(`${route}/`)
  );

  // Check if accessing auth page
  const isAuthPage = AUTH_ROUTES.some((route) => pathname === route);

  const token = getTokenFromRequest(request);
  const authToken = token ? await verifyAuth(token) : null;
  const isAuthenticated = !!authToken;

  // Client auth currently stores session outside server-readable cookies.
  // Avoid redirect loops by redirecting only when a presented token is invalid.
  if (isProtected && token && !isAuthenticated) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Auth pages: redirect authenticated users to logger
  if (isAuthPage && isAuthenticated) {
    return NextResponse.redirect(new URL("/logger", request.url));
  }

  // Get the response
  const response = NextResponse.next();

  // Add Content Security Policy headers
  const cspDirectives = {
    'default-src': ["'self'"],
    'connect-src': [
      "'self'",
      'https://*.supabase.co',
      'https://voice-first-calorie-tracker-backend.onrender.com',
      'https://voice-first-calorie-tracker-frontend.onrender.com',
      'http://localhost:8000',
      'http://localhost:3000'
    ],
    'script-src': [
      "'self'",
      "'unsafe-inline'",
      "'unsafe-eval'"
    ],
    'style-src': [
      "'self'",
      "'unsafe-inline'"
    ],
    'img-src': [
      "'self'",
      'data:',
      'https://*.supabase.co'
    ],
    'font-src': [
      "'self'",
      'data:'
    ],
    'frame-src': [
      "'self'"
    ],
    'base-uri': ["'self'"],
    'form-action': ["'self'"],
    'frame-ancestors': ["'none'"],
    'upgrade-insecure-requests': []
  };

  // Convert CSP directives to string format
  const cspString = Object.entries(cspDirectives)
    .map(([key, values]) => {
      if (values.length === 0) return key;
      return `${key} ${values.join(' ')}`;
    })
    .join('; ');

  // Add CSP header
  response.headers.set('Content-Security-Policy', cspString);
  
  // Add other security headers
  response.headers.set('X-Content-Type-Options', 'nosniff');
  response.headers.set('X-Frame-Options', 'DENY');
  response.headers.set('X-XSS-Protection', '1; mode=block');
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');

  return response;
}

export const config = {
  matcher: [
    "/logger/:path*", 
    "/journal/:path*", 
    "/profile/:path*", 
    "/login", 
    "/signup",
    "/api/:path*",  // Also apply CSP to API routes
    "/"  // Apply to homepage too
  ],
};
