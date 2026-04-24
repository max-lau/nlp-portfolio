"""
Entity confidence scoring and salience calculation.
"""
import spacy
import math
from typing import List, Dict

nlp = spacy.load("en_core_web_sm")

TYPE_CONFIDENCE = {
    "PERSON":  0.91, "ORG":     0.87, "GPE":     0.93,
    "LOC":     0.85, "DATE":    0.95, "TIME":    0.93,
    "MONEY":   0.97, "PERCENT": 0.96, "LAW":     0.78,
    "PRODUCT": 0.74, "EVENT":   0.71, "CARDINAL": 0.89,
    "ORDINAL": 0.91, "OTHER":   0.65,
}

def score_entities(text: str, entities: List[Dict]) -> List[Dict]:
    if not entities:
        return entities

    doc       = nlp(text[:5000])
    spacy_ents = {ent.text.strip().lower(): ent for ent in doc.ents}

    scored = []
    for ent in entities:
        ent_text  = ent.get("text", "")
        ent_type  = ent.get("type", "OTHER")
        ent_lower = ent_text.lower()

        base_conf   = TYPE_CONFIDENCE.get(ent_type, 0.65)
        spacy_boost = 0.05 if spacy_ents.get(ent_lower) else -0.03
        cap_boost   = 0.02 if ent_text and ent_text[0].isupper() else -0.02
        mw_boost    = 0.03 if len(ent_text.split()) > 1 else 0.0
        len_penalty = -0.10 if len(ent_text) <= 2 else 0.0

        confidence = min(0.99, max(0.30,
            base_conf + spacy_boost + cap_boost + mw_boost + len_penalty
        ))

        freq       = text.lower().count(ent_lower)
        freq_score = min(1.0, math.log(1 + freq) / math.log(10))
        first_pos  = text.lower().find(ent_lower)
        pos_score  = 1.0 - (first_pos / max(len(text), 1))
        type_weight = {
            "PERSON": 1.0, "ORG": 0.95, "GPE": 0.85,
            "MONEY": 0.90, "LAW": 0.85, "DATE": 0.70,
            "PERCENT": 0.75, "LOC": 0.80, "OTHER": 0.60
        }.get(ent_type, 0.65)

        salience = round(
            freq_score * 0.40 + pos_score * 0.35 + type_weight * 0.25, 3
        )

        scored.append({
            **ent,
            "confidence": round(confidence, 3),
            "salience":   salience,
            "frequency":  freq,
            "signals": {
                "type_baseline":   round(base_conf, 3),
                "spacy_confirmed": spacy_ents.get(ent_lower) is not None,
                "multi_word":      len(ent_text.split()) > 1,
                "capitalized":     ent_text[0].isupper() if ent_text else False
            }
        })

    scored.sort(key=lambda x: x["salience"], reverse=True)
    return scored

def get_entity_summary(scored_entities: List[Dict]) -> Dict:
    if not scored_entities:
        return {}

    confidences = [e["confidence"] for e in scored_entities]
    saliences   = [e["salience"]   for e in scored_entities]
    type_counts = {}
    for e in scored_entities:
        t = e.get("type", "OTHER")
        type_counts[t] = type_counts.get(t, 0) + 1

    high_conf   = [e for e in scored_entities if e["confidence"] >= 0.90]
    low_conf    = [e for e in scored_entities if e["confidence"] <  0.75]
    top_salient = sorted(scored_entities,
                         key=lambda x: x["salience"], reverse=True)[:3]

    return {
        "total_entities":       len(scored_entities),
        "avg_confidence":       round(sum(confidences)/len(confidences), 3),
        "avg_salience":         round(sum(saliences)/len(saliences), 3),
        "high_confidence":      len(high_conf),
        "low_confidence":       len(low_conf),
        "type_distribution":    type_counts,
        "top_salient_entities": [e["text"] for e in top_salient],
        "review_recommended":   [e["text"] for e in low_conf]
    }