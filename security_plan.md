## Plan: Free Security Baseline for Vocalorie

Implement a layered, zero-cost security foundation using Supabase Auth + RLS, backend token verification, strict input controls, and operational hardening. This approach secures user data end-to-end without paid services and aligns with strict privacy defaults.

**Steps**
1. Phase 1: Secrets and configuration lockdown
2. Rotate all leaked or previously committed keys (USDA, Groq, Tavily, Supabase) and remove hardcoded credential examples that encourage service-role usage in client-facing contexts.
3. Split backend-only vs client-safe environment variables, ensuring service-role key is never available to the browser and only used in trusted backend paths that require elevated privileges.
4. Add environment validation at startup (fail fast when required vars are missing or malformed), and add .env.example with placeholders only. *parallel with step 5*
5. Update README security section with least-privilege guidance and key-rotation workflow. *parallel with step 4*
6. Phase 2: Authentication and session enforcement
7. Implement Supabase Auth in Next.js login/signup flows (email+password and Google OAuth), replacing UI-only forms with real sign-in/sign-up handlers and session-aware redirects.
8. Add route protection in Next.js for journal/logger/profile so anonymous users are redirected to login.
9. Propagate Supabase JWT from frontend to FastAPI for protected endpoints and verify token signature/claims server-side on each authenticated request.
10. Add identity binding: backend operations must execute in user context and never trust client-submitted user_id fields. *depends on 9*
11. Phase 3: Data-layer authorization (strict privacy)
12. Align user-owned tables to the active schema (`users`, `daily_logs`, `personal_foods`) with owner columns tied to auth.uid().
13. Enable Row Level Security for all user-data tables and add deny-by-default policies; allow read/write only where row owner equals auth.uid().
14. Add explicit policies for insert/update/delete separation and prevent cross-user reads through joins/views.
15. Add migration scripts and policy verification checks (positive and negative cases). *depends on 12-14*
16. Phase 4: API and input hardening
17. Restrict CORS to explicit origins by environment, remove wildcard method/header posture where unnecessary, and disable credentials unless required.
18. Add request validation for all endpoint inputs (query length, allowed characters, file size/type limits for audio uploads).
19. Add rate limiting (IP + user-based quotas) to abuse-prone endpoints: /api/voice and /api/foods/search.
20. Add safe error handling: remove raw provider error prints from responses/logs, redact sensitive fields, and return normalized error payloads.
21. Phase 5: Security headers and transport
22. Add HTTP security headers in Next.js and backend responses (CSP, frame-ancestors, nosniff, referrer-policy, strict transport assumptions for production).
23. Ensure secure cookie settings for auth sessions (httpOnly, secure in production, sameSite) and avoid storing sensitive tokens in localStorage.
24. Enforce HTTPS-only deployment guidance and trusted reverse-proxy configuration.
25. Phase 6: Verification and operational readiness
26. Add automated security checks in CI: dependency audit, static linting, and secret scanning before merge.
27. Create a minimal abuse test matrix (unauthenticated access, cross-user data access, oversized upload, repeated voice calls).
28. Add incident playbook notes (key compromise, forced logout, token revocation, suspicious traffic response).
29. Add Next.js middleware-based route protection (server-side redirect before render) for journal/logger/profile.
30. Add concrete CSP and core security headers in Next.js plus baseline security headers in FastAPI responses.
31. Add initial SQL migration for user-owned tables + RLS policies and include local verification queries.
32. Add a repeatable security smoke-test script to validate auth, validation, and upload protections after every change.
33. Add owner-bound profile and journal persistence endpoints with anti-spoofing request validation and a dedicated identity-binding test script.
34. Wire logger confirm action to authenticated journal persistence so frontend logging follows identity-bound backend paths.

