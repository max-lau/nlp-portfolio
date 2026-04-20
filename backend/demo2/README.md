\# Demo 2 — Legal Document Intelligence Engine



Analyzes legal text and returns clause classification, risk assessment,

obligation extraction, and a plain language summary. Mirrors real-world

NLP workflows used in legal AI and contract review tools.



\## What it does



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



\## Real-world relevance



This demo directly maps to the job requirement:

> "Work with our lawyers to review initial results and improve model accuracy."



The output is designed to be readable by a non-technical lawyer —

plain English explanations alongside the structured data.



\## API



POST http://localhost:8001/analyze

Content-Type: application/json

{ "text": "Paste legal document text here..." }



\## Running locally



```bash

uvicorn backend.demo2.main:app --reload --port 8001

```



\## Supported clause types



`indemnification` `termination` `payment` `confidentiality`

`jurisdiction` `arbitration` `liability` `ip` `other`



\## Next steps for production



\- Fine-tune a BERT model on the CUAD legal dataset for clause classification

\- Add batch processing endpoint for full contracts (not just excerpts)

\- Add confidence scores per clause

\- Build evaluation pipeline with F1 scores per clause type

\- Add lawyer feedback loop to flag incorrect classifications





