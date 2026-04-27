"""
slack_teams.py
==============
FastAPI APIRouter: Slack / Teams Integration (#23)
Send NLP analysis results to Slack or Microsoft Teams channels.

Slack:   Incoming Webhooks (Block Kit formatting)
Teams:   Incoming Webhooks (Adaptive Cards)

Endpoints:
  POST /notify/slack/configure   - save Slack webhook URL
  POST /notify/teams/configure   - save Teams webhook URL
  POST /notify/slack/send        - send message to Slack
  POST /notify/teams/send        - send message to Teams
  POST /notify/slack/analysis    - send NLP analysis result to Slack
  POST /notify/teams/analysis    - send NLP analysis result to Teams
  POST /notify/risk/alert        - send risk alert to all configured channels
  GET  /notify/config            - view current configuration
  GET  /notify/logs              - view delivery logs
"""

import sqlite3
import httpx
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

router  = APIRouter()
DB_PATH = "backend/demo1/analyses.db"

# ── DB Setup ───────────────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_notify_table():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notify_config (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            platform    TEXT    NOT NULL,
            label       TEXT    DEFAULT '',
            webhook_url TEXT    NOT NULL,
            active      INTEGER DEFAULT 1,
            created_at  TEXT    NOT NULL,
            last_used   TEXT,
            send_count  INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notify_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            platform    TEXT    NOT NULL,
            event_type  TEXT    NOT NULL,
            sent_at     TEXT    NOT NULL,
            status_code INTEGER,
            success     INTEGER DEFAULT 0,
            error       TEXT,
            preview     TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("[Notify] Tables initialized ✓")


def log_delivery(platform, event_type, status_code, success, error=None, preview=""):
    try:
        conn = get_conn()
        conn.execute("""
            INSERT INTO notify_log
              (platform, event_type, sent_at, status_code, success, error, preview)
            VALUES (?,?,?,?,?,?,?)
        """, (
            platform, event_type,
            datetime.now(timezone.utc).isoformat(),
            status_code, 1 if success else 0,
            str(error) if error else None, preview[:200]
        ))
        conn.execute("""
            UPDATE notify_config SET last_used=?, send_count=send_count+1
            WHERE platform=? AND active=1
        """, (datetime.now(timezone.utc).isoformat(), platform))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Notify] Log error: {e}")


# ── Slack Block Kit builders ───────────────────────────────────────────────────

def build_slack_analysis(result: dict, label: str = "Document") -> dict:
    """Build a Slack Block Kit message for an NLP analysis result."""
    sentiment  = result.get("sentiment", "N/A").upper()
    score      = round(result.get("score", 0) * 100, 1)
    entities   = result.get("entities", [])
    top_ents   = ", ".join(e.get("text","") for e in entities[:5]) or "None"
    emoji      = {"POSITIVE": "✅", "NEGATIVE": "🔴", "NEUTRAL": "⚪"}.get(sentiment, "📄")

    return {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} NLP Analysis — {label}"}
            },
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Sentiment*\n{sentiment}"},
                    {"type": "mrkdwn", "text": f"*Confidence*\n{score}%"},
                ]
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Top Entities*\n{top_ents}"}
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn",
                    "text": f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · NLP Text Analyzer API"}]
            }
        ]
    }


def build_slack_risk(risk: dict, label: str = "Document") -> dict:
    """Build a Slack Block Kit message for a risk alert."""
    score  = risk.get("score", 0)
    level  = risk.get("level", "unknown").upper()
    emojis = {"CRITICAL": "🚨", "HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢", "MINIMAL": "✅"}
    emoji  = emojis.get(level, "⚠️")
    cats   = risk.get("category_breakdown", {})
    cat_text = "\n".join(f"• {k.replace('_',' ').title()}: {v}" for k,v in cats.items())

    return {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} Risk Alert — {label}"}
            },
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Risk Score*\n{score} / 10"},
                    {"type": "mrkdwn", "text": f"*Risk Level*\n{level}"},
                ]
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Category Breakdown*\n{cat_text or 'N/A'}"}
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn",
                    "text": f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · NLP Text Analyzer API"}]
            }
        ]
    }


