#!/usr/bin/env bash
set -euo pipefail

SUPABASE_URL="${SUPABASE_URL:-${NEXT_PUBLIC_SUPABASE_URL:-}}"
SUPABASE_ANON_KEY="${SUPABASE_ANON_KEY:-${NEXT_PUBLIC_SUPABASE_ANON_KEY:-}}"
ACCESS_TOKEN_A="${ACCESS_TOKEN_A:-}"
ACCESS_TOKEN_B="${ACCESS_TOKEN_B:-}"

if [[ -z "$SUPABASE_URL" ]]; then
  echo "SUPABASE_URL (or NEXT_PUBLIC_SUPABASE_URL) is required."
  exit 1
fi

if [[ -z "$SUPABASE_ANON_KEY" ]]; then
  echo "SUPABASE_ANON_KEY (or NEXT_PUBLIC_SUPABASE_ANON_KEY) is required."
  exit 1
fi

if [[ -z "$ACCESS_TOKEN_A" || -z "$ACCESS_TOKEN_B" ]]; then
  echo "ACCESS_TOKEN_A and ACCESS_TOKEN_B are required."
  exit 1
fi

pass() {
  echo "[PASS] $1"
}

fail() {
  echo "[FAIL] $1"
  exit 1
}

status_and_body() {
  local output_file="$1"
  shift
  curl -s -o "$output_file" -w '%{http_code}' "$@"
}

auth_user_field() {
  local token="$1"
  local field="$2"
  local body_file
  body_file=$(mktemp)
  local status
  status=$(status_and_body "$body_file" \
    -H "apikey: ${SUPABASE_ANON_KEY}" \
    -H "Authorization: Bearer ${token}" \
    "${SUPABASE_URL}/auth/v1/user")

  if [[ "$status" != "200" ]]; then
    echo "Auth user lookup failed (status=${status}):"
    cat "$body_file"
    rm -f "$body_file"
    exit 1
  fi

  local value
  value=$(BODY_FILE="$body_file" FIELD="$field" python3 - <<'PY'
import json, os
with open(os.environ["BODY_FILE"], "r", encoding="utf-8") as f:
    body = json.load(f)
print(body.get(os.environ["FIELD"], ""))
PY
)
  rm -f "$body_file"
  echo "$value"
}

create_daily_log_as_a() {
  local user_id_a="$1"
  local body_file
  body_file=$(mktemp)

  local status
  status=$(status_and_body "$body_file" \
    -X POST "${SUPABASE_URL}/rest/v1/daily_logs" \
    -H "apikey: ${SUPABASE_ANON_KEY}" \
    -H "Authorization: Bearer ${ACCESS_TOKEN_A}" \
    -H "Content-Type: application/json" \
    -H "Prefer: return=representation" \
    -d "[{\"user_id\":\"${user_id_a}\",\"food_name\":\"RLS Test Meal\",\"calories\":111,\"protein\":10,\"carbs\":8,\"fat\":4}]")

  if [[ "$status" != "201" && "$status" != "200" ]]; then
    echo "daily_logs create failed (status=${status}). Did you apply supabase/migrations/20260411_initial_security_schema.sql?"
    cat "$body_file"
    rm -f "$body_file"
    exit 1
  fi

  local entry_id
  entry_id=$(BODY_FILE="$body_file" python3 - <<'PY'
import json, os
with open(os.environ["BODY_FILE"], "r", encoding="utf-8") as f:
    body = json.load(f)
print((body[0] if body else {}).get("id", ""))
PY
)
  rm -f "$body_file"

  if [[ -z "$entry_id" ]]; then
    echo "Could not parse daily_logs entry id"
    exit 1
  fi

  echo "$entry_id"
}

