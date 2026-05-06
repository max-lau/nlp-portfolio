"""
pdf_module_export.py
====================
FastAPI APIRouter: Generic /export/module endpoint.

Accepts a standard JSON payload describing any module's results
and renders a branded ParaIQ PDF — no per-module backend code needed.

Section payload types:
  { "type": "kv",      "heading": "...", "data": [["Key","Val"]] }
  { "type": "table",   "heading": "...", "headers": [...], "rows": [[...]] }
  { "type": "text",    "heading": "...", "content": "..." }
  { "type": "bullets", "heading": "...", "items": ["...", "..."] }

Mount in main.py:
  from backend.demo1.pdf_module_export import router as module_pdf_router
  app.include_router(module_pdf_router, prefix="/export", tags=["PDF Export"])
"""

import io
from datetime import datetime, timezone
from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional, List, Any

from reportlab.platypus import Paragraph, Spacer, KeepTogether
from reportlab.lib.units import inch

from backend.demo1.pdf_utils import (
    get_styles, make_header, make_kv_table, make_data_table,
    make_footer, make_divider, new_doc, GRAY
)

router = APIRouter()


# ── Pydantic models ────────────────────────────────────────────────────────────

class Section(BaseModel):
    type:    str                       # kv | table | text | bullets
    heading: Optional[str] = None
    # kv
    data:    Optional[List[List[str]]] = None
    # table
    headers: Optional[List[str]] = None
    rows:    Optional[List[List[Any]]] = None
    col_widths_in: Optional[List[float]] = None  # column widths in inches
    # text
    content: Optional[str] = None
    # bullets
    items:   Optional[List[str]] = None

class ModuleExportBody(BaseModel):
    module:   str                      # e.g. "credibility", "compare"
    title:    str                      # Report title
    subtitle: Optional[str] = None
    metadata: Optional[List[List[str]]] = None   # kv pairs for header table
    sections: List[Section]
    filename: Optional[str] = None


# ── PDF builder ────────────────────────────────────────────────────────────────

def build_module_pdf(body: ModuleExportBody) -> bytes:
    buf    = io.BytesIO()
    doc    = new_doc(buf)
    styles = get_styles()
    story  = []

    # ── Title + rule ─────────────────────────────────────────────────────────
    subtitle = body.subtitle or datetime.now(timezone.utc).strftime("%B %d, %Y")
    make_header(story, styles, body.title, subtitle)

    # ── Optional metadata table (date, attorney, case#, etc.) ──────────────
    if body.metadata:
        story.append(make_kv_table(body.metadata))
        story.append(Spacer(1, 10))

    # ── Sections ─────────────────────────────────────────────────────────────
    for sec in body.sections:

        block = []  # group heading + content in KeepTogether where possible

        if sec.heading:
            block.append(Paragraph(sec.heading, styles["section"]))

        if sec.type == "kv" and sec.data:
            block.append(make_kv_table(sec.data))
            block.append(Spacer(1, 8))

        elif sec.type == "table" and sec.headers and sec.rows is not None:
            cw = ([w * inch for w in sec.col_widths_in]
                  if sec.col_widths_in else None)
            # Stringify all cells for ReportLab safety
            safe_rows = [[str(c) for c in row] for row in sec.rows]
            block.append(make_data_table(sec.headers, safe_rows, col_widths=cw))
            block.append(Spacer(1, 8))

        elif sec.type == "text" and sec.content:
            # Escape XML-unsafe characters; preserve line breaks
            safe = (sec.content
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace("\n", "<br/>"))
            block.append(Paragraph(safe, styles["body"]))
            block.append(Spacer(1, 6))

        elif sec.type == "bullets" and sec.items:
            for item in sec.items:
                safe = (str(item)
                        .replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;"))
                block.append(Paragraph(f"• {safe}", styles["bullet"]))
            block.append(Spacer(1, 6))

        # Keep heading + first content element together across page breaks
        if len(block) > 1:
            story.append(KeepTogether(block[:2]))
            story.extend(block[2:])
        else:
            story.extend(block)

    # ── Footer ────────────────────────────────────────────────────────────────
    story.extend(make_divider())
    story.append(make_footer(styles))

    doc.build(story)
    return buf.getvalue()


# ── Route ──────────────────────────────────────────────────────────────────────

@router.post("/module")
def export_module_pdf(body: ModuleExportBody):
    """
    Generic PDF export for any ParaIQ module.
    Called by the frontend paraiq-export.js utility.
    """
    pdf_bytes = build_module_pdf(body)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = body.filename or f"{body.module}_report_{ts}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
