const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";

export interface AuthToken {
  sub: string;
  email?: string;
  role?: string;
  iat?: number;
  exp?: number;
}

/**
 * Verify and decode a Supabase JWT token (server-side).
 * Used by middleware and API routes to validate session tokens.
 */
export async function verifyAuth(token: string): Promise<AuthToken | null> {
  try {
    if (!token || !supabaseUrl || !supabaseAnonKey) {
      return null;
    }

    const cleanToken = token.replace(/^Bearer\s+/i, "");

    const response = await fetch(`${supabaseUrl}/auth/v1/user`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${cleanToken}`,
        apikey: supabaseAnonKey,
      },
      cache: "no-store",
    });

    if (!response.ok) {
      return null;
    }

    const payload = (await response.json()) as Record<string, unknown>;
    const sub = typeof payload.id === "string" ? payload.id : null;
    if (!sub) {
      return null;
    }

    return {
      sub,
      email: typeof payload.email === "string" ? payload.email : undefined,
      role: typeof payload.role === "string" ? payload.role : undefined,
    };
  } catch {
    return null;
  }
}

/**
 * Extract JWT from Authorization header or cookies (for SSR).
 * Cookies are set by Supabase client-side auth automatically.
 */
export function getTokenFromRequest(request: Request): string | null {
  const authHeader = request.headers.get("authorization");
  if (authHeader) {
    return authHeader.replace(/^Bearer\s+/i, "");
  }

  const cookieString = request.headers.get("cookie") || "";
  const cookies: Record<string, string> = {};
  for (const rawCookie of cookieString.split(";")) {
    const trimmed = rawCookie.trim();
    if (!trimmed) continue;

    const separator = trimmed.indexOf("=");
    if (separator <= 0) continue;

    const key = trimmed.slice(0, separator);
    const value = trimmed.slice(separator + 1);
    cookies[key] = decodeURIComponent(value);
  }

  const sessionCookie = Object.entries(cookies).find(
    ([key]) => key.includes("auth-token") && key.startsWith("sb-")
  );
  
  if (sessionCookie) {
    try {
      const sessionData = JSON.parse(sessionCookie[1]);
      if (sessionData.access_token) {
        return sessionData.access_token;
      }
    } catch {
      // Invalid cookie format
    }
  }

  return null;
}
