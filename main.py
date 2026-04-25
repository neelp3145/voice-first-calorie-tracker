# Add these imports at the top (keep your existing imports)
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
import asyncio
from datetime import datetime

# Add after your existing Pydantic models
class DataSource(str, Enum):
    USDA = "usda"
    AGENT_WEB = "agent_web"
    AGENT_AI = "agent_ai"
    FALLBACK = "fallback"
    PERSONAL = "personal"

class AgentSearchResult(BaseModel):
    success: bool
    food_name: str
    nutrition: Dict[str, Any]
    source: DataSource
    confidence: float
    notes: Optional[str] = None
    serving_size: Optional[str] = None

# Add after client initialization
AGENT_ENABLED = bool(TAVILY_API_KEY and GROQ_API_KEY)

# Critical: Cache for agent results to avoid repeated API calls
agent_cache = {}
CACHE_TTL = 3600  # 1 hour

# ============= ENHANCED USDA WITH AGENT FALLBACK =============

async def fetch_usda_enhanced(food_name: str, user_id: str = None) -> Tuple[Dict[str, Any], DataSource, float]:
    """
    Enhanced USDA fetch with intelligent agent fallback.
    Returns: (nutrition_data, source, confidence_score)
    """
    
    # Step 1: Check cache first (prevents redundant API calls)
    cache_key = f"{food_name}:{user_id if user_id else 'public'}"
    if cache_key in agent_cache:
        cached_time, cached_result = agent_cache[cache_key]
        if (datetime.now() - cached_time).total_seconds() < CACHE_TTL:
            logger.info(f"Cache hit for {food_name}")
            return cached_result
    
    # Step 2: Try personal foods first (user's custom entries)
    if user_id:
        personal_food = await fetch_personal_food(user_id, food_name)
        if personal_food:
            result = (personal_food["nutrition"], DataSource.PERSONAL, 0.95)
            agent_cache[cache_key] = (datetime.now(), result)
            return result
    
    # Step 3: Query USDA API
    usda_result = await fetch_usda_api(food_name)
    
    if usda_result and is_usda_data_complete(usda_result):
        # USDA has good data - use as ground truth
        confidence = calculate_usda_confidence(usda_result, food_name)
        result = (usda_result, DataSource.USDA, confidence)
        agent_cache[cache_key] = (datetime.now(), result)
        return result
    
    # Step 4: USDA data incomplete or missing - ACTIVATE AGENT MODE
    logger.info(f"⚠️ USDA data incomplete for '{food_name}'. Activating AI Agent fallback...")
    
    agent_result = await activate_agent_mode(AgentSearchRequest(
        food_name=food_name,
        quantity=1.0,
        usda_results=usda_result
    ))
    
    if agent_result.success and agent_result.confidence >= 0.6:
        # Agent found good data
        result = (agent_result.nutrition, agent_result.source, agent_result.confidence)
        agent_cache[cache_key] = (datetime.now(), result)
        return result
    
    # Step 5: Ultimate fallback - estimate based on food category
    logger.warning(f"⚠️ All sources failed for '{food_name}'. Using category fallback.")
    fallback_result = await category_fallback(food_name)
    result = (fallback_result, DataSource.FALLBACK, 0.3)
    agent_cache[cache_key] = (datetime.now(), result)
    return result

