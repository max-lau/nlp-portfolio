"""
custom_entities.py
==================
FastAPI APIRouter: Custom Entity Types (#9)
Allows users to define custom entity types with keyword/pattern rules.
Built-in legal entity types:
  - STATUTE   : 18 U.S.C. § 1343
  - COURT     : Southern District of New York
  - JUDGE     : Judge Rakoff
  - DOCKET    : 12 CR. 99 SHS
  - LEGAL_TERM: wire fraud, habeas corpus, mens rea

Users can add their own types + patterns via the API.
All custom types are stored in analyses.db and applied on /entities/custom.
"""

import re
import sqlite3
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router  = APIRouter()
DB_PATH = "backend/demo1/analyses.db"

# ── Built-in legal entity definitions ─────────────────────────────────────────

BUILTIN_ENTITIES = [
    # STATUTE
    {
        "type": "STATUTE",
        "label": "US Code Statute",
        "pattern": r'\b\d+\s+U\.?S\.?C\.?\s*[§§\s]*\d+[\w\-]*',
        "examples": ["18 U.S.C. § 1343", "18 USC 1341", "42 U.S.C. § 1983"],
        "builtin": True,
    },
    {
        "type": "STATUTE",
        "label": "Federal Rules",
        "pattern": r'\bRule\s+\d+[\w\(\)\.]*\b',
        "examples": ["Rule 12(b)(6)", "Rule 56", "Rule 11"],
        "builtin": True,
    },

    # COURT
    {
        "type": "COURT",
        "label": "Federal District Court",
        "pattern": r'\b(?:United States District Court|U\.S\. District Court)[\w\s,\.]+',
        "examples": ["United States District Court, S.D. New York"],
        "builtin": True,
    },
    {
        "type": "COURT",
        "label": "District Abbreviation",
        "pattern": r'\b(?:S\.D\.N\.Y\.|E\.D\.N\.Y\.|N\.D\.Cal\.|C\.D\.Cal\.|D\.D\.C\.)\b',
        "examples": ["S.D.N.Y.", "E.D.N.Y.", "N.D.Cal."],
        "builtin": True,
    },
    {
        "type": "COURT",
        "label": "Circuit Court",
        "pattern": r'\b(?:Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth|Eleventh)\s+Circuit\b',
        "examples": ["Second Circuit", "Ninth Circuit"],
        "builtin": True,
    },

    # JUDGE
    {
        "type": "JUDGE",
        "label": "Judge Title",
        "pattern": r'\bJudge\s+[A-Z][a-z]+(?:\s+[A-Z]\.?\s*[A-Z][a-z]+)?\b',
        "examples": ["Judge Rakoff", "Judge Sidney H. Stein"],
        "builtin": True,
    },
    {
        "type": "JUDGE",
        "label": "District Judge",
        "pattern": r'\b[A-Z][a-z]+(?:\s+[A-Z]\.?\s*)?\s+[A-Z][a-z]+,\s+(?:U\.S\.|United States)\s+District Judge\b',
        "examples": ["Sidney H. Stein, U.S. District Judge"],
        "builtin": True,
    },

    # DOCKET
    {
        "type": "DOCKET",
        "label": "Criminal Docket",
        "pattern": r'\b\d{2}\s+(?:CR|Cr|cr)\.?\s*[\d]+(?:\s*\([A-Z]+\))?\b',
        "examples": ["12 CR. 99 SHS", "09 Cr. 1243 (LAK)"],
        "builtin": True,
    },
    {
        "type": "DOCKET",
        "label": "Civil Docket",
        "pattern": r'\b(?:No\.|Case No\.)\s*[\d:\-]+(?:\s*\([A-Z]+\))?\b',
        "examples": ["No. 12 Civ. 1422(JSR)", "Case No. 1:24-cr-00142"],
        "builtin": True,
    },

    # LEGAL_TERM
    {
        "type": "LEGAL_TERM",
        "label": "Criminal Charges",
        "pattern": r'\b(?:wire fraud|mail fraud|securities fraud|bank fraud|money laundering|'
                   r'conspiracy|racketeering|embezzlement|bribery|extortion|perjury|'
                   r'obstruction of justice|contempt of court)\b',
        "examples": ["wire fraud", "money laundering", "conspiracy"],
        "builtin": True,
    },
    {
        "type": "LEGAL_TERM",
        "label": "Latin Legal Terms",
        "pattern": r'\b(?:habeas corpus|mens rea|actus reus|prima facie|pro se|'
                   r'in camera|ex parte|amicus curiae|res judicata|stare decisis|'
                   r'voir dire|nolo contendere|nolle prosequi)\b',
        "examples": ["habeas corpus", "mens rea", "prima facie"],
        "builtin": True,
    },
    {
        "type": "LEGAL_TERM",
        "label": "Procedural Terms",
        "pattern": r'\b(?:summary judgment|motion to dismiss|preliminary injunction|'
                   r'default judgment|directed verdict|class action|bench trial|'
                   r'grand jury|petit jury|indictment|arraignment|plea bargain)\b',
        "examples": ["summary judgment", "motion to dismiss", "grand jury"],
        "builtin": True,
    },
]


