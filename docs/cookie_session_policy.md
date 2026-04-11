# Cookie and Session Security Policy

This document outlines how cookies and sessions are managed securely in Vocalorie.

## Overview

Vocalorie uses **Supabase Auth** for user session management. Sessions are stored using JWTs (JSON Web Tokens) with the following characteristics:

| Property | Value | Rationale |
|----------|-------|-----------|
| Storage | Secure, HttpOnly cookies (Supabase default) | Prevents JavaScript access; immune to XSS theft |
| Scope | SameSite=Lax (Supabase default) | Protects from CSRF attacks while allowing navigation |
| Encryption | JWT signed with Supabase key | Token tampering is cryptographically detectable |
| Expiry | 1 hour (access token); 7 days (refresh token) | Balance between usability and security |
| Domain | Restricted to current origin | Prevents cross-domain token leakage |

## Session Lifecycle

### 1. Session Creation (Sign-In)

When a user signs in via email/password or Google OAuth:

1. User submits credentials to Supabase Auth
2. Supabase validates and returns an access token + refresh token
3. Supabase Auth client stores tokens in secure, HttpOnly cookies
4. Frontend receives session metadata but **not** the token itself
5. Browser automatically sends cookies with subsequent requests

**Security Properties:**
- Tokens never stored in localStorage (immune to XSS)
- HttpOnly flag prevents JavaScript access
- Secure flag enforces HTTPS in production

### 2. Session Validation

On each protected route access:

1. Middleware extracts the session token from cookies/headers
2. Token signature is verified using Supabase's public key (`NEXT_PUBLIC_SUPABASE_ANON_KEY`)
3. Token claims (`sub`, `exp`, `role`) are validated
4. If valid, request proceeds; if invalid, user is redirected to login

**Security Properties:**
- Cryptographic verification prevents token forgery
- Expiry check prevents use of revoked tokens
- Role-based access control enforced server-side

### 3. Session Refresh

Access tokens expire after 1 hour:

1. Supabase Auth client detects expiry and requests a refresh token exchange
2. Refresh token is sent to Supabase (over HTTPS)
3. New access token is issued and stored in cookies
4. User experiences seamless continuation

**Security Properties:**
- Short-lived access tokens limit exposure window
- Refresh tokens are long-lived but require server validation
- Refresh token rotation can be enabled in Supabase

### 4. Session Termination (Sign-Out)

When a user signs out:

1. Sign-out call is made to Supabase Auth
2. Session is invalidated on the server
3. Cookies are cleared in the browser
4. User is redirected to login page

**Security Properties:**
- Server-side invalidation ensures immediate logout
- Cleared cookies prevent accidental reuse
- Refresh token is blacklisted

## Cookie Configuration

### Secure Defaults (Supabase)

Supabase Auth sets the following cookie attributes:

```
Set-Cookie: sb-<project-id>-auth-token=<jwt>; Path=/; HttpOnly; Secure; SameSite=Lax
```

**Breakdown:**
- **HttpOnly**: JavaScript cannot access the token (prevents XSS attacks)
- **Secure**: Cookie only sent over HTTPS (prevents MITM in production)
- **SameSite=Lax**: Cookie sent on same-site requests and safe cross-site navigation (prevents CSRF)
- **Path=/**: Cookie available to entire application

### Custom Configuration (If Needed)

If you need to override Supabase defaults, use the Supabase client options:

```typescript
// lib/supabase.ts
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  {
    auth: {
      persistSession: true,  // Use cookies for persistence
      autoRefreshToken: true, // Auto-refresh on expiry
      storage: window.localStorage, // (Not recommended; Supabase prefers cookies)
    },
  }
);
```

## Third-Party Cookies & CORS

### Allowed Origins

Only these origins can make authenticated API requests:

```
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://yourdomain.com
```

**CORS Behavior:**
- Preflight requests (OPTIONS) are validated against allowed origins
- Credentials (cookies) are only sent if origin matches
- Wildcard origins (`*`) are NOT used (prevents credential leakage)

### Production CORS Configuration

Before deploying to production:

1. Update `ALLOWED_ORIGINS` to your production domain:
   ```env
   ALLOWED_ORIGINS=https://yourdomain.com
   ```

2. Update Supabase project settings:
   - Go to Authentication → URL Configuration
   - Add your production domain under "Site URL"
   - Add OAuth redirect URIs

3. Verify no wildcard in `ALLOWED_ORIGINS` env var

## Session Storage Alternatives

| Approach | Use Case | Trade-offs |
|----------|----------|------------|
| Supabase Cookies (Current) | General use | Secure by default; requires HTTPS in prod |
| Server-side sessions + refresh | High-security apps | More complex; better offline revocation |
| JWT in Authorization header | API-only clients | No automatic inclusion; manual header needed |
| OAuth2 Authorization Code Flow | Enterprise/SAML | Complex; forces server backend |

**Recommendation:** Keep the current Supabase cookie strategy. It balances security and convenience for web applications.

## Deployment Checklist

Before deploying to production:

- [ ] HTTPS is enforced (TLS termination at reverse proxy)
- [ ] `ALLOWED_ORIGINS` contains only production domain
- [ ] Supabase Site URL is set to your production domain
- [ ] Secure cookie flag is enabled (automatic with HTTPS)
- [ ] SameSite=Lax is used (Supabase default)
- [ ] HttpOnly flag is enabled (Supabase default)
- [ ] Session timeout is configured (1 hour for access token)
- [ ] Refresh token rotation is monitored
- [ ] Logout endpoints work correctly (clear cookies server-side)
- [ ] CORS preflight requests pass validation

## Troubleshooting

### Cookies Not Persisting

**Symptom:** User appears logged out after page refresh.

**Causes:**
1. HTTPS not enforced (Secure flag prevents HTTP transmission)
2. Cookie domain mismatch (subdomain isolation)
3. `persistSession: false` in Supabase client options

**Solution:**
```typescript
// Ensure persistence is enabled
const supabase = createClient(url, key, {
  auth: { persistSession: true },
});
```

### CORS Errors on Authentication

**Symptom:** `Access to XMLHttpRequest blocked by CORS policy`.

**Cause:** Origin not in `ALLOWED_ORIGINS` or Supabase Site URL mismatch.

**Solution:**
```bash
# Update .env
ALLOWED_ORIGINS=https://yourdomain.com

# Update Supabase URL Configuration
# Go to Authentication → URL Configuration → Site URL → https://yourdomain.com
```

### Token Expiry Loops

**Symptom:** User is logged out after 1 hour despite refresh tokens.

**Cause:** Refresh token rotation or network failure during refresh attempt.

**Solution:**
1. Verify network connectivity
2. Check Supabase session logs for token errors
3. Manual re-login may be required

## References

- Supabase Auth: https://supabase.com/docs/guides/auth
- OWASP Session Management: https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
- HTTP Cookies: https://developer.mozilla.org/en-US/docs/Web/HTTP/Cookies
- HttpOnly & Secure Flags: https://owasp.org/www-community/attacks/csrf

