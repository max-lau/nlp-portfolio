"""
audit_trail.py
==============
FastAPI Middleware + APIRouter: Audit Trail (#20)
Logs every API request to the audit_log table in analyses.db:
  - endpoint, method, status_code, response_time_ms
  - timestamp, client_ip, request_body_size
Query endpoints to review audit history.
"""

import time
import sqlite3
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional

DB_PATH = "backend/demo1/analyses.db"
router  = APIRouter()


# ── DB Setup ───────────────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_audit_table():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT    NOT NULL,
            method          TEXT    NOT NULL,
            endpoint        TEXT    NOT NULL,
            status_code     INTEGER,
            response_time_ms REAL,
            client_ip       TEXT,
            body_size_bytes INTEGER,
            error           TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("[AuditTrail] Table initialized ✓")


def log_request(method, endpoint, status_code, response_time_ms,
                client_ip, body_size, error=None):
    try:
        conn = get_conn()
        conn.execute("""
            INSERT INTO audit_log
              (timestamp, method, endpoint, status_code,
               response_time_ms, client_ip, body_size_bytes, error)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            method, endpoint, status_code,
            round(response_time_ms, 2),
            client_ip, body_size,
            str(error) if error else None
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[AuditTrail] Log error: {e}")


# ── Middleware ─────────────────────────────────────────────────────────────────

class AuditMiddleware(BaseHTTPMiddleware):
    """Intercepts every request and logs it to audit_log."""

    # Skip noisy internal endpoints
    SKIP_PATHS = {"/docs", "/openapi.json", "/redoc", "/favicon.ico", "/health"}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in self.SKIP_PATHS:
            return await call_next(request)

        start      = time.perf_counter()
        client_ip  = request.client.host if request.client else "unknown"
        body       = await request.body()
        body_size  = len(body)

        # Re-inject body so downstream handlers can still read it
        async def receive():
            return {"type": "http.request", "body": body}
        request._receive = receive

        status_code = 500
        error       = None
        try:
            response    = await call_next(request)
            status_code = response.status_code
        except Exception as e:
            error = str(e)
            response = JSONResponse(
                {"detail": "Internal server error"}, status_code=500
            )

        elapsed_ms = (time.perf_counter() - start) * 1000

        log_request(
            method           = request.method,
            endpoint         = path,
            status_code      = status_code,
            response_time_ms = elapsed_ms,
            client_ip        = client_ip,
            body_size        = body_size,
            error            = error,
        )

        return response


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/logs")
def get_audit_logs(
    endpoint: Optional[str] = None,
    method:   Optional[str] = None,
    status:   Optional[int] = None,
    limit:    int = 50,
):
    """
    Retrieve audit log entries with optional filters.
    - endpoint: filter by path (partial match)
    - method: GET, POST, PUT, DELETE
    - status: HTTP status code
    - limit: max records (default 50, max 200)
    """
    limit = min(limit, 200)
    conn  = get_conn()

    query  = "SELECT * FROM audit_log WHERE 1=1"
    params = []

    if endpoint:
        query += " AND endpoint LIKE ?"
        params.append(f"%{endpoint}%")
    if method:
        query += " AND method = ?"
        params.append(method.upper())
    if status:
        query += " AND status_code = ?"
        params.append(status)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return {
        "success": True,
        "count": len(rows),
        "logs": [dict(r) for r in rows],
    }


@router.get("/stats")
def audit_stats():
    """Aggregate statistics from the audit log."""
    conn = get_conn()

    total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]

    by_endpoint = conn.execute("""
        SELECT endpoint, COUNT(*) cnt,
               ROUND(AVG(response_time_ms),2) avg_ms,
               MIN(status_code) min_status,
               MAX(status_code) max_status
        FROM audit_log
        GROUP BY endpoint
        ORDER BY cnt DESC
        LIMIT 20
    """).fetchall()

    by_status = conn.execute("""
        SELECT status_code, COUNT(*) cnt
        FROM audit_log
        GROUP BY status_code
        ORDER BY cnt DESC
    """).fetchall()

    slowest = conn.execute("""
        SELECT endpoint, method, response_time_ms, timestamp
        FROM audit_log
        ORDER BY response_time_ms DESC
        LIMIT 5
    """).fetchall()

    errors = conn.execute("""
        SELECT endpoint, method, error, timestamp
        FROM audit_log
        WHERE error IS NOT NULL
        ORDER BY id DESC
        LIMIT 10
    """).fetchall()

    conn.close()

    return {
        "success": True,
        "total_requests": total,
        "by_endpoint": [dict(r) for r in by_endpoint],
        "by_status_code": [dict(r) for r in by_status],
        "slowest_endpoints": [dict(r) for r in slowest],
        "recent_errors": [dict(r) for r in errors],
    }


@router.delete("/logs/clear")
def clear_audit_logs():
    """Clear all audit log entries. Use with caution."""
    conn = get_conn()
    conn.execute("DELETE FROM audit_log")
    conn.commit()
    conn.close()
    return {"success": True, "message": "Audit log cleared"}
