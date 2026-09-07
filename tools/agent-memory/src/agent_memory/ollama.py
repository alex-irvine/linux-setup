from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]


@dataclass(frozen=True)
class DegradedStatus:
    reason: str


class OllamaClient:
    def __init__(self, url: str | None = None, timeout: float = 2.0) -> None:
        self.url = (url or os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = timeout

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch | DegradedStatus:
        request = Request(f"{self.url}/api/embed", data=json.dumps({"input": list(texts)}).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
            vectors = payload["embeddings"]
            if len(vectors) != len(texts):
                return DegradedStatus("unexpected embedding count")
            return EmbeddingBatch([[float(value) for value in vector] for vector in vectors])
        except (OSError, URLError, ValueError, KeyError, json.JSONDecodeError) as error:
            return DegradedStatus(str(error))

    def review_capture(self, candidate: dict) -> dict | DegradedStatus:
        request = Request(f"{self.url}/api/generate", data=json.dumps({"stream": False,
            "prompt": "Return strict JSON only: {\\\"accept\\\": boolean, \\\"reason\\\": string}. Review this memory candidate: " + json.dumps(candidate, sort_keys=True)}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                review = json.loads(json.loads(response.read())["response"])
            if set(review) != {"accept", "reason"} or not isinstance(review["accept"], bool) or not isinstance(review["reason"], str):
                return DegradedStatus("invalid capture review")
            return review
        except (OSError, URLError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            return DegradedStatus(str(error))
