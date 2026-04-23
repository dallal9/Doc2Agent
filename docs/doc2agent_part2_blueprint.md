# Doc2Agent Part 2

## Summary

## What we are building
Extend Doc2Agent into a **local system for dataset creation and evaluation on PDFs**.

## Core flow


PDF → Annotation → Dataset → Prediction → Evaluation

## What it does
- Annotate PDFs to create Q&A + evidence spans
- Build datasets from annotations
- Run existing pipeline to generate predictions
- Evaluate results (manual or LLM-as-judge)
- Track performance via metrics

## Key idea
Reuse the current pipeline and make **annotation the source of truth** for evaluation.

## Outcome
Doc2Agent becomes a **document evaluation and experimentation tool**, not just a chat interface.


## Milestone 1 — Document Ingestion & Annotation

This should be like a new page, tab, or app in the gradio app, where we have document editor and annotator. This could be a react app or something similar. 

This should be a nice react app where you can select text from the pdf and it would be marked automatically as span. Use https://docs.tagtog.com/ as inspiration.  

### Goal
Create structured labeled data (`Document` + `Annotation`) from PDFs.

### Scope
Implements:
- `Document`
- `Annotation`
- `Span`

### Features
- Document Annotation Tab:
  - Upload and store PDF locally
  - Text in the document should be selectable. 
  - Highlight text spans (mapped to `Span`)
  - Support:
    - span-based annotations: user can select multiple parts of the document to represent the span. 
    - page-based annotations user can select pages by number so their text would be fully used in the span. 
  - Add:
    - Q&A annotations (`Annotation`)
    - User should select a span and enter question and answer and the tuple should be stored  
  - there should be distinction between original document (PDF), and annotation +  document, we could have different versions of the same documents by annotating it differently so we can create a new unique label using original document name. 

### Output
- Persisted `Document`
- Persisted `Annotation` (linked to document)
- There is a nice view here user can scroll through and annotated document, view, edit annotations. 
- The annotations can be exported as a json mostly tuples (question, answer, and spans)


---

## Milestone 2 — Dataset Creation & Pipeline Execution

### Goal
Construct datasets from annotations and run the existing pipeline to generate predictions.

### Scope
Implements:
- `Dataset`
- `Prediction`

### Features

#### Dataset Creation Tab
- Select existing annotations
- Group into `Dataset`
- Add:
  - name
  - description

#### Run Evaluation Tab (Execution Phase)
- Load dataset
- For each `Annotation`:
  - run pipeline (same as Chat Tab)
  - generate `Prediction`
- Store:
  - predicted_answer
  - context_used
  - link to annotation

### Output
- `Dataset` containing annotations
- `Prediction` linked to each annotation

---

## Milestone 3 — Evaluation & Metrics System

### Goal
Evaluate predictions using defined metrics and provide aggregated results.

### Scope
Implements:
- `Metric`
- `Evaluation`
- `EvaluationResult`

### Features

#### Metrics & Evaluation Setup Tab
- Define `Metric`:
  - type: bool | int | float
  - aggregation: avg | sum | max | min
  - optional `judge_prompt`
- Define `Evaluation`:
  - dataset_id
  - metrics

#### Run Evaluation Tab (Scoring Phase)
- For each `Prediction`:
  - compare with `Annotation.expected_answer`

Evaluation modes:
- Manual:
  - user assigns score
- LLM-as-judge:
  - use `Metric.judge_prompt`

Store:
- `EvaluationResult` per prediction per metric

---

## Milestone 4 — Dashboard & System Overview

### Goal
Provide visibility over documents, datasets, and evaluation performance.

### Scope
No new models (uses existing)

### Features
- Dashboard Tab:
  - Documents overview
  - Datasets overview
  - Evaluation runs
  - Aggregated metrics:
    - avg score per metric
    - per-dataset breakdown
- Optional:
  - filter low-score predictions
  - inspect failure cases

---

## Execution Flow (Final)
PDF → Document → Annotation → Dataset
Dataset → Pipeline → Prediction
Prediction → Evaluation → EvaluationResult


---

## Notes

- Chat Tab remains unchanged (reused for pipeline execution)
- Annotation is the source of truth for datasets
- Evaluation reuses the same inference pipeline
- No OCR, no multi-user, local-only system