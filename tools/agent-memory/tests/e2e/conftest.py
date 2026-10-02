import os

import pytest

FALLBACK_ENV = ("OLLAMA_FALLBACK_URL", "OPENROUTER_API_KEY", "OLLAMA_FALLBACK_REVIEW_MODEL",
                "OLLAMA_FALLBACK_EMBED_MODEL", "OLLAMA_FALLBACK_EMBED_DIMENSIONS",
                "OLLAMA_FALLBACK_TIMEOUT", "OLLAMA_PROBE_TIMEOUT")


@pytest.fixture(autouse=True, scope="session")
def _scrub_fallback_env():
    saved = {name: os.environ.pop(name) for name in FALLBACK_ENV if name in os.environ}
    yield
    os.environ.update(saved)
