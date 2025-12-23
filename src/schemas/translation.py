from pydantic import BaseModel


class TranslationRequest(BaseModel):
    text: str
    source_lang: str = "en"
    target_lang: str = "de"


class TranslationResponse(BaseModel):
    translated_text: str

