"""
Named Entity Disambiguation + Coreference Resolution
Uses spaCy sm (light) + Claude for reasoning.
"""
import json
import re
import os
import spacy
import anthropic
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

nlp = spacy.load("en_core_web_sm")

def clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return raw.strip()

def extract_entities_spacy(text: str) -> list:
    doc = nlp(text[:5000])
    entities = []
    seen = set()
    for ent in doc.ents:
        key = (ent.text.strip().lower(), ent.label_)
        if key not in seen:
            seen.add(key)
            entities.append({
                "text":  ent.text.strip(),
                "type":  ent.label_,
                "start": ent.start_char,
                "end":   ent.end_char
            })
    return entities

def disambiguate_entities(text: str) -> dict:
    entities = extract_entities_spacy(text)
    prompt = f"""You are a named entity disambiguation expert.
Resolve each ambiguous entity to its canonical real-world form based on context.

IMPORTANT: Respond ONLY with valid JSON. No markdown. No backticks.
Start with {{ and end with }}

Text: \"\"\"{text[:2000]}\"\"\"
Extracted entities: {json.dumps(entities[:15])}

Return exactly this structure:
{{
  "disambiguated": [
    {{
      "mention": "exact text as it appears",
      "canonical_form": "full official name",
      "entity_type": "PERSON|ORG|GPE|LOC|MONEY|DATE|LAW|OTHER",
      "category": "e.g. Technology Company",
      "confidence": 0.95,
      "aliases": ["other ways referred to in text"],
      "context_clues": ["words that helped identify this entity"],
      "ambiguous": false,
      "alternative_interpretations": []
    }}
  ],
  "entity_graph": [
    {{
      "entity_a": "canonical form",
      "entity_b": "canonical form",
      "relationship": "plain English relationship"
    }}
  ],
  "summary": "one sentence about the key entities"
}}

Rules: max 10 entities, max 5 graph pairs, confidence 0.0-1.0."""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        result = json.loads(clean_json(message.content[0].text))
        result["raw_entities"] = entities
        return result
    except Exception as e:
        return {
            "disambiguated": [],
            "entity_graph":  [],
            "raw_entities":  entities,
            "summary":       f"Failed: {str(e)}"
        }

def resolve_coreferences(text: str) -> dict:
    entities = extract_entities_spacy(text)
    prompt = f"""You are a coreference resolution expert.
Find ALL pronouns and noun phrases that refer to a previously mentioned entity.

IMPORTANT: Respond ONLY with valid JSON. No markdown. No backticks.
Start with {{ and end with }}

Text: \"\"\"{text[:3000]}\"\"\"

Return exactly this structure:
{{
  "chains": [
    {{
      "entity": "canonical name",
      "entity_type": "PERSON|ORG|MONEY|DATE|OTHER",
      "mentions": [
        {{
          "text": "exact mention text",
          "type": "proper_noun|pronoun|definite_np|indefinite_np",
          "is_first_mention": true,
          "position": "sentence 1"
        }}
      ]
    }}
  ],
  "resolved_text": "original text with pronouns replaced by [Entity Name]",
  "ambiguous_pronouns": [
    {{
      "pronoun": "it",
      "possible_referents": ["entity A", "entity B"],
      "most_likely": "entity A",
      "reason": "why"
    }}
  ],
  "statistics": {{
    "total_mentions": 0,
    "chains_found": 0,
    "pronouns_resolved": 0,
    "ambiguous_count": 0
  }}
}}

Rules: max 8 chains, max 3 ambiguous pronouns."""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        result = json.loads(clean_json(message.content[0].text))
        result["raw_entities"] = entities
        return result
    except Exception as e:
        return {
            "chains":             [],
            "resolved_text":      text,
            "ambiguous_pronouns": [],
            "statistics":         {},
            "raw_entities":       entities,
            "error":              str(e)
        }