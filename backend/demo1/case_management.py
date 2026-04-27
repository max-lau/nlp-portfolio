"""
case_management.py
==================
FastAPI APIRouter: Legal Case Management System

Register in main.py:
    from backend.demo1.case_management import router as cases_router
    app.include_router(cases_router, prefix="/cases", tags=["Case Management"])

Endpoints:
  POST   /cases/                    - create new case
  GET    /cases/                    - list all cases (filtered/paginated)
  GET    /cases/stats               - dashboard stats
  GET    /cases/search              - full-text cross-case search
  GET    /cases/{case_id}           - case detail + docs + notes
  PUT    /cases/{case_id}/status    - update status
  DELETE /cases/{case_id}          - soft-delete
  POST   /cases/{case_id}/documents - add document to case
  GET    /cases/{case_id}/documents - list documents
  GET    /cases/{case_id}/timeline  - auto-generated timeline
  POST   /cases/{case_id}/notes     - add note
  GET    /cases/{case_id}/notes     - list notes
"""

import sqlite3
import json
import re
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router  = APIRouter()
DB_PATH = "analyses.db"   # same DB as the rest of the NLP pipeline


# ══════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ══════════════════════════════════════════════════════════════════════════════

class CreateCaseBody(BaseModel):
    case_number:   str
    client_name:   str
    matter_number: Optional[str] = ""
    status:        Optional[str] = "open"
    court:         Optional[str] = ""
    judge:         Optional[str] = ""
    filing_date:   Optional[str] = ""
    description:   Optional[str] = ""
    tags:          Optional[List[str]] = []

class UpdateStatusBody(BaseModel):
    status: str
    author: Optional[str] = "System"

class AddDocumentBody(BaseModel):
    document_name:  str
    doc_text:       Optional[str] = ""
    sentiment:      Optional[str] = None
    risk_score:     Optional[float] = None
    events_json:    Optional[list] = None
    entities_json:  Optional[list] = None
    summary:        Optional[str] = ""
    language:       Optional[str] = "en"
    source:         Optional[str] = "uploaded"
    pacer_doc_id:   Optional[str] = ""
    pacer_seq_no:   Optional[str] = ""

class AddNoteBody(BaseModel):
    note:   str
    author: Optional[str] = "Counsel"
    pinned: Optional[int] = 0


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE INIT
# ══════════════════════════════════════════════════════════════════════════════

def init_case_db():
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            case_number   TEXT UNIQUE NOT NULL,
            client_name   TEXT NOT NULL,
            matter_number TEXT,
            status        TEXT DEFAULT 'open'
                          CHECK(status IN ('open','pending','closed','archived')),
            court         TEXT,
            judge         TEXT,
            filing_date   TEXT,
            description   TEXT,
            risk_level    TEXT DEFAULT 'unknown',
            created_at    TEXT DEFAULT (datetime('now')),
            updated_at    TEXT DEFAULT (datetime('now')),
            deleted       INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS case_documents (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id       INTEGER NOT NULL REFERENCES cases(id),
            document_name TEXT NOT NULL,
            source        TEXT DEFAULT 'uploaded'
                          CHECK(source IN ('uploaded','pacer','email','manual')),
            doc_text      TEXT,
            sentiment     TEXT,
            risk_score    REAL,
            events_json   TEXT,
            entities_json TEXT,
            summary       TEXT,
            language      TEXT DEFAULT 'en',
            upload_date   TEXT DEFAULT (datetime('now')),
            pacer_doc_id  TEXT,
            pacer_seq_no  TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS case_notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id    INTEGER NOT NULL REFERENCES cases(id),
            author     TEXT DEFAULT 'System',
            note       TEXT NOT NULL,
            pinned     INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS case_tags (
            case_id INTEGER NOT NULL REFERENCES cases(id),
            tag     TEXT NOT NULL,
            PRIMARY KEY (case_id, tag)
        )
    """)

    c.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS case_fts
        USING fts5(
            case_id UNINDEXED,
            document_name,
            doc_text,
            summary,
            content='case_documents',
            content_rowid='id'
        )
    """)

    c.execute("""
        CREATE TRIGGER IF NOT EXISTS case_fts_insert
        AFTER INSERT ON case_documents BEGIN
            INSERT INTO case_fts(rowid, case_id, document_name, doc_text, summary)
            VALUES (new.id, new.case_id, new.document_name,
                    COALESCE(new.doc_text,''), COALESCE(new.summary,''));
        END
    """)

    c.execute("""
        CREATE TRIGGER IF NOT EXISTS case_fts_update
        AFTER UPDATE ON case_documents BEGIN
            INSERT INTO case_fts(case_fts, rowid, case_id, document_name, doc_text, summary)
            VALUES('delete', old.id, old.case_id, old.document_name,
                   COALESCE(old.doc_text,''), COALESCE(old.summary,''));
            INSERT INTO case_fts(rowid, case_id, document_name, doc_text, summary)
            VALUES (new.id, new.case_id, new.document_name,
                    COALESCE(new.doc_text,''), COALESCE(new.summary,''));
        END
    """)

    conn.commit()
    conn.close()
    print("[CaseDB] Tables initialized ✓")


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def row_to_dict(row):
    return dict(row) if row else None

