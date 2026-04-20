# Demo 2 — Legal Document Intelligence Engine

Analyzes legal text and returns clause classification, risk assessment,
obligation extraction, and a plain language summary. Mirrors real-world
NLP workflows used in legal AI and contract review tools.

## Model Performance

Fine-tuned `distilbert-base-uncased` on a labeled legal clause dataset.

| Metric | Score |
|--------|-------|
| Accuracy | 87.50% |
| F1 Score (weighted) | 0.8333 |
| Precision | 0.8125 |
| Recall | 0.8750 |
| Model | DistilBERT fine-tuned |
| Training samples | 32 |
| Test samples | 8 |
| Classes | 8 |

### Per-class breakdown

| Clause type | Precision | Recall | F1 |
|-------------|-----------|--------|----|
| arbitration | 1.0000 | 1.0000 | 1.0000 |
| confidentiality | 1.0000 | 1.0000 | 1.0000 |
| indemnification | 0.0000 | 0.0000 | 0.0000 |
| ip | 1.0000 | 1.0000 | 1.0000 |
| jurisdiction | 1.0000 | 1.0000 | 1.0000 |
| liability | 0.5000 | 1.0000 | 0.6667 |
| payment | 1.0000 | 1.0000 | 1.0000 |
| termination | 1.0000 | 1.0000 | 1.0000 |

> Note: indemnification score reflects a single misclassified test sample
> (confused with liability — semantically related classes). Would improve
> significantly with a larger labeled dataset.

## What it does

| Feature | Description |
|---------|-------------|
| Risk scoring | 0–100 risk score with severity level |
| Risk flags | Specific issues flagged with plain English explanations |
| Clause classification | Identifies indemnification, termination, payment, NDA, etc. |
| Obligation extraction | Who must do what, in plain English |
| Entity extraction | Parties, dates, dollar amounts, jurisdictions |
| Plain summary | 2–3 sentence non-legal summary |
| Completeness score | How complete the document appears |
| Favor analysis | Which party the document structurally favors |

## Real-world relevance

This demo directly maps to the job requirement:
> "Work with our lawyers to review initial results and improve model accuracy."

The output is designed to be readable by a non-technical lawyer —
plain English explanations alongside structured data. The per-class F1
scores give lawyers a concrete way to validate model accuracy per clause type.

## API


POST http://localhost:8001/analyze
Content-Type: application/json
{ "text": "Paste legal document text here..." }


## Running locally

```bash
uvicorn backend.demo2.main:app --reload --port 8001
```

## Training pipeline

See `notebooks/cuad_clause_classifier.ipynb` (Google Colab) for the full
fine-tuning pipeline:
- Custom labeled dataset — 40 samples, 8 clause types
- DistilBERT tokenization with max_length=128
- AdamW optimizer, lr=2e-5, 10 epochs
- Tesla T4 GPU on Google Colab

## Next steps for production

- Expand training data to 500+ samples per class using CUAD dataset
- Add confidence scores per clause prediction
- Build lawyer feedback loop to flag incorrect classifications
- Evaluate on held-out contract corpus with macro F1 target of 0.90+

