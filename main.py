from dotenv import load_dotenv
load_dotenv()

import os
import httpx
import json
import re
import logging
import time
import asyncio
from datetime import date, datetime, timedelta
from collections import defaultdict, OrderedDict
from threading import Lock
from uuid import UUID
from typing import Optional, Dict, Any, List, Tuple
from functools import lru_cache

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from tavily import TavilyClient
from openai import OpenAI
from supabase_client import supabase_admin
from journal import get_chart_data, get_journal, get_journal_summary, is_test_food_name

app = FastAPI()
logger = logging.getLogger("vocalorie.api")
logging.basicConfig(level=logging.INFO)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

MAX_QUERY_LENGTH = 200
MAX_AUDIO_BYTES = 10 * 1024 * 1024
ALLOWED_AUDIO_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/wav",
    "audio/mpeg",
    "audio/mp4",
}

RATE_LIMIT_BUCKETS = defaultdict(list)
RATE_LIMIT_LOCK = Lock()

# Nutrition cache with TTL
class NutritionCache:
    def __init__(self, max_size=1000, ttl_seconds=3600):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.lock = Lock()
    
    def get(self, key: str) -> Optional[Dict]:
        with self.lock:
            if key in self.cache:
                entry = self.cache[key]
                if time.time() - entry['timestamp'] < self.ttl_seconds:
                    # Move to end (LRU)
                    self.cache.move_to_end(key)
                    return entry['data']
                else:
                    del self.cache[key]
        return None
    
    def set(self, key: str, data: Dict):
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            else:
                if len(self.cache) >= self.max_size:
                    self.cache.popitem(last=False)
                self.cache[key] = {
                    'data': data,
                    'timestamp': time.time()
                }

nutrition_cache = NutritionCache()

port = int(os.environ.get("PORT", 8000))

def validate_environment() -> None:
    required = [
        "USDA_API_KEY",
        "GROQ_API_KEY",
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
    ]
    missing = [name for name in required if not os.getenv(name)]

    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    supabase_url = os.getenv("SUPABASE_URL", "")
    if not supabase_url.startswith("https://"):
        raise RuntimeError("SUPABASE_URL must start with https://")

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "microphone=(self), camera=(), geolocation=()"

    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"

    return response

# ------------------ API KEYS ------------------

validate_environment()

USDA_API_KEY = os.getenv("USDA_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# ------------------ CLIENTS ------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://voice-first-calorie-tracker-frontend.onrender.com",
        "http://localhost:3000",
        "https://voice-first-calorie-tracker-oipo.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

groq_client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

stt_client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

tavily = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None
templates = Jinja2Templates(directory="templates")

# ------------------ MODELS ------------------

class ProfileUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    daily_calorie_goal: int | None = Field(default=None, ge=100, le=10000)
    protein_goal_g: int | None = Field(default=None, ge=0, le=1000)
    carb_goal_g: int | None = Field(default=None, ge=0, le=2000)
    fat_goal_g: int | None = Field(default=None, ge=0, le=1000)
    model_config = {"extra": "forbid"}

class JournalEntryCreateRequest(BaseModel):
    food_name: str = Field(min_length=1, max_length=200)
    quantity: float = Field(default=1, gt=0, le=100)
    calories: float | None = Field(default=None, ge=0, le=5000)
    protein_g: float | None = Field(default=None, ge=0, le=1000)
    carbs_g: float | None = Field(default=None, ge=0, le=1000)
    fat_g: float | None = Field(default=None, ge=0, le=1000)
    model_config = {"extra": "forbid"}

class JournalEntryUpdateRequest(BaseModel):
    food_name: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: float | None = Field(default=None, gt=0, le=100)
    calories: float | None = Field(default=None, ge=0, le=5000)
    protein_g: float | None = Field(default=None, ge=0, le=1000)
    carbs_g: float | None = Field(default=None, ge=0, le=1000)
    fat_g: float | None = Field(default=None, ge=0, le=1000)
    model_config = {"extra": "forbid"}

class PersonalFoodCreateRequest(BaseModel):
    food_name: str = Field(min_length=1, max_length=200)
    calories: float = Field(default=0, ge=0, le=5000)
    protein: float = Field(default=0, ge=0, le=1000)
    carbs: float = Field(default=0, ge=0, le=1000)
    fat: float = Field(default=0, ge=0, le=1000)
    model_config = {"extra": "forbid"}

# ------------------ HELPER FUNCTIONS ------------------

def get_admin_supabase_or_503():
    if not supabase_admin:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database admin client is not configured.",
        )
    return supabase_admin

def _is_missing_table_error(exc: Exception) -> bool:
    lower_message = str(exc).lower()
    return (
        "pgrst205" in lower_message
        or "could not find the table" in lower_message
        or ("relation" in lower_message and "does not exist" in lower_message)
    )

def _translate_supabase_error(exc: Exception) -> HTTPException:
    message = str(exc)
    lower_message = message.lower()

    if "23503" in lower_message and "user_id_fkey" in lower_message:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User record prerequisite missing for journal writes.",
        )
    if "relation" in lower_message and "does not exist" in lower_message:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database schema is not initialized.",
        )
    if "invalid api key" in lower_message or "apikey" in lower_message:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase admin key is invalid.",
        )
    if "permission denied" in lower_message or "row-level security" in lower_message:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Database denied access. Verify RLS policies.",
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Supabase persistence error: {message}",
    )

def ensure_user_record(client, user: dict) -> None:
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session payload.")

    payload = {"id": user_id}
    email = user.get("email")
    if email:
        payload["email"] = email

    user_metadata = user.get("user_metadata") or {}
    display_name = user_metadata.get("full_name") or user_metadata.get("name")
    if display_name:
        payload["display_name"] = display_name

    try:
        client.table("users").upsert(payload, on_conflict="id").execute()
    except Exception as exc:
        translated = _translate_supabase_error(exc)
        logger.exception("Failed to ensure users row for authenticated user")
        raise translated

