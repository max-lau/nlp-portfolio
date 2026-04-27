"""
fine_tune.py
============
FastAPI APIRouter: Fine-tune Domain-Specific Model (#14)
Fine-tunes DistilBERT on legal sentiment classification:
  - PROSECUTION_FAVORABLE : language favoring the government
  - DEFENSE_FAVORABLE     : language favoring the defendant
  - NEUTRAL               : procedural/neutral language

Training data: curated legal sentences (generated in-module)
Model saved to: models/legal_classifier/
Endpoints:
  POST /model/train        - start fine-tuning (background task)
  GET  /model/status       - check training status
  POST /model/predict      - classify legal text
  GET  /model/info         - model metadata
  GET  /model/examples     - show example predictions
"""

import os
import json
import sqlite3
import threading
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Optional

router  = APIRouter()
DB_PATH = "backend/demo1/analyses.db"
MODEL_DIR = "models/legal_classifier"

# ── Training state (in-memory) ─────────────────────────────────────────────────
training_state = {
    "status":    "idle",   # idle | training | complete | error
    "progress":  0,
    "message":   "No training run yet",
    "started_at": None,
    "completed_at": None,
    "metrics":   {},
    "error":     None,
}

# ── Legal training dataset ─────────────────────────────────────────────────────

TRAINING_DATA = [
    # PROSECUTION_FAVORABLE
    ("A grand jury indicted the defendant on three counts of wire fraud.", "PROSECUTION_FAVORABLE"),
    ("The government presented overwhelming evidence of the defendant's guilt.", "PROSECUTION_FAVORABLE"),
    ("The jury convicted the defendant on all counts.", "PROSECUTION_FAVORABLE"),
    ("The court found the defendant guilty of conspiracy to commit mail fraud.", "PROSECUTION_FAVORABLE"),
    ("The United States Attorney sought maximum penalties under federal law.", "PROSECUTION_FAVORABLE"),
    ("Evidence showed the defendant knowingly defrauded investors of millions.", "PROSECUTION_FAVORABLE"),
    ("The defendant was sentenced to five years in federal prison.", "PROSECUTION_FAVORABLE"),
    ("The court ordered forfeiture of all proceeds derived from the scheme.", "PROSECUTION_FAVORABLE"),
    ("Wiretap evidence conclusively established the defendant's participation.", "PROSECUTION_FAVORABLE"),
    ("The defendant's co-conspirators testified against him at trial.", "PROSECUTION_FAVORABLE"),
    ("The FBI investigation revealed a pattern of systematic deception.", "PROSECUTION_FAVORABLE"),
    ("The defendant pled guilty to one count of securities fraud.", "PROSECUTION_FAVORABLE"),
    ("Restitution of $2.3 million was ordered to be paid to victims.", "PROSECUTION_FAVORABLE"),
    ("The defendant violated his supervised release conditions.", "PROSECUTION_FAVORABLE"),
    ("The court upheld the conviction on appeal.", "PROSECUTION_FAVORABLE"),
    ("The defendant's fingerprints were found at the scene.", "PROSECUTION_FAVORABLE"),
    ("Multiple witnesses identified the defendant as the perpetrator.", "PROSECUTION_FAVORABLE"),
    ("The defendant's bank records showed transfers consistent with money laundering.", "PROSECUTION_FAVORABLE"),
    ("The court denied the defendant's motion to suppress evidence.", "PROSECUTION_FAVORABLE"),
    ("The defendant was remanded to custody pending sentencing.", "PROSECUTION_FAVORABLE"),

    # DEFENSE_FAVORABLE
    ("The defendant was acquitted of all charges by the jury.", "DEFENSE_FAVORABLE"),
    ("The court granted the defendant's motion to dismiss for lack of evidence.", "DEFENSE_FAVORABLE"),
    ("The defendant maintains his innocence and intends to appeal.", "DEFENSE_FAVORABLE"),
    ("The evidence was insufficient to support a conviction beyond reasonable doubt.", "DEFENSE_FAVORABLE"),
    ("The court suppressed the evidence obtained through an illegal search.", "DEFENSE_FAVORABLE"),
    ("The defendant's alibi was corroborated by multiple witnesses.", "DEFENSE_FAVORABLE"),
    ("The conviction was reversed on appeal due to prosecutorial misconduct.", "DEFENSE_FAVORABLE"),
    ("The court found ineffective assistance of counsel warranted a new trial.", "DEFENSE_FAVORABLE"),
    ("The defendant was released on bail pending trial.", "DEFENSE_FAVORABLE"),
    ("The charges were dismissed without prejudice.", "DEFENSE_FAVORABLE"),
    ("The government failed to disclose exculpatory evidence under Brady.", "DEFENSE_FAVORABLE"),
    ("The defendant's constitutional rights were violated during interrogation.", "DEFENSE_FAVORABLE"),
    ("The court granted habeas corpus relief to the defendant.", "DEFENSE_FAVORABLE"),
    ("The statute of limitations had expired prior to the indictment.", "DEFENSE_FAVORABLE"),
    ("The defendant cooperated with authorities and received a reduced sentence.", "DEFENSE_FAVORABLE"),
    ("The court found entrapment by government agents.", "DEFENSE_FAVORABLE"),
    ("Expert testimony established the defendant lacked criminal intent.", "DEFENSE_FAVORABLE"),
    ("The defendant's sentence was reduced on appeal.", "DEFENSE_FAVORABLE"),
    ("The court granted a judgment of acquittal after the government rested.", "DEFENSE_FAVORABLE"),
    ("The defendant was found not guilty by reason of insanity.", "DEFENSE_FAVORABLE"),

    # NEUTRAL
    ("The case was filed in the Southern District of New York.", "NEUTRAL"),
    ("The court scheduled a status conference for March 15, 2024.", "NEUTRAL"),
    ("Pursuant to Rule 12(b)(6), the defendant moved to dismiss the complaint.", "NEUTRAL"),
    ("The parties submitted a joint stipulation extending the discovery deadline.", "NEUTRAL"),
    ("The court issued a scheduling order setting trial for September 2024.", "NEUTRAL"),
    ("Both parties filed motions for summary judgment.", "NEUTRAL"),
    ("The deposition of the plaintiff was scheduled for next Tuesday.", "NEUTRAL"),
    ("The court entered a consent decree resolving the dispute.", "NEUTRAL"),
    ("The matter was referred to a magistrate judge for settlement.", "NEUTRAL"),
    ("The parties agreed to mediation before the American Arbitration Association.", "NEUTRAL"),
    ("The court granted an extension of time to file the answer.", "NEUTRAL"),
    ("The defendant removed the case to federal court under 28 U.S.C. 1441.", "NEUTRAL"),
    ("The plaintiff filed an amended complaint adding additional defendants.", "NEUTRAL"),
    ("The court held oral argument on the pending motions.", "NEUTRAL"),
    ("The jury was selected from the Eastern District venire.", "NEUTRAL"),
    ("The parties entered into a confidential settlement agreement.", "NEUTRAL"),
    ("The court certified the class under Rule 23(b)(3).", "NEUTRAL"),
    ("The appeal was docketed in the Second Circuit Court of Appeals.", "NEUTRAL"),
    ("The defendant requested a continuance due to scheduling conflicts.", "NEUTRAL"),
    ("The court issued a preliminary injunction pending final resolution.", "NEUTRAL"),
]

