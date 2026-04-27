"""
webhook.py
==========
FastAPI APIRouter: Webhook Notifications (#10)
Allows users to register webhook URLs that get called when events occur:
  - high_risk_document  : risk score >= 7.0
  - case_created        : new case added
  - contradiction_found : contradiction scan finds issues
  - citation_resolved   : citation successfully resolved

Storage: webhook_subscriptions table in analyses.db
Delivery: async HTTP POST to registered URL with event payload
"""

import sqlite3
import httpx
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, HttpUrl
from typing import Optional

router  = APIRouter()
DB_PATH = "backend/demo1/analyses.db"

# ── Valid event types ──────────────────────────────────────────────────────────
VALID_EVENTS = {
    "high_risk_document",
    "case_created",
    "contradiction_found",
    "citation_resolved",
}

# ── DB Setup ───────────────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_webhook_table():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS webhook_subscriptions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event       TEXT    NOT NULL,
            url         TEXT    NOT NULL,
            label       TEXT    DEFAULT '',
            active      INTEGER DEFAULT 1,
            created_at  TEXT    NOT NULL,
            last_fired  TEXT,
            fire_count  INTEGER DEFAULT 0,
            last_status INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS webhook_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            subscription_id INTEGER NOT NULL,
            event           TEXT    NOT NULL,
            fired_at        TEXT    NOT NULL,
            status_code     INTEGER,
            success         INTEGER DEFAULT 0,
            error           TEXT,
            payload_preview TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("[Webhooks] Tables initialized ✓")


# ── Pydantic models ────────────────────────────────────────────────────────────

class RegisterWebhook(BaseModel):
    event: str
    url:   str
    label: Optional[str] = ""

class TestWebhook(BaseModel):
    subscription_id: int

class FireEventBody(BaseModel):
    event:   str
    payload: dict


# ── Delivery engine ────────────────────────────────────────────────────────────

async def deliver_webhook(subscription_id: int, event: str, url: str, payload: dict):
    """
    Async HTTP POST to the registered URL.
    Logs result to webhook_log.
    """
    fired_at      = datetime.now(timezone.utc).isoformat()
    payload_str   = str(payload)[:200]
    status_code   = None
    success       = 0
    error         = None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json={
                    "event":      event,
                    "fired_at":   fired_at,
                    "payload":    payload,
                    "source":     "NLP Text Analyzer API",
                },
                headers={
                    "Content-Type":  "application/json",
                    "X-NLP-Event":   event,
                    "X-NLP-Version": "1.0",
                }
            )
            status_code = resp.status_code
            success     = 1 if resp.status_code < 400 else 0

    except httpx.TimeoutException:
        error = "Timeout after 10s"
    except Exception as e:
        error = str(e)

    # Log result
    try:
        conn = get_conn()
        conn.execute("""
            INSERT INTO webhook_log
              (subscription_id, event, fired_at, status_code, success, error, payload_preview)
            VALUES (?,?,?,?,?,?,?)
        """, (subscription_id, event, fired_at, status_code, success, error, payload_str))

        conn.execute("""
            UPDATE webhook_subscriptions
            SET last_fired=?, fire_count=fire_count+1, last_status=?
            WHERE id=?
        """, (fired_at, status_code, subscription_id))

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Webhooks] Log error: {e}")


async def fire_event(event: str, payload: dict):
    """
    Look up all active subscriptions for this event and deliver to each.
    Called internally by other modules.
    """
    if event not in VALID_EVENTS:
        return

    conn = get_conn()
    subs = conn.execute(
        "SELECT id, url FROM webhook_subscriptions WHERE event=? AND active=1",
        (event,)
    ).fetchall()
    conn.close()

    tasks = [
        deliver_webhook(row["id"], event, row["url"], payload)
        for row in subs
    ]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


# ── Public fire function (sync wrapper for use in sync endpoints) ──────────────

