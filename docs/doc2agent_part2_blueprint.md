# Doc2Agent Part 2 — Annotation & Evaluation Extension

## Goal
Extend Doc2Agent to support:
- Creation of labeled datasets from PDFs
- Running pipelines on datasets
- Evaluating outputs (manual + LLM-based)

This extends the existing system without changing core architecture.

---

## Core Concepts (Pydantic Models)

### Document
```python
class Document(BaseModel):
    id: str
    file_path: str
    metadata: dict
    labels: list[str]  # document-level labels
```

### Annotation (Q&A)
```python
class Annotation(BaseModel):
    document_id: str
    query: str
    expected_answer: str
    evidence_spans: list[Span]  # highlighted text regions
```

```python
class Span(BaseModel):
    page: int
    start: int
    end: int
    text: str
```

### Dataset
```python
class Dataset(BaseModel):
    id: str
    name: str
    description: str
    annotations: list[Annotation]
```

### Prediction (Pipeline Output)
```python
class Prediction(BaseModel):
    annotation_id: str
    predicted_answer: str
    context_used: list[str]
```

### Metric
```python
class Metric(BaseModel):
    name: str
    type: Literal["bool", "int", "float"]
    aggregation: Literal["avg", "sum", "max", "min"]
    judge_prompt: Optional[str]  # for LLM-as-judge
```

### Evaluation
```python
class Evaluation(BaseModel):
    dataset_id: str
    metrics: list[Metric]
```

### EvaluationResult
```python
class EvaluationResult(BaseModel):
    prediction_id: str
    metric_name: str
    score: float | bool
```

---

## Application Structure (Tabs)

### 1. Chat Tab (existing)
- No change
- Uses same pipeline for inference

### 2. Document Annotation Tab
Purpose: Create `Document` + `Annotation`

Features:
- Upload PDF (store locally)
- Extract text (no OCR required)
- Highlight text spans (per page)
- Add:
  - document-level labels
  - Q&A annotations
- Support:
  - span-based annotation
  - page-based annotation

### 3. Dataset Creation Tab
Purpose: Create `Dataset`

Features:
- Select documents
- Select annotations
- Add dataset metadata (name, description)
- Save dataset

### 4. Metrics & Evaluation Setup Tab
Purpose: Define `Metric` and `Evaluation`

Features:
- Create metrics:
  - exact match
  - similarity (embedding or LLM)
  - custom LLM judge
- Define aggregation method
- Define evaluation config (dataset + metrics)

### 5. Run Evaluation Tab
Purpose: Execute pipeline on dataset

Flow:
1. Load dataset
2. For each annotation:
   - run pipeline (same as chat)
   - generate `Prediction`
3. Store predictions

Evaluation modes:
- **Manual**
  - user reviews predictions
  - assigns scores
- **LLM-as-judge**
  - use `judge_prompt`
  - compare predicted vs expected

Output:
- `EvaluationResult`
- link predictions to annotations

### 6. Dashboard Tab
Purpose: Overview & statistics

Displays:
- Documents count
- Datasets
- Evaluation runs
- Metrics summary:
  - avg scores
  - per-metric breakdown
- Optional:
  - failure cases
  - low-score samples

---

## Data Flow

```
PDF → Document → Annotation → Dataset
Dataset → Pipeline → Prediction
Prediction + Annotation → Evaluation → Results
```

---

## Key Constraints

- PDFs must be text-based (no OCR for now)
- All data stored locally
- Reuse same pipeline for:
  - chat
  - evaluation
- Annotation is the source of truth for datasets

---

## Non-Goals (for now)

- No multi-user support
- No cloud storage
- No real-time collaboration
