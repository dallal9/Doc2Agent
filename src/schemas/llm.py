from pydantic import BaseModel


class LLMRequest(BaseModel):
    prompt: str
    temperature: float = 0.2


class LLMResponse(BaseModel):
    text: str
    tokens: int
    time_s: float
