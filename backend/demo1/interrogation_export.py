"""
interrogation_export.py
ParaIQ — Court-ready PDF export for the Interrogation Analyzer module.
Generates a multi-page ReportLab PDF with:
  Page 1 : Header + metadata + summary bar
  Page 2 : Full speaker diarization transcript
  Page 3 : Q&A segmentation pairs
  Page 4 : Contradiction detection findings
  Page 5 : Evasion & inconsistency findings
  Final  : Attorney certification
"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse, Response, Response
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone
import io

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

router = APIRouter()

# ── Colour palette (matches ParaIQ dark UI, rendered on white paper) ──────────
PURPLE      = colors.HexColor('#7c3aed')
PURPLE_DARK = colors.HexColor('#5b21b6')
PURPLE_LIGHT= colors.HexColor('#a78bfa')
CYAN        = colors.HexColor('#0891b2')
GREEN       = colors.HexColor('#059669')
RED         = colors.HexColor('#dc2626')
AMBER       = colors.HexColor('#d97706')
SLATE_DARK  = colors.HexColor('#1e293b')
SLATE_MID   = colors.HexColor('#334155')
SLATE_LIGHT = colors.HexColor('#64748b')
WHITE       = colors.white
OFF_WHITE   = colors.HexColor('#f8fafc')
LIGHT_GRAY  = colors.HexColor('#e2e8f0')

# ── Pydantic models ────────────────────────────────────────────────────────────

class Turn(BaseModel):
    label: str
    role: str          # attorney | witness | judge | other
    text: str

class QAPair(BaseModel):
    q_label: str
    q_text: str
    a_label: str
    a_text: str

class Contradiction(BaseModel):
    title: str
    explanation: str
    quote_a: Optional[str] = ""
    quote_b: Optional[str] = ""

class Evasion(BaseModel):
    title: str
    explanation: str
    quote: Optional[str] = ""

class ExportRequest(BaseModel):
    case_name:     Optional[str] = "Untitled Matter"
    attorney_name: Optional[str] = ""
    court:         Optional[str] = ""
    date_analyzed: Optional[str] = ""
    turns:         List[Turn]    = []
    qa_pairs:      List[QAPair]  = []
    contradictions: List[Contradiction] = []
    evasions:      List[Evasion] = []

# ── Style factory ──────────────────────────────────────────────────────────────

def styles():
    base = dict(fontName='Helvetica', leading=14)
    bold = dict(fontName='Helvetica-Bold')
    return {
        'title':    ParagraphStyle('title',    fontSize=20, **bold, textColor=SLATE_DARK,  alignment=TA_CENTER, spaceAfter=4),
        'subtitle': ParagraphStyle('subtitle', fontSize=11, **base, textColor=SLATE_LIGHT, alignment=TA_CENTER, spaceAfter=12),
        'h1':       ParagraphStyle('h1',       fontSize=13, **bold, textColor=WHITE,       spaceAfter=8),
        'h2':       ParagraphStyle('h2',       fontSize=11, **bold, textColor=SLATE_DARK,  spaceAfter=6, spaceBefore=10),
        'body':     ParagraphStyle('body',     fontSize=9,  **base, textColor=SLATE_DARK),
        'body_sm':  ParagraphStyle('body_sm',  fontSize=8,  **base, textColor=SLATE_MID),
        'label':    ParagraphStyle('label',    fontSize=7,  **bold, textColor=SLATE_LIGHT, spaceAfter=1),
        'quote':    ParagraphStyle('quote',    fontSize=8,  fontName='Helvetica-Oblique',
                                   textColor=SLATE_MID, leftIndent=12, rightIndent=12,
                                   borderPad=4, spaceAfter=4),
        'atty':     ParagraphStyle('atty',     fontSize=9,  **base, textColor=colors.HexColor('#5b21b6')),
        'witness':  ParagraphStyle('witness',  fontSize=9,  **base, textColor=CYAN),
        'judge':    ParagraphStyle('judge',    fontSize=9,  **base, textColor=AMBER),
        'other':    ParagraphStyle('other',    fontSize=9,  **base, textColor=SLATE_MID),
        'footer':   ParagraphStyle('footer',   fontSize=7,  **base, textColor=SLATE_LIGHT, alignment=TA_CENTER),
        'center':   ParagraphStyle('center',   fontSize=9,  **base, textColor=SLATE_DARK,  alignment=TA_CENTER),
        'right':    ParagraphStyle('right',    fontSize=9,  **base, textColor=SLATE_DARK,  alignment=TA_RIGHT),
    }

def safe(text: str) -> str:
    """Escape XML special chars for ReportLab Paragraph."""
    return (text or '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

# ── Section banner ─────────────────────────────────────────────────────────────

def section_banner(label: str, bg: colors.Color, story: list, s: dict):
    banner_data = [[Paragraph(f'<b>{label}</b>', s['h1'])]]
    t = Table(banner_data, colWidths=[6.5*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), bg),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING',   (0,0), (-1,-1), 12),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))

# ── PAGE 1 — Cover / Metadata / Summary ───────────────────────────────────────

def build_cover(req: ExportRequest, s: dict, story: list):
    now = req.date_analyzed or datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    # Court header
    story.append(Paragraph('INTERROGATION ANALYSIS REPORT', s['title']))
    story.append(Paragraph('Generated by ParaIQ Legal NLP Platform', s['subtitle']))
    story.append(HRFlowable(width='100%', thickness=2, color=PURPLE, spaceAfter=14))

    # Metadata table
    meta_rows = [
        ['Matter / Case', safe(req.case_name)],
        ['Court / Jurisdiction', safe(req.court) or '—'],
        ['Analyzing Attorney', safe(req.attorney_name) or '—'],
        ['Analysis Date', safe(now)],
        ['Analysis System', 'ParaIQ AI — Interrogation Analyzer'],
    ]
    meta_table = Table(
        [[Paragraph(f'<b>{r[0]}</b>', s['body_sm']),
          Paragraph(r[1], s['body'])] for r in meta_rows],
        colWidths=[2*inch, 4.5*inch]
    )
    meta_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (0,-1), LIGHT_GRAY),
        ('ROWBACKGROUNDS',(1,0), (1,-1), [OFF_WHITE, WHITE]),
        ('GRID',          (0,0), (-1,-1), 0.4, LIGHT_GRAY),
        ('TOPPADDING',    (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 18))

    # Summary bar
    n_turns   = len(req.turns)
    n_pairs   = len(req.qa_pairs)
    n_contra  = len(req.contradictions)
    n_evasion = len(req.evasions)

    sum_data = [[
        Paragraph(f'<b><font color="{CYAN.hexval()}">{n_turns}</font></b><br/><font size="7">TOTAL TURNS</font>', s['center']),
        Paragraph(f'<b><font color="{GREEN.hexval()}">{n_pairs}</font></b><br/><font size="7">Q&amp;A PAIRS</font>', s['center']),
        Paragraph(f'<b><font color="{RED.hexval()}">{n_contra}</font></b><br/><font size="7">CONTRADICTIONS</font>', s['center']),
        Paragraph(f'<b><font color="{AMBER.hexval()}">{n_evasion}</font></b><br/><font size="7">EVASIONS</font>', s['center']),
    ]]
    sum_table = Table(sum_data, colWidths=[1.625*inch]*4)
    sum_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), SLATE_DARK),
        ('TOPPADDING',    (0,0), (-1,-1), 12),
        ('BOTTOMPADDING', (0,0), (-1,-1), 12),
        ('INNERGRID',     (0,0), (-1,-1), 0.5, SLATE_MID),
        ('BOX',           (0,0), (-1,-1), 1, PURPLE),
        ('FONTSIZE',      (0,0), (-1,-1), 16),
    ]))
    story.append(sum_table)
    story.append(PageBreak())

# ── PAGE 2 — Speaker Diarization ──────────────────────────────────────────────

ROLE_COLOR = {
    'attorney': colors.HexColor('#ede9fe'),
    'witness':  colors.HexColor('#e0f2fe'),
    'judge':    colors.HexColor('#fef3c7'),
    'other':    OFF_WHITE,
}
ROLE_LABEL_COLOR = {
    'attorney': PURPLE,
    'witness':  CYAN,
    'judge':    AMBER,
    'other':    SLATE_MID,
}

def build_diarization(req: ExportRequest, s: dict, story: list):
    section_banner('SPEAKER DIARIZATION — FULL TRANSCRIPT', CYAN, story, s)

    if not req.turns:
        story.append(Paragraph('No labeled turns detected.', s['body']))
        story.append(PageBreak())
        return

    for turn in req.turns:
        role  = turn.role or 'other'
        bg    = ROLE_COLOR.get(role, OFF_WHITE)
        lc    = ROLE_LABEL_COLOR.get(role, SLATE_MID)
        label_p = Paragraph(f'<b><font color="{lc.hexval()}">{safe(turn.label)}</font></b>', s['label'])
        text_p  = Paragraph(safe(turn.text), s['body'])
        row = Table([[label_p], [text_p]], colWidths=[6.5*inch])
        row.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), bg),
            ('LEFTPADDING',   (0,0), (-1,-1), 10),
            ('RIGHTPADDING',  (0,0), (-1,-1), 10),
            ('TOPPADDING',    (0,0), (0,0),   5),
            ('BOTTOMPADDING', (0,1), (0,1),   7),
            ('LINEAFTER',     (0,0), (0,-1),  3, lc),
        ]))
        story.append(KeepTogether([row, Spacer(1, 4)]))

    story.append(PageBreak())

# ── PAGE 3 — Q&A Segmentation ─────────────────────────────────────────────────

def build_qa(req: ExportRequest, s: dict, story: list):
    section_banner('Q&amp;A SEGMENTATION', GREEN, story, s)

    if not req.qa_pairs:
        story.append(Paragraph('No Q&A pairs detected.', s['body']))
        story.append(PageBreak())
        return

    for i, pair in enumerate(req.qa_pairs, 1):
        q_label = Paragraph(f'<b><font color="{PURPLE.hexval()}">Q — {safe(pair.q_label)}</font></b>', s['label'])
        q_text  = Paragraph(safe(pair.q_text), s['body'])
        q_block = Table([[q_label], [q_text]], colWidths=[6.5*inch])
        q_block.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), colors.HexColor('#f5f3ff')),
            ('LEFTPADDING',   (0,0), (-1,-1), 10),
            ('RIGHTPADDING',  (0,0), (-1,-1), 10),
            ('TOPPADDING',    (0,0), (0,0),   5),
            ('BOTTOMPADDING', (0,1), (0,1),   7),
            ('LINEAFTER',     (0,0), (0,-1),  3, PURPLE),
        ]))

        a_label = Paragraph(f'<b><font color="{CYAN.hexval()}">A — {safe(pair.a_label)}</font></b>', s['label'])
        a_text  = Paragraph(safe(pair.a_text), s['body'])
        a_block = Table([[a_label], [a_text]], colWidths=[6*inch])
        a_block.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), colors.HexColor('#ecfeff')),
            ('LEFTPADDING',   (0,0), (-1,-1), 10),
            ('RIGHTPADDING',  (0,0), (-1,-1), 10),
            ('TOPPADDING',    (0,0), (0,0),   5),
            ('BOTTOMPADDING', (0,1), (0,1),   7),
            ('LINEAFTER',     (0,0), (0,-1),  3, CYAN),
        ]))

        story.append(KeepTogether([
            q_block, Spacer(1, 3),
            Table([[None, a_block]], colWidths=[0.5*inch, 6*inch]),
            Spacer(1, 8)
        ]))

    story.append(PageBreak())

# ── PAGE 4 — Contradictions ───────────────────────────────────────────────────

def build_contradictions(req: ExportRequest, s: dict, story: list):
    section_banner('CONTRADICTION DETECTION', RED, story, s)

    if not req.contradictions:
        story.append(Paragraph('No contradictions detected.', s['body']))
        story.append(PageBreak())
        return

    for i, c in enumerate(req.contradictions, 1):
        elems = [
            Paragraph(f'<b>{i}. {safe(c.title)}</b>', s['h2']),
            Paragraph(safe(c.explanation), s['body']),
            Spacer(1, 4),
        ]
        if c.quote_a:
            elems.append(Paragraph(f'"{safe(c.quote_a)}"', s['quote']))
        if c.quote_b:
            elems.append(Paragraph(f'"{safe(c.quote_b)}"', s['quote']))

        block_data = [[e] for e in elems]
        block = Table(block_data, colWidths=[6.5*inch])
        block.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), colors.HexColor('#fff1f2')),
            ('LEFTPADDING',   (0,0), (-1,-1), 12),
            ('RIGHTPADDING',  (0,0), (-1,-1), 12),
            ('TOPPADDING',    (0,0), (0,0),   8),
            ('BOTTOMPADDING', (0,-1),(-1,-1), 8),
            ('BOX',           (0,0), (-1,-1), 0.5, RED),
            ('LINEAFTER',     (0,0), (0,-1),  4,   RED),
        ]))
        story.append(KeepTogether([block, Spacer(1, 10)]))

    story.append(PageBreak())

# ── PAGE 5 — Evasion & Inconsistency ─────────────────────────────────────────

def build_evasions(req: ExportRequest, s: dict, story: list):
    section_banner('EVASION &amp; INCONSISTENCY', AMBER, story, s)

    if not req.evasions:
        story.append(Paragraph('No evasions detected.', s['body']))
        story.append(PageBreak())
        return

    for i, e in enumerate(req.evasions, 1):
        elems = [
            Paragraph(f'<b>{i}. {safe(e.title)}</b>', s['h2']),
            Paragraph(safe(e.explanation), s['body']),
            Spacer(1, 4),
        ]
        if e.quote:
            elems.append(Paragraph(f'"{safe(e.quote)}"', s['quote']))

        block_data = [[el] for el in elems]
        block = Table(block_data, colWidths=[6.5*inch])
        block.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), colors.HexColor('#fffbeb')),
            ('LEFTPADDING',   (0,0), (-1,-1), 12),
            ('RIGHTPADDING',  (0,0), (-1,-1), 12),
            ('TOPPADDING',    (0,0), (0,0),   8),
            ('BOTTOMPADDING', (0,-1),(-1,-1), 8),
            ('BOX',           (0,0), (-1,-1), 0.5, AMBER),
            ('LINEAFTER',     (0,0), (0,-1),  4,   AMBER),
        ]))
        story.append(KeepTogether([block, Spacer(1, 10)]))

    story.append(PageBreak())

# ── FINAL PAGE — Attorney Certification ───────────────────────────────────────

def build_certification(req: ExportRequest, s: dict, story: list):
    section_banner('ATTORNEY CERTIFICATION', PURPLE_DARK, story, s)

    cert_text = (
        "I, the undersigned attorney, hereby certify that the foregoing Interrogation Analysis Report "
        "was generated using the ParaIQ Legal NLP Platform and that the contradiction and evasion "
        "findings identified herein are based on the transcript provided. This report is prepared as "
        "attorney work product and is intended solely for use in connection with the above-referenced matter."
    )
    story.append(Paragraph(cert_text, s['body']))
    story.append(Spacer(1, 30))

    sig_data = [
        [Paragraph('<b>Attorney Signature</b>', s['body_sm']), '', Paragraph('<b>Date</b>', s['body_sm'])],
        ['_' * 45, '', '_' * 20],
        [Paragraph(f'Print Name: {safe(req.attorney_name) or "_" * 30}', s['body_sm']), '',
         Paragraph('Bar Number: _______________', s['body_sm'])],
    ]
    sig_table = Table(sig_data, colWidths=[3.5*inch, 0.5*inch, 2.5*inch])
    sig_table.setStyle(TableStyle([
        ('TOPPADDING',    (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(sig_table)
    story.append(Spacer(1, 30))
    story.append(HRFlowable(width='100%', thickness=0.5, color=LIGHT_GRAY))
    story.append(Spacer(1, 6))
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    story.append(Paragraph(
        f'Generated by ParaIQ Legal NLP Platform | {now} | CONFIDENTIAL — ATTORNEY WORK PRODUCT',
        s['footer']
    ))

# ── PAGE NUMBERING ─────────────────────────────────────────────────────────────

def add_page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(SLATE_LIGHT)
    page_num = f'Page {doc.page}'
    canvas.drawRightString(7.5*inch, 0.4*inch, page_num)
    canvas.drawString(inch, 0.4*inch, 'ParaIQ — CONFIDENTIAL ATTORNEY WORK PRODUCT')
    canvas.restoreState()

# ── MAIN EXPORT ENDPOINT ───────────────────────────────────────────────────────

@router.post('/interrogate/export-pdf')
def export_interrogation_pdf(req: ExportRequest):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch,
        title=f'Interrogation Report — {req.case_name}',
        author='ParaIQ Legal NLP Platform',
        subject='Legal Interrogation Analysis',
    )

    s = styles()
    story = []

    build_cover(req, s, story)
    build_diarization(req, s, story)
    build_qa(req, s, story)
    build_contradictions(req, s, story)
    build_evasions(req, s, story)
    build_certification(req, s, story)

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    pdf_bytes = buffer.read()

    filename = f"interrogation_report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )
