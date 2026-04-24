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
        raise HTTPException(status_code=400, detail="Text too short")

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
    "summary": "one sentence about overall risk profile"
  }},
  "risk_flags": [
    {{
      "severity": "high",
      "title": "Short flag name",
      "description": "Plain English explanation"
    }}
  ],
  "clauses": [
    {{
      "type": "indemnification",
      "text": "exact short excerpt max 80 chars",
      "note": "brief plain English note"
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
      "obligation": "plain English description max 80 chars"
    }}
  ],
  "plain_summary": "2-3 sentence plain English summary",
  "completeness_score": 72,
  "favor_party": "Disclosing Party"
}}

Rules:
- risk.level must be: low medium high critical
- risk.score is 0-100
- risk_flags: max 4, severity: high medium low
- clauses: max 6, type: indemnification termination payment confidentiality jurisdiction arbitration liability ip other
- entities: max 8, type: party date money jurisdiction other
- obligations: max 6
- favor_party: name or balanced"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw     = message.content[0].text
        print(f"\n--- RAW ---\n{raw}\n--- END ---\n")
        cleaned = clean_json(raw)
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"JSON parse error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/criminal/score")
def criminal_score(body: LegalInput):
    """Risk scoring specifically for criminal complaints."""
    if not body.text or len(body.text.strip()) < 50:
        raise HTTPException(status_code=400, detail="Text too short")

    prompt = f"""You are a criminal law NLP analyst. Analyze this criminal complaint
and return a comprehensive risk assessment.

IMPORTANT: Your entire response must be ONLY a raw JSON object.
Do NOT use markdown. Do NOT use backticks. Do NOT add any explanation.
Start your response with {{ and end with }}

Criminal complaint text: \"\"\"{body.text[:4000]}\"\"\"

Return exactly this structure:
{{
  "case_overview": {{
    "case_number": "extracted case number or null",
    "court": "court name",
    "jurisdiction": "jurisdiction",
    "date_filed": "YYYY-MM-DD or null",
    "document_type": "criminal complaint|indictment|information|other"
  }},
  "defendant": {{
    "name": "defendant name",
    "address": "address or null",
    "criminal_history_mentioned": false,
    "flight_risk_indicators": ["list any mentioned indicators or empty array"]
  }},
  "charges": [
    {{
      "count": 1,
      "charge": "full charge name",
      "statute": "statute citation e.g. PL 155.40",
      "felony_class": "A|B|C|D|E|misdemeanor|violation",
      "max_sentence_years": 0,
      "severity_score": 0,
      "description": "plain English description of what this charge means"
    }}
  ],
  "risk_assessment": {{
    "overall_score": 75,
    "level": "low|medium|high|critical",
    "prosecution_strength": "weak|moderate|strong|overwhelming",
    "factors": [
      {{
        "factor": "factor name",
        "impact": "aggravating|mitigating",
        "description": "plain English explanation"
      }}
    ]
  }},
  "financial": {{
    "amount_stolen": "dollar amount or null",
    "restitution_likely": true,
    "fine_exposure": "estimated range or null",
    "assets_mentioned": ["list any assets mentioned"]
  }},
  "evidence": {{
    "strength": "weak|moderate|strong|overwhelming",
    "types": ["documentary","forensic","witness","digital","financial"],
    "key_evidence": ["list key evidence items mentioned"]
  }},
  "sentencing_exposure": {{
    "min_years": 0,
    "max_years": 0,
    "likely_range": "e.g. 3-7 years",
    "factors_that_increase": ["list aggravating factors"],
    "factors_that_decrease": ["list mitigating factors"],
    "notes": "plain English sentencing context"
  }},
  "victim_profile": {{
    "type": "individual|corporation|government|multiple",
    "name": "victim name or null",
    "impact": "plain English description of victim impact"
  }},
  "plain_summary": "3-4 sentence plain English summary of the case for a non-lawyer",
  "defense_vulnerabilities": ["list potential defense arguments or weaknesses in the case"],
  "similar_cases_outcome": "brief note on typical outcomes for similar charges"
}}

Rules:
- severity_score per charge: 0-100 (100 = most severe)
- overall_score: 0-100 weighted across all factors
- Be precise with statute citations if mentioned
- max_sentence_years: use 0 if not determinable
- prosecution_strength based on evidence described"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw     = message.content[0].text
        print(f"\n--- CRIMINAL SCORE RAW ---\n{raw}\n--- END ---\n")
        cleaned = clean_json(raw)
        parsed  = json.loads(cleaned)

        # Add computed fields
        charges = parsed.get("charges", [])
        parsed["charge_count"]    = len(charges)
        parsed["max_severity"]    = max((c.get("severity_score", 0) for c in charges), default=0)
        parsed["total_max_years"] = sum(c.get("max_sentence_years", 0) for c in charges)

        return parsed
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"JSON parse error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
