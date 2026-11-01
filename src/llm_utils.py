import os
from langchain_google_genai import ChatGoogleGenerativeAI

# Override from .env / Render without touching code:
#   GEMINI_MODEL=gemini-3.6-flash        (logged-in parents / therapists)
#   GEMINI_GUEST_MODEL=gemini-3.5-flash-lite   (public visitors, cheaper)
#   GEMINI_FALLBACK_MODELS=gemini-3.7-flash,gemini-3.5-flash,gemini-2.5-flash
PRIMARY_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GUEST_MODEL = os.getenv("GEMINI_GUEST_MODEL", "gemini-3.5-flash-lite")
FALLBACK_MODELS = [
    m.strip()
    for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.7-flash,gemini-3.5-flash,gemini-2.5-flash").split(",")
    if m.strip()
]


def build_llm(api_key: str, temperature: float = 0.7, model: str = None, max_output_tokens: int = None):
    """Gemini chat model that retries briefly, then falls back to other models."""
    first = model or PRIMARY_MODEL

    def make(name: str):
        kw = dict(model=name, google_api_key=api_key, temperature=temperature, max_retries=2, timeout=30)
        if max_output_tokens:
            kw["max_output_tokens"] = max_output_tokens
        return ChatGoogleGenerativeAI(**kw)

    names = []
    for n in [PRIMARY_MODEL] + FALLBACK_MODELS:
        if n != first and n not in names:
            names.append(n)
    primary = make(first)
    return primary.with_fallbacks([make(n) for n in names]) if names else primary


def friendly_error(e: Exception) -> str:
    text = str(e)
    if any(k in text for k in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "overloaded")):
        return "The assistant is very busy right now. Please try again in a moment."
    return "Something went wrong while generating a reply. Please try again."