def ts_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def compute_case_risk(docs: list) -> str:
    scores = [d["risk_score"] for d in docs if d.get("risk_score") is not None]
    if not scores: return "unknown"
    avg = sum(scores) / len(scores)
    if avg >= 7: return "high"
    if avg >= 4: return "medium"
    return "low"

def extract_dates_from_text(text: str) -> list:
    patterns = [
        r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b",
        r"\b(\d{4}-\d{2}-\d{2})\b",
        r"\b(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s+\d{4}\b",
    ]
    found, seen, unique = [], set(), []
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            s = max(0, m.start()-60); e = min(len(text), m.end()+60)
            found.append({"date": m.group(),
                          "context": text[s:e].replace("\n"," ").strip(),
                          "pos": m.start()})
    for item in sorted(found, key=lambda x: x["pos"]):
        if item["date"] not in seen:
            seen.add(item["date"]); unique.append(item)
    return unique


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/")
async def create_case(body: CreateCaseBody):
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO cases
              (case_number, client_name, matter_number, status,
               court, judge, filing_date, description)
            VALUES (?,?,?,?,?,?,?,?)
        """, (body.case_number.strip(), body.client_name.strip(),
              body.matter_number, body.status, body.court,
              body.judge, body.filing_date, body.description))

        case_id = conn.execute(
            "SELECT id FROM cases WHERE case_number=?",
            (body.case_number,)).fetchone()["id"]

        for tag in body.tags:
            conn.execute("INSERT OR IGNORE INTO case_tags VALUES (?,?)",
                         (case_id, tag.lower().strip()))
        conn.execute(
            "INSERT INTO case_notes (case_id, note) VALUES (?,?)",
            (case_id, f"Case created: {body.case_number} for {body.client_name}"))
        conn.commit()
        return {"success": True, "case_id": case_id,
                "case_number": body.case_number}
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Case number already exists")
    finally:
        conn.close()


@router.get("/stats")
async def case_stats():
    conn  = get_db()
    stats = {}
    rows  = conn.execute(
        "SELECT status, COUNT(*) cnt FROM cases WHERE deleted=0 GROUP BY status"
    ).fetchall()
    stats["by_status"] = {r["status"]: r["cnt"] for r in rows}
    rows = conn.execute(
        "SELECT risk_level, COUNT(*) cnt FROM cases WHERE deleted=0 GROUP BY risk_level"
    ).fetchall()
    stats["by_risk"] = {r["risk_level"]: r["cnt"] for r in rows}
    stats["total_documents"] = conn.execute(
        "SELECT COUNT(*) FROM case_documents").fetchone()[0]
    rows = conn.execute(
        "SELECT source, COUNT(*) cnt FROM case_documents GROUP BY source"
    ).fetchall()
    stats["docs_by_source"] = {r["source"]: r["cnt"] for r in rows}
    rows = conn.execute("""
        SELECT c.case_number, c.client_name, COUNT(cd.id) doc_count
        FROM cases c LEFT JOIN case_documents cd ON cd.case_id=c.id
        WHERE c.deleted=0 GROUP BY c.id ORDER BY doc_count DESC LIMIT 5
    """).fetchall()
    stats["most_active_cases"] = [row_to_dict(r) for r in rows]
    conn.close()
    return stats


@router.get("/search")
async def search_cases(
    q:       str           = Query(...),
    case_id: Optional[int] = Query(None),
    limit:   int           = Query(20, le=50),
):
    conn = get_db()
    base = """
        SELECT cf.rowid, cf.case_id, cf.document_name,
               snippet(case_fts,2,'<mark>','</mark>','…',20) AS snippet,
               c.case_number, c.client_name
        FROM   case_fts cf JOIN cases c ON c.id=cf.case_id
        WHERE  case_fts MATCH ? {extra}
        ORDER BY rank LIMIT ?
    """
    if case_id:
        rows = conn.execute(
            base.format(extra="AND cf.case_id=?"), (q, case_id, limit)).fetchall()
    else:
        rows = conn.execute(
            base.format(extra=""), (q, limit)).fetchall()
    conn.close()
    return {"query": q, "results": [row_to_dict(r) for r in rows],
            "count": len(rows)}


@router.get("/{case_id}")
async def get_case(case_id: int):
    conn = get_db()
    case = row_to_dict(conn.execute(
        "SELECT * FROM cases WHERE id=? AND deleted=0", (case_id,)).fetchone())
    if not case:
        conn.close()
        raise HTTPException(404, "Case not found")
    docs  = [row_to_dict(r) for r in conn.execute(
        "SELECT * FROM case_documents WHERE case_id=? ORDER BY upload_date DESC",
        (case_id,)).fetchall()]
    notes = [row_to_dict(r) for r in conn.execute(
        "SELECT * FROM case_notes WHERE case_id=? ORDER BY pinned DESC, created_at DESC",
        (case_id,)).fetchall()]
    tags  = [r["tag"] for r in conn.execute(
        "SELECT tag FROM case_tags WHERE case_id=?", (case_id,)).fetchall()]
    conn.close()
    for d in docs:
        for f in ["events_json","entities_json"]:
            if d.get(f):
                try: d[f] = json.loads(d[f])
                except: pass
    case.update({"documents": docs, "notes": notes,
                 "tags": tags, "doc_count": len(docs)})
    return case


@router.put("/{case_id}/status")
async def update_status(case_id: int, body: UpdateStatusBody):
    if body.status not in ("open","pending","closed","archived"):
        raise HTTPException(400, "Invalid status")
    conn = get_db()
    conn.execute("UPDATE cases SET status=?, updated_at=? WHERE id=?",
                 (body.status, ts_now(), case_id))
    conn.execute(
        "INSERT INTO case_notes (case_id, author, note) VALUES (?,?,?)",
        (case_id, body.author, f"Status changed to: {body.status}"))
    conn.commit(); conn.close()
    return {"success": True, "case_id": case_id, "status": body.status}


@router.delete("/{case_id}")
async def delete_case(case_id: int):
    conn = get_db()
    conn.execute("UPDATE cases SET deleted=1, updated_at=? WHERE id=?",
                 (ts_now(), case_id))
    conn.commit(); conn.close()
    return {"success": True, "message": "Case soft-deleted"}


@router.post("/{case_id}/documents")
async def add_document(case_id: int, body: AddDocumentBody):
    conn = get_db()
    if not conn.execute(
            "SELECT id FROM cases WHERE id=? AND deleted=0",
            (case_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "Case not found")
    conn.execute("""
        INSERT INTO case_documents
          (case_id, document_name, source, doc_text, sentiment, risk_score,
           events_json, entities_json, summary, language, pacer_doc_id, pacer_seq_no)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (case_id, body.document_name, body.source, body.doc_text,
          body.sentiment, body.risk_score,
          json.dumps(body.events_json)   if body.events_json   else None,
          json.dumps(body.entities_json) if body.entities_json else None,
          body.summary, body.language, body.pacer_doc_id, body.pacer_seq_no))
    docs     = conn.execute(
        "SELECT risk_score FROM case_documents WHERE case_id=?",
        (case_id,)).fetchall()
    new_risk = compute_case_risk([row_to_dict(d) for d in docs])
    conn.execute("UPDATE cases SET risk_level=?, updated_at=? WHERE id=?",
                 (new_risk, ts_now(), case_id))
    conn.commit(); conn.close()
    return {"success": True, "case_id": case_id,
            "document_name": body.document_name, "new_risk_level": new_risk}


