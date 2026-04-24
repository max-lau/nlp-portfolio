"""
Multi-language NLP support.
Spanish + French: spaCy models
Chinese + others: Claude direct processing
"""
import os
import re
import json
import spacy
import anthropic
from dotenv import load_dotenv
from typing import Dict

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Lazy-load language models
_MODELS = {}

def get_model(lang: str):
    global _MODELS
    if lang not in _MODELS:
        model_map = {
            "es": "es_core_news_sm",
            "fr": "fr_core_news_sm",
        }
        if lang in model_map:
            try:
                _MODELS[lang] = spacy.load(model_map[lang])
            except Exception:
                _MODELS[lang] = None
        else:
            _MODELS[lang] = None
    return _MODELS[lang]

def clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return raw.strip()

SUPPORTED_LANGUAGES = {
    "en": {"name": "English",    "flag": "🇺🇸", "model": "spacy+claude"},
    "zh": {"name": "Chinese",    "flag": "🇨🇳", "model": "claude"},
    "es": {"name": "Spanish",    "flag": "🇪🇸", "model": "spacy+claude"},
    "fr": {"name": "French",     "flag": "🇫🇷", "model": "spacy+claude"},
    "de": {"name": "German",     "flag": "🇩🇪", "model": "claude"},
    "ja": {"name": "Japanese",   "flag": "🇯🇵", "model": "claude"},
    "ar": {"name": "Arabic",     "flag": "🇸🇦", "model": "claude"},
    "pt": {"name": "Portuguese", "flag": "🇧🇷", "model": "claude"},
}

def detect_language(text: str) -> dict:
    """Detect language using Claude."""
    prompt = f"""Detect the language of this text. Respond ONLY with JSON.
Start with {{ and end with }}

Text: \"\"\"{text[:500]}\"\"\"

Return:
{{
  "language_code": "en|zh|es|fr|de|ja|ar|pt|other",
  "language_name": "English",
  "confidence": 0.99,
  "script": "latin|chinese|arabic|cyrillic|other",
  "is_mixed": false
}}"""

    try:
        msg    = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        return json.loads(clean_json(msg.content[0].text))
    except Exception:
        return {
            "language_code": "en",
            "language_name": "English",
            "confidence":    0.5,
            "script":        "latin",
            "is_mixed":      False
        }

def extract_entities_spacy_multilingual(text: str, lang: str) -> list:
    """Extract entities using spaCy for supported languages."""
    model = get_model(lang)
    if not model:
        return []
    doc      = model(text[:5000])
    entities = []
    seen     = set()
    for ent in doc.ents:
        key = ent.text.strip().lower()
        if key not in seen:
            seen.add(key)
            entities.append({
                "text": ent.text.strip(),
                "type": ent.label_
            })
    return entities

def analyze_multilingual(text: str, lang_code: str = "auto") -> Dict:
    """
    Full NLP analysis in any supported language.
    Returns same structure as English analyze endpoint.
    """
    # Auto-detect language if not specified
    if lang_code == "auto":
        lang_info = detect_language(text)
        lang_code = lang_info.get("language_code", "en")
    else:
        lang_info = SUPPORTED_LANGUAGES.get(lang_code, {
            "name": lang_code, "flag": "🌐", "model": "claude"
        })
        lang_info["language_code"] = lang_code

    lang_name = SUPPORTED_LANGUAGES.get(lang_code, {}).get("name", lang_code)

    # Get spaCy entities for supported languages
    spacy_entities = []
    if lang_code in ["es", "fr"]:
        spacy_entities = extract_entities_spacy_multilingual(text, lang_code)

    prompt = f"""Analyze this {lang_name} text for NLP tasks.

IMPORTANT: Respond ONLY with valid JSON. No markdown. No backticks.
Start with {{ and end with }}

Text: \"\"\"{text[:2000]}\"\"\"

Return exactly this structure:
{{
  "sentiment": {{
    "label": "positive|negative|neutral|mixed",
    "score": 0.85,
    "explanation": "one sentence in English"
  }},
  "entities": [
    {{"text": "entity", "type": "PERSON|ORG|GPE|LOC|DATE|MONEY|OTHER"}}
  ],
  "keywords": [
    {{"word": "keyword", "importance": "high|medium|low"}}
  ],
  "tone": ["analytical"],
  "summary": "2-sentence summary in English",
  "translation": "English translation of the full text (max 100 words)",
  "key_phrases_native": ["important phrases kept in original language"]
}}

Rules:
- summary and explanation MUST be in English
- translation: concise English translation
- key_phrases_native: important terms in the ORIGINAL language
- max 8 entities, max 10 keywords, max 3 tone items
- Merge with these spaCy entities if helpful: {json.dumps(spacy_entities[:8])}"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}]
        )
        raw    = message.content[0].text
        result = json.loads(clean_json(raw))

        # Add language metadata
        result["language"] = {
            "code":      lang_code,
            "name":      lang_name,
            "flag":      SUPPORTED_LANGUAGES.get(lang_code, {}).get("flag", "🌐"),
            "model":     SUPPORTED_LANGUAGES.get(lang_code, {}).get("model", "claude"),
            "confidence": lang_info.get("confidence", 1.0),
            "script":    lang_info.get("script", "latin")
        }
        result["word_count"] = len(text.split())
        return result

    except Exception as e:
        return {
            "error":    str(e),
            "language": {"code": lang_code, "name": lang_name}
        }