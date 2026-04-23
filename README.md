\# NLP Portfolio — Text \& Legal Intelligence Demos



Two production-style NLP demos built with FastAPI, Python, and Claude AI.

Designed to demonstrate real-world NLP data science skills for a data scientist role

focused on NLP model development, legal AI, and data pipeline architecture.



\## Demos

| Demo | Description | Port |
|------|-------------|------|
| [Demo 1 — NLP Text Analyzer](./frontend/demo1/index.html) | Sentiment analysis, named entity recognition, keyword extraction | 8000 |
| [Demo 1 — Timeline Extractor](./frontend/demo1/timeline.html) | Chronological event extraction from legal and business documents | 8000 |
| [Demo 2 — Legal Intelligence Engine](./frontend/demo2/index.html) | Clause classification, risk scoring, obligation extraction | 8001 |

## API Endpoints

### Demo 1 (port 8000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/analyze` | Sentiment, entities, keywords — auto-saved to SQLite |
| POST | `/timeline` | Extract chronological events from any document |
| GET | `/history` | Query past analyses with filters |
| GET | `/stats` | Aggregate statistics across all stored analyses |



\## Tech Stack



\- \*\*Backend:\*\* Python 3.14, FastAPI, Uvicorn

\- \*\*NLP:\*\* Anthropic Claude API (claude-haiku-4-5), spaCy (notebook)

\- \*\*Frontend:\*\* Vanilla HTML/CSS/JavaScript

\- \*\*Key libraries:\*\* anthropic, pydantic, python-dotenv



\## Project Structure



nlp-portfolio/

├── backend/

│   ├── demo1/

│   │   ├── main.py          # FastAPI app — sentiment, NER, keywords

│   │   └── init.py

│   └── demo2/

│       ├── main.py          # FastAPI app — clause classification, risk scoring

│       └── init.py

├── frontend/

│   ├── demo1/

│   │   └── index.html       # NLP Text Analyzer UI

│   └── demo2/

│       └── index.html       # Legal Intelligence Engine UI

├── notebooks/

│   └── nlp\_concepts\_walkthrough.ipynb

├── .env.example             # API key template

├── .gitignore

├── requirements.txt

└── README.md



\## Quick Start



\### 1. Clone the repo



```bash

git clone https://github.com/YOUR\_USERNAME/nlp-portfolio.git

cd nlp-portfolio

```



\### 2. Create virtual environment



```bash

python -m venv .venv



\# Windows

.venv\\Scripts\\activate



\# Mac/Linux

source .venv/bin/activate

```



\### 3. Install dependencies



```bash

pip install -r requirements.txt

```



\### 4. Set up your API key



```bash

cp .env.example .env

\# Edit .env and add your Anthropic API key

\# Get one at: https://console.anthropic.com

```



\### 5. Run Demo 1 — NLP Text Analyzer



```bash

uvicorn backend.demo1.main:app --reload --port 8000

```



Open `frontend/demo1/index.html` in your browser.



\### 6. Run Demo 2 — Legal Intelligence Engine



```bash

uvicorn backend.demo2.main:app --reload --port 8001

```



Open `frontend/demo2/index.html` in your browser.



\## API Endpoints



\### Demo 1 (port 8000)



| Method | Endpoint | Description |

|--------|----------|-------------|

| GET | `/health` | Health check |

| POST | `/analyze` | Analyze text for sentiment, entities, keywords |



\*\*Request body:\*\*

```json

{ "text": "Your text here..." }

```



\*\*Response:\*\*

```json

{

&#x20; "sentiment": { "label": "positive", "score": 0.85, "explanation": "..." },

&#x20; "entities": \[{ "text": "Apple", "type": "ORG" }],

&#x20; "keywords": \[{ "word": "revenue", "importance": "high" }],

&#x20; "tone": \["analytical", "confident"],

&#x20; "summary": "Plain English summary..."

}

```



\### Demo 2 (port 8001)



| Method | Endpoint | Description |

|--------|----------|-------------|

| GET | `/health` | Health check |

| POST | `/analyze` | Analyze legal document |



\*\*Response includes:\*\* risk score, risk flags, clause classification,

extracted entities, obligations, plain language summary.



\## NLP Concepts Covered



\- \*\*Sentiment Analysis\*\* — classifying emotional tone of text

\- \*\*Named Entity Recognition (NER)\*\* — extracting people, orgs, locations, dates

\- \*\*Keyword Extraction\*\* — identifying important terms by TF-IDF weight

\- \*\*Text Classification\*\* — categorizing legal clauses by type

\- \*\*Information Extraction\*\* — pulling structured data from unstructured text

\- \*\*Risk Scoring\*\* — combining signals into an interpretable score



\## Notebook



See `notebooks/nlp\_concepts\_walkthrough.ipynb` for a step-by-step walkthrough

of the NLP pipeline using spaCy and Hugging Face Transformers — showing how each

component works under the hood.



\## Author



Maxwell L. — \[GitHub](https://github.com/max-lau)

