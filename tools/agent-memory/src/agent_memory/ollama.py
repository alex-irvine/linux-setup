from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import resources


FALLBACK_KEEP_ALIVE = "1m"
FALLBACK_NUM_CTX = 4096


def _tagged(model: str) -> str:
    return model if ":" in model else f"{model}:latest"


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    source: str = "primary"
    model: str = ""


@dataclass(frozen=True)
class DegradedStatus:
    reason: str
    fallback: bool = False


class OllamaClient:
    def __init__(self, url: str | None = None, timeout: float | None = None,
                 review_model: str | None = None, embed_model: str | None = None) -> None:
        self.url = (url or os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = timeout if timeout is not None else float(os.environ.get("OLLAMA_TIMEOUT", "60"))
        self.review_model = review_model or os.environ.get("OLLAMA_REVIEW_MODEL", "qwen3:1.7b")
        self.embed_model = embed_model or os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
        # A second Ollama, normally this machine's own, with the same models.
        # It is used only while the primary does not answer.
        self.fallback_url = os.environ.get("OLLAMA_FALLBACK_URL", "").rstrip("/") or None
        self.fallback_timeout = float(os.environ.get("OLLAMA_FALLBACK_TIMEOUT", "120"))
        self.fallback_limit = int(os.environ.get("OLLAMA_FALLBACK_LIMIT", "10"))
        self.fallback_threads = int(os.environ.get("OLLAMA_FALLBACK_THREADS", "4"))
        self.fallback_min_cpu_idle = float(os.environ.get("OLLAMA_FALLBACK_MIN_CPU_IDLE", "50"))
        self.fallback_min_memory = float(os.environ.get("OLLAMA_FALLBACK_MIN_MEMORY", "25"))
        self.fallback_on_battery = os.environ.get("OLLAMA_FALLBACK_ON_BATTERY", "0") == "1"
        self.probe_timeout = float(os.environ.get("OLLAMA_PROBE_TIMEOUT", "3"))
        self.provider: str | None = None

    def _select_provider(self) -> str:
        if self.provider is not None:
            return self.provider
        self.provider = "primary"
        if self.fallback_url:
            try:
                with urlopen(f"{self.url}/api/tags", timeout=self.probe_timeout) as response:
                    response.read()
            except HTTPError:
                pass
            except OSError:
                self.provider = "fallback"
        return self.provider

    def available(self) -> DegradedStatus | None:
        """Return None when a provider can take work now, or why none can.

        Uses the short probe timeout, so an unreachable host costs seconds
        rather than one full request timeout per queued capture. The local
        fallback also has to have spare capacity: it must not be running
        another model, and the machine must have the CPU, memory and power
        set by the OLLAMA_FALLBACK_* limits.
        """
        if self._select_provider() == "fallback":
            reason = self._fallback_shortage()
            return DegradedStatus(f"Ollama at {self.url} unreachable and local Ollama unused: {reason}",
                                  fallback=True) if reason else None
        try:
            with urlopen(f"{self.url}/api/tags", timeout=self.probe_timeout) as response:
                response.read()
        except HTTPError:
            return None
        except OSError as error:
            return DegradedStatus(f"Ollama at {self.url} unreachable: {error}", fallback=True)
        return None

    def _fallback_shortage(self) -> str | None:
        try:
            with urlopen(f"{self.fallback_url}/api/ps", timeout=self.probe_timeout) as response:
                loaded = json.loads(response.read()).get("models") or []
        except (OSError, ValueError) as error:
            return f"{self.fallback_url} unreachable: {error}"
        ours = {_tagged(self.review_model), _tagged(self.embed_model)}
        others = sorted({_tagged(str(model.get("name", ""))) for model in loaded} - ours)
        if others:
            return f"it is running {', '.join(others)}"
        return resources.shortage(self.fallback_min_cpu_idle, self.fallback_min_memory, self.fallback_on_battery)

    def _fallback_body(self, body: dict) -> dict:
        # Fewer threads leave CPU for the user's work, a small context keeps
        # the model's memory down, and a short keep_alive unloads it soon
        # after the run instead of after Ollama's default.
        return {**body, "keep_alive": FALLBACK_KEEP_ALIVE,
                "options": {"num_thread": self.fallback_threads, "num_ctx": FALLBACK_NUM_CTX}}

    def _post_json(self, url: str, body: dict, timeout: float) -> dict | DegradedStatus:
        request = Request(url, data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except HTTPError as error:
            return DegradedStatus(str(error), fallback=error.code >= 500)
        except URLError as error:
            return DegradedStatus(str(error), fallback=True)
        except (TimeoutError, OSError) as error:
            return DegradedStatus(str(error), fallback=True)
        except (OverflowError, TypeError, ValueError) as error:
            return DegradedStatus(str(error))

    def _generate_at(self, provider: str, prompt: str) -> str | DegradedStatus:
        body = {"model": self.review_model, "stream": False, "think": False, "format": "json", "prompt": prompt}
        if provider == "fallback":
            payload = self._post_json(f"{self.fallback_url}/api/generate", self._fallback_body(body), self.fallback_timeout)
        else:
            payload = self._post_json(f"{self.url}/api/generate", body, self.timeout)
        if isinstance(payload, DegradedStatus):
            return payload
        response = payload.get("response")
        return response if isinstance(response, str) else DegradedStatus("invalid generate response")

    def _generate(self, prompt: str) -> str | DegradedStatus:
        if self._select_provider() == "fallback":
            return self._generate_at("fallback", prompt)
        result = self._generate_at("primary", prompt)
        if isinstance(result, DegradedStatus) and result.fallback and self.fallback_url:
            self.provider = "fallback"
            return self._generate_at("fallback", prompt)
        return result

    @staticmethod
    def _embedding_batch(vectors, expected: int, source: str, model: str) -> EmbeddingBatch | DegradedStatus:
        if (not isinstance(vectors, list) or len(vectors) != expected
                or any(not isinstance(vector, list) or not vector for vector in vectors)
                or any(not isinstance(value, (int, float)) or isinstance(value, bool)
                       for vector in vectors for value in vector)):
            return DegradedStatus("invalid embedding response")
        try:
            return EmbeddingBatch([[float(value) for value in vector] for vector in vectors], source, model)
        except (OverflowError, ValueError) as error:
            return DegradedStatus(str(error))

    def _embed_at(self, provider: str, texts: Sequence[str]) -> EmbeddingBatch | DegradedStatus:
        body = {"model": self.embed_model, "input": list(texts)}
        if provider == "fallback":
            payload = self._post_json(f"{self.fallback_url}/api/embed", self._fallback_body(body), self.fallback_timeout)
        else:
            payload = self._post_json(f"{self.url}/api/embed", body, self.timeout)
        if isinstance(payload, DegradedStatus):
            return payload
        return self._embedding_batch(payload.get("embeddings"), len(texts), provider, self.embed_model)

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch | DegradedStatus:
        if self._select_provider() == "fallback":
            return self._embed_at("fallback", texts)
        result = self._embed_at("primary", texts)
        if isinstance(result, DegradedStatus) and result.fallback and self.fallback_url:
            self.provider = "fallback"
            return self._embed_at("fallback", texts)
        return result

    def review_capture(self, candidate: dict) -> dict | DegradedStatus:
        generated = self._generate("Return strict JSON only with exactly these keys: type (one of preference, correction, fact, convention, decision, lesson), scope (one of global, project), project (string or null, null when scope is global), content (concise durable statement), importance (number 0 to 1), confidence (number 0 to 1), tags (array of strings), durability (boolean true), supersedes (array of strings). Curate completed-work evidence; never copy transcripts or private data. " + json.dumps(candidate, sort_keys=True))
        if isinstance(generated, DegradedStatus):
            return generated
        try:
            review = json.loads(generated)
            required = {"type", "scope", "project", "content", "importance", "confidence", "tags", "durability", "supersedes"}
            if set(review) != required:
                return DegradedStatus("invalid capture review")
        except (TypeError, ValueError) as error:
            return DegradedStatus(str(error))
        return review

    def review_relation(self, candidate: str, existing: str) -> str | DegradedStatus:
        generated = self._generate("Return strict JSON only: {\"relation\":\"duplicate|contradiction|distinct\"}. "
                                   "Decide the factual relation between candidate and existing. "
                                   + json.dumps({"candidate": candidate, "existing": existing}, sort_keys=True))
        if isinstance(generated, DegradedStatus):
            return generated
        try:
            result = json.loads(generated)
            if set(result) != {"relation"} or result["relation"] not in {"duplicate", "contradiction", "distinct"}:
                return DegradedStatus("invalid relation review")
        except (TypeError, ValueError) as error:
            return DegradedStatus(str(error))
        return result["relation"]
