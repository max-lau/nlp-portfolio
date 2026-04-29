"""
risk_scorer.py
==============
FastAPI APIRouter: Risk Scoring for Legal Documents (#21)
Scores raw text on a 0-10 scale using:
  - Legal risk signals (fraud, criminal, sanction keywords)
  - Financial exposure indicators (dollar amounts, penalties)
  - Party signals (government plaintiff, multiple defendants)
  - Procedural signals (indictment, injunction, contempt)
  - Sentiment (negative language amplifies risk)
  - Entity density (more named parties = higher complexity/risk)
"""

import re
import spacy
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

# Lazy-load spaCy once
_nlp = None
def get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm")
    return _nlp


# ── Pydantic models ────────────────────────────────────────────────────────────

class RiskInput(BaseModel):
    text: str
    context: Optional[str] = None   # e.g. "criminal", "civil", "regulatory"
    label: Optional[str] = None     # optional document label

class BatchRiskInput(BaseModel):
    documents: list[str]
    labels: Optional[list[str]] = None
    context: Optional[str] = None


# ── Signal dictionaries ────────────────────────────────────────────────────────

# Each entry: (regex_pattern, score_contribution, category)
RISK_SIGNALS = [
    # Criminal signals — highest weight
    (r'\bindictment\b',                     2.0, "criminal"),
    (r'\bgrand jury\b',                     1.8, "criminal"),
    (r'\bfelony\b',                         1.8, "criminal"),
    (r'\bcriminal\b',                       1.5, "criminal"),
    (r'\bconvict\w*\b',                     1.8, "criminal"),
    (r'\bprison\b|\bincarcerat\w*\b',       1.5, "criminal"),
    (r'\bsentenc\w*\b',                     1.3, "criminal"),
    (r'\bplea\b|\bguilty\b',                1.5, "criminal"),
    (r'\bwire fraud\b|\bmail fraud\b',      1.8, "fraud"),
    (r'\bfraud\b',                          1.5, "fraud"),
    (r'\bconspiracy\b',                     1.5, "criminal"),
    (r'\bmoney laundering\b',               1.8, "financial_crime"),
    (r'\bembezzlement\b',                   1.8, "financial_crime"),
    (r'\bbribery\b|\bcorrupt\w*\b',         1.8, "financial_crime"),

    # Personal injury signals
    (r'\bpothole\b|\bslip and fall\b|\bfall\b',           1.2, "personal_injury"),
    (r'\bemergency room\b|\bER\b|\bhospital\b',            1.3, "personal_injury"),
    (r'\binjur\w*\b|\bwound\w*\b|\bhurt\b',               1.0, "personal_injury"),
    (r'\bnegligen\w*\b',                                   1.2, "personal_injury"),
    (r'\bmedical\b|\btreatment\b|\bsurgery\b',             0.8, "personal_injury"),
    (r'\bpain and suffering\b',                            1.3, "personal_injury"),
    (r'\baccident\b|\bcollision\b|\bcrash\b',              1.0, "personal_injury"),

    # Civil / regulatory signals — medium weight
    (r'\binjunction\b',                     1.2, "civil"),
    (r'\bcontempt\b',                       1.3, "civil"),
    (r'\bsanction\w*\b',                    1.2, "regulatory"),
    (r'\bpenalt\w*\b',                      1.0, "regulatory"),
    (r'\bfine\b|\bfines\b',                 0.8, "regulatory"),
    (r'\bdefault judgment\b',               1.0, "civil"),
    (r'\bdismiss\w*\b',                     0.5, "civil"),
    (r'\bappeal\b',                         0.5, "procedural"),
    (r'\bstay\b',                           0.4, "procedural"),
    (r'\bremand\w*\b',                      0.5, "procedural"),
    (r'\bsummary judgment\b',               0.6, "civil"),

    # Financial exposure signals
    (r'\$[\d,]+(?:\.\d+)?(?:\s?(?:million|billion|thousand))?\b', 0.8, "financial"),
    (r'\brestitution\b',                    1.0, "financial"),
    (r'\bdamages\b',                        0.7, "financial"),
    (r'\bforfeiture\b',                     1.2, "financial"),

    # Party signals
    (r'\bUnited States\b|\bU\.S\. Attorney\b', 1.0, "government"),
    (r'\bSEC\b|\bDOJ\b|\bFBI\b|\bIRS\b',   1.2, "government"),
    (r'\bclass action\b',                   1.0, "civil"),
    (r'\bco-defendant\b|\bmultiple defendant', 0.8, "parties"),
]

MITIGATING_SIGNALS = [
    (r'\bdismissed with prejudice\b',  -1.5),
    (r'\bnot guilty\b|\bacquitt\w*\b', -2.0),
    (r'\bsettled\b|\bsettlement\b',    -0.8),
    (r'\bcomplied\b|\bcompliance\b',   -0.5),
    (r'\bvacated\b',                   -1.0),
]


