from backend.demo1.ocr_intake import init_intake_table, router as intake_router
from backend.demo1.fine_tune import init_model_table, router as model_router
from backend.demo1.slack_teams import init_notify_table, router as notify_router
from backend.demo1.auth import init_auth_table, router as auth_router
from backend.demo1.custom_entities import init_custom_entity_table, router as custom_entities_router
from backend.demo1.webhook import init_webhook_table, router as webhook_router
from backend.demo1.pdf_export import router as pdf_router
from backend.demo1.pdf_module_export import router as module_pdf_router
from backend.demo1.interrogation_export import router as interrogation_export_router
from backend.demo1.audit_trail import AuditMiddleware, init_audit_table, router as audit_router
from backend.demo1.risk_scorer import router as risk_router
from backend.demo1.document_comparison import router as comparison_router
from backend.demo1.citation_resolver import router as citations_router
from backend.demo1.case_management   import router as cases_router
from backend.demo1.pacer_integration import router as pacer_router
from backend.demo1.multilingual import analyze_multilingual, detect_language, SUPPORTED_LANGUAGES
from backend.demo1.summary_scorer import score_summary, batch_score_summaries
from backend.demo1.entity_confidence import score_entities, get_entity_summary
from backend.demo1.entity_linker import find_linked_entities, link_documents_by_entity
from backend.demo1.entity_confidence import score_entities, get_entity_summary
from backend.demo1.coref_disambig import disambiguate_entities, resolve_coreferences
from backend.demo1.contradiction import run_contradiction_scan
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
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

# ── API Key Auth Middleware ───────────────────────────────────────────────────

PARAIQ_API_KEY = os.getenv("PARAIQ_API_KEY", "")

EXEMPT_PATHS = {"/health", "/openapi.json", "/docs", "/redoc", "/favicon.ico"}
EXEMPT_PREFIXES = ("/docs/", "/redoc/")

class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Always allow OPTIONS (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)
        # Allow exempt paths
        path = request.url.path
        if path in EXEMPT_PATHS or any(path.startswith(p) for p in EXEMPT_PREFIXES):
            return await call_next(request)
        # Check key
        key = request.headers.get("X-API-Key", "")
        if not PARAIQ_API_KEY or key != PARAIQ_API_KEY:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"}
            )
        return await call_next(request)