def apply_rate_limit(identifier: str, route_key: str, limit: int, window_seconds: int):
    now = time.time()
    bucket_key = f"{route_key}:{identifier}"

    with RATE_LIMIT_LOCK:
        timestamps = RATE_LIMIT_BUCKETS[bucket_key]
        RATE_LIMIT_BUCKETS[bucket_key] = [ts for ts in timestamps if now - ts < window_seconds]
        timestamps = RATE_LIMIT_BUCKETS[bucket_key]

        if len(timestamps) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Try again later.",
            )
        timestamps.append(now)

def validate_query(query: str) -> str:
    if not query or not query.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Query is required.")
    cleaned = query.strip()
    if len(cleaned) > MAX_QUERY_LENGTH:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Query too long.")
    return cleaned

async def get_current_user(authorization: str = Header(default="")) -> dict:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication is not configured.")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token.")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY},
            )
        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session.")
        
        data = response.json()
        if not data.get("id"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session payload.")
        return data
    except HTTPException:
        raise
    except Exception:
        logger.warning("Auth verification failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed.")

# ------------------ FOOD PARSER PROMPT ------------------

FOOD_PARSER_PROMPT = """
You are a HIGH-PRECISION food parser designed for nutrition tracking.
Convert natural language food descriptions into structured JSON.
Return ONLY valid JSON. NO explanations. NO extra text.

OUTPUT FORMATS (ONLY TWO ALLOWED):

1. MULTIPLE DISTINCT FOODS:
[
    {"food": "egg", "quantity": 2},
    {"food": "milk", "quantity": 1, "unit": "cup"},
    {"food": "maggi noodles", "quantity": 1, "brand": "Maggi", "intent": "branded_product"}
]

2. SINGLE DISH:
{"dish": "chicken alfredo pasta with mushrooms"}

CORE PRINCIPLE: Decide whether input represents ONE dish or MULTIPLE foods.

WHEN TO RETURN MULTIPLE FOODS:
1. Different food categories (solid + drink)
2. Multiple main items (eggs + bacon + toast)
3. Items that could be ordered separately
4. Explicit quantities on different items
5. Time separation ("later", "after", "then")

WHEN TO RETURN A SINGLE DISH:
1. One combined food: "chicken alfredo pasta with mushrooms"
2. "with" describes ingredients or sides of same plate
3. "burger with fries" -> SINGLE DISH

BRANDED PRODUCT RULES:
- Preserve brand/product identity
- Add "brand" and "intent": "branded_product" when applicable
- Treat short brand-like queries as packaged products

PARSING RULES:
- Convert number words to numbers
- "a/an" -> 1
- Only apply quantities to individual foods
- Include units only if explicitly stated
- Simplify: "scrambled eggs" -> "egg"

Return ONLY valid JSON. NO explanations.
"""

# ------------------ ROUTES ------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "front_end.html", {"request": request})

@app.get("/foods/search", response_class=HTMLResponse)
async def usda_api(request: Request, query: str):
    query = clean_voice_input(validate_query(query))
    foods = await extract_foods_with_ai(query)
    return await process_foods(request, foods)

@app.get("/api/foods/search")
async def usda_api_json(
    request: Request,
    query: str,
    user: dict = Depends(get_current_user),
):
    query = clean_voice_input(validate_query(query))
    apply_rate_limit(user["id"], "foods_search", limit=60, window_seconds=60)
    if request.client and request.client.host:
        apply_rate_limit(request.client.host, "foods_search_ip", limit=90, window_seconds=60)

    foods = await extract_foods_with_ai(query)
    results, totals = await compute_results_and_totals(foods, user_id=user["id"])
    return {"query": query, "results": results, "totals": totals}

@app.get("/api/me")
async def me(user: dict = Depends(get_current_user)):
    return {"id": user.get("id"), "email": user.get("email"), "role": user.get("role")}

@app.get("/api/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    client = get_admin_supabase_or_503()
    user_id = user["id"]

    try:
        response = (
            client.table("profiles")
            .select("user_id, full_name, daily_calorie_goal, protein_goal_g, carb_goal_g, fat_goal_g, updated_at")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if rows:
            return rows[0]

        return {
            "user_id": user_id,
            "full_name": user.get("user_metadata", {}).get("full_name"),
            "daily_calorie_goal": 2300,
            "protein_goal_g": 180,
            "carb_goal_g": 220,
            "fat_goal_g": 70,
            "updated_at": None,
        }
    except Exception as exc:
        if _is_missing_table_error(exc):
            try:
                users_response = (
                    client.table("users")
                    .select("id, email, display_name, daily_calorie_goal, created_at, updated_at")
                    .eq("id", user_id)
                    .limit(1)
                    .execute()
                )
                users_rows = users_response.data or []
                if users_rows:
                    row = users_rows[0]
                    return {
                        "user_id": row.get("id"),
                        "full_name": row.get("display_name"),
                        "daily_calorie_goal": row.get("daily_calorie_goal") or 2300,
                        "protein_goal_g": 180,
                        "carb_goal_g": 220,
                        "fat_goal_g": 70,
                        "updated_at": row.get("updated_at"),
                    }
                return {
                    "user_id": user_id,
                    "full_name": user.get("user_metadata", {}).get("full_name"),
                    "daily_calorie_goal": 2300,
                    "protein_goal_g": 180,
                    "carb_goal_g": 220,
                    "fat_goal_g": 70,
                    "updated_at": None,
                }
            except Exception as users_exc:
                translated = _translate_supabase_error(users_exc)
                logger.exception("Failed to fetch profile from users fallback")
                raise translated
        translated = _translate_supabase_error(exc)
        logger.exception("Failed to fetch profile")
        raise translated

@app.put("/api/profile")
async def update_profile(payload: ProfileUpdateRequest, user: dict = Depends(get_current_user)):
    client = get_admin_supabase_or_503()
    user_id = user["id"]
    profile_payload = {"user_id": user_id}
    updates = payload.model_dump(exclude_none=True)
    profile_payload.update(updates)

    try:
        response = client.table("profiles").upsert(profile_payload, on_conflict="user_id").execute()
        rows = response.data or []
        return rows[0] if rows else profile_payload
    except Exception as exc:
        if _is_missing_table_error(exc):
            users_payload = {"id": user_id}
            email = user.get("email")
            if email:
                users_payload["email"] = email
            if "full_name" in updates:
                users_payload["display_name"] = updates["full_name"]
            if "daily_calorie_goal" in updates:
                users_payload["daily_calorie_goal"] = updates["daily_calorie_goal"]
            try:
                users_response = client.table("users").upsert(users_payload, on_conflict="id").execute()
                users_rows = users_response.data or []
                row = users_rows[0] if users_rows else users_payload
                return {
                    "user_id": row.get("id", user_id),
                    "full_name": row.get("display_name"),
                    "daily_calorie_goal": row.get("daily_calorie_goal") or 2300,
                    "protein_goal_g": 180,
                    "carb_goal_g": 220,
                    "fat_goal_g": 70,
                    "updated_at": row.get("updated_at"),
                }
            except Exception as users_exc:
                translated = _translate_supabase_error(users_exc)
                logger.exception("Failed to update profile in users fallback")
                raise translated
        translated = _translate_supabase_error(exc)
        logger.exception("Failed to update profile")
        raise translated

@app.get("/api/journal/entries")
async def list_journal_entries(user: dict = Depends(get_current_user), limit: int = 50):
    client = get_admin_supabase_or_503()
    user_id = user["id"]
    safe_limit = max(1, min(limit, 200))

    try:
        response = (
            client.table("daily_logs")
            .select("id, user_id, food_name, calories, protein, carbs, fat, logged_at, created_at")
            .eq("user_id", user_id)
            .order("logged_at", desc=True)
            .limit(safe_limit)
            .execute()
        )
        mapped_entries = []
        for row in response.data or []:
            if is_test_food_name(row.get("food_name")):
                continue
            mapped_entries.append({
                "id": row.get("id"),
                "user_id": row.get("user_id"),
                "food_name": row.get("food_name"),
                "quantity": 1,
                "calories": row.get("calories"),
                "protein_g": row.get("protein"),
                "carbs_g": row.get("carbs"),
                "fat_g": row.get("fat"),
                "logged_at": row.get("logged_at"),
                "created_at": row.get("created_at"),
            })
        return {"entries": mapped_entries}
    except Exception as exc:
        translated = _translate_supabase_error(exc)
        logger.exception("Failed to list journal entries")
        raise translated

@app.post("/api/journal/entries")
async def create_journal_entry(payload: JournalEntryCreateRequest, user: dict = Depends(get_current_user)):
    client = get_admin_supabase_or_503()
    user_id = user["id"]
    ensure_user_record(client, user)

    insert_payload = {
        "user_id": user_id,
        "food_name": payload.food_name,
        "calories": payload.calories if payload.calories is not None else 0,
        "protein": payload.protein_g if payload.protein_g is not None else 0,
        "carbs": payload.carbs_g if payload.carbs_g is not None else 0,
        "fat": payload.fat_g if payload.fat_g is not None else 0,
    }

    try:
        response = client.table("daily_logs").insert(insert_payload).execute()
        rows = response.data or []
        row = rows[0] if rows else insert_payload
        return {
            "id": row.get("id"),
            "user_id": row.get("user_id", user_id),
            "food_name": row.get("food_name", payload.food_name),
            "quantity": payload.quantity,
            "calories": row.get("calories"),
            "protein_g": row.get("protein"),
            "carbs_g": row.get("carbs"),
            "fat_g": row.get("fat"),
            "logged_at": row.get("logged_at"),
            "created_at": row.get("created_at"),
        }
    except Exception as exc:
        translated = _translate_supabase_error(exc)
        logger.exception("Failed to create journal entry")
        raise translated

@app.post("/api/personal-foods")
async def create_personal_food(payload: PersonalFoodCreateRequest, user: dict = Depends(get_current_user)):
    client = get_admin_supabase_or_503()
    user_id = user["id"]
    ensure_user_record(client, user)

    personal_food_payload = {
        "user_id": user_id,
        "food_name": payload.food_name,
        "calories": payload.calories,
        "protein": payload.protein,
        "carbs": payload.carbs,
        "fat": payload.fat,
        "source": "manual",
    }

    try:
        response = client.table("personal_foods").insert(personal_food_payload).execute()
        rows = response.data or []
        return rows[0] if rows else personal_food_payload
    except Exception as exc:
        translated = _translate_supabase_error(exc)
        logger.exception("Failed to create personal food")
        raise translated

@app.put("/api/journal/entries/{entry_id}")
async def update_journal_entry(entry_id: UUID, payload: JournalEntryUpdateRequest, user: dict = Depends(get_current_user)):
    client = get_admin_supabase_or_503()
    user_id = user["id"]
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="At least one field is required.")

    daily_log_updates = {}
    if "food_name" in updates:
        daily_log_updates["food_name"] = updates["food_name"]
    if "calories" in updates:
        daily_log_updates["calories"] = updates["calories"]
    if "protein_g" in updates:
        daily_log_updates["protein"] = updates["protein_g"]
    if "carbs_g" in updates:
        daily_log_updates["carbs"] = updates["carbs_g"]
    if "fat_g" in updates:
        daily_log_updates["fat"] = updates["fat_g"]

    if not daily_log_updates:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Only food name and macro updates are supported.")

    try:
        response = (
            client.table("daily_logs")
            .update(daily_log_updates)
            .eq("id", str(entry_id))
            .eq("user_id", user_id)
            .execute()
        )
        rows = response.data or []
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journal entry not found.")
        row = rows[0]
        return {
            "id": row.get("id"),
            "user_id": row.get("user_id", user_id),
            "food_name": row.get("food_name"),
            "quantity": 1,
            "calories": row.get("calories"),
            "protein_g": row.get("protein"),
            "carbs_g": row.get("carbs"),
            "fat_g": row.get("fat"),
            "logged_at": row.get("logged_at"),
            "created_at": row.get("created_at"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        translated = _translate_supabase_error(exc)
        logger.exception("Failed to update journal entry")
        raise translated

@app.delete("/api/journal/entries/{entry_id}")
async def delete_journal_entry(entry_id: UUID, user: dict = Depends(get_current_user)):
    client = get_admin_supabase_or_503()
    user_id = user["id"]

    try:
        response = (
            client.table("daily_logs")
            .delete()
            .eq("id", str(entry_id))
            .eq("user_id", user_id)
            .execute()
        )
        rows = response.data or []
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journal entry not found.")
        return {"deleted": True, "id": str(entry_id)}
    except HTTPException:
        raise
    except Exception as exc:
        translated = _translate_supabase_error(exc)
        logger.exception("Failed to delete journal entry")
        raise translated

@app.get("/api/journal/day")
async def get_journal_day(journal_date: date | None = None, user: dict = Depends(get_current_user)):
    return get_journal(user["id"], journal_date)

@app.get("/api/journal/summary")
async def get_journal_summary_range(start_date: date, end_date: date, user: dict = Depends(get_current_user)):
    if start_date > end_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="start_date must be on or before end_date.")
    return get_journal_summary(user["id"], start_date, end_date)

@app.get("/api/journal/chart")
async def get_journal_chart(start_date: date, end_date: date, user: dict = Depends(get_current_user)):
    if start_date > end_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="start_date must be on or before end_date.")
    return get_chart_data(user["id"], start_date, end_date)

@app.post("/voice")
async def voice_input(request: Request, file: UploadFile = File(...)):
    transcript = await transcribe_audio(file)
    if not transcript:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Transcription failed.")
    
    cleaned_query = clean_voice_input(normalize_transcript(transcript))
    foods = await extract_foods_with_ai(cleaned_query)
    return await process_foods(request, foods, transcript=transcript)

@app.post("/api/voice")
async def voice_input_json(request: Request, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    apply_rate_limit(user["id"], "voice", limit=20, window_seconds=60)
    if request.client and request.client.host:
        apply_rate_limit(request.client.host, "voice_ip", limit=35, window_seconds=60)

    transcript = await transcribe_audio(file)
    if not transcript:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Transcription failed.")

    try:
        cleaned_query = clean_voice_input(normalize_transcript(transcript))
        foods = await extract_foods_with_ai(cleaned_query)
        results, totals = await compute_results_and_totals(foods, user_id=user["id"])
    except HTTPException:
        raise
    except Exception:
        logger.exception("Voice processing pipeline failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Voice processing failed.")

    return {"transcript": transcript, "results": results, "totals": totals}

# ------------------ CLEAN INPUT ------------------

def clean_voice_input(query: str):
    query = query.lower()
    fillers = ["i ate", "i had", "i just ate", "for breakfast", "for lunch", "for dinner"]
    for f in fillers:
        query = query.replace(f, "")
    return query.strip()

def normalize_transcript(text: str):
    return re.sub(r"[^\w\s]", "", text.lower()).strip()

# ------------------ WHISPER ------------------

async def transcribe_audio(file):
    if file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported audio type.")

    try:
        audio_bytes = await file.read()
        if not audio_bytes:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Uploaded file is empty.")
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"Audio file too large.")
        
        filename = file.filename or "audio.webm"
        content_type = file.content_type or "application/octet-stream"
        response = stt_client.audio.transcriptions.create(
            file=("audio.wav", audio_bytes),
            model="whisper-large-v3-turbo"
        )
        return response.text
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Whisper transcription failed: %s", type(e).__name__)
        return None

# ------------------ ENHANCED NUTRITION AGENT ------------------

def safe_groq_call(user_prompt: str, system_prompt: str, max_retries: int = 2):
    """Make Groq API call with retry logic"""
    for attempt in range(max_retries):
        try:
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0,
                max_tokens=400
            )
            return response.choices[0].message.content
        except Exception as e:
            if attempt == max_retries - 1:
                logger.warning("Groq call failed after %d attempts: %s", max_retries, type(e).__name__)
                return None
            time.sleep(0.5 * (attempt + 1))  # Exponential backoff
    return None

def extract_json(text):
    """Extract JSON from text, handling various formats"""
    if not text:
        return None
    try:
        return json.loads(text)
    except:
        try:
            match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
        except:
            return None
    return None

def validate_nutrition_data(data: Dict[str, Any]) -> bool:
    """Validate extracted nutrition data is within reasonable bounds"""
    if not data:
        return False
    
    calories = data.get("calories", 0)
    protein = data.get("protein_g", 0)
    carbs = data.get("carbs_g", 0)
    fat = data.get("fat_g", 0)
    
    # Reasonable bounds check
    if not (0 <= calories <= 5000):
        return False
    if not (0 <= protein <= 1000):
        return False
    if not (0 <= carbs <= 1000):
        return False
    if not (0 <= fat <= 1000):
        return False
    
    return True

def classify_food_type(food_name: str) -> Dict[str, Any]:
    """Classify food to improve search queries"""
    food_lower = food_name.lower()
    
    # Branded restaurants
    restaurant_brands = [
        "chipotle", "starbucks", "mcdonald", "wendy", "burger king",
        "taco bell", "kfc", "subway", "panera", "dunkin",
        "chick-fil-a", "in-n-out", "five guys", "panda express", "olive garden"
    ]
    
    # Packaged brands
    packaged_brands = [
        "maggi", "oreo", "coke", "pepsi", "lays", "kitkat",
        "kellogg", "nestle", "nutella", "doritos", "pringles", "snickers"
    ]
    
    is_restaurant = any(brand in food_lower for brand in restaurant_brands)
    is_packaged = any(brand in food_lower for brand in packaged_brands)
    
    return {
        "is_restaurant": is_restaurant,
        "is_packaged": is_packaged,
        "is_branded": is_restaurant or is_packaged,
        "food_lower": food_lower
    }

def construct_tavily_query(food_name: str, classification: Dict) -> str:
    """Build optimized query based on food type"""
    if classification["is_restaurant"]:
        return f"{food_name} official nutrition facts calories protein carbs fat menu"
    elif classification["is_packaged"]:
        return f"{food_name} nutrition label facts calories per serving"
    else:
        return f"{food_name} nutrition facts calories protein carbs fat serving size"

async def fetch_with_tavily(food_name: str) -> Optional[Dict]:
    """Enhanced Tavily search with better querying and validation"""
    if not tavily:
        logger.warning("Tavily client not configured")
        return None
    
    # Check cache first
    cache_key = f"tavily:{food_name.lower().strip()}"
    cached_result = nutrition_cache.get(cache_key)
    if cached_result:
        logger.info(f"Cache hit for Tavily: {food_name}")
        return cached_result

    try:
        classification = classify_food_type(food_name)
        search_query = construct_tavily_query(food_name, classification)
        
        logger.info(f"Tavily search: {search_query}")
        
        # Use timeout wrapper
        search_result = await asyncio.wait_for(
            asyncio.to_thread(
                tavily.search,
                query=search_query,
                search_depth="advanced",
                max_results=5
            ),
            timeout=10.0
        )
        
        if not search_result or not search_result.get("results"):
            logger.info(f"No Tavily results for {food_name}")
            return None
        
        # Extract and combine content from results
        search_content = "\n".join([
            f"Source: {r.get('title', 'Unknown')}\nContent: {r.get('content', '')[:500]}"
            for r in search_result.get("results", [])[:3]
        ])
        
        extraction_prompt = f"""
You are a nutrition data extractor. Extract nutrition information for "{food_name}" from these search results.

IMPORTANT CONTEXT:
- Food type: {'Restaurant item' if classification['is_restaurant'] else 'Packaged product' if classification['is_packaged'] else 'Generic food'}
- Look for OFFICIAL nutrition data from reliable sources
- For restaurants, use their official nutrition PDFs/pages
- For packaged foods, use the nutrition label data

Return ONLY JSON in this exact format (use 0 for missing values):
{{
    "calories": number,
    "protein_g": number,
    "carbs_g": number,
    "fat_g": number,
    "sugar_g": number,
    "fiber_g": number,
    "confidence": "high" | "medium" | "low",
    "source_url": "string or null"
}}

Search results:
{search_content}

Guidelines:
- Calories should be per serving as listed in the source
- If multiple values found, use the most specific to the brand/restaurant
- Set confidence based on consistency of sources
- HIGH confidence: official restaurant/supplement facts
- MEDIUM: multiple sources agree
- LOW: single source or estimates

ONLY RETURN VALID JSON. NO OTHER TEXT.
"""
        
        result_text = safe_groq_call(extraction_prompt, "You are a precise nutrition data extractor.")
        
        if not result_text:
            return None
        
        nutrition_data = extract_json(result_text)
        
        if nutrition_data and validate_nutrition_data(nutrition_data):
            result = {
                "calories": nutrition_data.get("calories", 0),
                "protein_g": nutrition_data.get("protein_g", 0),
                "carbs_g": nutrition_data.get("carbs_g", 0),
                "fat_g": nutrition_data.get("fat_g", 0),
                "sugar_g": nutrition_data.get("sugar_g", 0),
                "fiber_g": nutrition_data.get("fiber_g", 0),
                "confidence": nutrition_data.get("confidence", "low"),
                "source": "Tavily",
            }
            
            # Cache the result
            nutrition_cache.set(cache_key, result)
            return result
        
        return None
        
    except asyncio.TimeoutError:
        logger.error(f"Tavily search timeout for {food_name}")
        return None
    except Exception as e:
        logger.error(f"Tavily fetch failed for {food_name}: {str(e)}")
        return None

async def fetch_usda(food_name: str) -> Optional[Dict]:
    """Fetch nutrition data from USDA with caching"""
    cache_key = f"usda:{food_name.lower().strip()}"
    cached_result = nutrition_cache.get(cache_key)
    if cached_result:
        logger.info(f"Cache hit for USDA: {food_name}")
        return cached_result
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://api.nal.usda.gov/fdc/v1/foods/search",
                params={"api_key": USDA_API_KEY},
                json={"query": food_name, "pageSize": 10, "requireAllWords": False}
            )

            if response.status_code != 200:
                return None

            foods = response.json().get("foods", [])
            if not foods:
                return None

            selected = select_usda_candidate(food_name, foods)
            if not selected:
                return None

            lookup = {
                "Energy": "calories",
                "Protein": "protein_g",
                "Carbohydrate, by difference": "carbs_g",
                "Total lipid (fat)": "fat_g",
                "Sugars, total including NLEA": "sugar_g",
                "Fiber, total dietary": "fiber_g",
                "Vitamin D (D2 + D3), International Units": "vitamin_d_mcg"
            }

            nutrition = {v: 0 for v in lookup.values()}
            nutrition["food_description"] = selected.get("description", "")

            for n in selected.get("foodNutrients", []):
                if n.get("nutrientName") in lookup:
                    nutrition[lookup[n["nutrientName"]]] = n.get("value", 0)

            # Normalize portion sizes for known foods
            nutrition = normalize_portion_size(food_name, nutrition)
            
            # Cache the result
            nutrition_cache.set(cache_key, nutrition)
            return nutrition
            
    except Exception as e:
        logger.error(f"USDA fetch failed for {food_name}: {str(e)}")
        return None

