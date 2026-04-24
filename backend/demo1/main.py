from backend.demo1.multilingual import analyze_multilingual, detect_language, SUPPORTED_LANGUAGES
from backend.demo1.summary_scorer import score_summary, batch_score_summaries
from backend.demo1.entity_confidence import score_entities, get_entity_summary
from backend.demo1.entity_linker import find_linked_entities, link_documents_by_entity
from backend.demo1.entity_confidence import score_entities, get_entity_summary
from backend.demo1.coref_disambig import disambiguate_entities, resolve_coreferences
from backend.demo1.contradiction import run_contradiction_scan
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from backend.demo1.database import (
    init_db, save_analysis, query_analyses, get_stats,
    save_feedback, get_feedback_queue, mark_reviewed, get_retraining_data
)
import anthropic
import os
import json
import re
import csv
import io
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

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
    labels: List[str] = []

class FeedbackInput(BaseModel):
    analysis_id: int
    text: str
    predicted: str
    predicted_score: float
    corrected: str
    feedback_type: str = "sentiment_correction"
    notes: str = ""

class ReviewInput(BaseModel):
    feedback_id: int

def clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return raw.strip()

def run_analysis(text: str, label: str = "") -> dict:
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
        raw     = message.content[0].text
        cleaned = clean_json(raw)
        parsed  = json.loads(cleaned)
        row_id  = save_analysis(text, parsed)
        parsed["id"]           = row_id
	# Score entities with confidence and salience
        if parsed.get("entities"):
            parsed["entities"] = score_entities(text, parsed["entities"])
            parsed["entity_summary"] = get_entity_summary(parsed["entities"])
        parsed["label"]        = label
        parsed["status"]       = "success"
        parsed["text_preview"] = text[:120] + "..." if len(text) > 120 else text
        parsed["word_count"]   = len(text.split())

        # Auto-flag low confidence for active learning
        score = parsed.get("sentiment", {}).get("score", 1.0)
        if score < 0.70:
            save_feedback(
                analysis_id     = row_id,
                text            = text[:500],
                predicted       = parsed.get("sentiment", {}).get("label", ""),
                predicted_score = score,
                corrected       = "",
                feedback_type   = "low_confidence",
                notes           = f"Auto-flagged: confidence {score:.2f} below threshold 0.70"
            )
            parsed["flagged"] = True
            parsed["flag_reason"] = f"Low confidence ({score:.0%}) — queued for human review"
        else:
            parsed["flagged"] = False

        return parsed
    except Exception as e:
        return {
            "status": "error", "error": str(e), "label": label,
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
    return run_analysis(body.text)

@app.post("/analyze/batch")
async def analyze_batch(body: BatchInput):
    if not body.documents:
        raise HTTPException(status_code=400, detail="No documents provided")
    if len(body.documents) > 20:
        raise HTTPException(status_code=400, detail="Max 20 documents per batch")
    labels = body.labels + [""] * (len(body.documents) - len(body.labels))
    loop   = asyncio.get_event_loop()
    tasks  = [
        loop.run_in_executor(executor, run_analysis, doc, label)
        for doc, label in zip(body.documents, labels)
    ]
    results    = await asyncio.gather(*tasks)
    successful = [r for r in results if r.get("status") == "success"]
    failed     = [r for r in results if r.get("status") == "error"]
    sentiments = [r.get("sentiment", {}).get("label", "") for r in successful]
    flagged    = [r for r in successful if r.get("flagged")]
    return {
        "total": len(results), "successful": len(successful),
        "failed": len(failed), "flagged": len(flagged),
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
    if not body.documents:
        raise HTTPException(status_code=400, detail="No documents provided")
    if len(body.documents) > 20:
        raise HTTPException(status_code=400, detail="Max 20 documents per batch")
    labels = body.labels + [""] * (len(body.documents) - len(body.labels))
    loop   = asyncio.get_event_loop()
    tasks  = [
        loop.run_in_executor(executor, run_analysis, doc, label)
        for doc, label in zip(body.documents, labels)
    ]
    results = await asyncio.gather(*tasks)
    output  = io.StringIO()
    writer  = csv.writer(output)
    writer.writerow([
        "id", "label", "status", "word_count", "sentiment", "score",
        "tone", "top_keywords", "entity_count", "flagged", "summary", "text_preview"
    ])
    for r in results:
        writer.writerow([
            r.get("id", ""), r.get("label", ""), r.get("status", ""),
            r.get("word_count", ""),
            r.get("sentiment", {}).get("label", "") if r.get("status") == "success" else "",
            r.get("sentiment", {}).get("score", "") if r.get("status") == "success" else "",
            ", ".join(r.get("tone", [])) if r.get("status") == "success" else "",
            ", ".join([k["word"] for k in r.get("keywords", [])[:3]]) if r.get("status") == "success" else "",
            len(r.get("entities", [])) if r.get("status") == "success" else "",
            r.get("flagged", False),
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
    "end":   "latest date in YYYY-MM-DD"
  }},
  "key_parties": ["list of main people and organizations"],
  "total_financial_impact": "total dollar amount if calculable, else null"
}}