create_personal_food_as_a() {
  local user_id_a="$1"
  local body_file
  body_file=$(mktemp)

  local status
  status=$(status_and_body "$body_file" \
    -X POST "${SUPABASE_URL}/rest/v1/personal_foods" \
    -H "apikey: ${SUPABASE_ANON_KEY}" \
    -H "Authorization: Bearer ${ACCESS_TOKEN_A}" \
    -H "Content-Type: application/json" \
    -H "Prefer: return=representation" \
    -d "[{\"user_id\":\"${user_id_a}\",\"food_name\":\"RLS Personal Food\",\"calories\":222,\"protein\":15,\"carbs\":20,\"fat\":5,\"source\":\"test\"}]")

  if [[ "$status" != "201" && "$status" != "200" ]]; then
    echo "personal_foods create failed (status=${status})."
    cat "$body_file"
    rm -f "$body_file"
    exit 1
  fi

  local entry_id
  entry_id=$(BODY_FILE="$body_file" python3 - <<'PY'
import json, os
with open(os.environ["BODY_FILE"], "r", encoding="utf-8") as f:
    body = json.load(f)
print((body[0] if body else {}).get("id", ""))
PY
)
  rm -f "$body_file"

  if [[ -z "$entry_id" ]]; then
    echo "Could not parse personal_foods entry id"
    exit 1
  fi

  echo "$entry_id"
}

echo "Running RLS verification tests against ${SUPABASE_URL}"

USER_ID_A=$(auth_user_field "$ACCESS_TOKEN_A" "id")
USER_ID_B=$(auth_user_field "$ACCESS_TOKEN_B" "id")
EMAIL_A=$(auth_user_field "$ACCESS_TOKEN_A" "email")
EMAIL_B=$(auth_user_field "$ACCESS_TOKEN_B" "email")

[[ -n "$USER_ID_A" && -n "$USER_ID_B" ]] || fail "Could not parse user ids from auth tokens"
[[ "$USER_ID_A" != "$USER_ID_B" ]] || fail "ACCESS_TOKEN_A and ACCESS_TOKEN_B must belong to different users"
pass "Resolved two distinct authenticated user ids"

USER_UPSERT_A_BODY=$(mktemp)
USER_UPSERT_A_STATUS=$(status_and_body "$USER_UPSERT_A_BODY" \
  -X POST "${SUPABASE_URL}/rest/v1/users?on_conflict=id" \
  -H "apikey: ${SUPABASE_ANON_KEY}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN_A}" \
  -H "Content-Type: application/json" \
  -H "Prefer: resolution=merge-duplicates,return=representation" \
  -d "[{\"id\":\"${USER_ID_A}\",\"email\":\"${EMAIL_A}\",\"display_name\":\"RLS User A\"}]")
[[ "$USER_UPSERT_A_STATUS" == "200" || "$USER_UPSERT_A_STATUS" == "201" ]] || {
  echo "users upsert for user A failed (status=${USER_UPSERT_A_STATUS})"
  cat "$USER_UPSERT_A_BODY"
  rm -f "$USER_UPSERT_A_BODY"
  fail "Could not upsert users row for user A"
}
rm -f "$USER_UPSERT_A_BODY"

USER_UPSERT_B_BODY=$(mktemp)
USER_UPSERT_B_STATUS=$(status_and_body "$USER_UPSERT_B_BODY" \
  -X POST "${SUPABASE_URL}/rest/v1/users?on_conflict=id" \
  -H "apikey: ${SUPABASE_ANON_KEY}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN_B}" \
  -H "Content-Type: application/json" \
  -H "Prefer: resolution=merge-duplicates,return=representation" \
  -d "[{\"id\":\"${USER_ID_B}\",\"email\":\"${EMAIL_B}\",\"display_name\":\"RLS User B\"}]")
[[ "$USER_UPSERT_B_STATUS" == "200" || "$USER_UPSERT_B_STATUS" == "201" ]] || {
  echo "users upsert for user B failed (status=${USER_UPSERT_B_STATUS})"
  cat "$USER_UPSERT_B_BODY"
  rm -f "$USER_UPSERT_B_BODY"
  fail "Could not upsert users row for user B"
}
rm -f "$USER_UPSERT_B_BODY"
pass "Both users can upsert their own users row"

