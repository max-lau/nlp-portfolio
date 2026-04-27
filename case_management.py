"""
case_management.py
==================
Flask Blueprint: Legal Case Management System
Integrates with the existing NLP pipeline (sentiment, timeline, risk scorer, etc.)

Endpoints:
  POST   /cases/create                  - create new case
  GET    /cases/list                    - list all cases (with filters)
  GET    /cases/<case_id>               - case detail + docs + stats
  PUT    /cases/<case_id>/status        - update status
  DELETE /cases/<case_id>              - soft-delete case
  POST   /cases/<case_id>/add_document  - link an existing analyzed doc to case
  GET    /cases/<case_id>/documents     - all documents in case
  GET    /cases/<case_id>/timeline      - auto-generated chronological timeline
  GET    /cases/<case_id>/summary       - AI summary of all docs in case
  GET    /cases/search                  - full-text cross-case search
  POST   /cases/<case_id>/note         - add a case note
  GET    /cases/<case_id>/notes        - list notes
  GET    /cases/stats                  - dashboard stats
"""

import sqlite3
import json
import re
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify

# ── Blueprint ──────────────────────────────────────────────────────────────────
cases_bp = Blueprint("cases", __name__, url_prefix="/cases")

DB_PATH = "legal_nlp.db"   # same DB used by the rest of the pipeline


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE INIT
# ══════════════════════════════════════════════════════════════════════════════

