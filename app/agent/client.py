from google import genai

from app.config import Settings

_client: genai.Client | None = None


def init_genai_client(settings: Settings):
    global _client
    _client = genai.Client(api_key=settings.gemini_api_key)


def get_genai_client() -> genai.Client:
    if _client is None:
        raise RuntimeError("GenAI client not initialized. Set GEMINI_API_KEY in .env")
    return _client
