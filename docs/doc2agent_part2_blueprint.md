# Doc2Agent Part 2 — Technical Blueprint

## Goal

Extend Doc2Agent from a local PDF chat assistant into a local dataset creation and evaluation workbench for PDF-based QA.

Core flow:

```text
PDF → Annotation → Dataset → Evaluation Run → Judge Run → Metrics → Dashboard
```

The existing Chat pipeline remains unchanged and is reused for evaluation execution.

---

## Current State

Already implemented:

- Multi-page Gradio app with `Chat` and `Datasets`
- Local PDF upload, parsing, storage, and chat
- Dataset creation from live chat sessions
- Manual PDF annotation with PDF.js viewer
- Text/page span staging
- Annotation sets pushed into datasets
- SQLite storage for documents, annotations, spans, and datasets

---

# Milestone 1 — Document Ingestion & Annotation

## Goal

Create structured labeled data from PDFs.

This milestone adds a document editor / annotator experience inside the Gradio app. It can be implemented as a React app, embedded frontend, or similar UI layer. The experience should be inspired by tools like TagTog: selectable PDF text, highlighted spans, and structured annotation creation.

## Scope

Models:

- `Document`
- `Annotation`
- `Span`

## Features

### Document Annotation Tab

- Upload and store PDF locally
- Render PDF with selectable text
- Highlight selected text and store it as one or more `Span`s
- Support span types:
  - text-based spans
  - page-based spans
- Allow selecting full pages by page number
- Create Q&A annotations:
  - `question`
  - `expected_answer`
  - linked spans
- Support multiple annotation versions for the same source PDF
- Distinguish between:
  - original PDF/document
  - annotation set over that document
- Allow annotation set names/labels based on the original document name

## Output

- Persisted `Document`
- Persisted `Annotation`
- Persisted `Span`
- Annotation set linked to document
- UI to view, edit, and export annotations
- JSON export containing question, expected answer, and spans

---

# Milestone 2 — Dataset Creation

## Goal

Create datasets from existing annotations and live chat sessions.

This milestone is already mostly implemented in the current project.

## Scope

Models:

- `Dataset`
- existing `Annotation`
- existing `Span`

## Implemented Dataset Sources

### 1. Live Chat Dataset

Create datasets from previous chat sessions.

Supports:

- Selecting a chat session
- Exporting chat turns as annotations
- Auto mode: export all turns
- Manual mode: select specific turns
- Storing user question and assistant answer
- Optionally storing retrieved context / reasoning traces as evidence spans when available

### 2. Manually Annotated Dataset

Create datasets from manual PDF annotations.

Supports:

- Selecting an annotation set
- Adding annotation set to an existing dataset
- Creating a new dataset from an annotation set
- Keeping document references and spans linked to annotations

## Dataset Fields

Each dataset should contain:

- `id`
- `name`
- `description`
- `source_type`: `live_chat | manual_annotation | mixed`
- linked annotation IDs
- created timestamp

## Output

- Persisted `Dataset`
- Dataset linked to annotations
- Dataset preview
- Dataset JSON export

---

# Milestone 3 — Evaluation Page & Execution Run

## Goal

Add a new top-level `Evaluation` page and a `Execution Run` tab.

This milestone runs a selected dataset against the existing Doc2Agent chat agent.

## UI

Add navbar item:

```text
Chat | Datasets | Evaluation
```

Evaluation page tabs:

```text
Execution Run
```

## Scope

Models:

- `EvaluationRun`
- `EvaluationPrediction`

## Execution Run Tab

The user selects:

- dataset
- run name
- optional description
- optional agent/backend config

For each annotation in the dataset:

1. Load the linked document
2. Attach/select the document for the chat agent
3. Send `annotation.question` as a one-turn query
4. Store the result

## Stored Per-Annotation Output

Store one `EvaluationPrediction` per annotation:

- `evaluation_run_id`
- `dataset_id`
- `annotation_id`
- `agent_answer`
- `agent_thoughts` if available
- `document_reference` if technically possible
- `context_used` if available
- `status`: `success | failed | skipped`
- `error_message`
- timestamp

## Requirements

- Evaluation must be one-turn only
- No prior chat history should affect the answer
- The document must come from the annotation/dataset reference
- Reuse the existing Chat pipeline instead of creating a new agent path
- Store traces/context only if the current pipeline exposes them cleanly

## Output

- Persisted `EvaluationRun`
- Persisted `EvaluationPrediction`s
- Results table showing:
  - question
  - expected answer
  - agent answer
  - document
  - status

---

# Milestone 4 — Metrics & Judge Run

## Goal

Add judging and metric scoring under the `Evaluation` page.

This milestone contains two tabs:

```text
Execution Run | Metrics | Judge Run
```

---

## 4.1 Metrics Tab

### Goal

Define reusable metrics that can be applied to evaluation predictions.

### Scope

Model:

- `Metric`

### Metric Fields

Each metric should include:

- `id`
- `name`
- `description`
- `type`: `bool | int | float`
- `aggregation`: `avg | sum | min | max`
- optional `judge_prompt`
- optional metadata:
  - min value
  - max value
  - allowed labels

