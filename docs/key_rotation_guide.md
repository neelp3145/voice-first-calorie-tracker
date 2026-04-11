# Key Rotation and Secret Hygiene Guide

This guide covers how to identify, rotate, and manage API keys and secrets without leaking them to version control or logs.

## Overview

Your app uses several external API keys:
- **USDA_API_KEY** — FoodData Central (backend-only)
- **GROQ_API_KEY** — Groq chat/transcription (backend-only)
- **TAVILY_API_KEY** — Tavily search (backend-only)
- **SUPABASE_ANON_KEY** — Public Supabase key (frontend-safe)
- **SUPABASE_SERVICE_ROLE_KEY** — Admin Supabase key (backend-only, sensitive)

## Key Manager Setup Decision

| Approach | Best For | Effort |
|----------|----------|--------|
| Environment variables (current) | Local dev, small teams | Low — keep .env.example + .gitignore |
| Secrets manager (e.g., 1Password, Vault) | Production, compliance | High — sync integration needed |
| GitHub Secrets + CI/CD only | CI/CD pipelines only | Medium — frontend still needs vars |

**Recommendation for MVP:** Keep environment variables locally (never commit), add validation to catch leaks, upgrade to managed secrets before deploying publicly.

## Per-Service Rotation Guide

### 1. USDA FoodData Central API Key

**Service:** https://fdc.nal.usda.gov/developers  
**Sensitivity:** High (can enumerate your food database)  
**Rotation frequency:** If leaked; yearly otherwise

#### Steps

1. Go to https://fdc.nal.usda.gov/api/swagger-ui/
2. Log in with your USDA account
3. Navigate to **API Keys** section
4. Click **Generate New Key**
5. Copy the new key (36-character string starting with number)
6. Update `.env` locally:
   ```env
   USDA_API_KEY="<new_key>"
   ```
7. Test with local backend:
   ```bash
   curl http://localhost:8000/api/foods/search?query=apple \
     -H "Authorization: Bearer <your_jwt>"
   ```
8. Confirm responses work (200 OK, food data returned)
9. Revoke old key in USDA dashboard

#### Validation
```bash
source .venv/bin/activate
python3 -c "
import os
from dotenv import load_dotenv
load_dotenv()
usda_key = os.getenv('USDA_API_KEY')
print(f'USDA key loaded: {usda_key[:4]}...')
"
```

---

### 2. Groq API Key

**Service:** https://console.groq.com  
**Sensitivity:** High (can use your quota for inference)  
**Rotation frequency:** If leaked; yearly otherwise

#### Steps

1. Go to https://console.groq.com/keys
2. Log in with your Groq account
3. Click **Create API Key** (or view existing keys)
4. Copy the new key (starts with `gsk_`)
5. Update `.env` locally:
   ```env
   GROQ_API_KEY="<new_key>"
   ```
6. Test with local backend:
   ```bash
   curl -X POST http://localhost:8000/api/voice \
     -H "Authorization: Bearer <your_jwt>" \
     -F "audio=@test.wav" \
     -F "mime_type=audio/wav"
   ```
7. Confirm transcription works
8. Revoke old key in Groq console

#### Validation
```bash
source .venv/bin/activate
python3 -c "
import os
from dotenv import load_dotenv
load_dotenv()
groq_key = os.getenv('GROQ_API_KEY')
print(f'Groq key loaded: {groq_key[:10]}...')
"
```

---

### 3. Tavily API Key

**Service:** https://tavily.com  
**Sensitivity:** Medium (used for search)  
**Rotation frequency:** If leaked; yearly otherwise

#### Steps

1. Go to https://app.tavily.com/home
2. Log in with your account
3. Navigate to **API Keys**
4. Click **Generate New Key** or **View Key**
5. Copy the new key (starts with `tvly-`)
6. Update `.env` locally:
   ```env
   TAVILY_API_KEY="<new_key>"
   ```
7. Test integration (if used in your flows):
   ```bash
   python3 -c "
   import os
   from dotenv import load_dotenv
   load_dotenv()
   print(f'Tavily key: {os.getenv(\"TAVILY_API_KEY\")[:10]}...')
   "
   ```
8. Revoke old key in Tavily console

---

### 4. Supabase ANON_KEY

**Service:** https://app.supabase.com/project/_/settings/api  
**Sensitivity:** Low (scoped to authenticated users only)  
**Rotation frequency:** If leaked; yearly otherwise

#### Steps

1. Go to https://app.supabase.com/project/YOUR_PROJECT/settings/api
2. Under **Project API Keys**, locate the **ANON key** row
3. Click the **regenerate** icon (circular arrow)
4. Confirm regeneration
5. Copy the new key
6. Update `.env` locally:
   ```env
   NEXT_PUBLIC_SUPABASE_ANON_KEY="<new_key>"
   ```
7. Update frontend `.tsx` files that hardcode the old key (if any)
8. Restart both frontend and backend:
   ```bash
   npm run dev  # new terminal
   python -m uvicorn main:app --reload  # another terminal
   ```
9. Test auth flow: sign up, sign in, navigate to `/logger`

#### Validation
```bash
grep -r "eyJhbGciOiJIUzI1NiIs" . --include="*.tsx" --include="*.ts"
# Should return nothing or only .env (if not gitignored)
```

---

### 5. Supabase SERVICE_ROLE_KEY (Critical)

**Service:** https://app.supabase.com/project/_/settings/api  
**Sensitivity:** Critical (full admin access; backend-only)  
**Rotation frequency:** If leaked; yearly otherwise

#### Steps

