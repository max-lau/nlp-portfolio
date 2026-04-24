"""
Cross-document entity linking using FAISS vector similarity search.
Finds the same entity mentioned differently across multiple documents.
"""
import json
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from backend.demo1.database import get_connection
from typing import List, Dict

# Load model once at module level
print("Loading sentence transformer model...")
EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")
print("Model loaded.")

def get_all_entities() -> List[Dict]:
    """Pull all entities from stored analyses."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, entities, text, created_at, sentiment FROM analyses"
    ).fetchall()
    conn.close()

    all_entities = []
    for row in rows:
        try:
            entities = json.loads(row["entities"] or "[]")
            for ent in entities:
                all_entities.append({
                    "analysis_id": row["id"],
                    "text":        ent.get("text", ""),
                    "type":        ent.get("type", "OTHER"),
                    "doc_preview": row["text"][:100],
                    "doc_sentiment": row["sentiment"],
                    "created_at":  row["created_at"]
                })
        except Exception:
            continue

    return all_entities

def find_linked_entities(query_entity: str, top_k: int = 5,
                          threshold: float = 0.75) -> List[Dict]:
    """
    Find entities across all documents that are semantically similar
    to the query entity — i.e. likely refer to the same real-world thing.
    """
    all_entities = get_all_entities()
    if not all_entities:
        return []

    # Build FAISS index
    texts      = [e["text"] for e in all_entities]
    embeddings = EMBEDDER.encode(texts, convert_to_numpy=True)
    embeddings = embeddings / np.linalg.norm(
        embeddings, axis=1, keepdims=True
    )  # normalize for cosine similarity

    dim   = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)  # inner product = cosine on normalized vecs
    index.add(embeddings.astype(np.float32))

    # Encode query
    query_vec = EMBEDDER.encode([query_entity], convert_to_numpy=True)
    query_vec = query_vec / np.linalg.norm(query_vec, axis=1, keepdims=True)

    # Search
    scores, indices = index.search(query_vec.astype(np.float32), top_k + 1)

    results = []
    seen_texts = set()
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0 or float(score) < threshold:
            continue
        ent = all_entities[idx]
        if ent["text"].lower() == query_entity.lower():
            continue  # skip exact match to self
        if ent["text"].lower() in seen_texts:
            continue
        seen_texts.add(ent["text"].lower())
        results.append({
            "entity":       ent["text"],
            "type":         ent["type"],
            "similarity":   round(float(score), 4),
            "analysis_id":  ent["analysis_id"],
            "doc_preview":  ent["doc_preview"],
            "doc_sentiment": ent["doc_sentiment"],
            "created_at":   ent["created_at"]
        })

    return results

def link_documents_by_entity(min_shared: int = 1) -> List[Dict]:
    """
    Find pairs of documents that share linked entities —
    i.e. mention the same real-world people/orgs/places.
    """
    all_entities = get_all_entities()
    if not all_entities:
        return []

    # Group by analysis_id
    doc_entities = {}
    for e in all_entities:
        aid = e["analysis_id"]
        if aid not in doc_entities:
            doc_entities[aid] = {
                "analysis_id": aid,
                "doc_preview": e["doc_preview"],
                "entities":    []
            }
        doc_entities[aid]["entities"].append(e["text"])

    docs = list(doc_entities.values())
    if len(docs) < 2:
        return []

    # Embed all entity sets as averaged vectors
    doc_vecs = []
    for doc in docs:
        ent_texts = doc["entities"]
        if not ent_texts:
            doc_vecs.append(np.zeros(384))
            continue
        vecs = EMBEDDER.encode(ent_texts, convert_to_numpy=True)
        avg  = vecs.mean(axis=0)
        avg  = avg / (np.linalg.norm(avg) + 1e-10)
        doc_vecs.append(avg)

    doc_vecs = np.array(doc_vecs, dtype=np.float32)

    # Find similar document pairs
    pairs = []
    for i in range(len(docs)):
        for j in range(i+1, len(docs)):
            sim = float(np.dot(doc_vecs[i], doc_vecs[j]))
            if sim > 0.5:
                # Find shared entity names
                set_i = set(e.lower() for e in docs[i]["entities"])
                set_j = set(e.lower() for e in docs[j]["entities"])
                shared = list(set_i & set_j)
                pairs.append({
                    "doc_a_id":      docs[i]["analysis_id"],
                    "doc_a_preview": docs[i]["doc_preview"],
                    "doc_b_id":      docs[j]["analysis_id"],
                    "doc_b_preview": docs[j]["doc_preview"],
                    "similarity":    round(sim, 4),
                    "shared_entities": shared[:5]
                })

    pairs.sort(key=lambda x: x["similarity"], reverse=True)
    return pairs[:10]