@router.get("/{case_id}/documents")
async def list_documents(case_id: int, source: Optional[str] = Query(None)):
    conn   = get_db()
    q      = "SELECT * FROM case_documents WHERE case_id=?"
    params = [case_id]
    if source: q += " AND source=?"; params.append(source)
    rows   = conn.execute(q + " ORDER BY upload_date DESC", params).fetchall()
    conn.close()
    docs = [row_to_dict(r) for r in rows]
    for d in docs:
        for f in ["events_json","entities_json"]:
            if d.get(f):
                try: d[f] = json.loads(d[f])
                except: pass
    return {"case_id": case_id, "documents": docs, "count": len(docs)}


@router.get("/{case_id}/timeline")
async def case_timeline(case_id: int):
    conn = get_db()
    docs = [row_to_dict(r) for r in conn.execute(
        "SELECT document_name, doc_text, events_json FROM case_documents WHERE case_id=?",
        (case_id,)).fetchall()]
    conn.close()
    all_events = []
    for doc in docs:
        if doc.get("events_json"):
            try:
                for ev in json.loads(doc["events_json"]):
                    ev["source_doc"] = doc["document_name"]
                    ev["source"]     = "nlp_extractor"
                    all_events.append(ev)
            except: pass
        if doc.get("doc_text"):
            for rd in extract_dates_from_text(doc["doc_text"]):
                all_events.append({**rd, "source_doc": doc["document_name"],
                                   "source": "regex_scan"})
    def sort_key(ev):
        for fmt in ("%Y-%m-%d","%m/%d/%Y","%m/%d/%y","%B %d, %Y","%B %d %Y"):
            try: return datetime.strptime((ev.get("date","")).strip(), fmt)
            except: pass
        return datetime.min
    all_events.sort(key=sort_key)
    return {"case_id": case_id, "event_count": len(all_events),
            "timeline": all_events}


@router.post("/{case_id}/notes")
async def add_note(case_id: int, body: AddNoteBody):
    conn = get_db()
    conn.execute(
        "INSERT INTO case_notes (case_id, author, note, pinned) VALUES (?,?,?,?)",
        (case_id, body.author, body.note, body.pinned))
    conn.commit(); conn.close()
    return {"success": True}


@router.get("/{case_id}/notes")
async def list_notes(case_id: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM case_notes WHERE case_id=? ORDER BY pinned DESC, created_at DESC",
        (case_id,)).fetchall()
    conn.close()
    return {"case_id": case_id, "notes": [row_to_dict(r) for r in rows]}


# Auto-init on import
init_case_db()
