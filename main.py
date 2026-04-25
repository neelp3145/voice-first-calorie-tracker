from dotenv import load_dotenv
load_dotenv()

import os, httpx, json, re, logging, time
from datetime import date
from collections import defaultdict
from threading import Lock

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from tavily import TavilyClient
from openai import OpenAI
from supabase_client import supabase_admin

# --------------------------------------------------
# APP SETUP
# --------------------------------------------------

app = FastAPI()
logger = logging.getLogger("vocalorie.api")
logging.basicConfig(level=logging.INFO)

# --------------------------------------------------
# ENV VALIDATION
# --------------------------------------------------

REQUIRED_ENV = ["USDA_API_KEY", "GROQ_API_KEY", "SUPABASE_URL", "SUPABASE_ANON_KEY"]

for key in REQUIRED_ENV:
    if not os.getenv(key):
        raise RuntimeError(f"Missing env var: {key}")

USDA_API_KEY = os.getenv("USDA_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# --------------------------------------------------
# CLIENTS
# --------------------------------------------------

groq_client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
stt_client = groq_client
tavily = TavilyClient(api_key=TAVILY_API_KEY)

# --------------------------------------------------
# RATE LIMIT
# --------------------------------------------------

RATE_LIMIT_BUCKETS = defaultdict(list)
LOCK = Lock()

def rate_limit(key: str, limit=60, window=60):
    now = time.time()
    with LOCK:
        timestamps = [t for t in RATE_LIMIT_BUCKETS[key] if now - t < window]
        if len(timestamps) >= limit:
            raise HTTPException(429, "Too many requests")
        timestamps.append(now)
        RATE_LIMIT_BUCKETS[key] = timestamps

# --------------------------------------------------
# AUTH
# --------------------------------------------------

async def get_user(auth: str = Header(default="")):
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing token")

    token = auth.replace("Bearer ", "")

    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY}
        )

    if res.status_code != 200:
        raise HTTPException(401, "Invalid session")

    return res.json()

# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def normalize(text: str):
    return re.sub(r"[^\w\s]", "", text.lower()).strip()

def empty_nutrition():
    return {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}

def build_result(food, nutrition, source, extra=None):
    result = {
        "food": food["food"],
        "quantity": food.get("quantity", 1),
        "nutrition": nutrition,
        "source": source,
    }
    if extra:
        result.update(extra)
    return result

# --------------------------------------------------
# USDA
# --------------------------------------------------

async def fetch_usda(query: str):
    async with httpx.AsyncClient() as client:
        res = await client.post(
            "https://api.nal.usda.gov/fdc/v1/foods/search",
            params={"api_key": USDA_API_KEY},
            json={"query": query, "pageSize": 5}
        )

    if res.status_code != 200:
        return None

    foods = res.json().get("foods", [])
    if not foods:
        return None

    food = foods[0]

    nutrients = {
        "calories": 0,
        "protein_g": 0,
        "carbs_g": 0,
        "fat_g": 0
    }

    for n in food.get("foodNutrients", []):
        name = n.get("nutrientName")
        val = n.get("value", 0)
        if name == "Energy":
            nutrients["calories"] = val
        elif name == "Protein":
            nutrients["protein_g"] = val
        elif name == "Carbohydrate, by difference":
            nutrients["carbs_g"] = val
        elif name == "Total lipid (fat)":
            nutrients["fat_g"] = val

    return nutrients

# --------------------------------------------------
# AGENT MODE (WEB + AI)
# --------------------------------------------------

def should_activate_agent(query: str, usda: dict | None):
    if not usda:
        return True

    cal = usda.get("calories", 0)

    if cal <= 0:
        return True

    if len(query.split()) >= 3 and cal < 150:
        return True

    if any(x in query.lower() for x in ["chipotle", "bowl", "meal", "combo"]):
        return True

    return False


async def run_agent(query: str):
    try:
        search = tavily.search(query=f"{query} calories protein carbs fat", max_results=3)

        content = " ".join(r.get("content", "") for r in search.get("results", []))

        prompt = f"""
        Extract nutrition for "{query}".
        Return JSON:
        {{
          "calories": number,
          "protein_g": number,
          "carbs_g": number,
          "fat_g": number
        }}
        Content:
        {content[:2000]}
        """

        res = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )

        data = json.loads(res.choices[0].message.content)

        return {
            "nutrition": data,
            "confidence": "medium"
        }

    except Exception:
        return None

# --------------------------------------------------
# PERSONAL FOOD
# --------------------------------------------------

async def fetch_personal_food(user_id: str, query: str):
    if not supabase_admin:
        return None

    res = supabase_admin.table("personal_foods").select("*").eq("user_id", user_id).execute()

    for row in res.data or []:
        if normalize(query) in normalize(row["food_name"]):
            return {
                "nutrition": {
                    "calories": row["calories"],
                    "protein_g": row["protein"],
                    "carbs_g": row["carbs"],
                    "fat_g": row["fat"]
                }
            }

    return None

# --------------------------------------------------
# CORE RESOLVER
# --------------------------------------------------

async def resolve_food(food, user_id=None):
    query = food["food"]

    # 1. personal
    if user_id:
        personal = await fetch_personal_food(user_id, query)
        if personal:
            return build_result(food, personal["nutrition"], "personal")

    # 2. USDA
    usda = await fetch_usda(query)

    if not should_activate_agent(query, usda):
        return build_result(food, usda, "USDA")

    # 3. AGENT MODE
    logger.info(f"Agent triggered: {query}")

    agent = await run_agent(query)
    if agent:
        return build_result(food, agent["nutrition"], "agent", {
            "confidence": agent["confidence"]
        })

    # 4. fallback
    if usda:
        return build_result(food, usda, "USDA_fallback")

    return build_result(food, empty_nutrition(), "fallback")

# --------------------------------------------------
# PROCESSING
# --------------------------------------------------

async def process_foods(foods, user_id=None):
    results = []
    totals = {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}

    for food in foods:
        resolved = await resolve_food(food, user_id)
        nutrition = resolved["nutrition"]
        qty = food.get("quantity", 1)

        for k in totals:
            totals[k] += nutrition.get(k, 0) * qty

        results.append({
            "food": food["food"],
            "quantity": qty,
            "source": resolved["source"],
            **nutrition
        })

    return results, totals

# --------------------------------------------------
# ROUTE
# --------------------------------------------------

class Query(BaseModel):
    query: str

@app.post("/api/foods")
async def foods(q: Query, user=Depends(get_user)):
    rate_limit(user["id"])

    foods = [{"food": q.query, "quantity": 1}]
    results, totals = await process_foods(foods, user["id"])

    return {"results": results, "totals": totals}
