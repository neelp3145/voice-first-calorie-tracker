from dotenv import load_dotenv
load_dotenv()

import os
import httpx
import json
import re

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from tavily import TavilyClient
from openai import OpenAI

app = FastAPI()

# ------------------ API KEYS ------------------

USDA_API_KEY = os.getenv("USDA_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

if not USDA_API_KEY:
    raise RuntimeError("USDA_API_KEY not set")

# ------------------ CLIENTS ------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000"
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

tavily = TavilyClient(api_key=TAVILY_API_KEY)
templates = Jinja2Templates(directory="templates")

# ------------------ FOOD PARSER PROMPT ------------------

FOOD_PARSER_PROMPT = """
You are a HIGH-PRECISION food parser designed for nutrition tracking.

Your job is to convert natural language food descriptions into structured JSON.

You MUST return ONLY valid JSON.
NO explanations. NO extra text.

-----------------------------------
OUTPUT FORMATS (ONLY TWO ALLOWED)
-----------------------------------

1. MULTIPLE DISTINCT FOODS:
[
  {"food": "egg", "quantity": 2},
  {"food": "milk", "quantity": 1, "unit": "cup"}
]

2. SINGLE DISH:
{
  "dish": "chicken alfredo pasta with mushrooms"
}

-----------------------------------
CORE PRINCIPLE
-----------------------------------

You must decide whether the input represents:

- ONE dish → return a single "dish"
- MULTIPLE foods → return a list

DO NOT default to a single dish blindly.
Use reasoning based on food structure.

-----------------------------------
MEAL vs DISH (CRITICAL)
-----------------------------------

A DISH = one prepared food item  
A MEAL = multiple distinct food items eaten together

You MUST return MULTIPLE foods when the input contains clearly separate items.

-----------------------------------
WHEN TO RETURN MULTIPLE FOODS
-----------------------------------

Return a LIST if ANY of the following are true:

1. DIFFERENT FOOD CATEGORIES:
   - Solid food + drink (e.g., pasta + coke)
   - Main + sandwich (e.g., pasta + grilled cheese)
   - Meal + beverage

2. MULTIPLE MAIN ITEMS:
   - pasta and sandwich
   - eggs and bacon and toast

3. ITEMS THAT COULD BE ORDERED SEPARATELY:
   - burger, fries, soda → separate

4. EXPLICIT QUANTITIES ON DIFFERENT ITEMS:
   - 2 eggs and 1 cup milk

5. TIME SEPARATION:
   - "later", "after", "then"

-----------------------------------
WHEN TO RETURN A SINGLE DISH
-----------------------------------

Return ONE "dish" ONLY if:

1. It is clearly ONE combined food:
   - "chicken alfredo pasta with mushrooms"
   - "burger with fries"
   - "salad with chicken"

2. "with" describes ingredients or sides that are part of the same plate

-----------------------------------
IMPORTANT DISTINCTION
-----------------------------------

"burger with fries" → SINGLE DISH  
"pasta with grilled cheese and coke" → MULTIPLE FOODS

Why?

- Fries are a typical side → same dish  
- Grilled cheese + coke → separate items

-----------------------------------
PARSING RULES
-----------------------------------

1. QUANTITIES
- Convert number words to numbers (one → 1, two → 2)
- "a/an" → 1
- Only apply quantities to individual foods
- NEVER assign quantity to "dish"

2. UNITS
- Include ONLY if explicitly stated
- Keep lowercase and singular (cup, slice, bowl)

3. FOOD NORMALIZATION
- Simplify:
  "scrambled eggs" → "egg"
  "a glass of milk" → "milk"

4. DISH PRESERVATION
- Keep full dish description intact
- Do NOT split ingredients inside a dish

5. IGNORE FILLER TEXT
Ignore:
"I had", "for lunch", "today", etc.

-----------------------------------
EDGE CASE RULES
-----------------------------------

1. "AND"
- Evaluate context carefully
- Do NOT assume single dish

2. DRINKS
- If paired with food → usually separate item
- Example: "pasta and coke" → split

3. "WITH"
- Sometimes same dish, sometimes not
- Decide based on food type:
   - ingredients → same dish
   - separate foods → split

-----------------------------------
FEW-SHOT EXAMPLES
-----------------------------------

Input: "2 eggs and 1 cup milk"
Output:
[
  {"food": "egg", "quantity": 2},
  {"food": "milk", "quantity": 1, "unit": "cup"}
]

---

Input: "chicken alfredo pasta with mushrooms"
Output:
{
  "dish": "chicken alfredo pasta with mushrooms"
}

---

Input: "burger with fries"
Output:
{
  "dish": "burger with fries"
}

---

Input: "pasta and salad"
Output:
[
  {"food": "pasta", "quantity": 1},
  {"food": "salad", "quantity": 1}
]

---

Input: "chicken alfredo pasta with grilled cheese and coke"
Output:
[
  {"food": "chicken alfredo pasta", "quantity": 1},
  {"food": "grilled cheese sandwich", "quantity": 1},
  {"food": "coke", "quantity": 1}
]

---

Input: "eggs toast and bacon"
Output:
[
  {"food": "egg", "quantity": 1},
  {"food": "toast", "quantity": 1},
  {"food": "bacon", "quantity": 1}
]

---

Input: "I had pasta and later drank milk"
Output:
[
  {"food": "pasta", "quantity": 1},
  {"food": "milk", "quantity": 1}
]

-----------------------------------
FINAL INSTRUCTION
-----------------------------------

Return ONLY valid JSON.
NO explanations.
NO extra text.
"""

# ------------------ ROUTES ------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("front_end.html", {"request": request})

@app.get("/foods/search", response_class=HTMLResponse)
async def usda_api(request: Request, query: str):
    query = clean_voice_input(query)
    foods = await extract_foods_with_ai(query)
    return await process_foods(request, foods)

@app.post("/voice")
async def voice_input(file: UploadFile = File(...)):
    transcript = await transcribe_audio(file)
    if not transcript:
        return {"error": "Transcription failed"}

    cleaned_query = clean_voice_input(normalize_transcript(transcript))
    foods = await extract_foods_with_ai(cleaned_query)

    results, totals = await process_foods_json(foods)

    return {
        "transcript": transcript,
        "results": results,
        "totals": totals
    }

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
    try:
        audio_bytes = await file.read()
        response = stt_client.audio.transcriptions.create(
            file=("audio.wav", audio_bytes),
            model="whisper-large-v3-turbo"
        )
        return response.text
    except Exception as e:
        print("Whisper error:", e)
        return None

# ------------------ GROQ ------------------

def safe_groq_call(user_prompt: str, system_prompt: str):
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0,
            max_tokens=300
        )
        return response.choices[0].message.content
    except Exception as e:
        print("Groq error:", e)
        return None

