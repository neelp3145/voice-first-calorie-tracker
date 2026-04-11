# Voice-First Calorie Tracker

This project has:
- A FastAPI backend (food parsing, transcription, nutrition lookup)
- A Next.js frontend (logger, journal, profile UI)

## Quick Start (Copy-Paste)

### 1) Add `.env` File

Run this once from the project root:

```bash
cat > .env << 'EOF'
USDA_API_KEY=your_usda_key
GROQ_API_KEY=your_groq_key
TAVILY_API_KEY=your_tavily_key
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key
EOF
```

### 2) Terminal 1 (Backend)

```bash
cd "/home/divya_ganesh/projects/Software engineering/NEW FOLDER/voice-first-calorie-tracker"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3) Terminal 2 (Frontend)

```bash
cd "/home/divya_ganesh/projects/Software engineering/NEW FOLDER/voice-first-calorie-tracker"
npm install
npm run dev
```

### 4) Run Everything

- Backend: http://localhost:8000
- Frontend: http://localhost:3000

## Prerequisites

- Python 3.11+
- Node.js 18+
- npm

## 1) Clone and Enter Project

```bash
git clone <your-repo-url>
cd voice-first-calorie-tracker
```

## 2) Set Up Environment Variables

Create a `.env` file in the project root:

```env
# Required for backend startup/food lookups
USDA_API_KEY=your_usda_key

# Required for parser + transcription
GROQ_API_KEY=your_groq_key

# Optional unless using Tavily workflows
TAVILY_API_KEY=your_tavily_key

# Optional unless using Supabase integration
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key

# Optional CORS override (comma-separated)
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Frontend -> backend URL
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

# Frontend Supabase Auth variables
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key
```

## 3) Set Up Python Backend

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install backend dependencies:

```bash
pip install -r requirements.txt
```

Run backend (FastAPI + Uvicorn):

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Backend URL:
- http://localhost:8000

## 4) Set Up Next.js Frontend

In a second terminal, from the same project folder:

```bash
npm install
npm run dev
```

Frontend URL:
- http://localhost:3000

## 5) Development Workflow

Run both servers at the same time:
- Terminal 1: backend on port 8000
- Terminal 2: frontend on port 3000

The logger page calls backend endpoints such as:
- `GET /api/foods/search`
- `POST /api/voice`

## Troubleshooting

- `No module named uvicorn`
	- Activate `.venv` and reinstall requirements:
	- `source .venv/bin/activate && pip install -r requirements.txt`

- Frontend cannot reach backend
	- Check `NEXT_PUBLIC_API_BASE_URL` in `.env`
	- Confirm backend is running on port 8000

- CORS issues from frontend
	- Add your frontend origin to `ALLOWED_ORIGINS`

- Image assets not loading on Linux
	- Filenames in `public/` are case-sensitive (for example `.PNG` vs `.png`)

## Security Operations

- Security implementation overview: `docs/security_implementation_guide.md`.
- CI security checks are defined in `.github/workflows/security-checks.yml`.
- Abuse test scenarios are in `docs/security_abuse_test_matrix.md`.
- Incident response steps are in `docs/security_incident_playbook.md`.
- Local security smoke checks: `npm run security:smoke`.
- Identity-binding checks (requires JWT): `ACCESS_TOKEN=<valid_jwt> npm run security:identity`.
- RLS policy verification (requires two user JWTs): `ACCESS_TOKEN_A=<user_a_jwt> ACCESS_TOKEN_B=<user_b_jwt> npm run security:rls`.

### Apply Database Security Migration (Supabase)

Run the SQL in:

- `supabase/migrations/20260411_initial_security_schema.sql`

This migration applies/updates:

- Owner-bound RLS policies for `users`, `daily_logs`, and `personal_foods`
- Explicit RLS lock-down for currently-unused `food_searches` and `global_foods`
- Verification snippets for negative access tests

RLS verification script prerequisites:

- `SUPABASE_URL` (or `NEXT_PUBLIC_SUPABASE_URL`)
- `SUPABASE_ANON_KEY` (or `NEXT_PUBLIC_SUPABASE_ANON_KEY`)
- `ACCESS_TOKEN_A` and `ACCESS_TOKEN_B` from two different authenticated users

### HTTPS Deployment Note

For production, terminate TLS at your reverse proxy/load balancer and forward only HTTPS traffic to users. Keep `ALLOWED_ORIGINS` restricted to trusted frontend hosts.
