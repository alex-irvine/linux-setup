import os

import pytest

FALLBACK_ENV = ("OLLAMA_FALLBACK_URL", "OLLAMA_FALLBACK_TIMEOUT", "OLLAMA_FALLBACK_LIMIT",
                "OLLAMA_FALLBACK_THREADS", "OLLAMA_FALLBACK_MIN_CPU_IDLE", "OLLAMA_FALLBACK_MIN_MEMORY",
                "OLLAMA_FALLBACK_ON_BATTERY", "OLLAMA_PROBE_TIMEOUT")


@pytest.fixture(autouse=True, scope="session")
def _scrub_fallback_env():
    saved = {name: os.environ.pop(name) for name in FALLBACK_ENV if name in os.environ}
    yield
    os.environ.update(saved)
