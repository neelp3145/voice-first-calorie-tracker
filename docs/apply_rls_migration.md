# Applying RLS Migration to Supabase (Existing Schema)

This guide applies RLS using your current schema:
- `users`
- `daily_logs`
- `personal_foods`

It also locks down currently-unused tables:
- `food_searches`
- `global_foods`

## What I verified in code

Current runtime code does **not** query `global_foods` or `food_searches`.
Current runtime code **does** query user-owned data via `users` and `daily_logs` (with compatibility paths).

## Step 1: Open Supabase SQL Editor

1. Go to https://app.supabase.com
2. Select your project
3. Open **SQL Editor**
4. Click **New Query**

## Step 2: Apply Migration SQL

1. Open this file in your repo:
   `supabase/migrations/20260411_initial_security_schema.sql`
2. Copy all SQL
3. Paste into Supabase SQL Editor
4. Click **Run**

Expected result:
- `Success. No rows returned`

## Step 3: Verify Tables + RLS State

In Supabase **Table Editor**, verify these tables exist and have lock icons:
- `users`
- `daily_logs`
- `personal_foods`
- `food_searches`
- `global_foods`

Policy expectations:
- `users`: 4 owner-only policies (`id = auth.uid()`)
- `daily_logs`: 4 owner-only policies (`user_id = auth.uid()`)
- `personal_foods`: 4 owner-only policies (`user_id = auth.uid()`)
- `food_searches`: RLS enabled, no client policies (locked down)
- `global_foods`: RLS enabled, no client policies (locked down)

## Step 4: Run Automated RLS Validation

Use two authenticated user JWTs:

```bash
cd "/home/divya_ganesh/projects/Software engineering/NEW FOLDER/voice-first-calorie-tracker"
ACCESS_TOKEN_A="<user_a_jwt>" ACCESS_TOKEN_B="<user_b_jwt>" \
SUPABASE_URL="<your_url>" SUPABASE_ANON_KEY="<your_anon_key>" \
npm run security:rls
```

Expected passes include:
- Distinct user identities resolved
- Own `users` row upsert allowed for each user
- Cross-user `users` read blocked
- Cross-user `daily_logs` read/update blocked
- Cross-user `daily_logs` spoofed insert blocked
- Cross-user `personal_foods` read blocked

## Step 5: Manual Spot Checks (optional)

Run as authenticated user:

```sql
-- own profile row
select * from public.users where id = auth.uid();

-- should be empty due to RLS
select * from public.daily_logs where user_id <> auth.uid();
select * from public.personal_foods where user_id <> auth.uid();
```

## Troubleshooting

### Could not find table public.profiles/public.journal_entries

That is expected with Option 1. The migration no longer depends on those tables.

### Permission denied on users/daily_logs/personal_foods

RLS is active and your token may not match row ownership.
- Verify JWT belongs to the same user id as row `id`/`user_id`.
- Verify you are not using an expired token.

### security:rls fails with 401/403

- Check `SUPABASE_URL` and `SUPABASE_ANON_KEY`
- Ensure both tokens are valid and from different users
- Re-run after refreshing tokens

## Verification Checklist

- [ ] RLS enabled on `users`, `daily_logs`, `personal_foods`
- [ ] Owner-only policies exist on all 3 user-owned tables
- [ ] `food_searches` and `global_foods` are RLS-enabled and locked down
- [ ] `npm run security:rls` passes
- [ ] App profile + journal flows still work for each user
- [ ] Cross-user data access is blocked

## Notes on Unused Tables

Because the app currently does not query `food_searches` and `global_foods`, this migration keeps them inaccessible to client tokens by default. If you later need one as shared read-only data, add an explicit `SELECT` policy intentionally.
