# RLS Migration Application Guide

## Overview

This project now applies RLS directly to the active schema:
- `users`
- `daily_logs`
- `personal_foods`

And explicitly locks down currently-unused tables:
- `food_searches`
- `global_foods`

Canonical step-by-step instructions are in:
- `docs/apply_rls_migration.md`

## Quick Apply

1. Open Supabase Dashboard -> SQL Editor
2. Paste and run `supabase/migrations/20260411_initial_security_schema.sql`
3. Verify lock icons on `users`, `daily_logs`, `personal_foods`, `food_searches`, `global_foods`
4. Run:

```bash
ACCESS_TOKEN_A=<user_a_jwt> ACCESS_TOKEN_B=<user_b_jwt> \
SUPABASE_URL=<your_supabase_url> \
SUPABASE_ANON_KEY=<your_anon_key> \
npm run security:rls
```

## Expected Verification Output

- `[PASS] Resolved two distinct authenticated user ids`
- `[PASS] Both users can upsert their own users row`
- `[PASS] Cross-user users read is blocked`
- `[PASS] Cross-user daily_logs read is blocked`
- `[PASS] Cross-user daily_logs update is blocked`
- `[PASS] Cross-user daily_logs spoofed insert is blocked`
- `[PASS] Cross-user personal_foods read is blocked`
- `[PASS] Cleanup completed`

## Policy Summary

| Table | Policy scope |
|-------|--------------|
| `users` | owner-only (`id = auth.uid()`) |
| `daily_logs` | owner-only (`user_id = auth.uid()`) |
| `personal_foods` | owner-only (`user_id = auth.uid()`) |
| `food_searches` | RLS enabled, no client policies (locked down) |
| `global_foods` | RLS enabled, no client policies (locked down) |

## Troubleshooting

- `permission denied` on user-owned tables:
  - Token/user mismatch or expired JWT; refresh tokens and retry.
- `security:rls` 401/403:
  - Check `SUPABASE_URL`/`SUPABASE_ANON_KEY` values and token validity.
- Missing table errors:
  - Confirm migration SQL ran successfully in Supabase SQL Editor.
