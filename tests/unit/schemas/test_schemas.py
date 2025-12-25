import pytest
from pydantic import ValidationError

from src.schemas import LLMRequest, LLMResponse, TranslationRequest, TranslationResponse


class TestLLMSchemas:
    def test_llm_request_valid(self):
        req = LLMRequest(prompt="Hello")
        assert req.prompt == "Hello"
        assert req.temperature == 0.2

    def test_llm_request_custom_temp(self):
        req = LLMRequest(prompt="Hello", temperature=0.8)
        assert req.temperature == 0.8

    def test_llm_request_missing_prompt(self):
        with pytest.raises(ValidationError):
            LLMRequest()

    def test_llm_response_valid(self):
        resp = LLMResponse(text="Hi", tokens=10, time_s=0.5)
        assert resp.text == "Hi"
        assert resp.tokens == 10
        assert resp.time_s == 0.5


class TestTranslationSchemas:
    def test_translation_request_valid(self):
        req = TranslationRequest(text="Hello")
        assert req.text == "Hello"
        assert req.source_lang == "en"
        assert req.target_lang == "de"

    def test_translation_request_custom_langs(self):
        req = TranslationRequest(text="Hello", source_lang="en", target_lang="ar")
        assert req.target_lang == "ar"

    def test_translation_request_missing_text(self):
        with pytest.raises(ValidationError):
            TranslationRequest()

    def test_translation_response_valid(self):
        resp = TranslationResponse(translated_text="Hallo")
        assert resp.translated_text == "Hallo"
