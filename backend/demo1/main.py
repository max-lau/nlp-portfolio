from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from backend.demo1.database import init_db, save_analysis, query_analyses, get_stats
import anthropic
import os
import json
import re

load_dotenv()

app = FastAPI(title="NLP Text Analyzer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database on startup
init_db()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

class TextInput(BaseModel):
    text: str

def clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return raw.strip()

@app.get("/health")
def health():
    return {"status": "ok", "model": "claude-haiku-4-5-20251001"}

@app.post("/analyze")
def analyze(body: TextInput):
    if not body.text or len(body.text.strip()) < 20:
        raise HTTPException(status_code=400, detail="Text too short")

    prompt = f"""Analyze this text for NLP tasks.

IMPORTANT: Your entire response must be ONLY a raw JSON object.
Do NOT use markdown. Do NOT use backticks. Do NOT add any explanation.
Start your response with {{ and end with }}

Text: \"\"\"{body.text[:2000]}\"\"\"

Return exactly this structure:
{{
  "sentiment": {{
    "label": "positive",
    "score": 0.85,
    "explanation": "one sentence about why"
  }},
  "entities": [
    {{"text": "Apple", "type": "ORG"}}
  ],
  "keywords": [
    {{"word": "revenue", "importance": "high"}}
  ],
  "tone": ["analytical", "confident"],
  "summary": "2-sentence plain English summary of the text"
}}

label must be one of: positive negative neutral mixed
importance must be one of: high medium low
Entity types: PERSON ORG GPE LOC DATE TIME MONEY PERCENT LAW PRODUCT OTHER
Max 8 entities, max 10 keywords, max 3 tone items."""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text
        print(f"\n--- RAW RESPONSE ---\n{raw}\n--- END ---\n")
        cleaned = clean_json(raw)
        parsed = json.loads(cleaned)

        # Save to database
        row_id = save_analysis(body.text, parsed)
        parsed["id"] = row_id
        print(f"Saved to DB with id: {row_id}")

        return parsed
    except json.JSONDecodeError as e:
        print(f"JSON ERROR: {e}\nRaw was: {raw}")
        raise HTTPException(status_code=500, detail=f"JSON parse error: {str(e)}")
    except Exception as e:
        print(f"GENERAL ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/history")
def history(
    sentiment: str = Query(None, description="Filter by sentiment: positive, negative, neutral, mixed"),
    keyword:   str = Query(None, description="Search keyword in text or keywords"),
    limit:     int = Query(20,   description="Max results to return")
):
    """Query past analyses from the database."""
    results = query_analyses(sentiment=sentiment, keyword=keyword, limit=limit)
    return {"count": len(results), "results": results}

@app.get("/stats")
def stats():
    """Aggregate statistics across all stored analyses."""
    return get_stats()