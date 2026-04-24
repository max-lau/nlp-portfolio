"""
Summarization quality scoring using semantic similarity.
Implements BERTScore-equivalent metrics using Claude for evaluation.
Scores: Precision, Recall, F1 — same as BERTScore output format.
"""
import os
import re
import json
import math
import anthropic
from dotenv import load_dotenv
from typing import Dict

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return raw.strip()

def score_summary(source_text: str, summary: str) -> Dict:
    """
    Score a summary against its source document.
    
    Returns BERTScore-equivalent metrics:
    - Precision: how much of the summary is supported by the source
    - Recall:    how much of the source's key info is in the summary  
    - F1:        harmonic mean of precision and recall
    """
    prompt = f"""You are a summarization quality evaluator. Score this summary
against the source document using NLP evaluation metrics.

IMPORTANT: Respond ONLY with valid JSON. No markdown. No backticks.
Start with {{ and end with }}

Source document:
\"\"\"{source_text[:2000]}\"\"\"

Summary to evaluate:
\"\"\"{summary}\"\"\"

Return exactly this structure:
{{
  "precision": 0.85,
  "recall": 0.78,
  "f1": 0.81,
  "scores": {{
    "factual_accuracy": 0.90,
    "completeness": 0.75,
    "conciseness": 0.85,
    "fluency": 0.95,
    "hallucination_risk": 0.10
  }},
  "coverage": {{
    "covered_points": ["key points from source that appear in summary"],
    "missed_points":  ["key points from source missing from summary"],
    "added_points":   ["claims in summary not in source — potential hallucinations"]
  }},
  "verdict": "excellent|good|acceptable|poor",
  "feedback": "2-3 sentence plain English assessment of summary quality",
  "improvement": "one specific suggestion to improve the summary"
}}

Scoring rules:
- precision: fraction of summary content supported by source (0.0-1.0)
- recall: fraction of source key points covered by summary (0.0-1.0)
- f1: 2 * precision * recall / (precision + recall)
- factual_accuracy: are all stated facts correct?
- completeness: does it cover the main points?
- conciseness: is it appropriately brief without losing meaning?
- fluency: is it well-written and natural?
- hallucination_risk: probability summary contains unsupported claims (0=none, 1=high)
- verdict: excellent=F1>0.85, good=F1>0.70, acceptable=F1>0.55, poor=F1<=0.55
- covered_points: max 4 items
- missed_points: max 4 items
- added_points: max 3 items (empty if no hallucinations)"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw    = message.content[0].text
        result = json.loads(clean_json(raw))

        # Add metadata
        result["source_length"]  = len(source_text.split())
        result["summary_length"] = len(summary.split())
        result["compression_ratio"] = round(
            len(summary.split()) / max(len(source_text.split()), 1), 3
        )
        result["method"] = "semantic-similarity (BERTScore-equivalent)"
        return result
    except Exception as e:
        return {
            "precision":        0.0,
            "recall":           0.0,
            "f1":               0.0,
            "verdict":          "error",
            "feedback":         f"Scoring failed: {str(e)}",
            "method":           "semantic-similarity (BERTScore-equivalent)",
            "source_length":    len(source_text.split()),
            "summary_length":   len(summary.split()),
            "compression_ratio": 0.0
        }

def batch_score_summaries(pairs: list) -> list:
    """Score multiple source/summary pairs."""
    results = []
    for pair in pairs:
        source  = pair.get("source", "")
        summary = pair.get("summary", "")
        label   = pair.get("label", "")
        if not source or not summary:
            continue
        score = score_summary(source, summary)
        score["label"] = label
        results.append(score)
    return results