1. Go to https://app.supabase.com/project/YOUR_PROJECT/settings/api
2. Under **Project API Keys**, locate the **SERVICE ROLE key** row
3. Click the **regenerate** icon
4. **CONFIRM** (you will see a warning)
5. Copy the new key
6. Update `.env` locally:
   ```env
   SUPABASE_SERVICE_ROLE_KEY="<new_key>"
   ```
7. Update `supabase_client.py`:
   - Verify it reads from `.env` and not hardcoded values
   - Restart backend server
8. Test profile/journal endpoints with a valid JWT:
   ```bash
   ACCESS_TOKEN="<valid_jwt>" npm run security:identity
   ```
9. If using Supabase in CI/CD, update repository secrets:
   - Go to Settings → Secrets and variables → Actions
   - Update `SUPABASE_SERVICE_ROLE_KEY` secret

#### Validation
```bash
# Check no SERVICE_ROLE key is hardcoded in Python
grep -r "sb_secret_" . --include="*.py" --exclude-dir=.venv
# Should return nothing
```

---

## Preventing Secrets Leaks

### 1. .env File Protection

Your `.gitignore` already prevents `.env` from being committed:
```bash
# .gitignore excerpt
.env
.env*
```

**Verify:**
```bash
git ls-files | grep -i env
# Should NOT show .env or .env.local
```

### 2. .env.example Template

Keep `.env.example` with placeholders only:
```bash
# .env.example (COMMIT THIS, NEVER THE REAL .env)
USDA_API_KEY=your_usda_key
GROQ_API_KEY=your_groq_key
...
```

### 3. Pre-Commit Validation Script

Before pushing, check that no secrets are about to be committed:

**Create `scripts/validate_no_secrets.sh`:**
```bash
#!/usr/bin/env bash

# Exit on error
set -euo pipefail

# Regex patterns for common secret formats
PATTERNS=(
  "gsk_[a-zA-Z0-9]{20,}"  # Groq keys
  "tvly-[a-zA-Z0-9]{20,}"  # Tavily keys
  "sb_secret_[a-zA-Z0-9]{20,}"  # Supabase keys
  "[0-9]{10}[a-zA-Z]{20,}"  # USDA key pattern (rough)
  "eyJ[A-Za-z0-9_-]+\\.eyJ[A-Za-z0-9_-]+"  # JWT tokens
)

# Check staged files for secrets
found_secrets=0
for pattern in "${PATTERNS[@]}"; do
  if git diff --cached | grep -E "$pattern" > /dev/null; then
    echo "[ERROR] Potential secret found matching pattern: $pattern"
    found_secrets=$((found_secrets + 1))
  fi
done

if [[ $found_secrets -gt 0 ]]; then
  echo "[BLOCKED] Commit contains potential secrets. Unstage and use .env instead."
  exit 1
fi

echo "[OK] No obvious secrets detected in staged files."
exit 0
```

**Make executable and run before commits:**
```bash
chmod +x scripts/validate_no_secrets.sh
bash scripts/validate_no_secrets.sh
```

### 4. CI/CD Secret Scanning (Already In Place)

Your `.github/workflows/security-checks.yml` includes a secret scanner:
```yaml
- name: Secret scanning
  uses: trufflesecurity/trufflehog@main
```

This will block any PRs that contain leaked secrets.

---

## Verification Checklist

After rotating all keys:

- [ ] USDA key generation confirmed at https://fdc.nal.usda.gov/api/swagger-ui/
- [ ] Groq key generated at https://console.groq.com/keys
- [ ] Tavily key rotated at https://app.tavily.com/home
- [ ] Supabase ANON_KEY regenerated
- [ ] Supabase SERVICE_ROLE_KEY regenerated
- [ ] `.env` updated locally with all new keys
- [ ] `.env` is in `.gitignore` (not committed)
- [ ] `npm run lint` passes
- [ ] `npm run security:smoke` passes
- [ ] `ACCESS_TOKEN=<jwt> npm run security:identity` passes
- [ ] Frontend sign-in/sign-up flow works
- [ ] Old keys revoked in respective dashboards

---

## Deployment Checklist

Before production:

1. **Use a secrets manager** (1Password, AWS Secrets Manager, etc.) instead of environment files
2. **Never log secrets** — ensure debug logs redact API keys
3. **HTTPS only** — terminate TLS at your reverse proxy
4. **Set up CI/CD secrets** — GitHub Actions, GitLab CI, etc. should inject secrets at runtime
5. **Audit access logs** — rotate keys if unusual API usage is detected
6. **Enable key rotation policies** — each service should support automated rotation

---

## Timeline & Frequency

| Service | Rotation Trigger | Frequency |
|---------|------------------|-----------|
| USDA | Leaked / compromised | Yearly or on incident |
| Groq | Leaked / compromised | Yearly or on incident |
| Tavily | Leaked / compromised | Yearly or on incident |
| Supabase ANON | Leaked | Yearly or on incident |
| Supabase SERVICE_ROLE | **Leaked or suspicious activity** | As needed; at least yearly |

---

## Emergency Response

If you suspect a secret was leaked:

1. **Immediately regenerate the key** in its respective dashboard
2. **Update `.env` locally** with the new key
3. **Restart affected services** (backend, frontend)
4. **Check API usage logs** for suspicious activity
5. **Document the incident** in a private log (not in git)
6. **Review git history** for any commits containing the old secret:
   ```bash
   git log --all --full-history -- .env | head -20
   ```
7. If found in history, consider squashing or using git filter-branch (advanced)

---

## References

- Supabase API Keys: https://supabase.com/docs/guides/api#api-keys
- USDA FDC API: https://fdc.nal.usda.gov/api/doc
- Groq API Docs: https://console.groq.com/docs/
- Tavily Documentation: https://docs.tavily.com

