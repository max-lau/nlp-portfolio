"""
patch_lease_diff.py
Run on VPS: python3 patch_lease_diff.py
Adds the /documents/lease-diff endpoint to main.py cleanly.
"""
import re

path = '/root/nlp-portfolio/backend/demo1/main.py'
content = open(path).read()

# Remove any broken previous attempts
content = re.sub(
    r'# ── Lease Clause Diff.*?(?=\n# ──|\n@app\.get\("/stats"\))',
    '',
    content,
    flags=re.DOTALL
)

new_ep = '''# ── Lease Clause Diff ─────────────────────────────────────────────────────────

class LeaseDiffInput(BaseModel):
    doc_a: str
    doc_b: str

@app.post("/documents/lease-diff")
def lease_diff(body: LeaseDiffInput):
    da = body.doc_a[:4000]
    db = body.doc_b[:4000]
    lines = [
        "You are a legal analyst specializing in lease contracts.",
        "Compare these two lease versions and identify all clause changes.",
        "Return ONLY valid JSON with these exact keys — no markdown, no backticks:",
        '{"key_term_changes":["Rent: $3500/mo to $3750/mo","Term: 12 months to 24 months"],',
        '"added":[{"clause":"Clause Name","detail":"What was added in Version B"}],',
        '"removed":[{"clause":"Clause Name","detail":"What was in Version A but removed in B"}],',
        '"modified":[{"clause":"Clause Name","change":"Exactly what changed between versions"}]}',
        "",
        "Lease Version A:",
        da,
        "",
        "Lease Version B:",
        db,
    ]
    prompt = "\n".join(lines)

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text
        return json.loads(clean_json(raw))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail="JSON parse error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

'''

target = '@app.get("/stats")'
if target in content:
    content = content.replace(target, new_ep + target, 1)
    open(path, 'w').write(content)
    print("SUCCESS — lease-diff endpoint added")
    print("Routes with 'lease':", ['lease-diff' in content])
else:
    print("ERROR — could not find insertion point")
