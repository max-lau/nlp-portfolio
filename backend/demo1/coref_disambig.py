"""
Named Entity Disambiguation + Coreference Resolution
Uses spaCy for extraction + Claude for reasoning.
Works on Python 3.14 without C compiler dependencies.
"""
import json
import re
import os
import spacy
import anthropic
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Load the large model for better NER
try:
    nlp = spacy.load("en_core_web_lg")
except Exception:
    nlp = spacy.load("en_core_web_sm")

def clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return raw.strip()

def extract_entities_spacy(text: str) -> list:
    """Extract entities with spaCy for grounding."""
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
    """
    Resolve ambiguous entity mentions to their canonical real-world form.
    e.g. 'Apple' -> 'Apple Inc. (technology company)'
         'Jordan' -> 'Michael Jordan (basketball player)' based on context
    """
    entities = extract_entities_spacy(text)

    prompt = f"""You are a named entity disambiguation expert.
Given this text and its extracted entities, resolve each ambiguous entity
to its most likely real-world canonical form based on context.

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
      "category": "e.g. Technology Company, Basketball Player, City",
      "confidence": 0.95,
      "aliases": ["other ways this entity is referred to in the text"],
      "context_clues": ["words/phrases that helped identify this entity"],
      "ambiguous": false,
      "alternative_interpretations": []
    }}
  ],
  "entity_graph": [
    {{
      "entity_a": "canonical form of first entity",
      "entity_b": "canonical form of second entity",
      "relationship": "plain English relationship between them"
    }}
  ],
  "summary": "one sentence about the key entities in this text"
}}

Rules:
- Only include entities that are worth disambiguating (skip trivial ones)
- ambiguous: true if multiple interpretations exist
- alternative_interpretations: only if ambiguous is true, max 2
- entity_graph: relationships between the TOP entities, max 5 pairs
- confidence: 0.0-1.0
- max 10 disambiguated entities"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw    = message.content[0].text
        result = json.loads(clean_json(raw))
        result["raw_entities"] = entities
        return result
    except Exception as e:
        return {
            "disambiguated": [],
            "entity_graph":  [],
            "raw_entities":  entities,
            "summary":       f"Disambiguation failed: {str(e)}"
        }

def resolve_coreferences(text: str) -> dict:
    """
    Find all pronoun and nominal references and link them
    to the entity they refer to.
    e.g. 'He' -> 'Alexander Vance'
         'the company' -> 'Citywide Venture Partners'
         'it' -> '$750,000'
    """
    # First extract entities with spaCy for grounding
    entities = extract_entities_spacy(text)

    prompt = f"""You are a coreference resolution expert.
Find ALL pronouns and noun phrases in this text that refer to
a previously mentioned entity, and link each one to its antecedent.

IMPORTANT: Respond ONLY with valid JSON. No markdown. No backticks.
Start with {{ and end with }}

Text: \"\"\"{text[:3000]}\"\"\"

Return exactly this structure:
{{
  "chains": [
    {{
      "entity": "canonical name of the entity",
      "entity_type": "PERSON|ORG|MONEY|DATE|OTHER",
      "mentions": [
        {{
          "text": "exact text of the mention",
          "type": "proper_noun|pronoun|definite_np|indefinite_np",
          "is_first_mention": true,
          "position": "approximate location e.g. sentence 1"
        }}
      ]
    }}
  ],
  "resolved_text": "the original text with pronouns replaced by their referents in [brackets]",
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

Rules:
- Track EVERY mention of each entity including pronouns
- type: proper_noun=full name, pronoun=he/she/it/they/his/her,
        definite_np=the company/the defendant,
        indefinite_np=a firm/an executive
- resolved_text: replace pronouns with [Entity Name] inline
- max 8 chains
- ambiguous_pronouns: only genuinely ambiguous ones, max 3"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw    = message.content[0].text
        result = json.loads(clean_json(raw))
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
