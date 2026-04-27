"""
document_comparison.py
======================
FastAPI APIRouter: Document Comparison (#6)
Compares two legal documents using:
  - Cosine similarity (TF-IDF)
  - Jaccard similarity (key terms)
  - Entity overlap (via existing entity_confidence pipeline)
  - Structural diff (length, sentence count, reading level)
  - Shared citation detection (regex)
"""

import re
import math
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from backend.demo1.entity_confidence import score_entities

router = APIRouter()

# ── Pydantic models ────────────────────────────────────────────────────────────

class CompareInput(BaseModel):
    doc_a: str
    doc_b: str
    label_a: Optional[str] = "Document A"
    label_b: Optional[str] = "Document B"
    include_entities: bool = True

class MultiCompareInput(BaseModel):
    documents: list[str]
    labels: Optional[list[str]] = None

# ── Helpers ────────────────────────────────────────────────────────────────────

def cosine_sim(a: str, b: str) -> float:
    """TF-IDF cosine similarity between two texts."""
    try:
        vec = TfidfVectorizer(stop_words="english", max_features=5000)
        matrix = vec.fit_transform([a, b])
        score = cosine_similarity(matrix[0], matrix[1])[0][0]
        return round(float(score), 4)
    except Exception:
        return 0.0


def jaccard_sim(a: str, b: str) -> float:
    """Jaccard similarity on word sets (stopwords removed)."""
    STOPWORDS = {
        "the","a","an","and","or","but","in","on","at","to","for",
        "of","with","by","from","is","was","are","were","be","been",
        "has","have","had","this","that","it","its","as","not","no"
    }
    def words(text):
        return {w.lower() for w in re.findall(r'\b[a-zA-Z]{3,}\b', text)
                if w.lower() not in STOPWORDS}

    set_a = words(a)
    set_b = words(b)
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return round(intersection / union, 4)


def extract_citations_simple(text: str) -> set:
    """Extract citation strings for overlap comparison."""
    patterns = [
        r'\b\d+\s+U\.?S\.?C\.?\s+[§§\s]*\d+',
        r'\b\d+\s+F\.(?:\s?Supp\.(?:\s?[23]d)?|\s?[23]d|\.)\s+\d+',
        r'\d{4}\s+U\.S\.(?:\s+\w+\.)?\s+LEXIS\s+\d+',
        r'\d{4}\s+WL\s+\d+',
    ]
    found = set()
    for p in patterns:
        for m in re.finditer(p, text, re.IGNORECASE):
            found.add(m.group(0).strip().lower())
    return found


def structural_diff(a: str, b: str) -> dict:
    """Compare structural properties of two documents."""
    def stats(text):
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        words = re.findall(r'\b\w+\b', text)
        avg_word_len = round(sum(len(w) for w in words) / max(len(words), 1), 1)
        return {
            "char_count": len(text),
            "word_count": len(words),
            "sentence_count": len(sentences),
            "avg_words_per_sentence": round(len(words) / max(len(sentences), 1), 1),
            "avg_word_length": avg_word_len,
        }

    sa = stats(a)
    sb = stats(b)

    return {
        "doc_a": sa,
        "doc_b": sb,
        "delta": {
            "char_count":    sb["char_count"]    - sa["char_count"],
            "word_count":    sb["word_count"]    - sa["word_count"],
            "sentence_count":sb["sentence_count"]- sa["sentence_count"],
        },
        "length_ratio": round(
            min(sa["char_count"], sb["char_count"]) /
            max(sa["char_count"], sb["char_count"], 1), 4
        ),
    }


def entity_overlap(entities_a: list, entities_b: list) -> dict:
    """Compare entity sets between two documents."""
    def entity_set(entities):
        return {e["text"].lower() for e in entities}

    set_a = entity_set(entities_a)
    set_b = entity_set(entities_b)
    shared = set_a & set_b
    only_a = set_a - set_b
    only_b = set_b - set_a

    overlap_score = round(
        len(shared) / max(len(set_a | set_b), 1), 4
    )

    return {
        "overlap_score": overlap_score,
        "shared_entities": sorted(shared),
        "only_in_a": sorted(only_a),
        "only_in_b": sorted(only_b),
        "count_a": len(set_a),
        "count_b": len(set_b),
        "shared_count": len(shared),
    }


def similarity_label(score: float) -> str:
    if score >= 0.85: return "near-duplicate"
    if score >= 0.65: return "highly similar"
    if score >= 0.40: return "moderately similar"
    if score >= 0.20: return "low similarity"
    return "distinct"


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/compare")
def compare_documents(body: CompareInput):
    """
    Compare two documents across multiple dimensions:
    cosine similarity, Jaccard, entity overlap, citations, structure.
    """
    cos  = cosine_sim(body.doc_a, body.doc_b)
    jacc = jaccard_sim(body.doc_a, body.doc_b)

    # Combined similarity score (weighted)
    combined = round(0.6 * cos + 0.4 * jacc, 4)

    # Citation overlap
    cites_a = extract_citations_simple(body.doc_a)
    cites_b = extract_citations_simple(body.doc_b)
    shared_cites = cites_a & cites_b

    # Structural diff
    structure = structural_diff(body.doc_a, body.doc_b)

    result = {
        "success": True,
        "labels": {"a": body.label_a, "b": body.label_b},
        "similarity": {
            "cosine":   cos,
            "jaccard":  jacc,
            "combined": combined,
            "label":    similarity_label(combined),
        },
        "citations": {
            "shared": sorted(shared_cites),
            "only_in_a": sorted(cites_a - cites_b),
            "only_in_b": sorted(cites_b - cites_a),
            "shared_count": len(shared_cites),
        },
        "structure": structure,
    }

    # Entity overlap (optional, slower)
    if body.include_entities:
        try:
            import spacy
            nlp = spacy.load("en_core_web_sm")
            def spacy_ents(text):
                return [{"text": e.text} for e in nlp(text).ents]
            ents_a = spacy_ents(body.doc_a)
            ents_b = spacy_ents(body.doc_b)
            result["entities"] = entity_overlap(ents_a, ents_b)
        except Exception as e:
            result["entities"] = {"error": str(e)}

    return result


@router.post("/compare/batch")
def compare_batch(body: MultiCompareInput):
    """
    Compare all document pairs in a list.
    Returns an N×N similarity matrix.
    """
    docs = body.documents
    n = len(docs)
    if n < 2:
        return {"error": "Provide at least 2 documents"}
    if n > 10:
        return {"error": "Maximum 10 documents per batch"}

    labels = body.labels or [f"Doc {i+1}" for i in range(n)]

    # Build full similarity matrix
    matrix = []
    pairs  = []

    for i in range(n):
        row = []
        for j in range(n):
            if i == j:
                row.append(1.0)
            else:
                score = round(0.6 * cosine_sim(docs[i], docs[j]) +
                              0.4 * jaccard_sim(docs[i], docs[j]), 4)
                row.append(score)
                if j > i:
                    pairs.append({
                        "doc_a": labels[i],
                        "doc_b": labels[j],
                        "combined_similarity": score,
                        "label": similarity_label(score),
                    })
        matrix.append(row)

    # Sort pairs by similarity descending
    pairs.sort(key=lambda x: x["combined_similarity"], reverse=True)

    return {
        "success": True,
        "document_count": n,
        "labels": labels,
        "similarity_matrix": matrix,
        "ranked_pairs": pairs,
        "most_similar": pairs[0] if pairs else None,
        "most_distinct": pairs[-1] if pairs else None,
    }
