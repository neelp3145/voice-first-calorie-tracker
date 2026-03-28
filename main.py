from dotenv import load_dotenv
load_dotenv()

import os
import httpx
import string
import json
import re

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from supabase_client import supabase

import google.generativeai as genai
from tavily import TavilyClient

app = FastAPI()

# ------------------ API KEYS ------------------

USDA_API_KEY = os.getenv("USDA_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

if not USDA_API_KEY:
    raise RuntimeError("USDA_API_KEY not set")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY not set")

if not TAVILY_API_KEY:
    raise RuntimeError("TAVILY_API_KEY not set")

# ------------------ GEMINI SETUP ------------------

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

tavily = TavilyClient(api_key=TAVILY_API_KEY)

templates = Jinja2Templates(directory="templates")

# ------------------ ROUTE ------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("front_end.html", {"request": request})


# ------------------ JSON EXTRACTION HELPER ------------------

def extract_json(text):
    """
    Extracts JSON from Gemini response safely.
    Handles both list [] and dict {} outputs.
    """
    try:
        match = re.search(r"\[.*\]|\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print("JSON extraction error:", e)
    return None


# ------------------ CLEAN INPUT ------------------

def clean_voice_input(query: str):

    fillers = [
        "i ate", "i had", "i just ate",
        "for breakfast", "for lunch", "for dinner"
    ]

    query = query.lower()

    for f in fillers:
        query = query.replace(f, "")

    query = query.translate(str.maketrans('', '', string.punctuation))

    return query.strip()


# ------------------ AI FOOD EXTRACTION ------------------

async def extract_foods_with_ai(query: str):

    prompt = f"""
    Extract food items with quantities.

    Return ONLY valid JSON list like:
    [
      {{"food": "egg", "quantity": 2, "unit": "whole"}},
      {{"food": "toast", "quantity": 2, "unit": "slice"}}
    ]

    If quantity missing, assume 1.

    Sentence: "{query}"
    """

    response = model.generate_content(prompt)
    data = extract_json(response.text)

    if data:
        return data

    return [{"food": query, "quantity": 1, "unit": "serving"}]


# ------------------ USDA FETCH ------------------

async def fetch_usda(food_name: str):

    async with httpx.AsyncClient() as http_client:

        response = await http_client.post(
            "https://api.nal.usda.gov/fdc/v1/foods/search",
            params={"api_key": USDA_API_KEY},
            json={
                "query": food_name,
                "dataType": [
                    "Foundation",
                    "Branded Foods",
                    "SR Legacy",
                    "Survey (FNDDS)"
                ]
            }
        )

        if response.status_code != 200:
            return None

        foods = response.json().get("foods", [])
        if not foods:
            return None

        selected_food = foods[0]

        nutrient_lookup = {
            "Energy": "calories",
            "Protein": "protein_g",
            "Carbohydrate, by difference": "carbs_g",
            "Total lipid (fat)": "fat_g",
            "Total Sugars": "sugar_g",
            "Fiber, total dietary": "fiber_g",
        }

        nutrition_data = {v: 0 for v in nutrient_lookup.values()}

        for nutrient in selected_food["foodNutrients"]:
            name = nutrient["nutrientName"]
            if name in nutrient_lookup:
                nutrition_data[nutrient_lookup[name]] = nutrient["value"]

        return nutrition_data


# ------------------ WEB SEARCH TOOL ------------------

def search_food_nutrition(food_name):

    results = tavily.search(
        query=f"{food_name} nutrition macros per serving",
        max_results=3
    )

    return results


# ------------------ EXTRACT MACROS FROM WEB ------------------

async def extract_macros_from_text(web_results):

    prompt = f"""
    Extract nutrition macros from this data.

    Return JSON:
    {{
      "calories": number,
      "protein_g": number,
      "carbs_g": number,
      "fat_g": number
    }}

    Data:
    {web_results}
    """

    response = model.generate_content(prompt)
    return extract_json(response.text)


# ------------------ VALIDATION AGENT ------------------

async def validate_macros(food_name, macros):

    prompt = f"""
    Validate these macros for realism.

    Food: {food_name}
    Macros: {macros}

    Fix if needed. Return JSON only.
    """

    response = model.generate_content(prompt)
    validated = extract_json(response.text)

    return validated if validated else macros


# ------------------ AGENT DECISION ------------------

async def get_best_nutrition(food):

    name = food["food"]
    quantity = food.get("quantity", 1)

    usda_data = await fetch_usda(name)

    if not usda_data or usda_data.get("calories", 0) == 0:

        web_results = search_food_nutrition(name)
        web_data = await extract_macros_from_text(web_results)

        if web_data:
            final = web_data
        else:
            final = {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}
    else:
        final = usda_data

    validated = await validate_macros(name, final)

    # scale by quantity
    for k in validated:
        validated[k] *= quantity

    return validated


# ------------------ MAIN ENDPOINT ------------------

@app.get("/foods/search", response_class=HTMLResponse)
async def usda_api(request: Request, query: str):

    query = clean_voice_input(query)

    foods = await extract_foods_with_ai(query)

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

        nutrition = await get_best_nutrition(food)

        result = {
            "food": f"{food['quantity']} x {food['food']}",
            "calories": nutrition.get("calories", 0),
            "protein_g": nutrition.get("protein_g", 0),
            "carbs_g": nutrition.get("carbs_g", 0),
            "fat_g": nutrition.get("fat_g", 0),
            "sugar_g": nutrition.get("sugar_g", 0),
            "fiber_g": nutrition.get("fiber_g", 0),
            "vitamin_d_mcg": 0
        }

        results.append(result)

        for key in totals:
            totals[key] += result.get(key, 0)

        # Save to Supabase
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
            "totals": totals
        }
    )