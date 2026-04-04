from dotenv import load_dotenv
load_dotenv()

import os
import httpx
import json
import re

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from supabase_client import supabase
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

groq_client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

# ✅ Whisper client (same Groq endpoint)
stt_client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

tavily = TavilyClient(api_key=TAVILY_API_KEY)
templates = Jinja2Templates(directory="templates")

# ------------------ ROUTE ------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("front_end.html", {"request": request})


# ------------------ CLEAN INPUT ------------------

def clean_voice_input(query: str):
    query = query.lower()
    fillers = [
        "i ate", "i had", "i just ate",
        "for breakfast", "for lunch", "for dinner"
    ]
    for f in fillers:
        query = query.replace(f, "")
    return query.strip()


# ------------------ NORMALIZE TRANSCRIPT ------------------

def normalize_transcript(text: str):
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    return text.strip()


# ------------------ WHISPER STT ------------------

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


# ------------------ SAFE GROQ CALL ------------------

def safe_groq_call(prompt: str):
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": """<KEEP YOUR EXISTING PROMPT EXACTLY AS IS>"""
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=500
        )

        return response.choices[0].message.content

    except Exception as e:
        print("Groq error:", e)
        return None


# ------------------ JSON EXTRACTION ------------------

def extract_json(text):
    try:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print("JSON error:", e)
    return None


# ------------------ VALIDATE FOODS ------------------

def validate_foods(data):
    VALID_STOPWORDS = {"and", "of", "a", "the"}
    clean = []
    for item in data:
        food = item.get("food", "").strip()
        if not food or food in VALID_STOPWORDS:
            continue
        quantity = item.get("quantity", 1)
        try:
            quantity = float(quantity)
        except:
            quantity = 1
        clean.append({
            "food": food,
            "quantity": quantity
        })
    return clean


# ------------------ AI FOOD EXTRACTION ------------------

async def extract_foods_with_ai(query: str):
    prompt = f'Extract foods from: "{query}"'
    text = safe_groq_call(prompt)
    if text:
        data = extract_json(text)
        if data:
            return validate_foods(data)

    return [{"food": query, "quantity": 1}]


# ------------------ USDA FETCH ------------------

async def fetch_usda(food_name: str):
    async with httpx.AsyncClient() as http_client:
        response = await http_client.post(
            "https://api.nal.usda.gov/fdc/v1/foods/search",
            params={"api_key": USDA_API_KEY},
            json={"query": food_name}
        )

        if response.status_code != 200:
            return None

        foods = response.json().get("foods", [])
        if not foods:
            return None

        def score_food(food):
            desc = food.get("description", "").lower()
            score = 0
            if "raw" in desc:
                score += 5
            if "large" in desc:
                score += 3
            bad_words = ["dried", "powder", "mix", "substitute", "liquid"]
            for word in bad_words:
                if word in desc:
                    score -= 10
            return score

        foods_sorted = sorted(foods, key=score_food, reverse=True)
        selected_food = foods_sorted[0]

        nutrient_lookup = {
            "Energy": "calories",
            "Protein": "protein_g",
            "Carbohydrate, by difference": "carbs_g",
            "Total lipid (fat)": "fat_g",
            "Total Sugars including NLEA": "sugar_g",
            "Fiber, total dietary": "fiber_g",
            "Vitamin D (D2 + D3)": "vitamin_d_mcg",
        }

        nutrition_data = {v: 0 for v in nutrient_lookup.values()}

        for nutrient in selected_food.get("foodNutrients", []):
            name = nutrient.get("nutrientName")
            if name in nutrient_lookup:
                nutrition_data[nutrient_lookup[name]] = nutrient.get("value", 0)

        # Serving normalization
        if "egg" in food_name.lower():
            for k in nutrition_data:
                nutrition_data[k] *= 0.5
        elif "milk" in food_name.lower():
            for k in nutrition_data:
                nutrition_data[k] *= 2.44

        return nutrition_data


# ------------------ TEXT INPUT ENDPOINT ------------------

@app.get("/foods/search", response_class=HTMLResponse)
async def usda_api(request: Request, query: str):
    query = clean_voice_input(query)
    foods = await extract_foods_with_ai(query)

    return await process_foods(request, foods)


# ------------------ VOICE INPUT ENDPOINT ------------------

@app.post("/voice")
async def voice_input(request: Request, file: UploadFile = File(...)):

    transcript = await transcribe_audio(file)

    if not transcript:
        return {"error": "Transcription failed"}

    print("Raw transcript:", transcript)

    cleaned_query = normalize_transcript(transcript)
    cleaned_query = clean_voice_input(cleaned_query)

    print("Cleaned:", cleaned_query)

    foods = await extract_foods_with_ai(cleaned_query)

    return await process_foods(request, foods, transcript=transcript)


# ------------------ SHARED PROCESSOR ------------------

async def process_foods(request, foods, transcript=None):

    results = []
    totals = {
        "calories": 0,
        "protein_g": 0,
        "carbs_g": 0,
        "fat_g": 0,
        "sugar_g": 0,
        "fiber_g": 0,
        "vitamin_d_mcg": 0
    }

    for food in foods:
        nutrition = await fetch_usda(food["food"]) or {
            "calories": 0,
            "protein_g": 0,
            "carbs_g": 0,
            "fat_g": 0,
            "sugar_g": 0,
            "fiber_g": 0,
            "vitamin_d_mcg": 0
        }

        for k in nutrition:
            nutrition[k] *= food["quantity"]

        result = {
            "food": f"{food['quantity']} x {food['food']}",
            **nutrition
        }

        results.append(result)

        for key in totals:
            totals[key] += result.get(key, 0)

        try:
            supabase.table("food_searches").insert({
                "food_name": result["food"],
                "calories": result["calories"],
                "protein": result["protein_g"],
                "carbs": result["carbs_g"],
                "fat": result["fat_g"]
            }).execute()
        except Exception as e:
            print("Supabase insert failed:", e)

    return templates.TemplateResponse(
        "front_end.html",
        {
            "request": request,
            "results": results,
            "totals": totals,
            "transcript": transcript
        }
    )