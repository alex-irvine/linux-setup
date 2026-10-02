from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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
        fallback_url = os.environ.get("OLLAMA_FALLBACK_URL", "").rstrip("/")
        self.fallback_key = os.environ.get("OPENROUTER_API_KEY") or None
        self.fallback_url = fallback_url if fallback_url and self.fallback_key else None
        self.fallback_review_model = os.environ.get("OLLAMA_FALLBACK_REVIEW_MODEL", "openai/gpt-4o-mini")
        self.fallback_embed_model = os.environ.get("OLLAMA_FALLBACK_EMBED_MODEL", "openai/text-embedding-3-small")
        self.fallback_embed_dimensions = int(os.environ.get("OLLAMA_FALLBACK_EMBED_DIMENSIONS", "768"))
        self.fallback_timeout = float(os.environ.get("OLLAMA_FALLBACK_TIMEOUT", "120"))
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
            except OSError:
                self.provider = "fallback"
        return self.provider

    def _post_json(self, url: str, body: dict, timeout: float,
                   headers: dict | None = None) -> dict | DegradedStatus:
        request = Request(url, data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
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

    def _generate_primary(self, prompt: str) -> str | DegradedStatus:
        payload = self._post_json(f"{self.url}/api/generate",
                                  {"model": self.review_model, "stream": False, "think": False,
                                   "format": "json", "prompt": prompt}, self.timeout)
        if isinstance(payload, DegradedStatus):
            return payload
        response = payload.get("response")
        return response if isinstance(response, str) else DegradedStatus("invalid generate response")

    def _generate_fallback(self, prompt: str) -> str | DegradedStatus:
        payload = self._post_json(f"{self.fallback_url}/chat/completions",
                                  {"model": self.fallback_review_model,
                                   "messages": [{"role": "user", "content": prompt}],
                                   "response_format": {"type": "json_object"}},
                                  self.fallback_timeout,
                                  {"Authorization": f"Bearer {self.fallback_key}"})
        if isinstance(payload, DegradedStatus):
            return payload
        try:
            content = payload["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError) as error:
            return DegradedStatus(str(error))
        return content if isinstance(content, str) else DegradedStatus("invalid fallback response")

    def _generate(self, prompt: str) -> str | DegradedStatus:
        if self._select_provider() == "fallback":
            return self._generate_fallback(prompt)
        result = self._generate_primary(prompt)
        if isinstance(result, DegradedStatus) and result.fallback and self.fallback_url:
            self.provider = "fallback"
            return self._generate_fallback(prompt)
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

    def _embed_primary(self, texts: Sequence[str]) -> EmbeddingBatch | DegradedStatus:
        payload = self._post_json(f"{self.url}/api/embed",
                                  {"model": self.embed_model, "input": list(texts)}, self.timeout)
        if isinstance(payload, DegradedStatus):
            return payload
        return self._embedding_batch(payload.get("embeddings"), len(texts), "primary", self.embed_model)

    def _embed_fallback(self, texts: Sequence[str]) -> EmbeddingBatch | DegradedStatus:
        payload = self._post_json(f"{self.fallback_url}/embeddings",
                                  {"model": self.fallback_embed_model, "input": list(texts),
                                   "dimensions": self.fallback_embed_dimensions},
                                  self.fallback_timeout,
                                  {"Authorization": f"Bearer {self.fallback_key}"})
        if isinstance(payload, DegradedStatus):
            return payload
        data = payload.get("data")
        vectors = [item.get("embedding") if isinstance(item, dict) else None
                   for item in data] if isinstance(data, list) else None
        return self._embedding_batch(vectors, len(texts), "fallback", self.fallback_embed_model)

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch | DegradedStatus:
        if self._select_provider() == "fallback":
            return self._embed_fallback(texts)
        result = self._embed_primary(texts)
        if isinstance(result, DegradedStatus) and result.fallback and self.fallback_url:
            self.provider = "fallback"
            return self._embed_fallback(texts)
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