Rules: extract ALL dates in chronological order, max 20 events."""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw     = message.content[0].text
        cleaned = clean_json(raw)
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"JSON parse error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Active learning endpoints ─────────────────────────────────────────────────

@app.post("/feedback")
def submit_feedback(body: FeedbackInput):
    """Submit a human correction for a model prediction."""
    row_id = save_feedback(
        analysis_id     = body.analysis_id,
        text            = body.text,
        predicted       = body.predicted,
        predicted_score = body.predicted_score,
        corrected       = body.corrected,
        feedback_type   = body.feedback_type,
        notes           = body.notes
    )
    return {
        "feedback_id": row_id,
        "message": "Feedback saved — added to retraining queue",
        "retraining_trigger": "Queue this sample for next model update"
    }

@app.get("/feedback/queue")
def feedback_queue():
    """Get all pending items awaiting human review."""
    items = get_feedback_queue(reviewed=False)
    return {
        "pending": len(items),
        "items": items
    }

@app.post("/feedback/review")
def review_feedback(body: ReviewInput):
    """Mark a feedback item as reviewed."""
    mark_reviewed(body.feedback_id)
    return {"message": f"Feedback {body.feedback_id} marked as reviewed"}

@app.get("/feedback/retraining-data")
def retraining_data():
    """Export all corrected samples ready for model retraining."""
    samples = get_retraining_data()
    return {
        "total_samples": len(samples),
        "message": f"{len(samples)} corrected samples ready for retraining",
        "samples": samples
    }

@app.get("/history")
def history(
    sentiment: str = Query(None),
    keyword:   str = Query(None),
    limit:     int = Query(20)
):
    results = query_analyses(sentiment=sentiment, keyword=keyword, limit=limit)
    return {"count": len(results), "results": results}

@app.post("/disambiguate")
def disambiguate(body: TextInput):
    """Resolve ambiguous entity mentions to canonical real-world forms."""
    if not body.text or len(body.text.strip()) < 20:
        raise HTTPException(status_code=400, detail="Text too short")
    return disambiguate_entities(body.text)

@app.post("/coreference")
def coreference(body: TextInput):
    """Resolve pronouns and noun phrases to their referent entities."""
    if not body.text or len(body.text.strip()) < 20:
        raise HTTPException(status_code=400, detail="Text too short")
    return resolve_coreferences(body.text)

@app.post("/entities/score")
def entities_score(body: TextInput):
    """Extract and score entities with confidence and salience metrics."""
    if not body.text or len(body.text.strip()) < 20:
        raise HTTPException(status_code=400, detail="Text too short")
    
    doc = nlp_spacy(body.text[:5000]) if hasattr(body, 'nlp_spacy') else None
    
    # Use Claude for initial extraction then score
    result = run_analysis(body.text)
    entities = result.get("entities", [])
    scored   = score_entities(body.text, entities)
    summary  = get_entity_summary(scored)
    
    return {
        "entities": scored,
        "summary":  summary,
        "text_preview": body.text[:100]
    }

@app.post("/summary/score")
def summary_score(body: TextInput):
    """
    Score a summary against its source document.
    Pass JSON with source and summary fields.
    """
    try:
        data    = json.loads(body.text)
        source  = data.get("source", "")
        summary = data.get("summary", "")
        if not source or not summary:
            raise HTTPException(
                status_code=400,
                detail="Provide JSON with 'source' and 'summary' fields"
            )
        return score_summary(source, summary)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Body must be JSON: {source: '...', summary: '...'}"
        )

@app.post("/summary/score/auto")
def summary_score_auto(body: TextInput):
    """
    Analyze text, generate summary, then immediately score it.
    One endpoint that does the full pipeline.
    """
    if not body.text or len(body.text.strip()) < 20:
        raise HTTPException(status_code=400, detail="Text too short")

    # Run full analysis to get the summary
    result  = run_analysis(body.text)
    summary = result.get("summary", "")

    if not summary:
        raise HTTPException(status_code=500, detail="No summary generated")

    # Score the summary
    score          = score_summary(body.text, summary)
    result["summary_score"] = score
    return result

@app.get("/languages")
def languages():
    """List all supported languages."""
    return {"languages": SUPPORTED_LANGUAGES}

@app.post("/analyze/multilingual")
def analyze_multilingual_endpoint(
    body: TextInput,
    lang: str = Query("auto", description="Language code: en, zh, es, fr, de, ja, ar, pt, auto")
):
    """Analyze text in any supported language."""
    if not body.text or len(body.text.strip()) < 10:
        raise HTTPException(status_code=400, detail="Text too short")
    return analyze_multilingual(body.text, lang)

@app.post("/detect/language")
def detect_language_endpoint(body: TextInput):
    """Detect the language of any text."""
    if not body.text or len(body.text.strip()) < 5:
        raise HTTPException(status_code=400, detail="Text too short")
    return detect_language(body.text)

@app.get("/stats")
def stats():
    return get_stats()

@app.get("/entities/link")
def entity_link(entity: str = Query(..., description="Entity name to search for")):
    """Find all documents mentioning entities similar to the query."""
    results = find_linked_entities(entity, top_k=10, threshold=0.70)
    return {
        "query":   entity,
        "matches": len(results),
        "results": results
    }

@app.get("/documents/linked")
def documents_linked():
    """Find document pairs that share linked entities."""
    pairs = link_documents_by_entity()
    return {
        "pairs_found": len(pairs),
        "pairs":       pairs
    }

@app.post("/contradictions/scan")
def contradictions_scan():
    """Scan all stored documents for factual contradictions."""
    return run_contradiction_scan()
