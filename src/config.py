import os

from dotenv import load_dotenv

load_dotenv()

# LLM
LLM_MODEL = os.getenv("LLM_MODEL", "gemma2:2b")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
LLM_PORT = int(os.getenv("LLM_PORT", "8001"))

# Translation
TRANSLATION_MODEL = os.getenv("TRANSLATION_MODEL", "Helsinki-NLP/opus-mt-en-ar")
TRANSLATION_PORT = int(os.getenv("TRANSLATION_PORT", "8002"))