def init_case_db():
    """Create case-management tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Core cases table
    c.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            case_number     TEXT UNIQUE NOT NULL,
            client_name     TEXT NOT NULL,
            matter_number   TEXT,
            status          TEXT DEFAULT 'open'
                            CHECK(status IN ('open','pending','closed','archived')),
            court           TEXT,
            judge           TEXT,
            filing_date     TEXT,
            description     TEXT,
            risk_level      TEXT DEFAULT 'unknown',
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now')),
            deleted         INTEGER DEFAULT 0
        )
    """)

    # Link table: case ↔ analyzed documents
    c.execute("""
        CREATE TABLE IF NOT EXISTS case_documents (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id         INTEGER NOT NULL REFERENCES cases(id),
            document_id     INTEGER,               -- FK to 'history' table if available
            document_name   TEXT NOT NULL,
            source          TEXT DEFAULT 'uploaded'
                            CHECK(source IN ('uploaded','pacer','email','manual')),
            doc_text        TEXT,                  -- full text cached here
            sentiment       TEXT,
            risk_score      REAL,
            events_json     TEXT,                  -- JSON array of extracted events
            entities_json   TEXT,                  -- JSON array of named entities
            summary         TEXT,
            language        TEXT DEFAULT 'en',
            upload_date     TEXT DEFAULT (datetime('now')),
            pacer_doc_id    TEXT,                  -- PACER doc ID if applicable
            pacer_seq_no    TEXT
        )
    """)

    # Case notes / memo pad
    c.execute("""
        CREATE TABLE IF NOT EXISTS case_notes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id     INTEGER NOT NULL REFERENCES cases(id),
            author      TEXT DEFAULT 'System',
            note        TEXT NOT NULL,
            pinned      INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)

    # Case tags
    c.execute("""
        CREATE TABLE IF NOT EXISTS case_tags (
            case_id     INTEGER NOT NULL REFERENCES cases(id),
            tag         TEXT NOT NULL,
            PRIMARY KEY (case_id, tag)
        )
    """)

    # FTS5 virtual table for full-text search across all case documents
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

    # Trigger: keep FTS in sync on insert
    c.execute("""
        CREATE TRIGGER IF NOT EXISTS case_fts_insert
        AFTER INSERT ON case_documents BEGIN
            INSERT INTO case_fts(rowid, case_id, document_name, doc_text, summary)
            VALUES (new.id, new.case_id, new.document_name,
                    COALESCE(new.doc_text,''), COALESCE(new.summary,''));
        END
    """)

    # Trigger: keep FTS in sync on update
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
    """Derive aggregate case risk from linked document risk scores."""
    if not docs:
        return "unknown"
    scores = [d["risk_score"] for d in docs if d["risk_score"] is not None]
    if not scores:
        return "unknown"
    avg = sum(scores) / len(scores)
    if avg >= 7:
        return "high"
    if avg >= 4:
        return "medium"
    return "low"


def extract_dates_from_text(text: str) -> list:
    """Regex date extractor — returns list of (date_str, context) tuples."""
    patterns = [
        r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b",
        r"\b(\d{4}-\d{2}-\d{2})\b",
        r"\b(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s+\d{4}\b",
        r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\s+\d{4})\b",
    ]
    found = []
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            start = max(0, m.start() - 60)
            end = min(len(text), m.end() + 60)
            context = text[start:end].replace("\n", " ").strip()
            found.append({"date": m.group(), "context": context,
                          "pos": m.start()})
    # deduplicate by position proximity
    seen = set()
    unique = []
    for item in sorted(found, key=lambda x: x["pos"]):
        key = item["date"]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES — CASE CRUD
# ══════════════════════════════════════════════════════════════════════════════

@cases_bp.route("/create", methods=["POST"])
def create_case():
    """
    Body (JSON):
      case_number*, client_name*, matter_number, status, court, judge,
      filing_date, description, tags (list)
    """
    data = request.get_json(force=True)
    required = ["case_number", "client_name"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"Missing required field: {field}"}), 400

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO cases
              (case_number, client_name, matter_number, status, court,
               judge, filing_date, description)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            data["case_number"].strip(),
            data["client_name"].strip(),
            data.get("matter_number", ""),
            data.get("status", "open"),
            data.get("court", ""),
            data.get("judge", ""),
            data.get("filing_date", ""),
            data.get("description", ""),
        ))
        case_id = conn.execute(
            "SELECT id FROM cases WHERE case_number=?",
            (data["case_number"],)).fetchone()["id"]

        # Insert tags
        for tag in data.get("tags", []):
            conn.execute("INSERT OR IGNORE INTO case_tags VALUES (?,?)",
                         (case_id, tag.lower().strip()))

        # Auto note
        conn.execute(
            "INSERT INTO case_notes (case_id, note) VALUES (?,?)",
            (case_id, f"Case created: {data['case_number']} for {data['client_name']}"))

        conn.commit()
        return jsonify({"success": True, "case_id": case_id,
                        "case_number": data["case_number"]}), 201

    except sqlite3.IntegrityError:
        return jsonify({"error": "Case number already exists"}), 409
    finally:
        conn.close()


@cases_bp.route("/list", methods=["GET"])
def list_cases():
    """
    Query params: status, client, search, sort (created/updated/risk), page, per_page
    """
    status = request.args.get("status")
    client = request.args.get("client")
    search = request.args.get("search", "").strip()
    sort   = request.args.get("sort", "updated")
    page   = max(1, int(request.args.get("page", 1)))
    per_pg = min(50, int(request.args.get("per_page", 20)))

    sort_map = {
        "created": "c.created_at DESC",
        "updated": "c.updated_at DESC",
        "risk":    "c.risk_level DESC",
        "client":  "c.client_name ASC",
    }
    order = sort_map.get(sort, "c.updated_at DESC")

    where_parts = ["c.deleted = 0"]
    params = []

    if status:
        where_parts.append("c.status = ?")
        params.append(status)
    if client:
        where_parts.append("c.client_name LIKE ?")
        params.append(f"%{client}%")
    if search:
        where_parts.append(
            "(c.case_number LIKE ? OR c.client_name LIKE ? OR c.description LIKE ?)")
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]

    where = " AND ".join(where_parts)
    offset = (page - 1) * per_pg

    conn = get_db()
    total = conn.execute(
        f"SELECT COUNT(*) FROM cases c WHERE {where}", params).fetchone()[0]

    rows = conn.execute(f"""
        SELECT c.*,
               COUNT(DISTINCT cd.id)    AS doc_count,
               GROUP_CONCAT(DISTINCT ct.tag) AS tags
        FROM   cases c
        LEFT JOIN case_documents cd ON cd.case_id = c.id
        LEFT JOIN case_tags ct ON ct.case_id = c.id
        WHERE  {where}
        GROUP BY c.id
        ORDER BY {order}
        LIMIT ? OFFSET ?
    """, params + [per_pg, offset]).fetchall()
    conn.close()

    cases = []
    for r in rows:
        d = row_to_dict(r)
        d["tags"] = d["tags"].split(",") if d["tags"] else []
        cases.append(d)

    return jsonify({
        "cases": cases,
        "total": total,
        "page": page,
        "per_page": per_pg,
        "pages": (total + per_pg - 1) // per_pg,
    })


@cases_bp.route("/<int:case_id>", methods=["GET"])
def get_case(case_id):
    conn = get_db()
    case = row_to_dict(conn.execute(
        "SELECT * FROM cases WHERE id=? AND deleted=0", (case_id,)).fetchone())
    if not case:
        conn.close()
        return jsonify({"error": "Case not found"}), 404

    docs  = [row_to_dict(r) for r in conn.execute(
        "SELECT * FROM case_documents WHERE case_id=? ORDER BY upload_date DESC",
        (case_id,)).fetchall()]
    notes = [row_to_dict(r) for r in conn.execute(
        "SELECT * FROM case_notes WHERE case_id=? ORDER BY pinned DESC, created_at DESC",
        (case_id,)).fetchall()]
    tags  = [r["tag"] for r in conn.execute(
        "SELECT tag FROM case_tags WHERE case_id=?", (case_id,)).fetchall()]
    conn.close()

    # Parse JSON fields
    for d in docs:
        for field in ["events_json", "entities_json"]:
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except Exception:
                    pass

    case["documents"] = docs
    case["notes"]     = notes
    case["tags"]      = tags
    case["doc_count"] = len(docs)
    return jsonify(case)


@cases_bp.route("/<int:case_id>/status", methods=["PUT"])
def update_status(case_id):
    data   = request.get_json(force=True)
    status = data.get("status")
    valid  = ("open", "pending", "closed", "archived")
    if status not in valid:
        return jsonify({"error": f"status must be one of {valid}"}), 400

    conn = get_db()
    conn.execute(
        "UPDATE cases SET status=?, updated_at=? WHERE id=?",
        (status, ts_now(), case_id))
    conn.execute(
        "INSERT INTO case_notes (case_id, author, note) VALUES (?,?,?)",
        (case_id, data.get("author", "System"), f"Status changed to: {status}"))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "case_id": case_id, "status": status})


@cases_bp.route("/<int:case_id>", methods=["DELETE"])
def delete_case(case_id):
    conn = get_db()
    conn.execute(
        "UPDATE cases SET deleted=1, updated_at=? WHERE id=?",
        (ts_now(), case_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Case soft-deleted"})


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES — DOCUMENTS
# ══════════════════════════════════════════════════════════════════════════════

@cases_bp.route("/<int:case_id>/add_document", methods=["POST"])
def add_document(case_id):
    """
    Add an analyzed document to a case.
    Body: document_name*, doc_text, sentiment, risk_score, events_json,
          entities_json, summary, language, source, pacer_doc_id, pacer_seq_no
    """
    data = request.get_json(force=True)
    if not data.get("document_name"):
        return jsonify({"error": "document_name required"}), 400

    events   = data.get("events_json")
    entities = data.get("entities_json")

    conn = get_db()
    # Verify case exists
    if not conn.execute(
            "SELECT id FROM cases WHERE id=? AND deleted=0",
            (case_id,)).fetchone():
        conn.close()
        return jsonify({"error": "Case not found"}), 404

    conn.execute("""
        INSERT INTO case_documents
          (case_id, document_name, source, doc_text, sentiment, risk_score,
           events_json, entities_json, summary, language, pacer_doc_id, pacer_seq_no)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        case_id,
        data["document_name"],
        data.get("source", "uploaded"),
        data.get("doc_text", ""),
        data.get("sentiment", ""),
        data.get("risk_score"),
        json.dumps(events)   if isinstance(events, list)    else events,
        json.dumps(entities) if isinstance(entities, list)  else entities,
        data.get("summary", ""),
        data.get("language", "en"),
        data.get("pacer_doc_id", ""),
        data.get("pacer_seq_no", ""),
    ))

    # Update case risk & timestamp
    docs = conn.execute(
        "SELECT risk_score FROM case_documents WHERE case_id=?",
        (case_id,)).fetchall()
    new_risk = compute_case_risk([row_to_dict(d) for d in docs])
    conn.execute(
        "UPDATE cases SET risk_level=?, updated_at=? WHERE id=?",
        (new_risk, ts_now(), case_id))

    conn.commit()
    conn.close()
    return jsonify({"success": True, "case_id": case_id,
                    "document_name": data["document_name"],
                    "new_risk_level": new_risk}), 201


