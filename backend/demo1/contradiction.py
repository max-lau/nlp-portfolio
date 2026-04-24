"""
Contradiction detection across documents using Claude + FAISS.
Finds conflicting claims about the same entities across stored analyses.
"""
import json
import os
import re
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from backend.demo1.database import get_connection
import anthropic
from dotenv import load_dotenv

load_dotenv()
client   = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")

def get_all_documents() -> list:
    """Pull full document texts from database."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, text, entities, sentiment, created_at FROM analyses"
    ).fetchall()
    conn.close()
    docs = []
    for row in rows:
        docs.append({
            "id":         row["id"],
            "text":       row["text"],
            "entities":   json.loads(row["entities"] or "[]"),
            "sentiment":  row["sentiment"],
            "created_at": row["created_at"]
        })
    return docs

def find_similar_doc_pairs(docs: list, top_k: int = 5) -> list:
    """Use FAISS to find document pairs worth checking for contradictions."""
    if len(docs) < 2:
        return []

    texts = [d["text"] for d in docs]
    vecs  = EMBEDDER.encode(texts, convert_to_numpy=True)
    vecs  = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)

    dim   = vecs.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(vecs.astype(np.float32))

    pairs = []
    seen  = set()
    for i, vec in enumerate(vecs):
        scores, indices = index.search(
            vec.reshape(1, -1).astype(np.float32), top_k + 1
        )
        for score, j in zip(scores[0], indices[0]):
            if j == i or j < 0:
                continue
            key = tuple(sorted([i, j]))
            if key in seen:
                continue
            seen.add(key)
            if float(score) > 0.40:
                pairs.append({
                    "doc_a": docs[i],
                    "doc_b": docs[j],
                    "similarity": round(float(score), 4)
                })

    pairs.sort(key=lambda x: x["similarity"], reverse=True)
    return pairs[:6]

def clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return raw.strip()

def detect_contradictions_in_pair(doc_a: dict, doc_b: dict) -> dict:
    """Use Claude to find contradictions between two documents."""
    prompt = f"""You are a legal fact-checker. Compare these two documents
and identify any factual contradictions — conflicting claims about the
same people, organizations, dates, locations, or amounts.

IMPORTANT: Respond ONLY with valid JSON. No markdown. No backticks.
Start with {{ and end with }}

Document A (ID {doc_a['id']}):
\"\"\"{doc_a['text'][:800]}\"\"\"

Document B (ID {doc_b['id']}):
\"\"\"{doc_b['text'][:800]}\"\"\"

Return this exact structure:
{{
  "has_contradictions": true,
  "contradictions": [
    {{
      "type": "date|location|amount|person|organization|fact",
      "severity": "high|medium|low",
      "entity": "who or what the contradiction is about",
      "claim_a": "what Document A says",
      "claim_b": "what Document B says",
      "explanation": "plain English explanation of the conflict"
    }}
  ],
  "shared_entities": ["entities mentioned in both documents"],
  "relationship": "related|unrelated|same_case|conflicting",
  "summary": "one sentence about the relationship between these documents"
}}

Rules:
- Only flag real contradictions, not just different topics
- max 4 contradictions
- If no contradictions found, return has_contradictions: false and empty array
- shared_entities: max 5"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw     = message.content[0].text
        cleaned = clean_json(raw)
        result  = json.loads(cleaned)
        result["doc_a_id"]      = doc_a["id"]
        result["doc_b_id"]      = doc_b["id"]
        result["doc_a_preview"] = doc_a["text"][:100]
        result["doc_b_preview"] = doc_b["text"][:100]
        result["similarity"]    = 0
        return result
    except Exception as e:
        return {
            "has_contradictions": False,
            "contradictions":     [],
            "shared_entities":    [],
            "relationship":       "unrelated",
            "summary":            f"Analysis failed: {str(e)}",
            "doc_a_id":           doc_a["id"],
            "doc_b_id":           doc_b["id"],
            "doc_a_preview":      doc_a["text"][:100],
            "doc_b_preview":      doc_b["text"][:100]
        }

def run_contradiction_scan() -> dict:
    """Full scan — find similar doc pairs then check each for contradictions."""
    docs = get_all_documents()
    if len(docs) < 2:
        return {
            "total_docs":         len(docs),
            "pairs_checked":      0,
            "contradictions_found": 0,
            "results":            []
        }

    pairs   = find_similar_doc_pairs(docs)
    results = []

    for pair in pairs:
        result = detect_contradictions_in_pair(pair["doc_a"], pair["doc_b"])
        result["similarity"] = pair["similarity"]
        results.append(result)

    contradictions_found = sum(
        1 for r in results if r.get("has_contradictions")
    )

    return {
        "total_docs":           len(docs),
        "pairs_checked":        len(pairs),
        "contradictions_found": contradictions_found,
        "results":              results
    }