USERS_CROSS_BODY=$(mktemp)
USERS_CROSS_STATUS=$(status_and_body "$USERS_CROSS_BODY" \
  -H "apikey: ${SUPABASE_ANON_KEY}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN_A}" \
  "${SUPABASE_URL}/rest/v1/users?id=eq.${USER_ID_B}&select=id")
[[ "$USERS_CROSS_STATUS" == "200" ]] || {
  cat "$USERS_CROSS_BODY"
  rm -f "$USERS_CROSS_BODY"
  fail "Cross-user users select did not return status 200"
}
USERS_CROSS_COUNT=$(BODY_FILE="$USERS_CROSS_BODY" python3 - <<'PY'
import json, os
with open(os.environ["BODY_FILE"], "r", encoding="utf-8") as f:
    body = json.load(f)
print(len(body) if isinstance(body, list) else -1)
PY
)
rm -f "$USERS_CROSS_BODY"
[[ "$USERS_CROSS_COUNT" == "0" ]] || fail "User A should not be able to read user B users row"
pass "Cross-user users read is blocked"

DAILY_ID_A=$(create_daily_log_as_a "$USER_ID_A")
pass "User A can create daily_logs entry"

DAILY_CROSS_READ_BODY=$(mktemp)
DAILY_CROSS_READ_STATUS=$(status_and_body "$DAILY_CROSS_READ_BODY" \
  -H "apikey: ${SUPABASE_ANON_KEY}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN_B}" \
  "${SUPABASE_URL}/rest/v1/daily_logs?id=eq.${DAILY_ID_A}&select=id,user_id")
[[ "$DAILY_CROSS_READ_STATUS" == "200" ]] || {
  cat "$DAILY_CROSS_READ_BODY"
  rm -f "$DAILY_CROSS_READ_BODY"
  fail "Cross-user daily_logs read did not return status 200"
}
DAILY_CROSS_READ_COUNT=$(BODY_FILE="$DAILY_CROSS_READ_BODY" python3 - <<'PY'
import json, os
with open(os.environ["BODY_FILE"], "r", encoding="utf-8") as f:
    body = json.load(f)
print(len(body) if isinstance(body, list) else -1)
PY
)
rm -f "$DAILY_CROSS_READ_BODY"
[[ "$DAILY_CROSS_READ_COUNT" == "0" ]] || fail "User B should not see user A daily_logs entry"
pass "Cross-user daily_logs read is blocked"

