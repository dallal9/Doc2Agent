from typing import Literal

from pydantic import BaseModel, Field

SpanKind = Literal["text", "page"]


class Span(BaseModel):
    span_id: str | None = None
    kind: SpanKind
    page_num: int
    quoted_text: str | None = None


class Annotation(BaseModel):
    annotation_id: str
    set_id: str
    question: str
    answer: str
    created_at: str | None = None
    spans: list[Span] = Field(default_factory=list)


class AnnotationSet(BaseModel):
    set_id: str
    doc_id: str
    label: str
    description: str | None = None
    created_at: str | None = None
