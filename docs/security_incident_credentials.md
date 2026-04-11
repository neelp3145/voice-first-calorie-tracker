# SECURITY INCIDENT: Credentials Exposed in Repository

**Status:** Review Required  
**Severity:** High  
**Date Identified:** April 11, 2026

## Summary

API keys and secrets may have been committed to `.env` or shared in version control. If your `.env` file is visible to others or committed, all credentials below must be considered **compromised** and should be rotated immediately.

## Affected Credentials

- ✗ `USDA_API_KEY` — FoodData Central API key
- ✗ `GROQ_API_KEY` — Groq API key for AI models
- ✗ `TAVILY_API_KEY` — Tavily search API key
- ✗ `SUPABASE_ANON_KEY` — Anonymous key (lower risk, but should be rotated as precaution)
- ✗ `SUPABASE_SERVICE_ROLE_KEY` — Admin key (critical; must be rotated immediately)

## Immediate Actions Required

### 1. Rotate All Exposed Keys (TODAY)

Follow the rotation guide in `docs/key_rotation_guide.md` for each service:
- USDA (FoodData Central)
- Groq
- Tavily
- Supabase (both keys)

### 2. Verify .env Is Not Committed

```bash
git log --all --full-history --source --remotes -- .env
```

If output shows commits, secret scan and audit those commits.

### 3. Update .env Locally with New Keys

Once rotated, replace values in `.env` with fresh credentials.

### 4. Enable Pre-Commit Secret Detection

Move forward to ensure this doesn't happen again:
```bash
npm install -D pre-commit
npm run set-up-pre-commit  # (optional; manual setup in docs)
```

## Prevention Going Forward

1. `.env` is in `.gitignore` — do not remove
2. Use `.env.example` as a template (never commit real secrets)
3. Run `npm run validate:no-secrets` before committing
4. CI secret-scanning workflow will block secrets at merge time

## After Rotation

1. Write date rotated in `.env` as a comment (local only)
2. Test all API calls to confirm new keys work
3. Run `npm run lint` and `npm run security:smoke` to validate integration
4. Update relevant `.md` docs if key format changed

## Reference

- Key Rotation Guide: [docs/key_rotation_guide.md](key_rotation_guide.md)
- .env.example: ../.env.example
- CI Secret Scanning: ../.github/workflows/security-checks.yml

