# Security Implementation Guide

## Purpose

This guide explains what security controls were added, why they matter, how to validate them, and what to do when you deploy to a new environment.

## Current Status

- Security baseline implementation is complete.
- RLS migration has been applied and verified in the current Supabase environment.
- `npm run security:rls` has passed with two authenticated users.

## What Was Implemented

### 1) Authentication and session enforcement

- Supabase Auth integrated into app flows.
- Protected route handling for `/logger`, `/journal`, and `/profile`.
- Auth-page redirect behavior for signed-in users (`/login`, `/signup`).
- Backend bearer-token verification for protected API routes.

Why it matters:
- Unauthenticated users are blocked from protected data and flows.
- Session state is enforced at both frontend and backend boundaries.

### 2) Identity-bound data access

- Profile and journal API operations are bound to the authenticated user identity.
- Client-supplied identity spoofing is rejected.
- Cross-user access checks are covered by dedicated security scripts.

Why it matters:
- A user cannot write or read another user's records through API payload manipulation.

### 3) Row Level Security (RLS)

- RLS enabled for user-owned tables:
  - `users`
  - `daily_logs`
  - `personal_foods`
- Unused tables explicitly locked down with RLS enabled and no client policies:
  - `food_searches`
  - `global_foods`

Why it matters:
- Database access is deny-by-default for non-owned rows.
- Cross-user reads/updates/inserts are blocked in the data layer.

### 4) API hardening

- Input validation for search/query and upload constraints.
- Audio MIME type and max upload-size controls.
- In-memory rate limiting by user and IP for abuse-prone endpoints.
- Safer error handling and response consistency.

Why it matters:
- Reduces abuse, malformed request risk, and accidental data exposure.

### 5) Browser and transport security

- Frontend security headers and CSP applied via Next.js.
- Backend security headers added for API responses.
- Cache-control hardening for API responses.

Why it matters:
- Reduces browser-side attack surface and protects sensitive response handling.

### 6) Operational security

- Secret scanning and no-secrets validation script.
- Security smoke tests and identity-bound tests.
- RLS verification script for two-user isolation checks.
- Deployment and incident documentation added.

Why it matters:
- Security becomes repeatable and testable, not one-off.

## Verification Commands

Run from project root:

```bash
npm run lint
npm run validate:no-secrets
npm run security:smoke
ACCESS_TOKEN="<valid_jwt>" npm run security:identity
ACCESS_TOKEN_A="<user_a_jwt>" ACCESS_TOKEN_B="<user_b_jwt>" \
SUPABASE_URL="<your_url>" SUPABASE_ANON_KEY="<your_key>" \
npm run security:rls
```

Expected outcome:
- All commands pass without failures.

## Core Security Docs Map

- RLS apply and verification guide: `docs/apply_rls_migration.md`
- Deployment hardening guide: `docs/deployment_hardening_guide.md`
- Cookie/session policy: `docs/cookie_session_policy.md`
- Key rotation guide: `docs/key_rotation_guide.md`
- Incident playbook: `docs/security_incident_playbook.md`
- Abuse test matrix: `docs/security_abuse_test_matrix.md`

## What To Do In New Environments

When creating a new Supabase project/environment:

1. Apply `supabase/migrations/20260411_initial_security_schema.sql`.
2. Follow `docs/apply_rls_migration.md`.
3. Run `npm run security:rls` with two real user tokens.
4. Confirm app profile/journal flows still work end-to-end.

## Notes

- Runtime code currently does not query `food_searches` or `global_foods`.
- Those tables are intentionally locked down unless a future feature explicitly needs them.
