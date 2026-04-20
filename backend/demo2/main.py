from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import anthropic
import os
import json
import re

load_dotenv()

app = FastAPI(title="Legal Document Intelligence API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

class LegalInput(BaseModel):
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
def analyze(body: LegalInput):
    if not body.text or len(body.text.strip()) < 50:
        raise HTTPException(status_code=400, detail="Text too short — need at least 50 characters")

    prompt = f"""You are a legal NLP analyst. Analyze this legal text.

IMPORTANT: Your entire response must be ONLY a raw JSON object.
Do NOT use markdown. Do NOT use backticks. Do NOT add any explanation.
Start your response with {{ and end with }}

Legal text: \"\"\"{body.text[:3000]}\"\"\"

Return exactly this structure:
{{
  "risk": {{
    "level": "low",
    "score": 35,
    "summary": "one sentence about the overall risk profile"
  }},
  "risk_flags": [
    {{
      "severity": "high",
      "title": "Short flag name",
      "description": "Plain English explanation of what this risk means"
    }}
  ],
  "clauses": [
    {{
      "type": "indemnification",
      "text": "exact short excerpt from the document max 80 chars",
      "note": "brief plain English note about this clause"
    }}
  ],
  "entities": [
    {{
      "text": "Vertex Capital Partners LLC",
      "type": "party"
    }}
  ],
  "obligations": [
    {{
      "party": "Receiving Party",
      "obligation": "plain English description of what they must do"
    }}
  ],
  "plain_summary": "2-3 sentence plain English summary of what this document does and what each party must do",
  "completeness_score": 72,
  "favor_party": "Disclosing Party"
}}

Rules:
- risk.level must be one of: low medium high critical
- risk.score is 0-100
- risk_flags: max 4 items, severity must be: high medium low
- clauses: max 6 items, type must be one of: indemnification termination payment confidentiality jurisdiction arbitration liability ip other
- entities: max 8 items, type must be one of: party date money jurisdiction other
- obligations: max 6 items
- completeness_score is 0-100
- favor_party: name of favored party or the word balanced"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text
        print(f"\n--- RAW RESPONSE ---\n{raw}\n--- END ---\n")
        cleaned = clean_json(raw)
        parsed = json.loads(cleaned)
        return parsed
    except json.JSONDecodeError as e:
        print(f"JSON ERROR: {e}\nRaw was: {raw}")
        raise HTTPException(status_code=500, detail=f"JSON parse error: {str(e)} | Raw: {raw[:300]}")
    except Exception as e:
        print(f"GENERAL ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))