async def fetch_usda_api(food_name: str) -> Optional[Dict[str, Any]]:
    """Pure USDA API call without fallback logic"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.nal.usda.gov/fdc/v1/foods/search",
                params={"api_key": USDA_API_KEY},
                json={"query": food_name, "pageSize": 10, "requireAllWords": False}
            )
            
            if response.status_code != 200:
                logger.error(f"USDA API error: {response.status_code}")
                return None
            
            data = response.json()
            foods = data.get("foods", [])
            if not foods:
                return None
            
            # Select best matching candidate
            selected = select_usda_candidate(food_name, foods)
            
            # Extract nutrition data
            nutrition = {
                "calories": 0.0,
                "protein_g": 0.0,
                "carbs_g": 0.0,
                "fat_g": 0.0,
                "sugar_g": 0.0,
                "fiber_g": 0.0,
                "vitamin_d_mcg": 0.0,
                "serving_size": "100g",
                "data_quality": "good"
            }
            
            nutrient_map = {
                "Energy": "calories",
                "Protein": "protein_g",
                "Carbohydrate, by difference": "carbs_g",
                "Total lipid (fat)": "fat_g",
                "Sugars, total including NLEA": "sugar_g",
                "Fiber, total dietary": "fiber_g",
            }
            
            for nutrient in selected.get("foodNutrients", []):
                nutrient_name = nutrient.get("nutrientName", "")
                if nutrient_name in nutrient_map:
                    value = nutrient.get("value", 0)
                    if value and value != "Not Available":
                        nutrition[nutrient_map[nutrient_name]] = float(value)
            
            # Add serving size info if available
            if selected.get("servingSize"):
                nutrition["serving_size"] = f"{selected.get('servingSize')} {selected.get('servingSizeUnit', 'g')}"
            
            return nutrition
            
    except Exception as e:
        logger.error(f"USDA API exception: {str(e)}")
        return None

def is_usda_data_complete(nutrition: Dict[str, Any]) -> bool:
    """Check if USDA data has minimum required fields"""
    required_fields = ["calories", "protein_g", "carbs_g", "fat_g"]
    
    for field in required_fields:
        value = nutrition.get(field, 0)
        if not isinstance(value, (int, float)) or value <= 0:
            # Allow zero values only for certain foods (like water, diet soda)
            if field == "calories" and value == 0:
                continue
            return False
    
    # Additional quality check: total should make sense
    calories = nutrition.get("calories", 0)
    if calories > 0 and calories < 5000:  # Sanity check
        return True
    
    return False

def calculate_usda_confidence(nutrition: Dict[str, Any], food_name: str) -> float:
    """Calculate confidence score for USDA data"""
    confidence = 0.7  # Base confidence
    
    # Bonus for complete macro data
    if nutrition.get("protein_g", 0) > 0:
        confidence += 0.1
    if nutrition.get("carbs_g", 0) > 0:
        confidence += 0.05
    if nutrition.get("fat_g", 0) > 0:
        confidence += 0.05
    
    # Penalty for missing sugar/fiber (common in USDA)
    if nutrition.get("sugar_g", 0) == 0:
        confidence -= 0.05
    if nutrition.get("fiber_g", 0) == 0:
        confidence -= 0.05
    
    return min(0.95, max(0.6, confidence))

# ============= AI AGENT MODE (FALLBACK) =============

async def activate_agent_mode(request: AgentSearchRequest) -> AgentSearchResult:
    """
    Activate AI agent when USDA fails.
    Uses Tavily web search + Groq AI for nutrition extraction.
    """
    
    if not AGENT_ENABLED:
        logger.warning("Agent mode requested but API keys missing")
        return await category_fallback_result(request.food_name)
    
    try:
        # Step 1: Search the web for nutrition data
        search_queries = [
            f"{request.food_name} nutrition facts USDA",
            f"{request.food_name} calories protein carbs fat per 100g",
            f"{request.food_name} nutritional information"
        ]
        
        all_results = []
        for query in search_queries[:2]:  # Limit to 2 searches to save API calls
            try:
                result = tavily.search(
                    query=query,
                    search_depth="basic",  # Use basic to save credits
                    max_results=3,
                    include_answer=True
                )
                all_results.append(result)
                await asyncio.sleep(0.5)  # Rate limiting
            except Exception as e:
                logger.error(f"Tavily search failed for '{query}': {str(e)}")
        
        if not all_results:
            return await ai_estimation_result(request.food_name)
        
        # Step 2: Extract nutrition data using AI
        nutrition_data = await extract_nutrition_with_ai(all_results, request.food_name)
        
        if nutrition_data and nutrition_data.get("confidence", 0) >= 0.6:
            return AgentSearchResult(
                success=True,
                food_name=request.food_name,
                nutrition={
                    "calories": nutrition_data.get("calories", 0),
                    "protein_g": nutrition_data.get("protein_g", 0),
                    "carbs_g": nutrition_data.get("carbs_g", 0),
                    "fat_g": nutrition_data.get("fat_g", 0),
                    "sugar_g": nutrition_data.get("sugar_g", 0),
                    "fiber_g": nutrition_data.get("fiber_g", 0),
                    "vitamin_d_mcg": nutrition_data.get("vitamin_d_mcg", 0),
                    "serving_size": nutrition_data.get("serving_size", "100g"),
                },
                source=DataSource.AGENT_WEB,
                confidence=nutrition_data.get("confidence", 0.7),
                notes=f"Found via web search - {nutrition_data.get('source_note', '')}"
            )
        
        # Step 3: Fallback to AI estimation
        return await ai_estimation_result(request.food_name)
        
    except Exception as e:
        logger.error(f"Agent mode error: {str(e)}")
        return await category_fallback_result(request.food_name)

async def extract_nutrition_with_ai(search_results: List[Dict], food_name: str) -> Optional[Dict]:
    """Extract structured nutrition data from search results using AI"""
    
    # Build context from search results
    context_parts = []
    for idx, result in enumerate(search_results[:2]):  # Limit context size
        if result.get("answer"):
            context_parts.append(f"Summary {idx + 1}: {result['answer']}")
        
        for res in result.get("results", [])[:2]:
            title = res.get("title", "")
            content = res.get("content", "")[:300]  # Limit content length
            if title and content:
                context_parts.append(f"Source: {title}\nContent: {content}")
    
    context = "\n\n".join(context_parts)
    
    extraction_prompt = f"""
