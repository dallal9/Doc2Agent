import logging
import time
import ollama
from fastapi import FastAPI

from src.config import LLM_MODEL, LLM_TEMPERATURE
from src.schemas import LLMRequest, LLMResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("llm")

app = FastAPI(title="LLM Service")


@app.post("/generate", response_model=LLMResponse)
def generate(req: LLMRequest) -> LLMResponse:
    temp = req.temperature or LLM_TEMPERATURE
    logger.info("generate model=%s temp=%.2f", LLM_MODEL, temp)
    t0 = time.time()

    resp = ollama.generate(model=LLM_MODEL, prompt=req.prompt, options={"temperature": temp})

    dt = time.time() - t0
    tokens = resp.get("eval_count", 0)
    logger.info("done tokens=%d time=%.2fs", tokens, dt)
    return LLMResponse(text=resp["response"], tokens=tokens, time_s=dt)


@app.get("/health")
def health():
    return {"status": "ok", "model": LLM_MODEL}

