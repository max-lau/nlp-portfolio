"""
patch_credibility.py
Run on VPS: python3 patch_credibility.py
Adds the /credibility/score endpoint to main.py.
"""

path = '/root/nlp-portfolio/backend/demo1/main.py'
content = open(path).read()

new_ep = '''
# ── Witness Credibility Scorer ────────────────────────────────────────────────

class CredibilityInput(BaseModel):
    transcript: str
    witness_name: str = "Witness"
    role: str = "Witness"
    case_name: str = ""

@app.post("/credibility/score")
def credibility_score(body: CredibilityInput):
    t = body.transcript[:6000]
    w = body.witness_name
    lines = [
        f"You are an expert legal analyst scoring the credibility of a witness named {w}.",
        "Analyze the provided testimony transcript and score the witness on 5 dimensions (0-10 each).",
        "Return ONLY valid JSON, no markdown, no backticks:",
        '{',
        '  "overall_score": 6.2,',
        '  "summary": "One sentence overall credibility assessment.",',
        '  "scores": {',
        '    "consistency": {"score": 7, "explanation": "explanation", "key_quote": "verbatim quote from transcript"},',
        '    "responsiveness": {"score": 6, "explanation": "explanation", "key_quote": "verbatim quote"},',
        '    "clarity": {"score": 5, "explanation": "explanation", "key_quote": "verbatim quote"},',
        '    "corroboration": {"score": 4, "explanation": "explanation", "key_quote": "verbatim quote"},',
        '    "demeanor": {"score": 3, "explanation": "explanation", "key_quote": "verbatim quote"}',
        '  },',
        '  "key_findings": [',
        '    {"type": "strength", "finding": "positive credibility observation"},',
        '    {"type": "concern", "finding": "credibility concern or red flag"}',
        '  ]',
        '}',
        '',
        'Scoring guide:',
        '- consistency: 10=no contradictions, 0=major self-contradictions',
        '- responsiveness: 10=answers all questions directly, 0=never answers directly',
        '- clarity: 10=clear precise language, 0=vague hedging throughout',
        '- corroboration: 10=testimony matches all evidence cited, 0=contradicts all evidence',
        '- demeanor: 10=calm direct confident, 0=evasive hesitant deflecting throughout',
        '',
        f'Transcript of {w}:',
        t
    ]
    prompt = "\n".join(lines)

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text
        return json.loads(clean_json(raw))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail="JSON parse error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

'''

# Find a safe insertion point — append before the last @app route or at end
import re
# Insert before the lease-diff or stats endpoint, or just append
if '/credibility/score' not in content:
    # Append to end of file
    content = content + new_ep
    open(path, 'w').write(content)
    print("SUCCESS — /credibility/score endpoint added")
else:
    print("Already exists — no changes made")
