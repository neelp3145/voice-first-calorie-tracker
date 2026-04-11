#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
ACCESS_TOKEN="${ACCESS_TOKEN:-}"

pass() {
  echo "[PASS] $1"
}

fail() {
  echo "[FAIL] $1"
  exit 1
}

expect_status() {
  local expected="$1"
  local command="$2"
  local label="$3"

  local actual
  actual=$(eval "$command")

  if [[ "$actual" == "$expected" ]]; then
    pass "$label (status=$actual)"
  else
    fail "$label (expected=$expected, got=$actual)"
  fi
}

echo "Running security smoke tests against ${API_BASE_URL}"

expect_status "401" \
  "curl -s -o /dev/null -w '%{http_code}' '${API_BASE_URL}/api/foods/search?query=apple'" \
  "Unauthorized foods/search blocked"

expect_status "401" \
  "curl -s -o /dev/null -w '%{http_code}' -X POST '${API_BASE_URL}/api/voice' -F 'file=@/etc/hosts;type=audio/webm'" \
  "Unauthorized voice upload blocked"

expect_status "401" \
  "curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: Bearer invalid-token' '${API_BASE_URL}/api/foods/search?query=apple'" \
  "Invalid token rejected"

if [[ -z "$ACCESS_TOKEN" ]]; then
  echo "Skipping token-required checks. Set ACCESS_TOKEN to run full suite."
  exit 0
fi

LONG_QUERY=$(printf 'a%.0s' {1..240})

expect_status "422" \
  "curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: Bearer ${ACCESS_TOKEN}' '${API_BASE_URL}/api/foods/search?query=${LONG_QUERY}'" \
  "Overlong query blocked"

TMP_TXT=$(mktemp)
echo "not-audio" > "$TMP_TXT"
expect_status "415" \
  "curl -s -o /dev/null -w '%{http_code}' -X POST '${API_BASE_URL}/api/voice' -H 'Authorization: Bearer ${ACCESS_TOKEN}' -F 'file=@${TMP_TXT};type=text/plain'" \
  "Unsupported upload mime blocked"
rm -f "$TMP_TXT"

ME_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${ACCESS_TOKEN}" "${API_BASE_URL}/api/me")
if [[ "$ME_STATUS" == "200" ]]; then
  pass "Identity endpoint available"
else
  fail "Identity endpoint failed (expected=200, got=${ME_STATUS})"
fi

echo "Security smoke tests completed successfully."
