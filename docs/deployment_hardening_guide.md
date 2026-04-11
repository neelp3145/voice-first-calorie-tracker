# Production Deployment Guide

This guide covers hardening, deployment architecture, and operational runbooks for Vocalorie in production.

## Pre-Deployment Checklist

### Code & Dependencies

- [ ] All linting passes: `npm run lint`
- [ ] All tests pass: `npm run security:smoke && npm run security:identity`
- [ ] Secret validation passes: `npm run validate:no-secrets`
- [ ] No hardcoded credentials in git history: `git log --all -p | grep -i "api_key\|secret" | wc -l` (should be 0)
- [ ] All environment variables are set from production `.env` (never `.env.example`)
- [ ] Dependencies are audited: `npm audit` (no critical vulnerabilities)

### Security Configuration

- [ ] HTTPS is enabled on reverse proxy/load balancer
- [ ] TLS 1.2+ only (TLS 1.0/1.1 disabled)
- [ ] Certificate is from trusted CA (not self-signed)
- [ ] HSTS header is set: `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- [ ] CSP header is configured and tested
- [ ] CORS `ALLOWED_ORIGINS` restricted to production domain only
- [ ] `.env` file is never committed and excluded from Docker images
- [ ] Secrets are injected via environment or secrets manager (not baked into container)

### Authentication & Sessions

- [ ] Supabase project is in production setup (not development)
- [ ] Supabase Auth Site URL is set to production domain
- [ ] Google OAuth (if used) is configured with production domain
- [ ] Session timeout is 1 hour for access tokens
- [ ] Cookie domain is set correctly (not wildcard)
- [ ] HttpOnly and Secure flags are enabled on all cookies

### Database & Data

- [ ] RLS policies are applied in Supabase: see `docs/apply_rls_migration.md`
- [ ] RLS is enabled on all user-owned tables (`users`, `daily_logs`, `personal_foods`)
- [ ] Backups are scheduled (Supabase automatic daily; enable Point-in-Time Recovery if available)
- [ ] Database size monitoring is enabled
- [ ] Connection pooling is configured (Supabase PgBouncer mode for high concurrency)

### Deployment Architecture

- [ ] Reverse proxy or load balancer is in front of application
- [ ] Multiple instances of backend are running (for high availability)
- [ ] Multiple instances of frontend are running (CDN or load balancer)
- [ ] Health-check endpoints are configured (`/health` or similar)
- [ ] Rate limiting is configured at reverse proxy level (optional; backend has in-app limits)
- [ ] DDoS protection is enabled (Cloudflare, AWS WAF, etc. optional for MVP)

### Monitoring & Logging

- [ ] Error logging is configured (e.g., Sentry, DataDog, or CloudWatch)
- [ ] Access logs are being collected
- [ ] Performance metrics are being tracked (response times, error rates)
- [ ] Alerts are configured for high error rates or downtimes
- [ ] No sensitive data (API keys, PII) is logged

### Key Rotation & Secrets

- [ ] All API keys have been rotated since development: see `docs/key_rotation_guide.md`
- [ ] Secrets are stored in environment variables or secrets manager (not hardcoded)
- [ ] Secrets manager is encrypted and access-controlled
- [ ] Key rotation schedule is documented and enforced

## Deployment Models

### Option 1: Vercel (Recommended for Next.js MVP)

**Pros:** Built for Next.js, automatic HTTPS, global CDN, easy secrets injection  
**Cons:** Vendor lock-in, limited backend customization

**Setup:**
1. Create account at https://vercel.com
2. Connect GitHub repo
3. Set environment variables in Vercel dashboard:
   ```
   NEXT_PUBLIC_SUPABASE_URL=...
   NEXT_PUBLIC_SUPABASE_ANON_KEY=...
   NEXT_PUBLIC_API_BASE_URL=https://api.yourdomain.com
   ```
4. Deploy: `git push` triggers automatic deployment
5. Domain: Configure custom domain in Vercel settings

**Backend Hosting:**
- Deploy FastAPI backend separately (Railway, AWS Lambda, Fly.io, etc.)
- Set `NEXT_PUBLIC_API_BASE_URL` to backend domain

### Option 2: Docker + Kubernetes (For Scale)

**Pros:** Full control, multi-region, enterprise-grade infrastructure  
**Cons:** Operational complexity, infrastructure costs

**Docker Compose (dev-like production):**

```yaml
version: "3.9"

services:
  frontend:
    build:
      context: .
      dockerfile: Dockerfile.frontend
    ports:
      - "3000:3000"
    environment:
      NEXT_PUBLIC_SUPABASE_URL: ${NEXT_PUBLIC_SUPABASE_URL}
      NEXT_PUBLIC_SUPABASE_ANON_KEY: ${NEXT_PUBLIC_SUPABASE_ANON_KEY}
      NEXT_PUBLIC_API_BASE_URL: http://backend:8000
    depends_on:
      - backend

  backend:
    build:
      context: .
      dockerfile: Dockerfile.backend
    ports:
      - "8000:8000"
    environment:
      SUPABASE_URL: ${SUPABASE_URL}
      SUPABASE_SERVICE_ROLE_KEY: ${SUPABASE_SERVICE_ROLE_KEY}
      USDA_API_KEY: ${USDA_API_KEY}
      GROQ_API_KEY: ${GROQ_API_KEY}
    restart: unless-stopped