# ------------------ JSON ------------------

def extract_json(text):
    try:
        return json.loads(text)
    except:
        return None

# ------------------ VALIDATE ------------------

def validate_foods(data):
    clean = []
    for item in data:
        try:
            clean.append({
                "food": item["food"],
                "quantity": float(item.get("quantity", 1))
            })
        except:
            continue
    return clean

# ------------------ PORTION ------------------

def estimate_portion(text: str):
    try:
        result = safe_groq_call(text, """
Return ONLY JSON: {"quantity": number} Rules: 1. NUMBER WORDS - one → 1, two → 2, three → 3, four → 4, five → 5 - a/an → 1 - half → 0.5, quarter → 0.25 - If a decimal is written (e.g., 1.5) → use it directly 2. UNITS - bowl, plate, cup, glass, slice → do NOT multiply; unit only helps clarify - Ignore words like 'serving', 'piece', 'portion' unless numeric 3. DEFAULT - If no number found → 1 - Fractions or mixed numbers should be handled correctly EXAMPLES: - "one bowl pasta" → 1 - "two bowls pasta" → 2 - "half cup rice" → 0.5 - "1.5 slices bread" → 1.5 - "a plate of chicken" → 1 Return JSON only, nothing else.
""")
        data = extract_json(result)
        return float(data.get("quantity", 1))
    except:
        return 1

# ------------------ AI EXTRACTION ------------------

async def extract_foods_with_ai(query: str):
    text = safe_groq_call(query, FOOD_PARSER_PROMPT)

    if text:
        data = extract_json(text)

        if isinstance(data, list):
            return validate_foods(data)

        elif isinstance(data, dict) and "dish" in data:
            return [{
                "food": data["dish"],
                "quantity": estimate_portion(query)
            }]

    return [{"food": query, "quantity": 1}]

# ------------------ USDA ------------------

async def fetch_usda(food_name: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.nal.usda.gov/fdc/v1/foods/search",
            params={"api_key": USDA_API_KEY},
            json={"query": food_name}
        )

        if response.status_code != 200:
            return None

        foods = response.json().get("foods", [])
        if not foods:
            return None

        selected = foods[0]

        lookup = {
            "Energy": "calories",
            "Protein": "protein_g",
            "Carbohydrate, by difference": "carbs_g",
            "Total lipid (fat)": "fat_g",
            "Sugars, total including NLEA": "sugar_g",
            "Fiber, total dietary": "fiber_g",
            "Vitamin D (D2 + D3), International Units": "vitamin_d_mcg"
        }

        nutrition = {v: "Not Available" for v in lookup.values()}

        for n in selected.get("foodNutrients", []):
            if n.get("nutrientName") in lookup:
                nutrition[lookup[n["nutrientName"]]] = n.get("value", "Not Available")

        return nutrition

# ------------------ PROCESS ------------------

async def process_foods_json(foods):
    results = []
    totals = {
        "calories": 0,
        "protein_g": 0,
        "carbs_g": 0,
        "fat_g": 0
    }

    for food in foods:
        nutrition = await fetch_usda(food["food"]) or {}

        for k in totals:
            val = nutrition.get(k)
            if isinstance(val, (int, float)):
                totals[k] += val * food["quantity"]

        results.append({
            "food": food["food"],
            "quantity": food["quantity"],
            "nutrition": nutrition
        })

    return results, totals