\# Demo 1 — NLP Text Analyzer



Analyzes any text and returns sentiment, named entities, key phrases, tone,

and a plain language summary. Built to demonstrate core NLP pipeline skills.



\## What it does



| Feature | Description | NLP concept |

|---------|-------------|-------------|

| Sentiment | Positive / negative / neutral / mixed + confidence score | Text classification |

| Named entities | People, orgs, locations, dates, money | NER |

| Key phrases | Important terms ranked by relevance | Keyword extraction |

| Tone | Analytical, confident, tentative, etc. | Multi-label classification |

| Summary | 2-sentence plain English summary | Abstractive summarization |

| Statistics | Word count, sentence count, readability score | Linguistic features |



\## API





POST http://localhost:8000/analyze

Content-Type: application/json

{ "text": "Your text here..." }



\## Running locally



```bash

uvicorn backend.demo1.main:app --reload --port 8000

```



\## Sample output



Input: Apple Inc. reported record quarterly revenue of $123.9 billion...



```json

{

&#x20; "sentiment": {

&#x20;   "label": "positive",

&#x20;   "score": 0.78,

&#x20;   "explanation": "Strong revenue figures and praised performance drive positive tone"

&#x20; },

&#x20; "entities": \[

&#x20;   { "text": "Apple Inc.", "type": "ORG" },

&#x20;   { "text": "Tim Cook", "type": "PERSON" },

&#x20;   { "text": "$123.9 billion", "type": "MONEY" },

&#x20;   { "text": "China", "type": "GPE" }

&#x20; ],

&#x20; "keywords": \[

&#x20;   { "word": "revenue", "importance": "high" },

&#x20;   { "word": "supply chain", "importance": "high" },

&#x20;   { "word": "iPhone 15", "importance": "medium" }

&#x20; ],

&#x20; "tone": \["analytical", "cautious"],

&#x20; "summary": "Apple reported record Q1 revenue driven by strong iPhone sales in Asia.

&#x20;             Supply chain risks in Taiwan may affect future output."

}

```