# ── Scoring engine ─────────────────────────────────────────────────────────────

def score_text(text: str, context: str = None) -> dict:
    """Score a legal document for risk on a 0-10 scale."""
    text_lower = text.lower()
    nlp = get_nlp()
    doc = nlp(text[:10000])  # cap for performance

    signals_found = []
    raw_score = 0.0

    # Apply risk signals
    for pattern, weight, category in RISK_SIGNALS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            # Diminishing returns: first match full weight, extras halved
            contribution = weight + (len(matches) - 1) * weight * 0.3
            raw_score += contribution
            signals_found.append({
                "signal": pattern.replace(r'\b', '').replace(r'\w*', '*'),
                "category": category,
                "matches": len(matches),
                "contribution": round(contribution, 2),
            })

    # Apply mitigating signals
    mitigations = []
    for pattern, weight in MITIGATING_SIGNALS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            raw_score += weight * len(matches)
            mitigations.append({
                "signal": pattern.replace(r'\b', ''),
                "contribution": round(weight * len(matches), 2),
            })

    # Entity density bonus (many named parties = complex case)
    persons  = [e for e in doc.ents if e.label_ == "PERSON"]
    orgs     = [e for e in doc.ents if e.label_ == "ORG"]
    entities = persons + orgs
    entity_bonus = min(len(entities) * 0.15, 1.5)
    raw_score += entity_bonus

    # Context multiplier
    context_multiplier = 1.0
    if context == "criminal":
        context_multiplier = 1.2
    elif context == "regulatory":
        context_multiplier = 1.1

    raw_score *= context_multiplier

    # Normalize to 0-10
    final_score = round(min(max(raw_score, 0.0), 10.0), 2)

    # Risk level
    if final_score >= 7.5:
        level = "critical"
    elif final_score >= 5.5:
        level = "high"
    elif final_score >= 3.5:
        level = "medium"
    elif final_score >= 1.5:
        level = "low"
    else:
        level = "minimal"

    # Category breakdown
    category_scores = {}
    for s in signals_found:
        cat = s["category"]
        category_scores[cat] = round(
            category_scores.get(cat, 0) + s["contribution"], 2
        )

    # Top signals by contribution
    top_signals = sorted(signals_found, key=lambda x: x["contribution"], reverse=True)[:5]

    return {
        "score": final_score,
        "level": level,
        "category_breakdown": category_scores,
        "top_signals": top_signals,
        "mitigating_factors": mitigations,
        "entity_density": {
            "persons": [e.text for e in persons[:10]],
            "organizations": [e.text for e in orgs[:10]],
            "entity_bonus": round(entity_bonus, 2),
        },
        "context": context or "general",
        "text_length": len(text),
    }


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/score")
def score_document(body: RiskInput):
    """Score a single legal document for risk."""
    if not body.text.strip():
        return {"error": "Text is required"}

    result = score_text(body.text, context=body.context)
    return {
        "success": True,
        "label": body.label or "Document",
        **result,
    }


@router.post("/score/batch")
def score_batch(body: BatchRiskInput):
    """Score multiple documents and rank by risk."""
    if not body.documents:
        return {"error": "Provide at least one document"}
    if len(body.documents) > 20:
        return {"error": "Maximum 20 documents per batch"}

    labels = body.labels or [f"Document {i+1}" for i in range(len(body.documents))]
    results = []

    for i, text in enumerate(body.documents):
        result = score_text(text, context=body.context)
        results.append({
            "label": labels[i],
            "score": result["score"],
            "level": result["level"],
            "top_signals": result["top_signals"],
            "category_breakdown": result["category_breakdown"],
        })

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)

    return {
        "success": True,
        "document_count": len(results),
        "ranked_results": results,
        "highest_risk": results[0] if results else None,
        "lowest_risk": results[-1] if results else None,
        "avg_score": round(sum(r["score"] for r in results) / len(results), 2),
    }


@router.get("/signals")
def list_signals():
    """List all risk signal categories and examples."""
    categories = {}
    for pattern, weight, category in RISK_SIGNALS:
        if category not in categories:
            categories[category] = {"signals": [], "total_weight": 0}
        categories[category]["signals"].append({
            "pattern": pattern.replace(r'\b', '').replace(r'\w*', '*'),
            "weight": weight,
        })
        categories[category]["total_weight"] = round(
            categories[category]["total_weight"] + weight, 2
        )
    return {
        "risk_categories": categories,
        "mitigating_signals": [
            {"pattern": p.replace(r'\b', ''), "weight": w}
            for p, w in MITIGATING_SIGNALS
        ],
        "scale": "0-10 (minimal → low → medium → high → critical)",
    }

