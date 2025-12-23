from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI
from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer

from src.logging import setup_logging
from src.schemas import TranslationRequest, TranslationResponse

logger = setup_logging("translation")

MODEL = "facebook/m2m100_418M"
tokenizer = None
model = None
device = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global tokenizer, model, device
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("loading model=%s device=%s", MODEL, device)
    tokenizer = M2M100Tokenizer.from_pretrained(MODEL)
    model = M2M100ForConditionalGeneration.from_pretrained(
        MODEL,
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
    ).to(device)
    logger.info("model loaded")
    yield


app = FastAPI(title="Translation Service", lifespan=lifespan)


@app.post("/translate", response_model=TranslationResponse)
def translate(req: TranslationRequest) -> TranslationResponse:
    logger.info("translate src=%s tgt=%s len=%d", req.source_lang, req.target_lang, len(req.text))
    tokenizer.src_lang = req.source_lang
    inputs = tokenizer(req.text, return_tensors="pt", truncation=True, max_length=512).to(device)

    with torch.inference_mode():
        outputs = model.generate(
            **inputs,
            forced_bos_token_id=tokenizer.get_lang_id(req.target_lang),
            max_new_tokens=512,
            num_beams=4,
        )
    translated = tokenizer.decode(outputs[0], skip_special_tokens=True)
    logger.info("done len=%d", len(translated))
    return TranslationResponse(translated_text=translated)


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL, "device": device}
