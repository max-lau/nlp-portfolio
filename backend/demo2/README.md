# Demo 2 — Legal Document Intelligence Engine

Analyzes legal text and returns clause classification, risk assessment,
obligation extraction, and a plain language summary. Mirrors real-world
NLP workflows used in legal AI and contract review tools.

## Model Performance

Fine-tuned `distilbert-base-uncased` on a labeled legal clause dataset.

### Version 2 — 200 samples (current)

| Metric | Score |
|--------|-------|
| Accuracy | 100.00% |
| F1 Score (weighted) | 1.0000 |
| Precision | 1.0000 |
| Recall | 1.0000 |
| Model | DistilBERT fine-tuned |
| Training samples | 160 |
| Test samples | 40 |
| Classes | 8 |

### Per-class breakdown (v2)

| Clause type | Precision | Recall | F1 | Support |
|-------------|-----------|--------|----|---------|
| arbitration | 1.0000 | 1.0000 | 1.0000 | 5 |
| confidentiality | 1.0000 | 1.0000 | 1.0000 | 5 |
| indemnification | 1.0000 | 1.0000 | 1.0000 | 5 |
| ip | 1.0000 | 1.0000 | 1.0000 | 5 |
| jurisdiction | 1.0000 | 1.0000 | 1.0000 | 5 |
| liability | 1.0000 | 1.0000 | 1.0000 | 5 |
| payment | 1.0000 | 1.0000 | 1.0000 | 5 |
| termination | 1.0000 | 1.0000 | 1.0000 | 5 |

### Version 1 — 40 samples (baseline)

| Metric | Score |
|--------|-------|
| Accuracy | 87.50% |
| F1 Score (weighted) | 0.8333 |
| Precision | 0.8125 |
| Recall | 0.8750 |

> Showing both versions demonstrates understanding of how dataset size
> affects model performance — a key data science skill.

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

See `notebooks/cuad_clause_classifier.ipynb` (Google Colab) for the
full fine-tuning pipeline:

- Custom labeled dataset — 200 samples, 8 clause types, 25 per class
- DistilBERT tokenization with max_length=128
- AdamW optimizer, lr=2e-5, weight_decay=0.01
- 15 epochs, batch size 16
- Tesla T4 GPU on Google Colab free tier
- 80/20 train/test split, stratified by class

## Version history

| Version | Samples | Accuracy | F1 |
|---------|---------|----------|----|
| v1 | 40 | 87.50% | 0.8333 |
| v2 | 200 | 100.00% | 1.0000 |

## Next steps for production

- Expand to 500+ samples per class using SEC EDGAR contract corpus
- Add confidence scores per clause prediction
- Build lawyer feedback loop to flag incorrect classifications
- Evaluate on held-out real-world contracts from SEC EDGAR
- Add macro F1 tracking across model versions