def normalize_portion_size(food_name: str, nutrition: dict) -> dict:
    """Normalize nutrition values to typical serving sizes"""
    if not nutrition:
        return nutrition
    
    food_lower = food_name.lower()
    
    # Special case for eggs - USDA often returns per 100g instead of per egg
    if "egg" in food_lower.split():
        logger.info(f"Forcing correct egg nutrition for '{food_name}'")
        return {
            "calories": 72.0,
            "protein_g": 6.3,
            "carbs_g": 0.5,
            "fat_g": 4.8,
            "sugar_g": 0.2,
            "fiber_g": 0,
            "vitamin_d_mcg": 1.0,
            "food_description": "Egg, whole, large",
        }
    
    # Define typical portion sizes (grams per typical serving)
    portion_rules = [
        (["chicken breast"], 150),
        (["chicken thigh"], 120),
        (["steak"], 150),
        (["burger patty"], 113),
        (["toast", "slice of bread"], 35),
        (["apple"], 150),
        (["banana"], 120),
        (["orange"], 130),
        (["carrot"], 61),
        (["broccoli"], 85),
        (["cheese slice"], 20),
        (["yogurt"], 150),
        (["rice cooked"], 150),
        (["pasta cooked"], 150),
    ]
    
    for keywords, grams_per_serving in portion_rules:
        if any(keyword in food_lower for keyword in keywords):
            multiplier = grams_per_serving / 100
            adjusted_nutrition = {}
            for key, value in nutrition.items():
                if isinstance(value, (int, float)) and key not in ["food_description"]:
                    adjusted_nutrition[key] = round(value * multiplier, 2)
                else:
                    adjusted_nutrition[key] = value
            logger.info(f"Normalized '{food_name}': multiplier {multiplier:.2f}")
            return adjusted_nutrition
    
    return nutrition