DAILY_CROSS_UPDATE_BODY=$(mktemp)
DAILY_CROSS_UPDATE_STATUS=$(status_and_body "$DAILY_CROSS_UPDATE_BODY" \
  -X PATCH "${SUPABASE_URL}/rest/v1/daily_logs?id=eq.${DAILY_ID_A}" \
  -H "apikey: ${SUPABASE_ANON_KEY}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN_B}" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=representation" \
  -d '{"food_name":"Spoof Update"}')
[[ "$DAILY_CROSS_UPDATE_STATUS" == "200" ]] || {
  cat "$DAILY_CROSS_UPDATE_BODY"
  rm -f "$DAILY_CROSS_UPDATE_BODY"
  fail "Cross-user daily_logs update returned unexpected status=${DAILY_CROSS_UPDATE_STATUS}"
}
DAILY_CROSS_UPDATE_COUNT=$(BODY_FILE="$DAILY_CROSS_UPDATE_BODY" python3 - <<'PY'
import json, os
with open(os.environ["BODY_FILE"], "r", encoding="utf-8") as f:
    body = json.load(f)
print(len(body) if isinstance(body, list) else -1)
PY
)
rm -f "$DAILY_CROSS_UPDATE_BODY"
[[ "$DAILY_CROSS_UPDATE_COUNT" == "0" ]] || fail "User B should not be able to update user A daily_logs entry"
pass "Cross-user daily_logs update is blocked"

DAILY_SPOOF_INSERT_BODY=$(mktemp)
DAILY_SPOOF_INSERT_STATUS=$(status_and_body "$DAILY_SPOOF_INSERT_BODY" \
  -X POST "${SUPABASE_URL}/rest/v1/daily_logs" \
  -H "apikey: ${SUPABASE_ANON_KEY}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN_B}" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=representation" \
  -d "[{\"user_id\":\"${USER_ID_A}\",\"food_name\":\"Spoof Insert\",\"calories\":1}]")
if [[ "$DAILY_SPOOF_INSERT_STATUS" == "200" || "$DAILY_SPOOF_INSERT_STATUS" == "201" ]]; then
  BODY_FILE="$DAILY_SPOOF_INSERT_BODY" python3 - <<'PY'
import json, os
with open(os.environ["BODY_FILE"], "r", encoding="utf-8") as f:
    print(json.load(f))
PY
  rm -f "$DAILY_SPOOF_INSERT_BODY"
  fail "User B should not be able to insert daily_logs row with user_id=user A"
fi
rm -f "$DAILY_SPOOF_INSERT_BODY"
pass "Cross-user daily_logs spoofed insert is blocked"

PERSONAL_ID_A=$(create_personal_food_as_a "$USER_ID_A")
pass "User A can create personal_foods entry"

PERSONAL_CROSS_READ_BODY=$(mktemp)
PERSONAL_CROSS_READ_STATUS=$(status_and_body "$PERSONAL_CROSS_READ_BODY" \
  -H "apikey: ${SUPABASE_ANON_KEY}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN_B}" \
  "${SUPABASE_URL}/rest/v1/personal_foods?id=eq.${PERSONAL_ID_A}&select=id,user_id")
[[ "$PERSONAL_CROSS_READ_STATUS" == "200" ]] || {
  cat "$PERSONAL_CROSS_READ_BODY"
  rm -f "$PERSONAL_CROSS_READ_BODY"
  fail "Cross-user personal_foods read did not return status 200"
}
PERSONAL_CROSS_READ_COUNT=$(BODY_FILE="$PERSONAL_CROSS_READ_BODY" python3 - <<'PY'
import json, os
with open(os.environ["BODY_FILE"], "r", encoding="utf-8") as f:
    body = json.load(f)
print(len(body) if isinstance(body, list) else -1)
PY
)
rm -f "$PERSONAL_CROSS_READ_BODY"
[[ "$PERSONAL_CROSS_READ_COUNT" == "0" ]] || fail "User B should not see user A personal_foods entry"
pass "Cross-user personal_foods read is blocked"

DAILY_CLEANUP_BODY=$(mktemp)
DAILY_CLEANUP_STATUS=$(status_and_body "$DAILY_CLEANUP_BODY" \
  -X DELETE "${SUPABASE_URL}/rest/v1/daily_logs?id=eq.${DAILY_ID_A}" \
  -H "apikey: ${SUPABASE_ANON_KEY}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN_A}" \
  -H "Prefer: return=representation")
[[ "$DAILY_CLEANUP_STATUS" == "200" ]] || {
  cat "$DAILY_CLEANUP_BODY"
  rm -f "$DAILY_CLEANUP_BODY"
  fail "Cleanup delete for user A daily_logs row failed"
}
rm -f "$DAILY_CLEANUP_BODY"

PERSONAL_CLEANUP_BODY=$(mktemp)
PERSONAL_CLEANUP_STATUS=$(status_and_body "$PERSONAL_CLEANUP_BODY" \
  -X DELETE "${SUPABASE_URL}/rest/v1/personal_foods?id=eq.${PERSONAL_ID_A}" \
  -H "apikey: ${SUPABASE_ANON_KEY}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN_A}" \
  -H "Prefer: return=representation")
[[ "$PERSONAL_CLEANUP_STATUS" == "200" ]] || {
  cat "$PERSONAL_CLEANUP_BODY"
  rm -f "$PERSONAL_CLEANUP_BODY"
  fail "Cleanup delete for user A personal_foods row failed"
}
rm -f "$PERSONAL_CLEANUP_BODY"
pass "Cleanup completed"

echo "RLS verification tests completed successfully."