```

**Dockerfile.frontend:**
```dockerfile
FROM node:18-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:18-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --production
COPY --from=builder /app/.next ./.next
COPY public ./public
EXPOSE 3000
CMD ["npm", "start"]
```

**Dockerfile.backend:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Option 3: Traditional VPS (EC2, DigitalOcean, etc.)

**Pros:** Simple, familiar, low cost for small deployments  
**Cons:** Manual management, no auto-scaling

**Setup:**
1. Provision Ubuntu 22.04 LTS server
2. Install Node.js, Python, Nginx
3. Clone repo: `git clone <your-repo>`
4. Set environment variables: `export SUPABASE_URL=...` (or use `.env`)
5. Start backend: `nohup python -m uvicorn main:app --host 127.0.0.1 --port 8000 &`
6. Configure Nginx as reverse proxy (see below)
7. Install systemd services for auto-restart

**Nginx Configuration:**
```nginx
server {
    listen 443 ssl http2;
    server_name yourdomain.com;
    
    ssl_certificate /etc/ssl/certs/yourdomain.crt;
    ssl_certificate_key /etc/ssl/private/yourdomain.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    
    # Frontend (Next.js)
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # Backend API
    location /api {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # Health check
    location /health {
        access_log off;
        return 200 "ok";
    }
}

server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$server_name$request_uri;
}
```

## Post-Deployment Validation

### Manual Testing

1. **Auth Flow:**
   - Sign up with new account
   - Sign in with email/password
   - Access protected routes (/logger, /journal, /profile)
   - Sign out and verify redirect to login

2. **Data Isolation:**
   - Log in as two users in separate browsers
   - Confirm each user sees only their own data
   - Attempt to access another user's profile (should be forbidden)

3. **Security Headers:**
   ```bash
   curl -I https://yourdomain.com
   # Verify headers: HSTS, CSP, X-Content-Type-Options, etc.
   ```

4. **API Auth:**
   ```bash
   # Should fail without token
   curl -X POST https://yourdomain.com/api/journal/entries
   
   # Should succeed with token
   curl -X GET https://yourdomain.com/api/me \
     -H "Authorization: Bearer <valid_jwt>"
   ```

### Automated Testing

```bash
# Run security suite
npm run security:smoke
npm run security:identity
npm run security:rls  # After RLS migration applied

# Check dependencies
npm audit

# Run linting
npm run lint
```

## Operational Runbooks

### Incident: High Error Rate

1. **Immediate Response:**
   - Check error logs (Sentry/CloudWatch)
   - Identify affected endpoints and error patterns
   - Assess user impact (auth vs data operations)

2. **Investigation:**
   ```bash
   # Check backend logs
   docker logs backend
   
   # Check error rate trends
   # (In your monitoring dashboard, look at last 1 hour)
   ```

3. **Mitigation:**
   - If storage quota exceeded: contact Supabase, increase plan
   - If rate limits hit: increase quotas in `main.py` or backend config
   - If external API down (USDA, Groq): implement fallback or disable feature temporarily
   - If database connection issues: check connection pooling config

4. **Resolution:**
   - Restart affected service if needed: `docker restart backend`
   - Monitor error rate for 10 minutes
   - Post-incident: log issue and update monitoring

### Incident: Suspected Security Breach

1. **Immediate Actions (First 15 minutes):**
   - Do NOT reset all passwords automatically (causes support load)
   - Check access logs for suspicious patterns
   - Review recent deployments for unintended changes

2. **Assessment:**
   - Was it credentials leaked? (check git history; see `docs/key_rotation_guide.md`)
   - Was it data exfiltration? (check database audit logs if available)
   - Was it infrastructure compromise? (check cloud provider security alerts)

3. **Response:**
   - If credentials leaked: rotate immediately (steps in key_rotation_guide.md)
   - If data accessed: evaluate if user notification required (depends on jurisdiction)
   - If infrastructure: rotate all secrets and redeploy

4. **Communication:**
   - Notify users if data was accessed (follow your legal/privacy policy)
   - Document incident with timestamps, root cause, and remediation

### Incident: Service Unavailability

1. **Triage (First 5 minutes):**
   - Check status page / uptime monitor
   - Determine: is it frontend, backend, or database?
   - Check logs for errors

2. **Quick Fixes:**
   ```bash
   # Restart backend
   docker restart backend
   
   # Check Supabase status at https://status.supabase.com
   
   # Scale up instances if CPU/memory high
   docker-compose up -d --scale backend=3
   ```

3. **Investigation:**
   - Memory leaks? Check process usage and restart
   - Database overwhelmed? Check query logs and kill slow queries
   - External dependency down? Switch to graceful fallback

4. **Recovery:**
   - Once running, verify with smoke tests: `npm run security:smoke`
   - Monitor for 30 minutes to confirm stability

### Key Rotation (Scheduled)

**Frequency:** Every 90 days or immediately if suspected compromise

**Steps:**
1. Follow [docs/key_rotation_guide.md](key_rotation_guide.md)
2. Update environment variables in production
3. Restart all services
4. Verify API calls work with new keys
5. Document rotation in change log

## Performance Optimization

### Caching

- **Frontend:** Next.js ISR (Incremental Static Regeneration) for meal data
- **Backend:** Cache USDA lookups in Supabase for 7 days
- **CDN:** Serve static assets (images, scripts) from global CDN

### Database Optimization

- Index on `user_id` and `created_at` for fast journal queries
- Vacuum and analyze tables weekly

### Rate Limiting

Currently in-memory; for production scaling:
- Use Redis for distributed rate limiting
- Increase per-IP and per-user quotas based on real usage patterns

## Further Reading

- Supabase Deployment: https://supabase.com/docs/guides/deployment
- OWASP Deployment Security: https://cheatsheetseries.owasp.org/
- Next.js Production: https://nextjs.org/docs/going-to-production
- FastAPI for Production: https://fastapi.tiangolo.com/deployment/