def fire_event_sync(event: str, payload: dict, background_tasks: BackgroundTasks):
    """
    Sync-friendly wrapper. Pass BackgroundTasks from FastAPI endpoint.
    Usage: fire_event_sync("case_created", {...}, background_tasks)
    """
    background_tasks.add_task(fire_event, event, payload)


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/subscribe")
def register_webhook(body: RegisterWebhook):
    """Register a new webhook URL for an event."""
    if body.event not in VALID_EVENTS:
        raise HTTPException(400, f"Invalid event. Valid events: {sorted(VALID_EVENTS)}")

    if not body.url.startswith("http"):
        raise HTTPException(400, "URL must start with http:// or https://")

    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO webhook_subscriptions (event, url, label, created_at)
        VALUES (?,?,?,?)
    """, (body.event, body.url, body.label, datetime.now(timezone.utc).isoformat()))
    sub_id = cur.lastrowid
    conn.commit()
    conn.close()

    return {
        "success": True,
        "subscription_id": sub_id,
        "event": body.event,
        "url":   body.url,
        "label": body.label,
        "message": f"Webhook registered for '{body.event}' events",
    }


@router.get("/subscriptions")
def list_subscriptions(event: Optional[str] = None):
    """List all registered webhook subscriptions."""
    conn  = get_conn()
    query = "SELECT * FROM webhook_subscriptions WHERE 1=1"
    params = []
    if event:
        query += " AND event=?"
        params.append(event)
    query += " ORDER BY id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return {
        "success": True,
        "count": len(rows),
        "subscriptions": [dict(r) for r in rows],
    }


@router.delete("/subscriptions/{sub_id}")
def delete_subscription(sub_id: int):
    """Delete (deactivate) a webhook subscription."""
    conn = get_conn()
    conn.execute(
        "UPDATE webhook_subscriptions SET active=0 WHERE id=?", (sub_id,)
    )
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Subscription {sub_id} deactivated"}


@router.post("/test/{sub_id}")
async def test_webhook(sub_id: int):
    """Send a test payload to a registered webhook URL."""
    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM webhook_subscriptions WHERE id=?", (sub_id,)
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(404, f"Subscription {sub_id} not found")

    await deliver_webhook(
        subscription_id = sub_id,
        event           = row["event"],
        url             = row["url"],
        payload         = {
            "test": True,
            "message": "This is a test webhook from NLP Text Analyzer API",
            "subscription_id": sub_id,
        }
    )
    return {"success": True, "message": f"Test webhook fired to {row['url']}"}


@router.post("/fire")
async def manually_fire_event(body: FireEventBody):
    """
    Manually fire an event to all subscribers.
    Useful for testing the full delivery pipeline.
    """
    if body.event not in VALID_EVENTS:
        raise HTTPException(400, f"Invalid event. Valid: {sorted(VALID_EVENTS)}")

    await fire_event(body.event, body.payload)
    return {
        "success": True,
        "event":   body.event,
        "message": "Event fired to all active subscribers",
    }


@router.get("/logs")
def webhook_logs(subscription_id: Optional[int] = None, limit: int = 50):
    """View webhook delivery logs."""
    limit = min(limit, 200)
    conn  = get_conn()
    query = "SELECT * FROM webhook_log WHERE 1=1"
    params = []
    if subscription_id:
        query += " AND subscription_id=?"
        params.append(subscription_id)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return {
        "success": True,
        "count": len(rows),
        "logs": [dict(r) for r in rows],
    }


@router.get("/events")
def list_events():
    """List all valid webhook event types."""
    return {
        "events": [
            {"event": "high_risk_document",  "description": "Fired when a document risk score >= 7.0"},
            {"event": "case_created",         "description": "Fired when a new case is created"},
            {"event": "contradiction_found",  "description": "Fired when contradictions are detected"},
            {"event": "citation_resolved",    "description": "Fired when a citation is successfully resolved"},
        ]
    }