async def fetch_personal_food(user_id: str, food_name: str) -> Optional[Dict]:
    """Fetch personal food entry from database"""
    client = get_admin_supabase_or_503()
    
    try:
        response = (
            client.table("personal_foods")
            .select("food_name, calories, protein, carbs, fat")
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as exc:
        translated = _translate_supabase_error(exc)
        logger.exception("Failed to search personal foods")
        raise translated

    best_match = None
    best_score = 0
    for row in response.data or []:
        score = _personal_food_match_score(food_name, row.get("food_name", ""))
        if score > best_score:
            best_score = score
            best_match = row

    if not best_match:
        return None

    return {
        "food": best_match.get("food_name", food_name),
        "nutrition": {
            "calories": best_match.get("calories", 0) or 0,
            "protein_g": best_match.get("protein", 0) or 0,
            "carbs_g": best_match.get("carbs", 0) or 0,
            "fat_g": best_match.get("fat", 0) or 0,
            "sugar_g": 0,
            "fiber_g": 0,
            "vitamin_d_mcg": 0,
        },
        "source": "personal",
    }

def _personal_food_match_score(query: str, food_name: str) -> int:
    """Calculate match score between query and personal food name"""
    normalized_query = normalize_food_text(query)
    normalized_food_name = normalize_food_text(food_name)
    
    if not normalized_query or not normalized_food_name:
        return 0
    
    if normalized_query == normalized_food_name:
        return 1000
    
    if normalized_food_name in normalized_query:
        return 900 + len(normalized_food_name)
    
    query_tokens = set(normalized_query.split())
    food_tokens = set(normalized_food_name.split())
    if food_tokens and food_tokens.issubset(query_tokens):
        return 700 + len(normalized_food_name)
    
    return 0

def normalize_food_text(text: str) -> str:
    """Normalize food text for comparison"""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()

def select_usda_candidate(query: str, foods: list) -> dict:
    """Select best USDA candidate based on scoring"""
    scored = sorted(
        ((score_usda_candidate(query, food), food) for food in foods),
        key=lambda item: item[0],
        reverse=True,
    )
    
    if not scored:
        return {}
    
    if len(scored) == 1:
        return scored[0][1]
    
    best_score, best_candidate = scored[0]
    second_score, _ = scored[1]
    
    # If close scores and brand-like query, use AI to decide
    if is_brand_like_query(query) and best_score - second_score <= 8:
        ai_choice = select_usda_candidate_with_ai(query, [candidate for _, candidate in scored[:5]])
        if ai_choice is not None and 0 <= ai_choice < min(len(scored), 5):
            return scored[ai_choice][1]
    
    return best_candidate

def score_usda_candidate(query: str, candidate: dict) -> float:
    """Score USDA candidate based on relevance"""
    normalized_query = normalize_food_text(query)
    query_tokens = [token for token in normalized_query.split() if token]
    candidate_tokens = set(normalize_food_text(candidate.get("description", "")).split())
    
    score = 0.0
    
    if normalized_query and normalized_query == normalize_food_text(candidate.get("description", "")):
        score += 120
    
    for token in query_tokens:
        if token in candidate_tokens:
            score += 12
    
    if candidate.get("dataType") == "Branded":
        score += 18
    
    if candidate.get("brandOwner"):
        if any(token in normalize_food_text(candidate.get("brandOwner", "")) for token in query_tokens):
            score += 25
    
    if is_brand_like_query(query):
        if candidate.get("dataType") == "Branded":
            score += 12
        else:
            score -= 12
    
    return score

def is_brand_like_query(query: str) -> bool:
    """Check if query appears to be a branded product"""
    normalized = normalize_food_text(query)
    tokens = [token for token in normalized.split() if token]
    if not tokens:
        return False
    
    brand_terms = {
        "maggi", "oreo", "coke", "pepsi", "lays", "kitkat",
        "kelloggs", "kellogg", "nestle", "nutella", "doritos",
        "pringles", "fanta", "sprite", "snickers", "twix"
    }
    
    return len(tokens) <= 3 or any(token in brand_terms for token in tokens)

def select_usda_candidate_with_ai(query: str, foods: list) -> Optional[int]:
    """Use AI to select best USDA candidate"""
    payload = []
    for index, food in enumerate(foods):
        payload.append({
            "index": index,
            "description": food.get("description"),
            "brandOwner": food.get("brandOwner"),
            "brandName": food.get("brandName"),
            "dataType": food.get("dataType"),
            "foodCategory": food.get("foodCategory"),
        })
    
    prompt = (
        "Choose the single best USDA food candidate for the user's intended food. "
        "Prefer the packaged product the user most likely means, not a loose ingredient or condiment. "
        "Return only JSON: {\"selected_index\": number}.\n\n"
        f"User query: {query}\n"
        f"Candidates: {json.dumps(payload, ensure_ascii=False)}"
    )
    
    text = safe_groq_call(prompt, "You are a strict food resolver that returns only JSON.")
    data = extract_json(text) if text else None
    if isinstance(data, dict) and isinstance(data.get("selected_index"), int):
        return data["selected_index"]
    
    return None

# ------------------ ENHANCED AGENT LOOP ------------------

async def fetch_nutrition_agent(food_name: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    TRUE MULTI-STEP AGENT LOOP:
    1. Check personal foods first (if user_id provided)
    2. Try USDA
    3. Evaluate USDA quality
    4. Try Tavily if USDA insufficient
    5. Compare results
    6. Fallback if needed
    """
    
    state = {
        "food": food_name,
        "personal_food": None,
        "usda": None,
        "tavily": None,
        "best_result": None,
        "attempts": 0,
    }
    
    # Step 1: Check personal foods first (fastest, most personalized)
    if user_id:
        try:
            personal_food = await fetch_personal_food(user_id, food_name)
            if personal_food:
                state["personal_food"] = personal_food
                logger.info(f"[AGENT] Found personal food for '{food_name}'")
                return {
                    **personal_food["nutrition"],
                    "source": "personal",
                    "confidence": "high",
                }
        except Exception as e:
            logger.warning(f"Personal food lookup failed: {e}")
    
    # Step 2: Try USDA
    logger.info(f"[AGENT] Fetching USDA data for '{food_name}'")
    usda_data = await fetch_usda(food_name)
    if usda_data:
        usda_data = normalize_portion_size(food_name, usda_data)
        state["usda"] = usda_data
    
    # Step 3: Evaluate if USDA result is good enough
    if state["usda"] and is_usda_result_reliable(state["usda"], food_name):
        logger.info(f"[AGENT] USDA result reliable for '{food_name}'")
        return {
            **{k: v for k, v in state["usda"].items() if k not in ["food_description"]},
            "source": "USDA",
            "confidence": "high",
        }
    
    # Step 4: USDA insufficient or missing, try Tavily
    if tavily:
        logger.info(f"[AGENT] Trying Tavily for '{food_name}'")
        tavily_data = await fetch_with_tavily(food_name)
        if tavily_data:
            tavily_data = normalize_portion_size(food_name, tavily_data)
            state["tavily"] = tavily_data
            
            # If we have both USDA and Tavily, use agent to decide
            if state["usda"] and state["tavily"]:
                decision = agent_compare_results(food_name, state["usda"], state["tavily"])
                if decision == "tavily":
                    logger.info(f"[AGENT] Agent chose Tavily over USDA for '{food_name}'")
                    return {
                        **{k: v for k, v in state["tavily"].items() if k not in ["source", "confidence"]},
                        "source": "Tavily",
                        "confidence": state["tavily"].get("confidence", "medium"),
                    }
            
            # No USDA or agent chose USDA, but Tavily is valid
            if not state["usda"]:
                logger.info(f"[AGENT] Using Tavily result for '{food_name}'")
                return {
                    **{k: v for k, v in state["tavily"].items() if k not in ["source", "confidence"]},
                    "source": "Tavily",
                    "confidence": state["tavily"].get("confidence", "medium"),
                }
    
    # Step 5: Fallback - use whatever we have
    if state["usda"]:
        logger.info(f"[AGENT] Using USDA fallback for '{food_name}'")
        return {
            **{k: v for k, v in state["usda"].items() if k not in ["food_description"]},
            "source": "USDA (fallback)",
            "confidence": "low",
        }
    
    # Step 6: Complete fallback - no data available
    logger.info(f"[AGENT] No data available for '{food_name}'")
    return {
        "calories": 0,
        "protein_g": 0,
        "carbs_g": 0,
        "fat_g": 0,
        "sugar_g": 0,
        "fiber_g": 0,
        "source": "none",
        "confidence": "none",
    }

def agent_compare_results(food_name: str, usda_data: Dict, tavily_data: Dict) -> str:
    """Use AI to compare USDA and Tavily results and choose the best one"""
    prompt = f"""
Compare these two nutrition data sources for "{food_name}" and choose the more accurate one.

USDA Data:
{json.dumps(usda_data, indent=2)}

Tavily Data:
{json.dumps(tavily_data, indent=2)}

Consider:
1. Which source is more likely correct for this specific food?
2. Are the calorie counts realistic for a typical serving?
3. Does the macro split make sense for this food type?
4. For branded/restaurant foods, Tavily might have more specific data

Return ONLY JSON: {{"choice": "usda" | "tavily", "reason": "brief explanation"}}
"""
    
    text = safe_groq_call(prompt, "You are a nutrition data validation expert.")
    data = extract_json(text) if text else None
    
    if isinstance(data, dict) and data.get("choice") in ["usda", "tavily"]:
        return data["choice"]
    
    # Default to Tavily for branded foods, USDA for generic
    food_lower = food_name.lower()
    if any(brand in food_lower for brand in ["chipotle", "starbucks", "mcdonald", "burger king"]):
        return "tavily"
    return "usda"

def is_usda_result_reliable(nutrition: dict, query: str = "") -> bool:
    """Enhanced reliability check for USDA results"""
    if not nutrition:
        return False
    
    query_lower = query.lower()
    
    # Special cases for known problem foods
    if "egg" in query_lower.split():
        calories = nutrition.get("calories", 0)
        if calories > 100:
            logger.info(f"Egg with {calories} cal marked unreliable (should be ~72)")
            return False
    
    # Check for branded foods that USDA often gets wrong
    brand_patterns = [
        "chipotle", "starbucks", "mcdonald", "wendy", "burger king",
        "taco bell", "kfc", "subway", "panera", "dunkin",
    ]
    
    for brand in brand_patterns:
        if brand in query_lower:
            food_desc = str(nutrition.get("food_description", "")).lower()
            if brand not in food_desc:
                logger.info(f"Brand '{brand}' not in USDA result - unreliable")
                return False
    
    # Basic validation
    calories = nutrition.get("calories", 0)
    protein = nutrition.get("protein_g", 0)
    carbs = nutrition.get("carbs_g", 0)
    fat = nutrition.get("fat_g", 0)
    
    if not (0 < calories <= 5000):
        return False
    
    # Macros shouldn't exceed calories (rough check)
    macro_calories = (protein * 4) + (carbs * 4) + (fat * 9)
    if macro_calories > calories * 1.5:  # Allow 50% margin for fiber, etc.
        return False
    
    return True

# ------------------ FOOD EXTRACTION ------------------

async def extract_foods_with_ai(query: str) -> List[Dict]:
    """Extract food items from natural language query"""
    text = safe_groq_call(query, FOOD_PARSER_PROMPT)
    
    if not text:
        return [{"food": query, "quantity": 1}]
    
    data = extract_json(text)
    
    if isinstance(data, list):
        foods = validate_foods(data)
        if not foods:
            return [{"food": query, "quantity": 1}]
        return foods
    
    elif isinstance(data, dict) and "dish" in data:
        return [{"food": data["dish"], "quantity": estimate_portion(query)}]
    
    logger.warning("AI returned unexpected format: %s", text)
    return [{"food": query, "quantity": 1}]

def validate_foods(data: List) -> List[Dict]:
    """Validate and clean food items"""
    clean = []
    for item in data:
        try:
            clean_item = {
                "food": str(item["food"]).strip(),
                "quantity": float(item.get("quantity", 1)),
            }
            
            if clean_item["quantity"] <= 0:
                clean_item["quantity"] = 1
            
            for optional_key in ("brand", "intent", "unit"):
                if optional_key in item and item[optional_key]:
                    clean_item[optional_key] = item[optional_key]
            
            clean.append(clean_item)
        except:
            continue
    
    return clean

def estimate_portion(text: str) -> float:
    """Estimate portion size from text"""
    try:
        result = safe_groq_call(
            text,
            """Return ONLY JSON: {"quantity": number}
            Rules:
            - "a", "an" = 1
            - "one" = 1, "two" = 2, etc.
            - "half" = 0.5
            - If nothing specified -> 1"""
        )
        data = extract_json(result) if result else None
        return float(data.get("quantity", 1)) if data else 1
    except:
        return 1

# ------------------ PROCESS RESULTS ------------------

async def compute_results_and_totals(foods: List[Dict], user_id: Optional[str] = None) -> Tuple[List[Dict], Dict]:
    """Compute nutrition results and totals from food items"""
    results = []
    totals = {
        "calories": 0,
        "protein_g": 0,
        "carbs_g": 0,
        "fat_g": 0
    }
    
    for food in foods:
        food_item = food.get("food", "")
        quantity = float(food.get("quantity", 1))
        brand = food.get("brand")
        
        # Build search query with brand if available
        search_query = food_item
        if brand and brand.lower() not in normalize_food_text(food_item):
            search_query = f"{brand} {food_item}".strip()
        
        # Get nutrition data through agent
        nutrition_data = await fetch_nutrition_agent(search_query, user_id=user_id)
        
        # Extract nutrition values
        nutrition = {
            "calories": nutrition_data.get("calories", 0),
            "protein_g": nutrition_data.get("protein_g", 0),
            "carbs_g": nutrition_data.get("carbs_g", 0),
            "fat_g": nutrition_data.get("fat_g", 0),
            "sugar_g": nutrition_data.get("sugar_g", 0),
            "fiber_g": nutrition_data.get("fiber_g", 0),
            "vitamin_d_mcg": nutrition_data.get("vitamin_d_mcg", 0),
        }
        
        source = nutrition_data.get("source", "none")
        confidence = nutrition_data.get("confidence", "none")
        
        # Multiply by quantity
        for key in totals:
            val = nutrition.get(key, 0)
            if isinstance(val, (int, float)):
                totals[key] += val * quantity
        
        # Create result entry
        label = f"{quantity:g} x {food_item}" if quantity != 1 else food_item
        
        results.append({
            "food": label,
            "quantity": quantity,
            "source": source,
            "source_item": food_item,
            "confidence": confidence,
            **nutrition,
        })
    
    return results, totals

async def process_foods(request: Request, foods: List[Dict], transcript: Optional[str] = None):
    """Process foods and return results"""
    results, totals = await compute_results_and_totals(foods)
    payload = {"results": results, "totals": totals}
    if transcript is not None:
        payload["transcript"] = transcript
    return payload
