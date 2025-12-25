import os

from dotenv import load_dotenv

load_dotenv()

# OpenRouter (for cloud inference)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Personal info for validation (dynamic JSON)
PERSONAL_INFO_JSON = os.getenv("PERSONAL_INFO_JSON", "{}")