### Example Metrics

```text
Correctness
Type: float
Aggregation: avg
Description: How correct is the agent answer compared to the expected answer?

Faithfulness
Type: float
Aggregation: avg
Description: Is the answer supported by the document evidence/reference?

Contains Expected Answer
Type: bool
Aggregation: avg
Description: Does the agent answer contain the expected answer?
```

### Metrics Tab Features

- Create metric
- Edit metric
- Delete metric
- List existing metrics
- Validate metric type and aggregation
- Store optional LLM judge prompt per metric

---

## 4.2 Judge Run Tab

### Goal

Score predictions from an evaluation run manually or with a minimal LLM-as-judge mode.

### Scope

Models:

- `JudgeRun`
- `EvaluationResult`

### Manual Judge View

The user selects:

- evaluation run
- metrics to apply

For each prediction, show:

- annotation question
- expected answer
- agent answer
- evidence spans / document reference
- document viewer if available
- metric names and descriptions
- score input per metric
- optional comment field

### Stored Judgment Output

Store one `EvaluationResult` per prediction per metric:

- `judge_run_id`
- `evaluation_run_id`
- `prediction_id`
- `annotation_id`
- `metric_id`
- `score`
- `judge_type`: `manual | llm`
- optional comment
- optional judge reasoning
- timestamp

### Optional LLM-as-Judge

If easy to implement, provide a minimal LLM judge mode.

The LLM receives:

- system prompt
- metric description
- metric judge prompt if defined
- question
- expected answer
- agent answer
- evidence spans / document reference
- optional context used

Expected structured output:

```json
{
  "score": 0.8,
  "reason": "The answer is mostly correct but misses one detail."
}
```

### Aggregation

After judging, aggregate results automatically based on each metric’s aggregation field.

Store or compute:

- score per metric
- aggregated score per metric
- judged sample count
- missing judgment count
- per-run summary

## Output

- Persisted `Metric`
- Persisted `JudgeRun`
- Persisted `EvaluationResult`
- Manual judge interface
- Optional LLM judge interface
- Aggregated metric summaries

---

# Milestone 5 — Dashboard & System Overview
add new page `Dashboard` to the Chat | Datasets | Evaluation |  Dashboard level
## Goal

Provide visibility into documents, datasets, evaluation runs, judge runs, and metric performance.

## Scope

Uses existing models from previous milestones.

No major new models required.

## Dashboard Features

Show overview of:

- documents
- annotation sets
- datasets
- evaluation runs
- judge runs
- metric summaries

## Aggregated Views

Display:

- average score per metric
- per-dataset metric breakdown
- per-evaluation-run breakdown
- per-judge-run breakdown
- number of evaluated samples
- number of judged samples
- missing judgments

## Failure Inspection

Optional filters/views:

- low-score predictions
- failed evaluation runs
- unanswered questions
- predictions missing document references
- cases where human and LLM judge disagree

## Output

- Dashboard tab under `Evaluation`
- Aggregated metric tables
- Links to inspect predictions and judgments
- Failure case view

---

# Suggested Data Models

## EvaluationRun

```python
class EvaluationRun(BaseModel):
    id: str
    dataset_id: str
    name: str
    description: str | None = None
    status: Literal["pending", "running", "completed", "failed"]
    agent_config: dict = {}
    created_at: datetime
    completed_at: datetime | None = None
```

## EvaluationPrediction

```python
class EvaluationPrediction(BaseModel):
    id: str
    evaluation_run_id: str
    dataset_id: str
    annotation_id: str
    agent_answer: str | None = None
    agent_thoughts: str | None = None
    document_reference: str | None = None
    context_used: str | None = None
    status: Literal["success", "failed", "skipped"]
    error_message: str | None = None
    created_at: datetime
```

## Metric

```python
class Metric(BaseModel):
    id: str
    name: str
    description: str
    type: Literal["bool", "int", "float"]
    aggregation: Literal["avg", "sum", "min", "max"]
    judge_prompt: str | None = None
    metadata: dict = {}
    created_at: datetime
```

## JudgeRun

```python
class JudgeRun(BaseModel):
    id: str
    evaluation_run_id: str
    name: str
    judge_type: Literal["manual", "llm"]
    metric_ids: list[str]
    status: Literal["pending", "running", "completed", "failed"]
    created_at: datetime
    completed_at: datetime | None = None
```

## EvaluationResult

```python
class EvaluationResult(BaseModel):
    id: str
    judge_run_id: str
    evaluation_run_id: str
    prediction_id: str
    annotation_id: str
    metric_id: str
    score: bool | int | float
    comment: str | None = None
    judge_reasoning: str | None = None
    created_at: datetime
```

---

# Implementation Constraints

- Keep system local-first
- Keep SQLite as persistence layer
- Reuse existing Chat pipeline
- Keep Chat page unchanged
- No OCR
- No multi-user support
- No hosted backend
- Evaluation runs should be reproducible through stored dataset/run/config metadata
