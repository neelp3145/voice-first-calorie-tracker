# Cleaned + Production-Ready FastAPI Backend

from dotenv import load_dotenv
load_dotenv()

import os
import httpx
import json
import re
import logging
import time
from datetime import date
from collections import defaultdict
from threading import Lock

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from openai import OpenAI
from tavily import TavilyClient
from supabase_client import supabase_admin
from journal import get_chart_data, get_journal, get_journal_summary

# ===================== APP SETUP =====================

app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vocalorie.api")

# ===================== ENV VALIDATION =====================

REQUIRED_ENV = [
    "USDA_API_KEY",
    "GROQ_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
]

for var in REQUIRED_ENV:
    if not os.getenv(var):
        raise RuntimeError(f"Missing env var: {var}")

USDA_API_KEY = os.getenv("USDA_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

# ===================== CLIENTS =====================

groq_client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

stt_client = groq_client

tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# ===================== RATE LIMIT =====================

RATE_LIMIT = defaultdict(list)
LOCK = Lock()

def rate_limit(key: str, limit=60, window=60):
    now = time.time()
    with LOCK:
        RATE_LIMIT[key] = [t for t in RATE_LIMIT[key] if now - t < window]
        if len(RATE_LIMIT[key]) >= limit:
            raise HTTPException(429, "Too many requests")
        RATE_LIMIT[key].append(now)

# ===================== AUTH =====================

async def get_current_user(auth: str = Header(default="")):
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing token")

    token = auth.split(" ")[1]

    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY}
        )

    if res.status_code != 200:
        raise HTTPException(401, "Invalid session")

    return res.json()

# ===================== MODELS =====================

class FoodQuery(BaseModel):
    query: str = Field(min_length=1, max_length=200)

# ===================== HELPERS =====================

def clean_text(text: str):
    return re.sub(r"[^a-zA-Z0-9 ]", "", text.lower()).strip()


def safe_groq(prompt: str, system: str):
    try:
        res = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        return res.choices[0].message.content
    except Exception:
        logger.exception("Groq failed")
        return None

# ===================== AI FOOD PARSING =====================

FOOD_PROMPT = "Return JSON list of foods with quantity."

async def extract_foods(query: str):
    res = safe_groq(query, FOOD_PROMPT)
    try:
        data = json.loads(res)
        return data if isinstance(data, list) else [{"food": query, "quantity": 1}]
    except:
        return [{"food": query, "quantity": 1}]

# ===================== USDA =====================

async def fetch_usda(food: str):
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.post(
            "https://api.nal.usda.gov/fdc/v1/foods/search",
            params={"api_key": USDA_API_KEY},
            json={"query": food, "pageSize": 1}
        )

    if res.status_code != 200:
        return {}

    foods = res.json().get("foods", [])
    if not foods:
        return {}

    nutrients = {}
    for n in foods[0].get("foodNutrients", []):
        name = n.get("nutrientName")
        val = n.get("value")

        if name == "Energy": nutrients["calories"] = val
        if name == "Protein": nutrients["protein_g"] = val
        if name == "Carbohydrate, by difference": nutrients["carbs_g"] = val
        if name == "Total lipid (fat)": nutrients["fat_g"] = val

    return nutrients

# ===================== PIPELINE =====================

async def process_foods(foods):
    results = []
    totals = {"calories":0,"protein_g":0,"carbs_g":0,"fat_g":0}

    for f in foods:
        nutrition = await fetch_usda(f["food"])

        for k in totals:
            if isinstance(nutrition.get(k), (int,float)):
                totals[k] += nutrition[k] * f.get("quantity",1)

        results.append({
            "food": f["food"],
            "quantity": f.get("quantity",1),
            "nutrition": nutrition
        })

    return results, totals

# ===================== ROUTES =====================

@app.get("/api/me")
async def me(user=Depends(get_current_user)):
    return {"id": user.get("id"), "email": user.get("email")}

@app.get("/api/foods/search")
async def search_food(query: str, user=Depends(get_current_user)):
    rate_limit(user["id"], 60)

    query = clean_text(query)
    foods = await extract_foods(query)
    results, totals = await process_foods(foods)

    return {"query": query, "results": results, "totals": totals}

@app.post("/api/voice")
async def voice(file: UploadFile = File(...), user=Depends(get_current_user)):
    audio = await file.read()

    res = stt_client.audio.transcriptions.create(
        file=("audio.wav", audio),
        model="whisper-large-v3-turbo"
    )

    text = clean_text(res.text)
    foods = await extract_foods(text)
    results, totals = await process_foods(foods)

    return {"transcript": text, "results": results, "totals": totals}

# ===================== JOURNAL =====================

@app.get("/api/journal/day")
async def journal_day(user=Depends(get_current_user), d: date | None = None):
    return get_journal(user["id"], d)

@app.get("/api/journal/summary")
async def journal_summary(user=Depends(get_current_user), start: date=None, end: date=None):
    return get_journal_summary(user["id"], start, end)

@app.get("/api/journal/chart")
async def journal_chart(user=Depends(get_current_user), start: date=None, end: date=None):
    return get_chart_data(user["id"], start, end)
