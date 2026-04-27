"""
citation_resolver.py
====================
FastAPI APIRouter: Legal Citation Resolver (#5)
Extracts and resolves legal citations from text:
  - US Code statutes  (18 U.S.C. § 1343)
  - Federal reporters (880 F. Supp. 2d 478)
  - Lexis citations   (2012 U.S. Dist. LEXIS 102391)
  - Neutral citations (2012 WL 3083477)
Resolves case citations against CourtListener API.
"""

import re
import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

CL_BASE = "https://www.courtlistener.com/api/rest/v4"

# ── Pydantic models ────────────────────────────────────────────────────────────

class CitationInput(BaseModel):
    text: str
    resolve: bool = True        # hit CourtListener for case citations
    court: Optional[str] = None # filter resolution to a specific court

class CitationResolveInput(BaseModel):
    citation: str               # single citation string to resolve
    court: Optional[str] = None

# ── Regex patterns ─────────────────────────────────────────────────────────────

PATTERNS = {
    "usc": {
        # 18 U.S.C. § 1343  |  18 U.S.C. §§ 1341 and 1343  |  18 USC 1343
        "regex": r'\b(\d+)\s+U\.?S\.?C\.?\s+[§§\s]*(\d+(?:\s+and\s+\d+)*)',
        "type": "statute",
        "label": "US Code"
    },
    "federal_reporter": {
        # 880 F. Supp. 2d 478  |  145 F.3d 23  |  731 F. Supp. 2d 321
        "regex": r'\b(\d+)\s+(F\.(?:\s?Supp\.(?:\s?[23]d)?|\s?[23]d|\.(?:\s?App\'?x)?|\.?))\s+(\d+)',
        "type": "case",
        "label": "Federal Reporter"
    },
    "lexis": {
        # 2012 U.S. Dist. LEXIS 102391
        "regex": r'(\d{4})\s+U\.S\.(?:\s+\w+\.)?\s+LEXIS\s+(\d+)',
        "type": "case",
        "label": "Lexis Citation"
    },
    "westlaw": {
        # 2012 WL 3083477
        "regex": r'(\d{4})\s+WL\s+(\d+)',
        "type": "case",
        "label": "Westlaw Citation"
    },
    "supreme_court": {
        # 543 U.S. 220
        "regex": r'\b(\d+)\s+U\.S\.\s+(\d+)',
        "type": "case",
        "label": "US Supreme Court"
    },
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def extract_citations(text: str) -> list:
    """Extract all legal citations from raw text."""
    found = []
    seen = set()

    for key, pat in PATTERNS.items():
        for m in re.finditer(pat["regex"], text, re.IGNORECASE):
            raw = m.group(0).strip()
            if raw in seen:
                continue
            seen.add(raw)
            found.append({
                "raw": raw,
                "pattern": key,
                "type": pat["type"],
                "label": pat["label"],
                "span": [m.start(), m.end()],
                "resolved": None,
                "resolve_status": "pending" if pat["type"] == "case" else "not_applicable"
            })

    # Sort by position in text
    found.sort(key=lambda x: x["span"][0])
    return found


def resolve_citation(raw: str, court: str = None) -> dict:
    """
    Try to resolve a case citation against CourtListener.
    Returns resolution dict or error info.
    """
    params = {
        "q": raw,
        "format": "json",
        "type": "o",  # opinions
    }
    if court:
        params["court"] = court

    try:
        resp = requests.get(
            f"{CL_BASE}/search/",
            params=params,
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])

        if not results:
            return {"status": "not_found", "matches": []}

        # Take top 3 matches
        matches = []
        for r in results[:3]:
            matches.append({
                "case_name": r.get("caseName", ""),
                "citation": r.get("citation", []),
                "court": r.get("court", ""),
                "date_filed": r.get("dateFiled", ""),
                "judge": r.get("judge", ""),
                "opinion_id": r.get("id"),
                "docket_id": r.get("docket_id"),
                "url": f"https://www.courtlistener.com{r.get('absolute_url', '')}",
                "status": r.get("status", ""),
                "cite_count": r.get("citeCount", 0),
            })

        return {
            "status": "resolved",
            "match_count": data.get("count", 0),
            "matches": matches,
            "top_match": matches[0] if matches else None,
        }

    except requests.exceptions.Timeout:
        return {"status": "timeout", "matches": []}
    except Exception as e:
        return {"status": "error", "error": str(e), "matches": []}


def build_summary(citations: list) -> dict:
    """Build aggregate summary of extracted citations."""
    by_type = {}
    by_label = {}
    resolved_count = 0
    unresolved_count = 0

    for c in citations:
        by_type[c["type"]] = by_type.get(c["type"], 0) + 1
        by_label[c["label"]] = by_label.get(c["label"], 0) + 1
        if c.get("resolve_status") == "resolved":
            resolved_count += 1
        elif c.get("resolve_status") == "not_found":
            unresolved_count += 1

    statutes = [c["raw"] for c in citations if c["type"] == "statute"]
    cases    = [c["raw"] for c in citations if c["type"] == "case"]

    return {
        "total_citations": len(citations),
        "by_type": by_type,
        "by_label": by_label,
        "statutes": statutes,
        "case_citations": cases,
        "resolved": resolved_count,
        "unresolved": unresolved_count,
    }


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/extract")
def extract_only(body: CitationInput):
    """
    Extract legal citations from text WITHOUT resolving them.
    Fast — no external API calls.
    """
    citations = extract_citations(body.text)
    return {
        "success": True,
        "citations": citations,
        "summary": build_summary(citations),
        "text_preview": body.text[:200],
    }


@router.post("/resolve")
def extract_and_resolve(body: CitationInput):
    """
    Extract citations from text AND resolve case citations
    against CourtListener. Slower but richer output.
    """
    citations = extract_citations(body.text)

    if body.resolve:
        for c in citations:
            if c["type"] == "case":
                result = resolve_citation(c["raw"], court=body.court)
                c["resolved"] = result
                c["resolve_status"] = result["status"]

    return {
        "success": True,
        "citations": citations,
        "summary": build_summary(citations),
        "text_preview": body.text[:200],
    }


@router.post("/lookup")
def lookup_single(body: CitationResolveInput):
    """
    Resolve a single citation string directly against CourtListener.
    Useful for UI lookup boxes.
    """
    if not body.citation.strip():
        raise HTTPException(400, "Citation string is required")

    result = resolve_citation(body.citation.strip(), court=body.court)

    return {
        "success": True,
        "citation": body.citation,
        "resolution": result,
    }


@router.get("/patterns")
def list_patterns():
    """List all supported citation patterns with examples."""
    return {
        "patterns": [
            {
                "key": k,
                "label": v["label"],
                "type": v["type"],
                "example": {
                    "usc":             "18 U.S.C. § 1343",
                    "federal_reporter":"880 F. Supp. 2d 478",
                    "lexis":           "2012 U.S. Dist. LEXIS 102391",
                    "westlaw":         "2012 WL 3083477",
                    "supreme_court":   "543 U.S. 220",
                }.get(k, "")
            }
            for k, v in PATTERNS.items()
        ]
    }