def build_slack_simple(text: str, title: str = "NLP Notification") -> dict:
    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": title}},
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {"type": "context", "elements": [{"type": "mrkdwn",
                "text": f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"}]}
        ]
    }


# ── Teams Adaptive Card builders ───────────────────────────────────────────────

def build_teams_analysis(result: dict, label: str = "Document") -> dict:
    """Build a Teams Adaptive Card for an NLP analysis result."""
    sentiment = result.get("sentiment", "N/A").upper()
    score     = round(result.get("score", 0) * 100, 1)
    entities  = result.get("entities", [])
    top_ents  = ", ".join(e.get("text","") for e in entities[:5]) or "None"

    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {"type": "TextBlock", "size": "Large", "weight": "Bolder",
                     "text": f"📄 NLP Analysis — {label}"},
                    {"type": "FactSet", "facts": [
                        {"title": "Sentiment", "value": sentiment},
                        {"title": "Confidence", "value": f"{score}%"},
                        {"title": "Top Entities", "value": top_ents},
                    ]},
                    {"type": "TextBlock", "size": "Small", "isSubtle": True,
                     "text": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
                ]
            }
        }]
    }


def build_teams_risk(risk: dict, label: str = "Document") -> dict:
    """Build a Teams Adaptive Card for a risk alert."""
    score = risk.get("score", 0)
    level = risk.get("level", "unknown").upper()
    cats  = risk.get("category_breakdown", {})

    facts = [
        {"title": "Risk Score", "value": f"{score} / 10"},
        {"title": "Risk Level", "value": level},
    ]
    for k, v in cats.items():
        facts.append({"title": k.replace("_"," ").title(), "value": str(v)})

    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {"type": "TextBlock", "size": "Large", "weight": "Bolder",
                     "text": f"🚨 Risk Alert — {label}"},
                    {"type": "FactSet", "facts": facts},
                    {"type": "TextBlock", "size": "Small", "isSubtle": True,
                     "text": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
                ]
            }
        }]
    }


# ── Delivery ───────────────────────────────────────────────────────────────────

async def send_to_platform(platform: str, payload: dict, event_type: str, mock: bool = False) -> dict:
    """Send payload to all active webhooks for the platform."""
    conn = get_conn()
    configs = conn.execute(
        "SELECT * FROM notify_config WHERE platform=? AND active=1", (platform,)
    ).fetchall()
    conn.close()

    if not configs:
        return {"sent": 0, "message": f"No active {platform} webhooks configured"}

    if mock:
        log_delivery(platform, event_type, 200, True, preview=str(payload)[:100])
        return {
            "sent": len(configs),
            "mock": True,
            "message": f"Mock delivery to {len(configs)} {platform} webhook(s)",
            "payload_preview": str(payload)[:200],
        }

    results = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for cfg in configs:
            try:
                resp = await client.post(cfg["webhook_url"], json=payload)
                success = resp.status_code < 400
                log_delivery(platform, event_type, resp.status_code, success,
                             preview=str(payload)[:100])
                results.append({"label": cfg["label"], "status": resp.status_code, "success": success})
            except Exception as e:
                log_delivery(platform, event_type, None, False, error=str(e))
                results.append({"label": cfg["label"], "error": str(e), "success": False})

    return {"sent": len(results), "results": results}


# ── Pydantic models ────────────────────────────────────────────────────────────

class ConfigureWebhook(BaseModel):
    webhook_url: str
    label:       Optional[str] = ""

class SendMessage(BaseModel):
    title:   Optional[str] = "NLP Notification"
    message: str
    mock:    Optional[bool] = True

class SendAnalysis(BaseModel):
    text:  str
    label: Optional[str] = "Document"
    mock:  Optional[bool] = True

