from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RunStatus = Literal["pending", "running", "completed", "failed"]
PredictionStatus = Literal["success", "failed", "skipped"]
MetricType = Literal["bool", "int", "float"]
Aggregation = Literal["avg", "sum", "min", "max"]
JudgeType = Literal["manual", "llm"]


class EvaluationRun(BaseModel):
    run_id: str
    dataset_id: str
    name: str
    description: str | None = None
    status: RunStatus = "pending"
    agent_config: dict = Field(default_factory=dict)
    created_at: str | None = None
    completed_at: str | None = None


class EvaluationPrediction(BaseModel):
    prediction_id: str
    run_id: str
    dataset_id: str
    annotation_id: str
    agent_answer: str | None = None
    agent_thoughts: str | None = None
    document_reference: str | None = None
    context_used: str | None = None
    status: PredictionStatus = "success"
    error_message: str | None = None
    created_at: str | None = None


class Metric(BaseModel):
    metric_id: str
    name: str
    description: str
    type: MetricType = "float"
    aggregation: Aggregation = "avg"
    judge_prompt: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: str | None = None


class JudgeRun(BaseModel):
    judge_run_id: str
    evaluation_run_id: str
    name: str
    judge_type: JudgeType = "manual"
    metric_ids: list[str] = Field(default_factory=list)
    status: RunStatus = "pending"
    created_at: str | None = None
    completed_at: str | None = None


class EvaluationResult(BaseModel):
    result_id: str
    judge_run_id: str
    evaluation_run_id: str
    prediction_id: str
    annotation_id: str
    metric_id: str
    score: float
    judge_type: JudgeType = "manual"
    comment: str | None = None
    judge_reasoning: str | None = None
    created_at: str | None = None
