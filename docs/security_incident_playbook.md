# Security Incident Playbook

Date: 2026-04-11
System: Vocalorie (Next.js + FastAPI + Supabase)

## 1. Key Compromise

1. Rotate compromised keys immediately in provider dashboards:
- Supabase service role key
- Supabase anon key
- USDA key
- Groq key
- Tavily key
2. Update environment variables in deployment and local development.
3. Redeploy backend/frontend.
4. Invalidate active sessions if Supabase auth keys were compromised.
5. Review logs for unusual request bursts, token abuse, and suspicious origins.

## 2. Suspected Account Takeover

1. Force logout affected user(s): revoke refresh tokens in Supabase.
2. Require password reset for affected accounts.
3. Check recent auth logs for unusual IP/geography.
4. Preserve evidence: timestamps, IPs, request IDs.
5. Notify user with recommended account hygiene actions.

## 3. API Abuse / Bot Traffic

1. Temporarily tighten rate limits in backend.
2. Restrict ALLOWED_ORIGINS to known frontend hosts only.
3. Block malicious IP ranges at reverse proxy.
4. Monitor 429 and 401 rates during mitigation.
5. Postmortem and adjust permanent rate-limit thresholds.

## 4. Data Exposure Response

1. Isolate affected endpoints and disable risky features.
2. Identify exposed dataset scope and affected users.
3. Apply emergency patches and redeploy.
4. Rotate keys/tokens, then validate RLS policies.
5. Document timeline and root cause.

## 5. Recovery Checklist

1. All compromised keys rotated.
2. Sessions revoked where required.
3. Patch deployed and verified.
4. Abuse and auth anomaly metrics stabilized.
5. Post-incident report completed with preventive actions.
