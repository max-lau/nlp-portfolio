"""
ocr_intake.py
=============
FastAPI APIRouter: OCR Intake Module
Uses Claude Vision API for handwriting (primary) and
Tesseract for printed/typed text (fallback).

Endpoints:
  POST /intake/scan      - upload image/PDF → extract text only
  POST /intake/analyze   - upload image/PDF → text + full NLP analysis
  POST /intake/form      - upload image/PDF → structured intake form fields
  GET  /intake/history   - view past intake scans
"""

import os
import io
import re
import base64
import sqlite3
from datetime import datetime, timezone
from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from typing import Optional
from PIL import Image
import pytesseract
import anthropic

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

router  = APIRouter()
DB_PATH = "backend/demo1/analyses.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_intake_table():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS intake_scans (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            filename      TEXT,
            raw_text      TEXT,
            word_count    INTEGER,
            confidence    REAL,
            ocr_engine    TEXT,
            sentiment     TEXT,
            risk_score    REAL,
            risk_level    TEXT,
            entities_json TEXT,
            form_fields   TEXT,
            created_at    TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("[Intake] OCR table initialized ✓")


# ── Claude Vision OCR ──────────────────────────────────────────────────────────

def ocr_with_claude(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """Use Claude Vision to transcribe handwritten/scanned documents."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    b64_image = base64.standard_b64encode(image_bytes).decode("utf-8")

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": b64_image,
                    }
                },
                {
                    "type": "text",
                    "text": """Transcribe ALL text in this document image exactly as written.
Rules:
- Preserve line breaks and labels (Client:, Date:, etc.)
- Transcribe every word and number visible
- Return ONLY the transcribed text, no commentary."""
                }
            ]
        }]
    )

    text = response.content[0].text.strip()
    return {
        "text":       text,
        "word_count": len(text.split()),
        "confidence": 95.0,
        "engine":     "claude-vision",
    }


# ── Tesseract OCR ──────────────────────────────────────────────────────────────

def ocr_with_tesseract(image_bytes: bytes, lang: str = "eng") -> dict:
    """Tesseract OCR — good for printed text."""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")

        data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
        confidences = [int(c) for c in data["conf"] if int(c) > 30]
        raw_text = pytesseract.image_to_string(image, lang=lang).strip()
        avg_conf  = round(sum(confidences) / len(confidences), 1) if confidences else 0

        return {
            "text":       raw_text,
            "word_count": len(raw_text.split()),
            "confidence": avg_conf,
            "engine":     "tesseract",
        }
    except Exception as e:
        raise HTTPException(400, f"OCR failed: {str(e)}")


# ── Smart dispatcher ───────────────────────────────────────────────────────────

def extract_text(image_bytes: bytes, lang: str = "eng",
                 engine: str = "auto", mime_type: str = "image/jpeg") -> dict:
    if engine == "tesseract":
        return ocr_with_tesseract(image_bytes, lang)
    try:
        return ocr_with_claude(image_bytes, mime_type)
    except Exception as e:
        print(f"[Intake] Claude Vision failed, falling back to Tesseract: {e}")
        return ocr_with_tesseract(image_bytes, lang)


def clean_ocr_text(text: str) -> str:
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


# ── Form field extractor ───────────────────────────────────────────────────────

def extract_form_fields(text: str) -> dict:
    fields = {
        "client_name":    None,
        "date":           None,
        "matter_type":    None,
        "opposing_party": None,
        "phone":          None,
        "email":          None,
        "key_facts":      [],
        "urgent":         False,
    }
    text_lower = text.lower()

    # Client name
    for p in [r'client\s*:\s*([A-Z][a-z]+ [A-Z][a-z]+)',
               r'name\s*:\s*([A-Z][a-z]+ [A-Z][a-z]+)']:
        m = re.search(p, text, re.IGNORECASE)
        if m: fields["client_name"] = m.group(1).strip(); break

    # Date
    for p in [r'date\s*:\s*([A-Za-z]+ \d{1,2},?\s*\d{4})',
               r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
               r'\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\b']:
        m = re.search(p, text, re.IGNORECASE)
        if m: fields["date"] = (m.group(1) if m.lastindex else m.group(0)).strip(); break

    # Matter type — explicit label first
    matter_m = re.search(r'matter\s*:\s*(.+?)(?:\n|$)', text, re.IGNORECASE)
    if matter_m:
        fields["matter_type"] = matter_m.group(1).strip()
    else:
        matter_map = {
            "employment":  ["wrongful termination", "fired", "terminated", "harassment", "employer"],
            "criminal":    ["indicted", "charged", "criminal", "felony", "arrest"],
            "civil":       ["lawsuit", "civil", "damages", "negligence"],
            "immigration": ["visa", "green card", "deportation", "asylum"],
            "real estate": ["property", "lease", "mortgage", "landlord"],
            "family":      ["divorce", "custody", "child support", "alimony"],
        }
        for matter, keywords in matter_map.items():
            if any(kw in text_lower for kw in keywords):
                fields["matter_type"] = matter; break

    # Phone
    m = re.search(r'\b(\(?\d{3}\)?[\s\-\.]\d{3}[\s\-\.]\d{4})\b', text)
    if m: fields["phone"] = m.group(1)

    # Email
    m = re.search(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b', text)
    if m: fields["email"] = m.group(0)

    # Urgency
    fields["urgent"] = any(kw in text_lower for kw in
        ["urgent", "asap", "immediately", "emergency", "deadline"])

    # Key facts
    legal_kws = ["terminated", "fired", "severance", "service", "charged",
                 "arrested", "contract", "damages", "employer", "years"]
    for sent in re.split(r'[.!?\n]+', text):
        if any(kw in sent.lower() for kw in legal_kws) and len(sent.strip()) > 15:
            fields["key_facts"].append(sent.strip())
    fields["key_facts"] = fields["key_facts"][:5]

    return fields


def pdf_to_image_bytes(pdf_bytes: bytes) -> bytes:
    from pdf2image import convert_from_bytes
    pages = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=200)
    if not pages:
        raise HTTPException(400, "Could not read PDF")
    buf = io.BytesIO()
    pages[0].save(buf, format="PNG")
    return buf.getvalue()


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/scan")
async def scan_document(
    file: UploadFile = File(...),
    lang: str = Form(default="eng"),
    engine: str = Form(default="auto")
):
    """Upload image/PDF → extract text via OCR."""
    contents = await file.read()
    mime_type = file.content_type
    if file.content_type == "application/pdf":
        contents = pdf_to_image_bytes(contents); mime_type = "image/png"

    result = extract_text(contents, lang=lang, engine=engine, mime_type=mime_type)
    result["text"] = clean_ocr_text(result["text"])

    conn = get_conn()
    conn.execute("INSERT INTO intake_scans (filename,raw_text,word_count,confidence,ocr_engine,created_at) VALUES (?,?,?,?,?,?)",
        (file.filename, result["text"], result["word_count"], result["confidence"], result["engine"], datetime.now(timezone.utc).isoformat()))
    conn.commit(); conn.close()

    return {"success": True, "filename": file.filename, **result}


@router.post("/analyze")
async def analyze_document(
    file: UploadFile = File(...),
    lang: str = Form(default="eng"),
    context: str = Form(default="general"),
    engine: str = Form(default="auto")
):
    """Upload image/PDF → OCR → full NLP pipeline."""
    import json
    contents = await file.read()
    mime_type = file.content_type
    if file.content_type == "application/pdf":
        contents = pdf_to_image_bytes(contents); mime_type = "image/png"

    ocr_result = extract_text(contents, lang=lang, engine=engine, mime_type=mime_type)
    text = clean_ocr_text(ocr_result["text"])

    if not text or len(text.split()) < 3:
        return {"success": False, "error": "Could not extract readable text.", "ocr_confidence": ocr_result["confidence"]}

    from backend.demo1.risk_scorer import score_text
    risk = score_text(text, context=context)

    import spacy
    nlp = spacy.load("en_core_web_sm")
    entities = [{"text": e.text, "type": e.label_} for e in nlp(text[:5000]).ents]

    from backend.demo1.custom_entities import extract_custom_entities
    custom_ents = extract_custom_entities(text)

    form_fields = extract_form_fields(text)

    conn = get_conn()
    conn.execute("""INSERT INTO intake_scans
        (filename,raw_text,word_count,confidence,ocr_engine,risk_score,risk_level,entities_json,form_fields,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (file.filename, text, ocr_result["word_count"], ocr_result["confidence"], ocr_result["engine"],
         risk["score"], risk["level"], json.dumps(entities), json.dumps(form_fields),
         datetime.now(timezone.utc).isoformat()))
    conn.commit(); conn.close()

    return {
        "success": True, "filename": file.filename,
        "ocr":     {"text": text, "word_count": ocr_result["word_count"],
                    "confidence": ocr_result["confidence"], "engine": ocr_result["engine"]},
        "risk":    {"score": risk["score"], "level": risk["level"],
                    "top_signals": risk["top_signals"][:3], "category_breakdown": risk["category_breakdown"]},
        "entities": entities[:20], "custom_entities": custom_ents[:15],
        "form_fields": form_fields,
    }


@router.post("/form")
async def extract_intake_form(
    file: UploadFile = File(...),
    lang: str = Form(default="eng"),
    engine: str = Form(default="auto")
):
    """Upload handwritten intake form → extract structured fields."""
    contents = await file.read()
    mime_type = file.content_type
    if file.content_type == "application/pdf":
        contents = pdf_to_image_bytes(contents); mime_type = "image/png"

    ocr_result = extract_text(contents, lang=lang, engine=engine, mime_type=mime_type)
    text = clean_ocr_text(ocr_result["text"])

    return {
        "success": True, "filename": file.filename,
        "raw_text": text, "confidence": ocr_result["confidence"],
        "engine": ocr_result["engine"], "form_fields": extract_form_fields(text),
    }


@router.get("/history")
def intake_history(limit: int = 20):
    import json
    conn = get_conn()
    rows = conn.execute("SELECT * FROM intake_scans ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        for f in ("entities_json", "form_fields"):
            if d.get(f):
                try: d[f] = json.loads(d[f])
                except: pass
        results.append(d)
    return {"success": True, "count": len(results), "scans": results}


@router.get("/supported-languages")
def supported_languages():
    return {
        "languages": [
            {"code": "eng", "name": "English"},
            {"code": "chi_sim", "name": "Chinese Simplified"},
            {"code": "chi_tra", "name": "Chinese Traditional"},
            {"code": "spa", "name": "Spanish"},
            {"code": "fra", "name": "French"},
            {"code": "deu", "name": "German"},
        ],
        "engines": [
            {"id": "auto",      "name": "Auto (Claude Vision → Tesseract fallback)"},
            {"id": "claude",    "name": "Claude Vision (best for handwriting)"},
            {"id": "tesseract", "name": "Tesseract (best for printed text)"},
        ]
    }

@router.post("/test-upload")
async def test_upload(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        print(f"[TEST] File received: {file.filename}, size: {len(contents)}, type: {file.content_type}")
        result = ocr_with_claude(contents, file.content_type)
        print(f"[TEST] Claude result: {result['text'][:100]}")
        return {"success": True, "text": result["text"], "engine": result["engine"]}
    except Exception as e:
        import traceback
        print(f"[TEST] ERROR: {e}")
        traceback.print_exc()
        return {"success": False, "error": str(e)}

@router.post("/analyze2")
async def analyze_document2(
    file: UploadFile = File(...),
    lang: str = Form(default="eng"),
    context: str = Form(default="general"),
    engine: str = Form(default="auto")
):
    import traceback
    try:
        contents = await file.read()
        mime_type = file.content_type
        print(f"[ANALYZE2] Got file: {file.filename}, {len(contents)} bytes, {mime_type}")
        
        ocr_result = extract_text(contents, lang=lang, engine=engine, mime_type=mime_type)
        text = clean_ocr_text(ocr_result["text"])
        print(f"[ANALYZE2] OCR done: {len(text)} chars")
        
        from backend.demo1.risk_scorer import score_text
        risk = score_text(text, context=context)
        print(f"[ANALYZE2] Risk done: {risk['score']}")
        
        import spacy
        nlp = spacy.load("en_core_web_sm")
        entities = [{"text": e.text, "type": e.label_} for e in nlp(text[:5000]).ents]
        print(f"[ANALYZE2] Entities done: {len(entities)}")
        
        from backend.demo1.custom_entities import extract_custom_entities
        custom_ents = extract_custom_entities(text)
        print(f"[ANALYZE2] Custom entities done: {len(custom_ents)}")
        
        form_fields = extract_form_fields(text)
        print(f"[ANALYZE2] Form fields done: {form_fields}")
        
        return {
            "success": True,
            "ocr": {"text": text, "word_count": ocr_result["word_count"],
                    "confidence": ocr_result["confidence"], "engine": ocr_result["engine"]},
            "risk": {"score": risk["score"], "level": risk["level"]},
            "entities": entities[:20],
            "custom_entities": custom_ents[:15],
            "form_fields": form_fields,
        }
    except Exception as e:
        print(f"[ANALYZE2] ERROR: {e}")
        traceback.print_exc()
        return {"success": False, "error": str(e)}

