"""
pdf_utils.py
============
Shared ReportLab utilities for ParaIQ PDF exports.
Imported by pdf_export.py, interrogation_export.py, and pdf_module_export.py.

Extracted from pdf_export.py to eliminate duplication.
"""

import io
from datetime import datetime, timezone
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

# ── Brand colours ──────────────────────────────────────────────────────────────

DARK   = colors.HexColor("#1a1a2e")
PURPLE = colors.HexColor("#7c3aed")
GOLD   = colors.HexColor("#c9a84c")
RED    = colors.HexColor("#c0392b")
GREEN  = colors.HexColor("#27ae60")
GRAY   = colors.HexColor("#7f8c8d")
LGRAY  = colors.HexColor("#ecf0f1")
FAINT  = colors.HexColor("#f8f9fa")


# ── Styles ─────────────────────────────────────────────────────────────────────

def get_styles() -> dict:
    """Return a dict of named ParagraphStyles matching ParaIQ brand."""
    return {
        "title": ParagraphStyle("piq_title",
            fontSize=22, textColor=DARK, fontName="Helvetica-Bold",
            spaceAfter=4, alignment=TA_LEFT),
        "subtitle": ParagraphStyle("piq_subtitle",
            fontSize=11, textColor=GRAY, fontName="Helvetica",
            spaceAfter=12, alignment=TA_LEFT),
        "section": ParagraphStyle("piq_section",
            fontSize=13, textColor=DARK, fontName="Helvetica-Bold",
            spaceBefore=14, spaceAfter=6),
        "body": ParagraphStyle("piq_body",
            fontSize=9, textColor=colors.black, fontName="Helvetica",
            spaceAfter=4, leading=14),
        "small": ParagraphStyle("piq_small",
            fontSize=8, textColor=GRAY, fontName="Helvetica",
            spaceAfter=2),
        "label": ParagraphStyle("piq_label",
            fontSize=8, textColor=GRAY, fontName="Helvetica-Bold",
            spaceAfter=1),
        "value": ParagraphStyle("piq_value",
            fontSize=10, textColor=DARK, fontName="Helvetica-Bold",
            spaceAfter=4),
        "bullet": ParagraphStyle("piq_bullet",
            fontSize=9, textColor=colors.black, fontName="Helvetica",
            spaceAfter=3, leftIndent=12, leading=14),
    }


# ── Risk colour map ────────────────────────────────────────────────────────────

def risk_color(level: str) -> colors.HexColor:
    return {
        "critical": colors.HexColor("#c0392b"),
        "high":     colors.HexColor("#e67e22"),
        "medium":   colors.HexColor("#f39c12"),
        "low":      colors.HexColor("#27ae60"),
        "minimal":  colors.HexColor("#2980b9"),
    }.get((level or "").lower(), GRAY)


# ── Building blocks ────────────────────────────────────────────────────────────

def make_header(story: list, styles: dict, title: str, subtitle: str = None):
    """Title + gold rule at top of every report."""
    from reportlab.platypus import Table, TableStyle as TS
    if subtitle:
        # Put title (left) and date (right) on the same row above the rule
        date_style = ParagraphStyle("piq_header_date",
            fontSize=9, textColor=GRAY, fontName="Helvetica",
            alignment=TA_RIGHT, leading=14)
        header_tbl = Table(
            [[Paragraph(title, styles["title"]), Paragraph(subtitle, date_style)]],
            colWidths=[4.5 * inch, 1.85 * inch]
        )
        header_tbl.setStyle(TS([
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING",   (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
        ]))
        story.append(header_tbl)
    else:
        story.append(Paragraph(title, styles["title"]))
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=2, color=GOLD, spaceAfter=18))


def make_kv_table(data: list, col_widths: list = None) -> Table:
    """
    Two-column key/value table.
    data: list of [key, value] pairs.
    Values are wrapped in Paragraphs so long text wraps instead of overflowing.
    """
    col_widths = col_widths or [2.2 * inch, 4.3 * inch]
    styles = get_styles()
    key_style = ParagraphStyle("kv_key",
        fontSize=9, fontName="Helvetica-Bold", textColor=DARK, leading=13)
    val_style = ParagraphStyle("kv_val",
        fontSize=9, fontName="Helvetica", textColor=colors.black, leading=13)
    wrapped = []
    for row in data:
        k = str(row[0]) if len(row) > 0 else ""
        v = str(row[1]) if len(row) > 1 else ""
        wrapped.append([Paragraph(k, key_style), Paragraph(v, val_style)])
    tbl = Table(wrapped, colWidths=col_widths)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, -1), LGRAY),
        ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",      (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",     (0, 0), (0, -1), DARK),
        ("ROWBACKGROUNDS",(0, 0), (-1, -1), [colors.white, FAINT]),
        ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
    ]))
    return tbl


def make_data_table(headers: list, rows: list, col_widths: list = None) -> Table:
    """
    Standard data table with dark header row.
    headers: list of column labels.
    rows: list of row value lists.
    """
    all_rows = [headers] + rows
    # Auto-distribute width if not specified
    if not col_widths:
        n = len(headers)
        total = 6.3  # usable inches (letter - margins)
        col_widths = [round(total / n, 2) * inch] * n

    tbl = Table(all_rows, colWidths=col_widths)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, LGRAY]),
        ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    return tbl


def make_footer(styles: dict) -> Paragraph:
    """Timestamp footer — goes on every report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return Paragraph(
        f"Generated by ParaIQ NLP Legal Intelligence · {now}",
        styles["small"]
    )


def make_divider() -> list:
    """Return [Spacer, HRFlowable, Spacer] to use before the footer."""
    return [
        Spacer(1, 16),
        HRFlowable(width="100%", thickness=0.5, color=GRAY),
        Spacer(1, 4),
    ]


# ── Document factory ───────────────────────────────────────────────────────────

def new_doc(buf: io.BytesIO) -> SimpleDocTemplate:
    """Standard ParaIQ letter-size document with consistent margins."""
    return SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=0.85 * inch, rightMargin=0.85 * inch,
        topMargin=0.9 * inch,   bottomMargin=0.9 * inch
    )
