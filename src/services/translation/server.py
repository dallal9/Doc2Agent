import logging
from fastapi import FastAPI
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

from src.config import TRANSLATION_MODEL
from src.schemas import TranslationRequest, TranslationResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("translation")

app = FastAPI(title="Translation Service")

tokenizer = None
model = None


def load_model():
    global tokenizer, model
    if model is None:
        logger.info("loading model=%s", TRANSLATION_MODEL)
        tokenizer = AutoTokenizer.from_pretrained(TRANSLATION_MODEL)
        model = AutoModelForSeq2SeqLM.from_pretrained(TRANSLATION_MODEL)
        logger.info("model loaded")


@app.on_event("startup")
def startup():
    load_model()


@app.post("/translate", response_model=TranslationResponse)
def translate(req: TranslationRequest) -> TranslationResponse:
    logger.info("translate src=%s tgt=%s len=%d", req.source_lang, req.target_lang, len(req.text))
    inputs = tokenizer(req.text, return_tensors="pt", truncation=True, max_length=512)
    outputs = model.generate(**inputs, max_length=512)
    translated = tokenizer.decode(outputs[0], skip_special_tokens=True)
    logger.info("done len=%d", len(translated))
    return TranslationResponse(translated_text=translated)


@app.get("/health")
def health():
    return {"status": "ok", "model": TRANSLATION_MODEL}

