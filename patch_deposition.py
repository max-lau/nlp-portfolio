"""
patch_deposition.py
Run on VPS: python3 patch_deposition.py
Adds the /deposition/summarize endpoint to main.py.
"""

path = '/root/nlp-portfolio/backend/demo1/main.py'
content = open(path).read()

new_ep = '''
# ── Deposition Summary Generator ─────────────────────────────────────────────

class DepositionInput(BaseModel):
    transcript: str
    case_name: str = "Untitled Matter"
    deponent: str = "Witness"
    exam_counsel: str = ""
    depos_date: str = ""

@app.post("/deposition/summarize")
def deposition_summarize(body: DepositionInput):
    t = body.transcript[:7000]
    lines = [
        "You are an expert legal analyst. Analyze this deposition transcript and extract a structured summary.",
        "Return ONLY valid JSON, no markdown, no backticks:",
        "{",
        '  "case_overview": {',
        '    "case_name": "case name",',
        '    "deponent": "witness name",',
        '    "date": "deposition date",',
        '    "examining_counsel": "counsel name",',
        '    "summary": "2-3 sentence overview of the deposition and its significance"',
        "  },",
        '  "parties": [',
        '    {"name": "full name", "role": "Deponent/Attorney/Judge", "representation": "firm or party represented"}',
        "  ],",
        '  "key_admissions": [',
        '    {"admission": "what the deponent admitted", "significance": "why it matters legally", "quote": "verbatim quote"}',
        "  ],",
        '  "disputed_facts": [',
        '    {"fact": "the disputed fact", "deponent_position": "what deponent claims", "contrary_evidence": "evidence that contradicts"}',
        "  ],",
        '  "timeline": [',
        '    {"date_or_period": "specific date or period", "event": "what happened", "source": "who stated this"}',
        "  ],",
        '  "legal_issues": [',
        '    {"issue": "legal issue raised", "context": "context and relevance", "objections": "any objections or rulings"}',
        "  ]",
        "}",
        "",
        f"Case: {body.case_name}",
        f"Deponent: {body.deponent}",
        f"Examining Counsel: {body.exam_counsel}",
        f"Date: {body.depos_date}",
        "",
        "Transcript:",
        t
    ]
    prompt = chr(10).join(lines)

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text
        return json.loads(clean_json(raw))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail="JSON parse error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

'''

if '/deposition/summarize' not in content:
    content = content + new_ep
    open(path, 'w').write(content)
    print("SUCCESS — /deposition/summarize endpoint added")
else:
    print("Already exists — no changes made")