Extract accurate nutritional information for "{food_name}" from the search results below.

IMPORTANT: Return ONLY valid JSON. NO extra text, NO markdown formatting.

Required format:
{{
    "calories": number (per 100g or typical serving),
    "protein_g": number,
    "carbs_g": number,
    "fat_g": number,
    "sugar_g": number,
    "fiber_g": number,
    "vitamin_d_mcg": number,
    "serving_size": "string (e.g., '100g', '1 medium')",
    "confidence": number (0.6-0.9 for web-sourced data),
    "source_note": "brief source attribution"
}}

Rules:
1. Always use per 100g when possible
2. If multiple sources conflict, use the most authoritative (USDA, official databases)
3. For branded foods, prioritize brand-specific data
4. Set confidence based on data consistency (0.6=low, 0.9=high)

Search Results:
{context}

Return ONLY the JSON object.
"""
    
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You extract nutrition data. Return only valid JSON. Never add explanatory text."},
                {"role": "user", "content": extraction_prompt}
            ],
            temperature=0.1,
            max_tokens=600,
            timeout=15.0
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Clean markdown code blocks if present
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        
        nutrition_data = json.loads(result_text)
        
        # Validate required fields
        required = ["calories", "protein_g", "carbs_g", "fat_g"]
        if all(k in nutrition_data for k in required):
            # Convert to float and ensure reasonable values
            for key in required:
                nutrition_data[key] = float(max(0, nutrition_data.get(key, 0)))
            
            return nutrition_data
            
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error in AI extraction: {str(e)}")
    except Exception as e:
        logger.error(f"AI extraction failed: {str(e)}")
    
    return None

async def ai_estimation_result(food_name: str) -> AgentSearchResult:
    """Estimate nutrition using AI when web search fails"""
    
    estimation_prompt = f"""
Estimate typical nutritional values for "{food_name}" per 100g serving.

Common reference values (per 100g):
- Apple: 52 cal, 0.3g protein, 14g carbs, 0.2g fat
- Chicken breast: 165 cal, 31g protein, 0g carbs, 3.6g fat
- Rice (cooked): 130 cal, 2.7g protein, 28g carbs, 0.3g fat
- Pasta (cooked): 158 cal, 5.8g protein, 31g carbs, 1.1g fat
- Banana: 89 cal, 1.1g protein, 23g carbs, 0.3g fat

Return ONLY JSON:
{{
    "calories": number,
    "protein_g": number,
    "carbs_g": number,
    "fat_g": number,
    "sugar_g": number,
    "fiber_g": number,
    "vitamin_d_mcg": number,
    "serving_size": "100g",
    "confidence": 0.5
}}
"""
    
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You estimate nutrition. Return only valid JSON."},
                {"role": "user", "content": estimation_prompt}
            ],
            temperature=0.2,
            max_tokens=400,
            timeout=10.0
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Clean response
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        
        nutrition_data = json.loads(result_text)
        
        return AgentSearchResult(
            success=True,
            food_name=food_name,
            nutrition={
                "calories": float(nutrition_data.get("calories", 100)),
                "protein_g": float(nutrition_data.get("protein_g", 5)),
                "carbs_g": float(nutrition_data.get("carbs_g", 15)),
                "fat_g": float(nutrition_data.get("fat_g", 5)),
                "sugar_g": float(nutrition_data.get("sugar_g", 5)),
                "fiber_g": float(nutrition_data.get("fiber_g", 2)),
                "vitamin_d_mcg": float(nutrition_data.get("vitamin_d_mcg", 0)),
                "serving_size": "100g",
            },
            source=DataSource.AGENT_AI,
            confidence=0.5,
            notes="AI estimated based on similar foods - please verify"
        )
        
    except Exception as e:
        logger.error(f"AI estimation failed: {str(e)}")
        return await category_fallback_result(food_name)

async def category_fallback(food_name: str) -> Dict[str, Any]:
    """Ultimate fallback based on food category"""
    result = await category_fallback_result(food_name)
    return result.nutrition

async def category_fallback_result(food_name: str) -> AgentSearchResult:
    """Get fallback values based on food category"""
    
    food_lower = food_name.lower()
    
    # Enhanced category detection with more specific defaults
    categories = {
        "fruit": {"calories": 60, "protein_g": 0.5, "carbs_g": 15, "fat_g": 0.3, "sugar_g": 12, "fiber_g": 2},
        "vegetable": {"calories": 25, "protein_g": 1, "carbs_g": 5, "fat_g": 0.2, "sugar_g": 2, "fiber_g": 2},
        "meat": {"calories": 200, "protein_g": 25, "carbs_g": 0, "fat_g": 10, "sugar_g": 0, "fiber_g": 0},
        "fish": {"calories": 150, "protein_g": 20, "carbs_g": 0, "fat_g": 7, "sugar_g": 0, "fiber_g": 0},
        "grain": {"calories": 130, "protein_g": 4, "carbs_g": 28, "fat_g": 1, "sugar_g": 1, "fiber_g": 2},
        "dairy": {"calories": 80, "protein_g": 6, "carbs_g": 5, "fat_g": 4, "sugar_g": 5, "fiber_g": 0},
        "beverage": {"calories": 40, "protein_g": 0, "carbs_g": 10, "fat_g": 0, "sugar_g": 10, "fiber_g": 0},
        "snack": {"calories": 150, "protein_g": 2, "carbs_g": 20, "fat_g": 7, "sugar_g": 8, "fiber_g": 1},
        "dessert": {"calories": 250, "protein_g": 4, "carbs_g": 35, "fat_g": 10, "sugar_g": 25, "fiber_g": 1},
    }
    
    # Detect category
    detected_category = "snack"
    for category, keywords in {
        "fruit": ["apple", "banana", "orange", "berry", "fruit", "grape", "peach", "pear"],
        "vegetable": ["carrot", "broccoli", "salad", "vegetable", "veggie", "spinach", "kale", "cucumber"],
        "meat": ["chicken", "beef", "pork", "lamb", "meat", "steak", "burger", "sausage"],
        "fish": ["salmon", "tuna", "fish", "shrimp", "crab", "lobster"],
        "grain": ["rice", "bread", "pasta", "oat", "cereal", "wheat", "quinoa"],
        "dairy": ["milk", "cheese", "yogurt", "butter", "cream"],
        "beverage": ["drink", "juice", "soda", "tea", "coffee", "shake", "smoothie"],
        "dessert": ["cake", "cookie", "pie", "ice cream", "brownie", "pastry"],
    }.items():
        if any(keyword in food_lower for keyword in keywords):
            detected_category = category
            break
    
    defaults = categories.get(detected_category, categories["snack"])
    
    return AgentSearchResult(
        success=True,
        food_name=food_name,
        nutrition={
            "calories": defaults["calories"],
            "protein_g": defaults["protein_g"],
            "carbs_g": defaults["carbs_g"],
            "fat_g": defaults["fat_g"],
            "sugar_g": defaults["sugar_g"],
            "fiber_g": defaults["fiber_g"],
            "vitamin_d_mcg": 0,
            "serving_size": "100g",
        },
        source=DataSource.FALLBACK,
        confidence=0.3,
        notes=f"Estimated as {detected_category} - please edit for accuracy"
    )

# ============= UPDATE YOUR EXISTING FUNCTIONS =============

# Replace your existing compute_results_and_totals function
async def compute_results_and_totals(foods, user_id: str | None = None):
    """Updated to use enhanced USDA with agent fallback"""
    results = []
    totals = {
        "calories": 0,
        "protein_g": 0,
        "carbs_g": 0,
        "fat_g": 0,
        "sugar_g": 0,
        "fiber_g": 0
    }
    
    for food_item in foods:
        food_name = food_item.get("food", "")
        quantity = float(food_item.get("quantity", 1))
        
        # Use enhanced fetch with agent fallback
        nutrition, source, confidence = await fetch_usda_enhanced(food_name, user_id)
        
        # Calculate totals (multiply by quantity)
        for key in totals:
            value = nutrition.get(key, 0)
            if isinstance(value, (int, float)):
                totals[key] += value * quantity
        
        # Build result item (matching your frontend expectations)
        result_item = {
            "food": f"{quantity:g} x {food_name}" if quantity != 1 else food_name,
            "quantity": quantity,
            "source": source.value,
            "source_item": food_name,
            "confidence": confidence,
            "calories": nutrition.get("calories", 0),
            "protein_g": nutrition.get("protein_g", 0),
            "carbs_g": nutrition.get("carbs_g", 0),
            "fat_g": nutrition.get("fat_g", 0),
            "sugar_g": nutrition.get("sugar_g", 0),
            "fiber_g": nutrition.get("fiber_g", 0),
            "vitamin_d_mcg": nutrition.get("vitamin_d_mcg", 0),
            "serving_size": nutrition.get("serving_size", "100g"),
        }
        
        # Add agent notes if applicable
        if source in [DataSource.AGENT_WEB, DataSource.AGENT_AI, DataSource.FALLBACK]:
            result_item["agent_note"] = nutrition.get("agent_note", "Estimated with AI assistance")
        
        results.append(result_item)
    
    return results, totals

# Add status endpoint
@app.get("/api/agent/status")
async def agent_status(user: dict = Depends(get_current_user)):
    """Check agent mode availability"""
    return {
        "agent_mode_enabled": AGENT_ENABLED,
        "usda_configured": bool(USDA_API_KEY),
        "tavily_configured": bool(TAVILY_API_KEY),
        "groq_configured": bool(GROQ_API_KEY),
        "cache_size": len(agent_cache),
        "active_fallbacks": ["web_search", "ai_estimation", "category_fallback"] if AGENT_ENABLED else ["category_fallback"]
    }

# Add cache management endpoint
@app.delete("/api/agent/cache")
async def clear_agent_cache(user: dict = Depends(get_current_user)):
    """Clear agent cache (admin only)"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    agent_cache.clear()
    return {"message": "Cache cleared", "cache_size": 0}
