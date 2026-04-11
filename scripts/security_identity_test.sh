#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
ACCESS_TOKEN="${ACCESS_TOKEN:-}"

if [[ -z "$ACCESS_TOKEN" ]]; then
  echo "ACCESS_TOKEN is required for identity tests."
  exit 1
fi

pass() {
  echo "[PASS] $1"
}

fail() {
  echo "[FAIL] $1"
  exit 1
}

status_of() {
  local cmd="$1"
  eval "$cmd"
}

echo "Running identity-binding tests against ${API_BASE_URL}"

ME_BODY=$(curl -s -H "Authorization: Bearer ${ACCESS_TOKEN}" "${API_BASE_URL}/api/me")
ME_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${ACCESS_TOKEN}" "${API_BASE_URL}/api/me")
[[ "$ME_STATUS" == "200" ]] || fail "/api/me should return 200"
pass "/api/me returns 200"

ME_ID=$(ME_BODY="$ME_BODY" python - <<'PY'
import json, os
body = json.loads(os.environ["ME_BODY"])
print(body.get("id", ""))
PY
)
[[ -n "$ME_ID" ]] || fail "Could not extract authenticated user id"
pass "Extracted authenticated user id"

PROFILE_BODY_FILE=$(mktemp)
PROFILE_STATUS=$(curl -s -o "$PROFILE_BODY_FILE" -w '%{http_code}' \
  -X PUT "${API_BASE_URL}/api/profile" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"full_name":"Security Test"}')
if [[ "$PROFILE_STATUS" != "200" ]]; then
  echo "Profile update response body:"
  cat "$PROFILE_BODY_FILE"
  rm -f "$PROFILE_BODY_FILE"
  fail "Profile update should succeed (status=${PROFILE_STATUS}). If this says schema not initialized, apply supabase/migrations/20260411_initial_security_schema.sql"
fi
rm -f "$PROFILE_BODY_FILE"
pass "Profile update works"

SPOOF_PROFILE_STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
  -X PUT "${API_BASE_URL}/api/profile" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"00000000-0000-0000-0000-000000000000","full_name":"Spoof Attempt"}')
[[ "$SPOOF_PROFILE_STATUS" == "422" ]] || fail "Spoofed user_id in profile payload must be rejected"
pass "Spoofed user_id rejected for profile update"

ENTRY_BODY_FILE=$(mktemp)
ENTRY_STATUS=$(curl -s -o "$ENTRY_BODY_FILE" -w '%{http_code}' \
  -X POST "${API_BASE_URL}/api/journal/entries" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"food_name":"Identity Test Meal","quantity":1,"calories":123}')
if [[ "$ENTRY_STATUS" != "200" ]]; then
  echo "Journal create response body:"
  cat "$ENTRY_BODY_FILE"
  rm -f "$ENTRY_BODY_FILE"
  fail "Journal entry creation should succeed (status=${ENTRY_STATUS}). If this says schema not initialized, apply supabase/migrations/20260411_initial_security_schema.sql"
fi
CREATED_ENTRY_ID=$(ENTRY_BODY_FILE="$ENTRY_BODY_FILE" python - <<'PY'
import json, os
body = json.loads(open(os.environ["ENTRY_BODY_FILE"], "r", encoding="utf-8").read())
print(body.get("id", ""))
PY
)
rm -f "$ENTRY_BODY_FILE"
[[ -n "$CREATED_ENTRY_ID" ]] || fail "Could not parse created journal entry id"
pass "Journal entry create works"

UPDATE_STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
  -X PUT "${API_BASE_URL}/api/journal/entries/${CREATED_ENTRY_ID}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"food_name":"Identity Test Meal Updated","calories":150,"protein_g":20}')
[[ "$UPDATE_STATUS" == "200" ]] || fail "Journal entry update should succeed"
pass "Journal entry update works"

SPOOF_ENTRY_STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
  -X POST "${API_BASE_URL}/api/journal/entries" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"00000000-0000-0000-0000-000000000000","food_name":"Spoof Meal","quantity":1}')
[[ "$SPOOF_ENTRY_STATUS" == "422" ]] || fail "Spoofed user_id in journal payload must be rejected"
pass "Spoofed user_id rejected for journal create"

LIST_BODY=$(curl -s -H "Authorization: Bearer ${ACCESS_TOKEN}" "${API_BASE_URL}/api/journal/entries?limit=10")
LIST_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${ACCESS_TOKEN}" "${API_BASE_URL}/api/journal/entries?limit=10")
[[ "$LIST_STATUS" == "200" ]] || fail "Journal list should return 200"

ALL_OWNED=$(ME_ID="$ME_ID" LIST_BODY="$LIST_BODY" python - <<'PY'
import json, os
me_id = os.environ["ME_ID"]
body = json.loads(os.environ["LIST_BODY"])
entries = body.get("entries", [])
print("yes" if all(e.get("user_id") == me_id for e in entries) else "no")
PY
)
[[ "$ALL_OWNED" == "yes" ]] || fail "Journal list contains rows not owned by authenticated user"
pass "Journal list rows are owned by current user"

DELETE_STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
  -X DELETE "${API_BASE_URL}/api/journal/entries/${CREATED_ENTRY_ID}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}")
[[ "$DELETE_STATUS" == "200" ]] || fail "Journal entry delete should succeed"
pass "Journal entry delete works"

echo "Identity-binding tests completed successfully."