**Implementation Status (April 11, 2026 — RLS Applied + Verified)**
- Implemented: steps 2, 3, 4, 5, 7, 8, 9, 12, 13, 14, 15, 17, 18, 19, 20, 22, 23, 24, 26, 27, 28, 29, 30, 31, 32, 33, 34.
- Partially implemented: step 10 (identity-bound persistence is implemented for backend and frontend profile/journal/logger flows, with create/update/delete anti-spoof test coverage; remaining work is broader data model enforcement across all app flows).
- Not yet implemented: none (all required steps are implemented or partially implemented).

**User Action Required (Before Production)**
- No immediate user action required for RLS in this environment (migration applied and `npm run security:rls` passed).
- For new Supabase environments, follow [docs/apply_rls_migration.md](docs/apply_rls_migration.md) and rerun `ACCESS_TOKEN_A='...' ACCESS_TOKEN_B='...' npm run security:rls`.

**Testing Steps (Current Implementation)**
1. Install dependencies and run static checks:
	- `npm run lint`
	- `npm run validate:no-secrets` (check for accidentally staged secrets)
	- `python -m pip install -r requirements.txt`
2. Start backend and frontend:
	- Backend: `python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
	- Frontend: `npm run dev`
3. Validate auth route protection manually:
	- Open `/logger`, `/journal`, `/profile` while signed out and confirm redirect to `/login`.
	- Open `/login` while signed in and confirm redirect to `/logger`.
	- Sign in with a valid account and confirm you land on `/logger` without looping back to `/login`.
4. Validate API auth guards:
	- Call `GET /api/foods/search` without bearer token and confirm `401`.
	- Call `POST /api/voice` without bearer token and confirm `401`.
5. Validate input controls with a valid token:
	- `GET /api/foods/search` with >200-char query returns `422`.
	- `POST /api/voice` with unsupported MIME type returns `415`.
	- `POST /api/voice` with oversized file returns `413`.
6. Validate rate-limiting behavior:
	- Burst requests to `/api/foods/search` and `/api/voice`; confirm `429` appears after threshold.
7. Validate response headers:
	- Confirm CSP, Referrer-Policy, X-Content-Type-Options, X-Frame-Options, and Permissions-Policy on frontend responses.
	- Confirm API responses include `Cache-Control: no-store`.
8. Validate RLS after migration apply (requires manual Supabase action):
	- Follow [docs/apply_rls_migration.md](docs/apply_rls_migration.md) to apply `supabase/migrations/20260411_initial_security_schema.sql` in Supabase Dashboard SQL Editor.
	- Verify tables and lock icons appear in Table Editor.
	- Confirm RLS policies are listed in Authentication → Policies.
9. Run scripted backend security checks:
	- `npm run security:smoke`
	- `ACCESS_TOKEN=<valid_jwt> npm run security:identity` (includes create/update/delete and anti-spoof checks)
10. Validate RLS policy behavior with two users:
	- `ACCESS_TOKEN_A=<user_a_jwt> ACCESS_TOKEN_B=<user_b_jwt> npm run security:rls`
11. Validate logger-to-journal integration manually:
	- Capture or query a meal on `/logger` and click `Confirm & Log`.
	- Verify the entry appears on `/journal` for the same authenticated user.

**Relevant files**
- /voice-first-calorie-tracker/main.py — add auth dependency, token verification, input validation, rate limits, safer error handling, CORS tightening.
- /voice-first-calorie-tracker/supabase_client.py — separate admin client usage and add safer initialization/validation.
- /voice-first-calorie-tracker/app/login/page.tsx — wire real sign-in actions and OAuth start.
- /voice-first-calorie-tracker/app/signup/page.tsx — wire real sign-up actions and post-signup verification UX.
- /voice-first-calorie-tracker/app/logger/page.tsx — include authenticated API calls with bearer token and auth-aware states.
- /voice-first-calorie-tracker/app/journal/page.tsx — protect page and load only authenticated user data.
- /voice-first-calorie-tracker/app/profile/page.tsx — protect page and bind updates to current user identity.
- /voice-first-calorie-tracker/README.md — add security setup and rotation guidance.
- /voice-first-calorie-tracker/requirements.txt — add auth/jwt/rate-limit/validation dependencies.
- /voice-first-calorie-tracker/.env.example — add non-secret template and variable documentation.
- /voice-first-calorie-tracker/middleware.ts — server-side route protection using JWT verification for protected routes; handles session validation and auth-page redirects without loops.
- /voice-first-calorie-tracker/lib/auth-server.ts — server-side JWT verification utilities for middleware and API routes; extracts and validates tokens from headers or Supabase auth cookies.
- /voice-first-calorie-tracker/next.config.ts — global CSP and browser security headers.
- /voice-first-calorie-tracker/supabase/migrations/20260411_initial_security_schema.sql — RLS policies aligned to active schema (`users`, `daily_logs`, `personal_foods`) plus explicit lock-down for currently-unused `food_searches` and `global_foods`.
- /voice-first-calorie-tracker/.github/workflows/security-checks.yml — CI security checks (lint, dependency audits, secret scanning).
- /voice-first-calorie-tracker/docs/security_abuse_test_matrix.md — abuse and auth-negative test scenarios.
- /voice-first-calorie-tracker/docs/security_incident_playbook.md — incident response runbook.
- /voice-first-calorie-tracker/scripts/security_smoke_test.sh — repeatable smoke-test checks for auth, validation, and upload protections.
- /voice-first-calorie-tracker/scripts/security_identity_test.sh — verifies owner binding and rejects user_id spoofing in profile/journal APIs.
- /voice-first-calorie-tracker/scripts/security_rls_test.sh — validates cross-user RLS isolation for `users`, `daily_logs`, and `personal_foods` with two authenticated user tokens.
- /voice-first-calorie-tracker/scripts/validate_no_secrets.sh — detects staged secrets before commit to prevent accidental leaks.
- /voice-first-calorie-tracker/.env.example — template with clear separation of backend-only vs frontend-safe keys.
- /voice-first-calorie-tracker/docs/key_rotation_guide.md — step-by-step instructions for rotating each API key and managing secrets securely.
- /voice-first-calorie-tracker/docs/security_incident_credentials.md — incident response guide for exposed credentials.
- /voice-first-calorie-tracker/docs/cookie_session_policy.md — cookie settings, session lifecycle, CORS configuration, and troubleshooting for auth sessions (step 23).
- /voice-first-calorie-tracker/docs/deployment_hardening_guide.md — production deployment models (Vercel, Docker, VPS), security checklists, operational runbooks, and incident response procedures (step 24).
- /voice-first-calorie-tracker/docs/apply_rls_migration.md — user-action guide for applying the RLS migration in Supabase Dashboard with step-by-step instructions, troubleshooting, and verification (steps 12-15 completion).

**Verification**
1. Auth flow checks: sign up, email login, Google login, logout, session refresh, and protected route redirect behavior.
2. Backend auth checks: protected endpoints reject missing/invalid/expired JWT and accept valid JWT.
3. RLS checks: user A cannot read/update/delete user B rows; service-role path is inaccessible from frontend.
4. Upload abuse checks: oversized file, wrong mime type, malformed multipart body, and rapid repeated requests are blocked.
5. CORS checks: allowed origins pass; untrusted origins fail preflight and credentialed requests.
6. Secret hygiene checks: no real keys in repo history going forward; secret scanner and dependency audit pass in CI.

**Decisions**
- Include: Supabase Auth (email + Google), strict RLS, backend JWT verification, rate limiting, and input validation.
- Exclude for now: paid WAF/CDN bot products, enterprise SIEM, dedicated HSM/KMS services.
- Use strict privacy defaults from day one because meal/journal data is user-personal.

**Further Considerations**
1. Rate limiting backend choice: in-memory for local MVP vs Redis-backed for multi-instance deployment. Recommendation: start in-memory now, upgrade before horizontal scaling.
2. Voice file retention: immediate delete after transcription vs short retention for debugging. Recommendation: immediate delete by default, opt-in debug retention with admin-only toggle.
3. Account recovery UX: magic link backup vs password reset only. Recommendation: support password reset and add magic link later if support burden increases.
