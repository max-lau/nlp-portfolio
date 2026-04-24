from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from backend.demo1.database import init_db, save_analysis, query_analyses, get_stats
import anthropic
import os
import json
import re
import csv
import io
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List

load_dotenv()

app = FastAPI(title="NLP Text Analyzer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
executor = ThreadPoolExecutor(max_workers=3)

class TextInput(BaseModel):
    text: str

class BatchInput(BaseModel):
    documents: List[str]
    labels: List[str] = []  # optional labels for each document

def clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return raw.strip()

def run_analysis(text: str, label: str = "") -> dict:
    """Run a single analysis — called in thread pool for batch."""
    prompt = f"""Analyze this text for NLP tasks.

IMPORTANT: Your entire response must be ONLY a raw JSON object.
Do NOT use markdown. Do NOT use backticks. Do NOT add any explanation.
Start your response with {{ and end with }}

Text: \"\"\"{text[:2000]}\"\"\"

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
        cleaned = clean_json(raw)
        parsed = json.loads(cleaned)
        row_id = save_analysis(text, parsed)
        parsed["id"] = row_id
        parsed["label"] = label
        parsed["status"] = "success"
        parsed["text_preview"] = text[:120] + "..." if len(text) > 120 else text
        parsed["word_count"] = len(text.split())
        return parsed
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "label": label,
            "text_preview": text[:120] + "..." if len(text) > 120 else text,
            "word_count": len(text.split())
        }

@app.get("/health")
def health():
    return {"status": "ok", "model": "claude-haiku-4-5-20251001"}

@app.post("/analyze")
def analyze(body: TextInput):
    if not body.text or len(body.text.strip()) < 20:
        raise HTTPException(status_code=400, detail="Text too short")
    result = run_analysis(body.text)
    return result

@app.post("/analyze/batch")
async def analyze_batch(body: BatchInput):
    if not body.documents:
        raise HTTPException(status_code=400, detail="No documents provided")
    if len(body.documents) > 20:
        raise HTTPException(status_code=400, detail="Max 20 documents per batch")

    # Pad labels if not provided
    labels = body.labels + [""] * (len(body.documents) - len(body.labels))

    # Process in parallel using thread pool
    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(executor, run_analysis, doc, label)
        for doc, label in zip(body.documents, labels)
    ]
    results = await asyncio.gather(*tasks)

    # Summary stats
    successful = [r for r in results if r.get("status") == "success"]
    failed     = [r for r in results if r.get("status") == "error"]
    sentiments = [r.get("sentiment", {}).get("label", "") for r in successful]

    return {
        "total":      len(results),
        "successful": len(successful),
        "failed":     len(failed),
        "summary": {
            "positive": sentiments.count("positive"),
            "negative": sentiments.count("negative"),
            "neutral":  sentiments.count("neutral"),
            "mixed":    sentiments.count("mixed"),
            "avg_score": round(
                sum(r.get("sentiment", {}).get("score", 0) for r in successful)
                / max(len(successful), 1), 3
            )
        },
        "results": list(results)
    }

@app.post("/analyze/batch/csv")
async def analyze_batch_csv(body: BatchInput):
    """Run batch analysis and return results as downloadable CSV."""
    if not body.documents:
        raise HTTPException(status_code=400, detail="No documents provided")
    if len(body.documents) > 20:
        raise HTTPException(status_code=400, detail="Max 20 documents per batch")

    labels = body.labels + [""] * (len(body.documents) - len(body.labels))

    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(executor, run_analysis, doc, label)
        for doc, label in zip(body.documents, labels)
    ]
    results = await asyncio.gather(*tasks)

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "label", "status", "word_count",
        "sentiment", "score", "tone",
        "top_keywords", "entity_count", "summary", "text_preview"
    ])

    for r in results:
        writer.writerow([
            r.get("id", ""),
            r.get("label", ""),
            r.get("status", ""),
            r.get("word_count", ""),
            r.get("sentiment", {}).get("label", "") if r.get("status") == "success" else "",
            r.get("sentiment", {}).get("score", "") if r.get("status") == "success" else "",
            ", ".join(r.get("tone", [])) if r.get("status") == "success" else "",
            ", ".join([k["word"] for k in r.get("keywords", [])[:3]]) if r.get("status") == "success" else "",
            len(r.get("entities", [])) if r.get("status") == "success" else "",
            r.get("summary", "") if r.get("status") == "success" else r.get("error", ""),
            r.get("text_preview", "")
        ])

    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=batch_analysis.csv"}
    )

@app.post("/timeline")
def timeline(body: TextInput):
    if not body.text or len(body.text.strip()) < 20:
        raise HTTPException(status_code=400, detail="Text too short")

    prompt = f"""Extract a chronological timeline from this text.

IMPORTANT: Your entire response must be ONLY a raw JSON object.
Do NOT use markdown. Do NOT use backticks. Do NOT add any explanation.
Start your response with {{ and end with }}

Text: \"\"\"{body.text[:3000]}\"\"\"

Return exactly this structure:
{{
  "title": "short descriptive title for this timeline",
  "events": [
    {{
      "date": "exact date or period as written in text",
      "date_normalized": "YYYY-MM-DD or YYYY-MM or YYYY",
      "event": "plain English description of what happened",
      "parties": ["person or org involved"],
      "amount": "$X or null if no amount",
      "significance": "high|medium|low",
      "category": "legal|financial|operational|communication|other"
    }}
  ],
  "date_range": {{
    "start": "earliest date in YYYY-MM-DD",
    "end": "latest date in YYYY-MM-DD"
  }},
  "key_parties": ["list of main people and organizations"],
  "total_financial_impact": "total dollar amount if calculable, else null"
}}

Rules:
- Extract ALL dates mentioned in chronological order
- significance: high=major event, medium=supporting, low=background
- Max 20 events"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text
        cleaned = clean_json(raw)
        parsed = json.loads(cleaned)
        return parsed
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"JSON parse error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/history")
def history(
    sentiment: str = Query(None),
    keyword:   str = Query(None),
    limit:     int = Query(20)
):
    results = query_analyses(sentiment=sentiment, keyword=keyword, limit=limit)
    return {"count": len(results), "results": results}

@app.get("/stats")
def stats():
    return get_stats()