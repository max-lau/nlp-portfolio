import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "analyses.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT    NOT NULL,
            text        TEXT    NOT NULL,
            word_count  INTEGER,
            sentiment   TEXT,
            score       REAL,
            tone        TEXT,
            entities    TEXT,
            keywords    TEXT,
            summary     TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_analysis(text: str, result: dict) -> int:
    """Save an analysis result to the database."""
    conn = get_connection()
    cursor = conn.execute("""
        INSERT INTO analyses
            (created_at, text, word_count, sentiment, score, tone, entities, keywords, summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.utcnow().isoformat(),
        text[:500],  # store first 500 chars
        len(text.split()),
        result.get("sentiment", {}).get("label", ""),
        result.get("sentiment", {}).get("score", 0.0),
        json.dumps(result.get("tone", [])),
        json.dumps(result.get("entities", [])),
        json.dumps(result.get("keywords", [])),
        result.get("summary", "")
    ))
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id

def query_analyses(
    sentiment: str = None,
    keyword: str = None,
    limit: int = 20
) -> list:
    """Query stored analyses with optional filters."""
    conn = get_connection()
    sql = "SELECT * FROM analyses WHERE 1=1"
    params = []

    if sentiment:
        sql += " AND sentiment = ?"
        params.append(sentiment)

    if keyword:
        sql += " AND (text LIKE ? OR keywords LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results = []
    for row in rows:
        results.append({
            "id":         row["id"],
            "created_at": row["created_at"],
            "text":       row["text"][:100] + "..." if len(row["text"]) > 100 else row["text"],
            "word_count": row["word_count"],
            "sentiment":  row["sentiment"],
            "score":      row["score"],
            "tone":       json.loads(row["tone"]),
            "entities":   json.loads(row["entities"]),
            "keywords":   json.loads(row["keywords"]),
            "summary":    row["summary"]
        })
    return results

def get_stats() -> dict:
    """Aggregate statistics across all analyses."""
    conn = get_connection()

    total = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]

    sentiment_counts = conn.execute("""
        SELECT sentiment, COUNT(*) as count
        FROM analyses
        GROUP BY sentiment
        ORDER BY count DESC
    """).fetchall()

    avg_score = conn.execute(
        "SELECT AVG(score) FROM analyses"
    ).fetchone()[0]

    avg_words = conn.execute(
        "SELECT AVG(word_count) FROM analyses"
    ).fetchone()[0]

    conn.close()

    return {
        "total_analyses": total,
        "avg_sentiment_score": round(avg_score or 0, 3),
        "avg_word_count": round(avg_words or 0, 1),
        "sentiment_breakdown": {
            row["sentiment"]: row["count"]
            for row in sentiment_counts
        }
    }