# Security Abuse Test Matrix

Date: 2026-04-11
Scope: FastAPI API endpoints, Next.js route guards, Supabase-authenticated flows.

## Test Cases

1. Unauthenticated search access
- Endpoint: GET /api/foods/search
- Input: No Authorization header
- Expected: 401 with "Missing bearer token."

2. Unauthenticated voice upload
- Endpoint: POST /api/voice
- Input: Multipart audio, no Authorization header
- Expected: 401 with "Missing bearer token."

3. Invalid/expired JWT
- Endpoint: GET /api/foods/search
- Input: Authorization: Bearer invalid-token
- Expected: 401 with "Invalid or expired session."

4. Oversized audio upload
- Endpoint: POST /api/voice
- Input: Audio file > 10MB
- Expected: 413 request entity too large

5. Unsupported audio MIME type
- Endpoint: POST /api/voice
- Input: text/plain multipart file
- Expected: 415 unsupported media type

6. Search query abuse
- Endpoint: GET /api/foods/search
- Input: query length > 200 chars
- Expected: 422 validation error

7. Rate-limit abuse by user
- Endpoint: POST /api/voice
- Input: > 20 calls/min for same user
- Expected: 429 too many requests

8. Rate-limit abuse by IP
- Endpoint: GET /api/foods/search
- Input: > 90 calls/min from same IP
- Expected: 429 too many requests

9. Protected route direct navigation
- Route: /logger, /journal, /profile
- Input: No Supabase session cookie
- Expected: Redirect to /login?next=<path>

10. Auth page access while logged in
- Route: /login, /signup
- Input: Valid Supabase session cookie
- Expected: Redirect to /logger

## RLS Validation Cases (after applying migration)

1. User A selects own rows
- Expected: success

2. User A selects User B rows
- Expected: zero rows returned

3. User A updates User B row
- Expected: denied by RLS

4. User A deletes User B row
- Expected: denied by RLS