LABEL_MAP = {"PROSECUTION_FAVORABLE": 0, "DEFENSE_FAVORABLE": 1, "NEUTRAL": 2}
ID_TO_LABEL = {v: k for k, v in LABEL_MAP.items()}


# ── DB Setup ───────────────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_model_table():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_runs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at   TEXT,
            completed_at TEXT,
            status       TEXT,
            accuracy     REAL,
            f1_score     REAL,
            train_size   INTEGER,
            epochs       INTEGER,
            model_path   TEXT,
            notes        TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("[FineTune] Model table initialized ✓")


# ── Training engine ────────────────────────────────────────────────────────────

def run_training(epochs: int = 3):
    """Fine-tune DistilBERT on legal classification dataset."""
    global training_state

    training_state.update({
        "status":    "training",
        "progress":  0,
        "message":   "Initializing training...",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "error":     None,
    })

    try:
        from transformers import (
            DistilBertTokenizerFast,
            DistilBertForSequenceClassification,
            TrainingArguments,
            Trainer,
        )
        from datasets import Dataset
        import numpy as np
        from sklearn.metrics import accuracy_score, f1_score
        from sklearn.model_selection import train_test_split
        import torch

        # ── Step 1: Prepare data ──────────────────────────────────────────────
        training_state["message"] = "Preparing legal training dataset..."
        training_state["progress"] = 10

        texts  = [t for t, _ in TRAINING_DATA]
        labels = [LABEL_MAP[l] for _, l in TRAINING_DATA]

        train_texts, val_texts, train_labels, val_labels = train_test_split(
            texts, labels, test_size=0.2, random_state=42, stratify=labels
        )

        # ── Step 2: Load tokenizer ────────────────────────────────────────────
        training_state["message"] = "Loading DistilBERT tokenizer..."
        training_state["progress"] = 20

        tokenizer = DistilBertTokenizerFast.from_pretrained(
            "distilbert-base-uncased"
        )

        def tokenize(texts):
            return tokenizer(
                texts, truncation=True, padding=True, max_length=128
            )

        train_enc = tokenize(train_texts)
        val_enc   = tokenize(val_texts)

        # ── Step 3: Build datasets ────────────────────────────────────────────
        training_state["message"] = "Building dataset objects..."
        training_state["progress"] = 30

        class LegalDataset(torch.utils.data.Dataset):
            def __init__(self, encodings, labels):
                self.encodings = encodings
                self.labels    = labels
            def __len__(self):
                return len(self.labels)
            def __getitem__(self, idx):
                item = {k: torch.tensor(v[idx]) for k, v in self.encodings.items()}
                item["labels"] = torch.tensor(self.labels[idx])
                return item

        train_dataset = LegalDataset(train_enc, train_labels)
        val_dataset   = LegalDataset(val_enc,   val_labels)

        # ── Step 4: Load model ────────────────────────────────────────────────
        training_state["message"] = "Loading DistilBERT model (3 classes)..."
        training_state["progress"] = 40

        model = DistilBertForSequenceClassification.from_pretrained(
            "distilbert-base-uncased",
            num_labels=3,
            id2label=ID_TO_LABEL,
            label2id=LABEL_MAP,
        )

        # ── Step 5: Training args ─────────────────────────────────────────────
        training_state["message"] = f"Starting fine-tuning ({epochs} epochs)..."
        training_state["progress"] = 50

        os.makedirs(MODEL_DIR, exist_ok=True)
        os.makedirs("models/checkpoints", exist_ok=True)

        def compute_metrics(eval_pred):
            logits, labels = eval_pred
            preds = np.argmax(logits, axis=-1)
            return {
                "accuracy": accuracy_score(labels, preds),
                "f1":       f1_score(labels, preds, average="weighted"),
            }

        args = TrainingArguments(
            output_dir                  = "models/checkpoints",
            num_train_epochs            = epochs,
            per_device_train_batch_size = 8,
            per_device_eval_batch_size  = 8,
            warmup_steps                = 10,
            weight_decay                = 0.01,
            logging_dir                 = "models/logs",
            logging_steps               = 5,
            eval_strategy         = "epoch",
            save_strategy               = "epoch",
            load_best_model_at_end      = True,
            metric_for_best_model       = "accuracy",
            report_to                   = "none",

        )

        # ── Step 6: Train ─────────────────────────────────────────────────────
        trainer = Trainer(
            model           = model,
            args            = args,
            train_dataset   = train_dataset,
            eval_dataset    = val_dataset,
            compute_metrics = compute_metrics,
        )

        training_state["message"] = "Training in progress..."
        training_state["progress"] = 60

        trainer.train()

        # ── Step 7: Evaluate ──────────────────────────────────────────────────
        training_state["message"] = "Evaluating model..."
        training_state["progress"] = 85

        metrics = trainer.evaluate()
        accuracy = round(metrics.get("eval_accuracy", 0), 4)
        f1       = round(metrics.get("eval_f1", 0), 4)

        # ── Step 8: Save ──────────────────────────────────────────────────────
        training_state["message"] = "Saving fine-tuned model..."
        training_state["progress"] = 92

        trainer.save_model(MODEL_DIR)
        tokenizer.save_pretrained(MODEL_DIR)

        # Save metadata
        meta = {
            "model":       "distilbert-base-uncased",
            "task":        "legal-sentiment-classification",
            "labels":      list(LABEL_MAP.keys()),
            "train_size":  len(train_texts),
            "val_size":    len(val_texts),
            "epochs":      epochs,
            "accuracy":    accuracy,
            "f1_score":    f1,
            "trained_at":  datetime.now(timezone.utc).isoformat(),
        }
        with open(f"{MODEL_DIR}/training_meta.json", "w") as f:
            json.dump(meta, f, indent=2)

        # Log to DB
        completed = datetime.now(timezone.utc).isoformat()
        conn = get_conn()
        conn.execute("""
            INSERT INTO model_runs
              (started_at, completed_at, status, accuracy, f1_score,
               train_size, epochs, model_path, notes)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            training_state["started_at"], completed, "complete",
            accuracy, f1, len(train_texts), epochs, MODEL_DIR,
            f"Legal classifier · {len(TRAINING_DATA)} samples"
        ))
        conn.commit()
        conn.close()

        training_state.update({
            "status":       "complete",
            "progress":     100,
            "message":      f"Training complete — accuracy: {accuracy:.1%}, F1: {f1:.3f}",
            "completed_at": completed,
            "metrics": {"accuracy": accuracy, "f1_score": f1,
                        "train_size": len(train_texts), "val_size": len(val_texts)},
        })

    except Exception as e:
        training_state.update({
            "status":  "error",
            "message": f"Training failed: {str(e)}",
            "error":   str(e),
        })
        print(f"[FineTune] Error: {e}")


# ── Inference ──────────────────────────────────────────────────────────────────

_model     = None
_tokenizer = None

def load_model():
    """Lazy-load the fine-tuned model for inference."""
    global _model, _tokenizer
    if _model is None:
        if not os.path.exists(MODEL_DIR):
            raise HTTPException(404, "No fine-tuned model found. Run /model/train first.")
        from transformers import (
            DistilBertTokenizerFast,
            DistilBertForSequenceClassification,
        )
        import torch
        _tokenizer = DistilBertTokenizerFast.from_pretrained(MODEL_DIR)
        _model     = DistilBertForSequenceClassification.from_pretrained(MODEL_DIR)
        _model.eval()
    return _model, _tokenizer


def predict(text: str) -> dict:
    """Run inference on text using fine-tuned model."""
    import torch
    import torch.nn.functional as F

    model, tokenizer = load_model()
    inputs = tokenizer(
        text, return_tensors="pt", truncation=True,
        padding=True, max_length=128
    )
    with torch.no_grad():
        outputs = model(**inputs)
        probs   = F.softmax(outputs.logits, dim=-1)[0]
        pred_id = probs.argmax().item()

    label = ID_TO_LABEL[pred_id]
    confidence = round(probs[pred_id].item(), 4)

    all_scores = {
        ID_TO_LABEL[i]: round(probs[i].item(), 4)
        for i in range(len(probs))
    }

    return {
        "label":      label,
        "confidence": confidence,
        "all_scores": all_scores,
        "text_preview": text[:150],
    }


# ── Pydantic models ────────────────────────────────────────────────────────────

class TrainBody(BaseModel):
    epochs: Optional[int] = 3

class PredictBody(BaseModel):
    text:  str
    label: Optional[str] = "Text"


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/train")
def start_training(body: TrainBody, background_tasks: BackgroundTasks):
    """Start fine-tuning DistilBERT on legal classification dataset."""
    if training_state["status"] == "training":
        return {"success": False, "message": "Training already in progress"}

    epochs = max(1, min(body.epochs, 10))
    background_tasks.add_task(run_training, epochs)

    return {
        "success": True,
        "message": f"Fine-tuning started — {epochs} epochs on {len(TRAINING_DATA)} legal samples",
        "epochs":  epochs,
        "labels":  list(LABEL_MAP.keys()),
        "dataset_size": len(TRAINING_DATA),
        "check_status": "GET /model/status",
    }


@router.get("/status")
def training_status():
    """Check current training status and progress."""
    return {
        "success": True,
        **training_state,
    }


@router.post("/predict")
def predict_text(body: PredictBody):
    """Classify legal text using the fine-tuned model."""
    if not body.text.strip():
        raise HTTPException(400, "Text is required")
    if training_state["status"] != "complete" and not os.path.exists(MODEL_DIR):
        raise HTTPException(503, "Model not trained yet. Run POST /model/train first.")

    result = predict(body.text)
    return {
        "success": True,
        "label":   body.label,
        **result,
    }


@router.get("/info")
def model_info():
    """Get fine-tuned model metadata."""
    meta_path = f"{MODEL_DIR}/training_meta.json"
    if not os.path.exists(meta_path):
        return {
            "success": False,
            "message": "No trained model found. Run POST /model/train first.",
            "training_state": training_state,
        }
    with open(meta_path) as f:
        meta = json.load(f)

    # Latest DB run
    conn = get_conn()
    run  = conn.execute(
        "SELECT * FROM model_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    return {
        "success":      True,
        "model":        meta,
        "latest_run":   dict(run) if run else None,
        "model_path":   MODEL_DIR,
        "ready":        os.path.exists(f"{MODEL_DIR}/config.json"),
    }


@router.get("/examples")
def run_examples():
    """Run the fine-tuned model on example legal sentences."""
    if not os.path.exists(MODEL_DIR):
        raise HTTPException(503, "Model not trained yet. Run POST /model/train first.")

    examples = [
        "The jury convicted the defendant on all counts of wire fraud.",
        "The court granted the defendant's motion to dismiss for insufficient evidence.",
        "The parties filed a joint stipulation extending the discovery deadline.",
        "The FBI investigation revealed a systematic pattern of financial deception.",
        "The conviction was reversed on appeal due to prosecutorial misconduct.",
    ]

    results = []
    for text in examples:
        result = predict(text)
        results.append({"text": text, **result})

    return {
        "success":  True,
        "examples": results,
    }


@router.get("/dataset")
def view_dataset():
    """View the legal training dataset."""
    by_label = {}
    for text, label in TRAINING_DATA:
        if label not in by_label:
            by_label[label] = []
        by_label[label].append(text)

    return {
        "success":      True,
        "total_samples": len(TRAINING_DATA),
        "labels":       list(LABEL_MAP.keys()),
        "by_label":     {k: {"count": len(v), "examples": v[:3]} for k, v in by_label.items()},
    }
