-- Security-focused RLS migration aligned to existing schema.
-- Target tables: users, daily_logs, personal_foods
-- Also locks down currently-unused tables: food_searches, global_foods

create extension if not exists pgcrypto;

-- Existing app tables
alter table if exists public.users enable row level security;
alter table if exists public.daily_logs enable row level security;
alter table if exists public.personal_foods enable row level security;

-- Unused tables in current codebase are explicitly locked down.
-- No client policies are created for these tables.
alter table if exists public.food_searches enable row level security;
alter table if exists public.global_foods enable row level security;

-- users policies (owner is id)
drop policy if exists "users_select_own" on public.users;
create policy "users_select_own"
on public.users
for select
using (auth.uid() = id);

drop policy if exists "users_insert_own" on public.users;
create policy "users_insert_own"
on public.users
for insert
with check (auth.uid() = id);

drop policy if exists "users_update_own" on public.users;
create policy "users_update_own"
on public.users
for update
using (auth.uid() = id)
with check (auth.uid() = id);

drop policy if exists "users_delete_own" on public.users;
create policy "users_delete_own"
on public.users
for delete
using (auth.uid() = id);

-- daily_logs policies (owner is user_id)
drop policy if exists "daily_logs_select_own" on public.daily_logs;
create policy "daily_logs_select_own"
on public.daily_logs
for select
using (auth.uid() = user_id);

drop policy if exists "daily_logs_insert_own" on public.daily_logs;
create policy "daily_logs_insert_own"
on public.daily_logs
for insert
with check (auth.uid() = user_id);

drop policy if exists "daily_logs_update_own" on public.daily_logs;
create policy "daily_logs_update_own"
on public.daily_logs
for update
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "daily_logs_delete_own" on public.daily_logs;
create policy "daily_logs_delete_own"
on public.daily_logs
for delete
using (auth.uid() = user_id);

-- personal_foods policies (owner is user_id)
drop policy if exists "personal_foods_select_own" on public.personal_foods;
create policy "personal_foods_select_own"
on public.personal_foods
for select
using (auth.uid() = user_id);

drop policy if exists "personal_foods_insert_own" on public.personal_foods;
create policy "personal_foods_insert_own"
on public.personal_foods
for insert
with check (auth.uid() = user_id);

drop policy if exists "personal_foods_update_own" on public.personal_foods;
create policy "personal_foods_update_own"
on public.personal_foods
for update
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "personal_foods_delete_own" on public.personal_foods;
create policy "personal_foods_delete_own"
on public.personal_foods
for delete
using (auth.uid() = user_id);

-- Keep updated_at fresh for user profiles.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists users_set_updated_at on public.users;
create trigger users_set_updated_at
before update on public.users
for each row execute function public.set_updated_at();

-- Verification snippets (run as authenticated users A/B in Supabase SQL editor):
-- select * from public.users where id = auth.uid();
-- select * from public.daily_logs where user_id <> auth.uid(); -- should return 0 rows
-- select * from public.personal_foods where user_id <> auth.uid(); -- should return 0 rows