class SendRiskAlert(BaseModel):
    text:    str
    context: Optional[str] = "general"
    label:   Optional[str] = "Document"
    mock:    Optional[bool] = True


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/slack/configure")
def configure_slack(body: ConfigureWebhook):
    """Save a Slack incoming webhook URL."""
    if not body.webhook_url.startswith("http"):
        raise HTTPException(400, "Invalid webhook URL")
    conn = get_conn()
    cur  = conn.execute("""
        INSERT INTO notify_config (platform, label, webhook_url, created_at)
        VALUES ('slack',?,?,?)
    """, (body.label, body.webhook_url, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()
    return {"success": True, "id": cur.lastrowid, "platform": "slack", "label": body.label}


@router.post("/teams/configure")
def configure_teams(body: ConfigureWebhook):
    """Save a Microsoft Teams incoming webhook URL."""
    if not body.webhook_url.startswith("http"):
        raise HTTPException(400, "Invalid webhook URL")
    conn = get_conn()
    cur  = conn.execute("""
        INSERT INTO notify_config (platform, label, webhook_url, created_at)
        VALUES ('teams',?,?,?)
    """, (body.label, body.webhook_url, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()
    return {"success": True, "id": cur.lastrowid, "platform": "teams", "label": body.label}


@router.post("/slack/send")
async def send_slack_message(body: SendMessage):
    """Send a simple text message to Slack."""
    payload = build_slack_simple(body.message, body.title)
    result  = await send_to_platform("slack", payload, "simple_message", mock=body.mock)
    return {"success": True, "platform": "slack", **result}


@router.post("/teams/send")
async def send_teams_message(body: SendMessage):
    """Send a simple text message to Teams."""
    payload = {"text": f"**{body.title}**\n\n{body.message}"}
    result  = await send_to_platform("teams", payload, "simple_message", mock=body.mock)
    return {"success": True, "platform": "teams", **result}


@router.post("/slack/analysis")
async def send_slack_analysis(body: SendAnalysis):
    """Run NLP analysis on text and send result to Slack."""
    from backend.demo1.risk_scorer import score_text
    # Build minimal analysis result
    result  = {"sentiment": "NEGATIVE", "score": 0.87, "entities": [], "label": body.label}
    payload = build_slack_analysis(result, label=body.label)
    outcome = await send_to_platform("slack", payload, "analysis", mock=body.mock)
    return {"success": True, "platform": "slack", **outcome}


@router.post("/teams/analysis")
async def send_teams_analysis(body: SendAnalysis):
    """Run NLP analysis on text and send result to Teams."""
    result  = {"sentiment": "NEGATIVE", "score": 0.87, "entities": [], "label": body.label}
    payload = build_teams_analysis(result, label=body.label)
    outcome = await send_to_platform("teams", payload, "analysis", mock=body.mock)
    return {"success": True, "platform": "teams", **outcome}


@router.post("/risk/alert")
async def send_risk_alert(body: SendRiskAlert):
    """Score text for risk and send alert to all configured channels."""
    from backend.demo1.risk_scorer import score_text
    risk = score_text(body.text, context=body.context)

    slack_payload = build_slack_risk(risk, label=body.label)
    teams_payload = build_teams_risk(risk, label=body.label)

    slack_result = await send_to_platform("slack", slack_payload, "risk_alert", mock=body.mock)
    teams_result = await send_to_platform("teams", teams_payload, "risk_alert", mock=body.mock)

    return {
        "success": True,
        "risk_score": risk["score"],
        "risk_level": risk["level"],
        "slack": slack_result,
        "teams": teams_result,
    }


@router.get("/config")
def get_config():
    """View all configured notification channels."""
    conn  = get_conn()
    rows  = conn.execute(
        "SELECT id, platform, label, active, created_at, last_used, send_count FROM notify_config ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return {"success": True, "count": len(rows), "channels": [dict(r) for r in rows]}


@router.get("/logs")
def get_notify_logs(platform: Optional[str] = None, limit: int = 50):
    """View notification delivery logs."""
    limit  = min(limit, 200)
    conn   = get_conn()
    query  = "SELECT * FROM notify_log WHERE 1=1"
    params = []
    if platform:
        query += " AND platform=?"
        params.append(platform)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return {"success": True, "count": len(rows), "logs": [dict(r) for r in rows]}