app = FastAPI(title="NLP Text Analyzer API")
app.add_middleware(APIKeyMiddleware)
app.include_router(intake_router, prefix="/intake", tags=["OCR Intake"])
app.include_router(model_router, prefix="/model", tags=["Fine-Tuned Model"])
app.include_router(notify_router, prefix="/notify", tags=["Slack & Teams"])
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(custom_entities_router, prefix="/entities/custom", tags=["Custom Entities"])
app.include_router(webhook_router, prefix="/webhooks", tags=["Webhooks"])
app.include_router(pdf_router, prefix="/export", tags=["PDF Export"])
app.include_router(module_pdf_router, prefix="/export", tags=["PDF Export"])
app.include_router(interrogation_export_router, tags=["Interrogation Export"])
app.add_middleware(AuditMiddleware)
app.include_router(audit_router, prefix="/audit", tags=["Audit Trail"])
app.include_router(risk_router, prefix="/risk", tags=["Risk Scoring"])
app.include_router(comparison_router, prefix="/documents", tags=["Document Comparison"])
app.include_router(citations_router, prefix="/citations", tags=["Citation Resolver"])
app.include_router(cases_router, prefix="/cases", tags=["Case Management"])
app.include_router(pacer_router, prefix="/pacer",  tags=["PACER"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()
init_audit_table()
init_webhook_table()
init_custom_entity_table()
init_auth_table()
init_notify_table()
init_model_table()
init_intake_table()
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


# ── Interrogation Analyzer ────────────────────────────────────────────────────

class InterrogationInput(BaseModel):
    transcript: str

@app.post("/interrogate")
def interrogate(body: InterrogationInput):
    if not body.transcript or len(body.transcript.strip()) < 20:
        raise HTTPException(status_code=400, detail="Transcript too short")
    prompt = f"""You are a legal transcript analyst. Analyze the following interrogation or deposition transcript for contradictions and evasions.

Return ONLY valid JSON with this exact structure — no markdown, no backticks, no preamble:
{{
  "contradictions": [
    {{
      "title": "Short descriptive title",
      "explanation": "What contradicts what, and why it matters legally.",
      "quote_a": "First statement verbatim from transcript",
      "quote_b": "Contradicting statement verbatim from transcript"
    }}
  ],
  "evasions": [
    {{
      "title": "Short descriptive title",
      "explanation": "Why this response is evasive, non-responsive, or inconsistent.",
      "quote": "The evasive statement verbatim from transcript"
    }}
  ]
}}

If there are no contradictions or no evasions, return empty arrays. Be precise and legally rigorous.

Transcript:
{body.transcript[:6000]}"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text
        cleaned = clean_json(raw)
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"JSON parse error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -- Lease Clause Diff --

class LeaseDiffInput(BaseModel):
    doc_a: str
    doc_b: str

@app.post("/documents/lease-diff")
def lease_diff(body: LeaseDiffInput):
    da = body.doc_a[:4000]
    db = body.doc_b[:4000]
    prompt = "\n".join([
        "You are a legal analyst specializing in lease contracts.",
        "Compare these two lease versions and identify all clause changes.",
        "Return ONLY valid JSON, no markdown, no backticks:",
        '{"key_term_changes":["example: Rent $3500 to $3750"],',
        '"added":[{"clause":"Name","detail":"description"}],',
        '"removed":[{"clause":"Name","detail":"description"}],',
        '"modified":[{"clause":"Name","change":"what changed"}]}',
        "", "Lease A:", da, "", "Lease B:", db
    ])
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        return json.loads(clean_json(msg.content[0].text))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail="JSON parse error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Witness Credibility Scorer ────────────────────────────────────────────────

class CredibilityInput(BaseModel):
    transcript: str
    witness_name: str = "Witness"
    role: str = "Witness"
    case_name: str = ""

@app.post("/credibility/score")
def credibility_score(body: CredibilityInput):
    t = body.transcript[:6000]
    w = body.witness_name
    lines = [
        f"You are an expert legal analyst scoring the credibility of a witness named {w}.",
        "Analyze the provided testimony transcript and score the witness on 5 dimensions (0-10 each).",
        "Return ONLY valid JSON, no markdown, no backticks:",
        '{',
        '  "overall_score": 6.2,',
        '  "summary": "One sentence overall credibility assessment.",',
        '  "scores": {',
        '    "consistency": {"score": 7, "explanation": "explanation", "key_quote": "verbatim quote from transcript"},',
        '    "responsiveness": {"score": 6, "explanation": "explanation", "key_quote": "verbatim quote"},',
        '    "clarity": {"score": 5, "explanation": "explanation", "key_quote": "verbatim quote"},',
        '    "corroboration": {"score": 4, "explanation": "explanation", "key_quote": "verbatim quote"},',
        '    "demeanor": {"score": 3, "explanation": "explanation", "key_quote": "verbatim quote"}',
        '  },',
        '  "key_findings": [',
        '    {"type": "strength", "finding": "positive credibility observation"},',
        '    {"type": "concern", "finding": "credibility concern or red flag"}',
        '  ]',
        '}',
        '',
        'Scoring guide:',
        '- consistency: 10=no contradictions, 0=major self-contradictions',
        '- responsiveness: 10=answers all questions directly, 0=never answers directly',
        '- clarity: 10=clear precise language, 0=vague hedging throughout',
        '- corroboration: 10=testimony matches all evidence cited, 0=contradicts all evidence',
        '- demeanor: 10=calm direct confident, 0=evasive hesitant deflecting throughout',
        '',
        f'Transcript of {w}:',
        t
    ]
    prompt = chr(10).join(lines)

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text
        return json.loads(clean_json(raw))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail="JSON parse error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Deposition Summary Generator ─────────────────────────────────────────────

class DepositionInput(BaseModel):
    transcript: str
    case_name: str = "Untitled Matter"
    deponent: str = "Witness"
    exam_counsel: str = ""
    depos_date: str = ""

@app.post("/deposition/summarize")
def deposition_summarize(body: DepositionInput):
    t = body.transcript[:7000]
    lines = [
        "You are an expert legal analyst. Analyze this deposition transcript and extract a structured summary.",
        "Return ONLY valid JSON, no markdown, no backticks:",
        "{",
        '  "case_overview": {',
        '    "case_name": "case name",',
        '    "deponent": "witness name",',
        '    "date": "deposition date",',
        '    "examining_counsel": "counsel name",',
        '    "summary": "2-3 sentence overview of the deposition and its significance"',
        "  },",
        '  "parties": [',
        '    {"name": "full name", "role": "Deponent/Attorney/Judge", "representation": "firm or party represented"}',
        "  ],",
        '  "key_admissions": [',
        '    {"admission": "what the deponent admitted", "significance": "why it matters legally", "quote": "verbatim quote"}',
        "  ],",
        '  "disputed_facts": [',
        '    {"fact": "the disputed fact", "deponent_position": "what deponent claims", "contrary_evidence": "evidence that contradicts"}',
        "  ],",
        '  "timeline": [',
        '    {"date_or_period": "specific date or period", "event": "what happened", "source": "who stated this"}',
        "  ],",
        '  "legal_issues": [',
        '    {"issue": "legal issue raised", "context": "context and relevance", "objections": "any objections or rulings"}',
        "  ]",
        "}",
        "",
        f"Case: {body.case_name}",
        f"Deponent: {body.deponent}",
        f"Examining Counsel: {body.exam_counsel}",
        f"Date: {body.depos_date}",
        "",
        "Transcript:",
        t
    ]
    prompt = chr(10).join(lines)

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text
        return json.loads(clean_json(raw))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail="JSON parse error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