@cases_bp.route("/<int:case_id>/documents", methods=["GET"])
def list_documents(case_id):
    source = request.args.get("source")
    conn   = get_db()
    query  = "SELECT * FROM case_documents WHERE case_id=?"
    params = [case_id]
    if source:
        query  += " AND source=?"
        params.append(source)
    query += " ORDER BY upload_date DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    docs = [row_to_dict(r) for r in rows]
    for d in docs:
        for field in ["events_json", "entities_json"]:
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except Exception:
                    pass
    return jsonify({"case_id": case_id, "documents": docs, "count": len(docs)})


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES — TIMELINE
# ══════════════════════════════════════════════════════════════════════════════

@cases_bp.route("/<int:case_id>/timeline", methods=["GET"])
def case_timeline(case_id):
    """
    Auto-generate a chronological timeline by extracting all dates from
    all documents in the case.  Returns events sorted by date.
    """
    conn = get_db()
    docs = conn.execute(
        "SELECT id, document_name, doc_text, events_json, upload_date "
        "FROM case_documents WHERE case_id=?", (case_id,)).fetchall()
    conn.close()

    all_events = []

    for doc in docs:
        doc = row_to_dict(doc)

        # 1. Events already extracted by the timeline extractor
        if doc.get("events_json"):
            try:
                events = json.loads(doc["events_json"])
                for ev in events:
                    ev["source_doc"] = doc["document_name"]
                    ev["source"]     = "nlp_extractor"
                    all_events.append(ev)
            except Exception:
                pass

        # 2. Regex date scan of raw text
        if doc.get("doc_text"):
            raw_dates = extract_dates_from_text(doc["doc_text"])
            for rd in raw_dates:
                all_events.append({
                    "date":       rd["date"],
                    "context":    rd["context"],
                    "source_doc": doc["document_name"],
                    "source":     "regex_scan",
                })

    # Sort: best-effort parse
    def sort_key(ev):
        date_str = ev.get("date", "") or ""
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y",
                    "%B %d, %Y", "%B %d %Y", "%d %b %Y"):
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except Exception:
                pass
        return datetime.min

    all_events.sort(key=sort_key)

    return jsonify({
        "case_id":    case_id,
        "event_count": len(all_events),
        "timeline":   all_events,
    })


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES — FULL-TEXT SEARCH
# ══════════════════════════════════════════════════════════════════════════════