# ── DB Setup ───────────────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_custom_entity_table():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS custom_entity_types (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            type        TEXT    NOT NULL,
            label       TEXT    NOT NULL,
            pattern     TEXT    NOT NULL,
            examples    TEXT    DEFAULT '[]',
            builtin     INTEGER DEFAULT 0,
            active      INTEGER DEFAULT 1,
            created_at  TEXT    NOT NULL
        )
    """)
    # Seed built-in types if not already present
    count = conn.execute(
        "SELECT COUNT(*) FROM custom_entity_types WHERE builtin=1"
    ).fetchone()[0]

    if count == 0:
        for e in BUILTIN_ENTITIES:
            import json
            conn.execute("""
                INSERT INTO custom_entity_types
                  (type, label, pattern, examples, builtin, active, created_at)
                VALUES (?,?,?,?,?,1,?)
            """, (
                e["type"], e["label"], e["pattern"],
                json.dumps(e["examples"]), 1 if e["builtin"] else 0,
                datetime.now(timezone.utc).isoformat()
            ))
        print(f"[CustomEntities] Seeded {len(BUILTIN_ENTITIES)} built-in entity patterns ✓")

    conn.commit()
    conn.close()
    print("[CustomEntities] Table initialized ✓")


# ── Extraction engine ──────────────────────────────────────────────────────────

def extract_custom_entities(text: str, types: list = None) -> list:
    """
    Run all active custom entity patterns against text.
    Optionally filter by entity type list.
    """
    import json
    conn = get_conn()
    query = "SELECT * FROM custom_entity_types WHERE active=1"
    params = []
    if types:
        placeholders = ",".join("?" * len(types))
        query += f" AND type IN ({placeholders})"
        params.extend(types)
    patterns = conn.execute(query, params).fetchall()
    conn.close()

    found = []
    seen  = set()

    for p in patterns:
        try:
            for m in re.finditer(p["pattern"], text, re.IGNORECASE):
                raw = m.group(0).strip()
                key = (raw.lower(), p["type"])
                if key in seen:
                    continue
                seen.add(key)
                found.append({
                    "text":    raw,
                    "type":    p["type"],
                    "label":   p["label"],
                    "span":    [m.start(), m.end()],
                    "builtin": bool(p["builtin"]),
                    "pattern_id": p["id"],
                })
        except re.error:
            continue

    found.sort(key=lambda x: x["span"][0])
    return found


# ── Pydantic models ────────────────────────────────────────────────────────────

class AddEntityType(BaseModel):
    type:     str                  # e.g. "COMPANY", "SANCTION"
    label:    str                  # e.g. "Fortune 500 Company"
    pattern:  str                  # regex pattern
    examples: Optional[list] = []

class ExtractBody(BaseModel):
    text:  str
    types: Optional[list] = None   # filter to specific types e.g. ["STATUTE","JUDGE"]


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/extract")
def extract_entities(body: ExtractBody):
    """Extract custom entities from text using all active patterns."""
    if not body.text.strip():
        raise HTTPException(400, "Text is required")

    entities = extract_custom_entities(body.text, types=body.types)

    # Group by type
    by_type = {}
    for e in entities:
        t = e["type"]
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(e)

    return {
        "success":      True,
        "total_found":  len(entities),
        "by_type":      by_type,
        "entities":     entities,
        "text_preview": body.text[:200],
    }


@router.get("/types")
def list_types():
    """List all active entity types (built-in + custom)."""
    import json
    conn  = get_conn()
    rows  = conn.execute(
        "SELECT * FROM custom_entity_types WHERE active=1 ORDER BY builtin DESC, type ASC"
    ).fetchall()
    conn.close()

    types = {}
    for r in rows:
        t = r["type"]
        if t not in types:
            types[t] = {"type": t, "patterns": [], "builtin": bool(r["builtin"])}
        types[t]["patterns"].append({
            "id":       r["id"],
            "label":    r["label"],
            "pattern":  r["pattern"],
            "examples": json.loads(r["examples"] or "[]"),
            "builtin":  bool(r["builtin"]),
        })

    return {
        "success":      True,
        "type_count":   len(types),
        "total_patterns": sum(len(v["patterns"]) for v in types.values()),
        "types":        list(types.values()),
    }


@router.post("/types")
def add_entity_type(body: AddEntityType):
    """Add a new custom entity type with a regex pattern."""
    import json

    # Validate regex
    try:
        re.compile(body.pattern)
    except re.error as e:
        raise HTTPException(400, f"Invalid regex pattern: {e}")

    conn = get_conn()
    cur  = conn.execute("""
        INSERT INTO custom_entity_types
          (type, label, pattern, examples, builtin, active, created_at)
        VALUES (?,?,?,?,0,1,?)
    """, (
        body.type.upper(), body.label, body.pattern,
        json.dumps(body.examples),
        datetime.now(timezone.utc).isoformat()
    ))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()

    return {
        "success":  True,
        "id":       new_id,
        "type":     body.type.upper(),
        "label":    body.label,
        "message":  f"Custom entity type '{body.type.upper()}' added",
    }


@router.delete("/types/{pattern_id}")
def delete_entity_type(pattern_id: int):
    """Deactivate a custom entity pattern (built-ins cannot be deleted)."""
    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM custom_entity_types WHERE id=?", (pattern_id,)
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(404, f"Pattern {pattern_id} not found")
    if row["builtin"]:
        conn.close()
        raise HTTPException(400, "Built-in patterns cannot be deleted")

    conn.execute(
        "UPDATE custom_entity_types SET active=0 WHERE id=?", (pattern_id,)
    )
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Pattern {pattern_id} deactivated"}


@router.post("/types/test")
def test_pattern(body: AddEntityType):
    """Test a regex pattern against sample text before saving."""
    try:
        compiled = re.compile(body.pattern, re.IGNORECASE)
    except re.error as e:
        raise HTTPException(400, f"Invalid regex: {e}")

    matches = []
    for example in body.examples:
        found = compiled.findall(example)
        matches.append({
            "input":   example,
            "matches": found,
            "matched": len(found) > 0,
        })

    return {
        "success":     True,
        "pattern":     body.pattern,
        "test_results": matches,
        "all_matched": all(m["matched"] for m in matches),
    }