@cases_bp.route("/search", methods=["GET"])
def search_cases():
    """
    Cross-case full-text search using SQLite FTS5.
    Query params: q* (search term), case_id (scope to one case), limit
    """
    q       = request.args.get("q", "").strip()
    case_id = request.args.get("case_id")
    limit   = min(50, int(request.args.get("limit", 20)))

    if not q:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    conn = get_db()

    if case_id:
        rows = conn.execute("""
            SELECT cf.rowid, cf.case_id, cf.document_name,
                   snippet(case_fts, 2, '<mark>', '</mark>', '…', 20) AS snippet,
                   c.case_number, c.client_name
            FROM   case_fts cf
            JOIN   cases c ON c.id = cf.case_id
            WHERE  case_fts MATCH ? AND cf.case_id = ?
            ORDER BY rank
            LIMIT ?
        """, (q, case_id, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT cf.rowid, cf.case_id, cf.document_name,
                   snippet(case_fts, 2, '<mark>', '</mark>', '…', 20) AS snippet,
                   c.case_number, c.client_name
            FROM   case_fts cf
            JOIN   cases c ON c.id = cf.case_id
            WHERE  case_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (q, limit)).fetchall()

    conn.close()
    results = [row_to_dict(r) for r in rows]
    return jsonify({"query": q, "results": results, "count": len(results)})


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES — NOTES
# ══════════════════════════════════════════════════════════════════════════════

@cases_bp.route("/<int:case_id>/note", methods=["POST"])
def add_note(case_id):
    data = request.get_json(force=True)
    if not data.get("note"):
        return jsonify({"error": "note required"}), 400
    conn = get_db()
    conn.execute(
        "INSERT INTO case_notes (case_id, author, note, pinned) VALUES (?,?,?,?)",
        (case_id, data.get("author", "User"),
         data["note"], data.get("pinned", 0)))
    conn.commit()
    conn.close()
    return jsonify({"success": True}), 201


@cases_bp.route("/<int:case_id>/notes", methods=["GET"])
def list_notes(case_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM case_notes WHERE case_id=? ORDER BY pinned DESC, created_at DESC",
        (case_id,)).fetchall()
    conn.close()
    return jsonify({"case_id": case_id,
                    "notes": [row_to_dict(r) for r in rows]})


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES — STATS
# ══════════════════════════════════════════════════════════════════════════════

@cases_bp.route("/stats", methods=["GET"])
def case_stats():
    conn = get_db()
    stats = {}

    # Case counts by status
    rows = conn.execute("""
        SELECT status, COUNT(*) AS cnt FROM cases
        WHERE deleted=0 GROUP BY status
    """).fetchall()
    stats["by_status"] = {r["status"]: r["cnt"] for r in rows}

    # Risk breakdown
    rows = conn.execute("""
        SELECT risk_level, COUNT(*) AS cnt FROM cases
        WHERE deleted=0 GROUP BY risk_level
    """).fetchall()
    stats["by_risk"] = {r["risk_level"]: r["cnt"] for r in rows}

    # Total documents
    stats["total_documents"] = conn.execute(
        "SELECT COUNT(*) FROM case_documents").fetchone()[0]

    # Source breakdown
    rows = conn.execute("""
        SELECT source, COUNT(*) AS cnt FROM case_documents GROUP BY source
    """).fetchall()
    stats["docs_by_source"] = {r["source"]: r["cnt"] for r in rows}

    # Most active cases (by doc count)
    rows = conn.execute("""
        SELECT c.case_number, c.client_name, COUNT(cd.id) AS doc_count
        FROM cases c
        LEFT JOIN case_documents cd ON cd.case_id = c.id
        WHERE c.deleted=0
        GROUP BY c.id
        ORDER BY doc_count DESC
        LIMIT 5
    """).fetchall()
    stats["most_active_cases"] = [row_to_dict(r) for r in rows]

    # Recent activity
    rows = conn.execute("""
        SELECT c.case_number, c.client_name, c.updated_at
        FROM cases c WHERE c.deleted=0
        ORDER BY c.updated_at DESC LIMIT 5
    """).fetchall()
    stats["recently_updated"] = [row_to_dict(r) for r in rows]

    conn.close()
    return jsonify(stats)


# ══════════════════════════════════════════════════════════════════════════════
# REGISTRATION HELPER
# ══════════════════════════════════════════════════════════════════════════════

def register(app):
    """Call from app.py:  from case_management import register; register(app)"""
    init_case_db()
    app.register_blueprint(cases_bp)
    print("[CaseManagement] Blueprint registered at /cases ✓")
